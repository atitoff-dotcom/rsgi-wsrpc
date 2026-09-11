import asyncio
import time
from contextvars import ContextVar
from itertools import count
from typing import Optional, Any

import orjson
from core.logger import logger
from core.lib.config import settings

# Контекстные переменные для доступа к сессиям из любой точки кода
current_transport_ctx: ContextVar = ContextVar("current_transport", default=None)
current_session_ctx: ContextVar = ContextVar("current_session", default=None)
current_rpc_id_ctx: ContextVar = ContextVar("current_rpc_id", default=None)
current_user_ctx: ContextVar = ContextVar("current_user", default=None)

# --- ГЛОБАЛЬНЫЕ РЕЕСТРЫ ---
ACTIVE_SESSIONS_SET = set()
RPC_REGISTRY = {}

class RPCError(Exception):
    """
    Исключение для RPC-ошибок, сообщения которых возвращаются клиенту.
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def rpc_method(name: str = None, role: Optional[Any] = None, http: bool = False, *args, **kwargs):
    """
    Декоратор для регистрации RPC-методов.

    Позволяет опционально ограничить доступ по роли пользователя (параметр role).
    """
    def decorator(func):
        method_name = name or func.__name__

        async def wrapper(session, params):
            """
            Обертка для проверки прав доступа и вызова исходного хендлера.
            """
            if role is not None:
                from core.constants import UserRole
                user_role = getattr(session, "user_role", UserRole.GUEST)
                if user_role != UserRole.ADMIN and user_role != role:
                    raise RPCError(f"Доступ запрещен: требуется роль {role.value if hasattr(role, 'value') else role}")
            return await func(session, params)

        RPC_REGISTRY[method_name] = wrapper
        wrapper.http = http
        return func
    return decorator


# --- СЕССИЯ RSGI ---

class JsonRpcSession:
    __slots__ = (
        "ws", "user_data", "session_id",
        "_id_generator", "_pending_requests", "_auth_timeout_task", "_idle_timeout_task",
        "_is_alive", "_handler_tasks", "tokens", "rate_limit_enabled", "_closed",
        "_reset_timer_handle", "_main_task", "last_activity",
        "ip", "data", "_on_close_callbacks"
    )

    def __init__(self, ws, session_id: int, ip: str = "0.0.0.0"):
        self.ws = ws
        self.session_id = session_id
        self.user_data = {}
        self.ip = ip
        self.data = None
        self._on_close_callbacks = []
        ACTIVE_SESSIONS_SET.add(self)

        self._id_generator = count()
        self._pending_requests = {}
        self._handler_tasks = set()
        self._auth_timeout_task = None
        self._idle_timeout_task = None
        self._is_alive = True
        self._closed = False
        self._reset_timer_handle = None
        self._main_task = None
        self.last_activity = time.time()

        # --- НАСТРОЙКИ ЗАЩИТЫ ---
        self.rate_limit_enabled = True  # True - включено, False - выключено
        self.tokens = 0                 # Текущий счетчик запросов в текущем окне

    def register_on_close(self, callback):
        """Регистрирует колбэк, который будет вызван при закрытии сессии."""
        self._on_close_callbacks.append(callback)

    @property
    def authenticated(self) -> bool:
        return self.data is not None

    def _reset_tokens_loop(self):
        """Быстрый таймер сброса лимитов без создания тяжелых asyncio.Task"""
        if self._closed:
            return
        self.tokens = 0  # Обнуляем счетчик каждую секунду
        self._reset_timer_handle = asyncio.get_running_loop().call_later(1.0, self._reset_tokens_loop)

    async def start(self):
        self._main_task = asyncio.current_task()
        self._auth_timeout_task = asyncio.create_task(self._auth_timeout_loop())
        self._idle_timeout_task = asyncio.create_task(self._idle_timeout_loop())
        
        # Запускаем ежесекундный сброс лимитов
        self._reset_tokens_loop()
        
        try:
            while True:
                msg = await self.ws.receive()
                self.last_activity = time.time()
                logger.info("[Бэкенд] Получено сообщение")
                # --- ИДЕАЛЬНАЯ ПРОВЕРКА НА ДИСКОННЕКТ ПО ТИПУ ОБЪЕКТА ---
                # Если прилетел объект WebsocketInboundCloseMessage (или пустой msg)
                if not msg or "CloseMessage" in type(msg).__name__:
                    # Просто выходим из цикла, падая в finally -> close()
                    logger.info(f"disconnect: session_id {self.session_id}")
                    break 
                # --------------------------------------------------------
                    
                self._is_alive = True              

                # --- УЛЬТРАБЫСТРАЯ ПРОВЕРКА ЛИМИТА ---
                if self.rate_limit_enabled:
                    self.tokens += 1
                    if self.tokens > 30:  # Максимум 30 запросов в секунду
                        logger.warning(f"[Защита] Сессия {self.session_id} заблокирована за RPC-флуд!")
                        await self._send_error(None, -32005, "Too many requests. Connection closing.")
                        break 
                # -------------------------------------

                try:
                    data = orjson.loads(msg.data)
                except Exception as e:
                    logger.error(f"[Бэкенд] Критическая ошибка парсинга orjson: {e}")
                    await self._send_error(None, -32700, "Parse error")
                    continue

                rpc_id = data.get("id")

                if rpc_id is not None and ("result" in data or "error" in data):
                    fut = self._pending_requests.pop(rpc_id, None)
                    if fut and not fut.done():
                        fut.set_result(data)
                    continue

                if data.get("jsonrpc") != "2.0" or "method" not in data:
                    await self._send_error(rpc_id, -32600, "Invalid Request")
                    continue

                method_name = data.get("method")
                params = data.get("params", {})

                handler = RPC_REGISTRY.get(method_name)
                if not handler:
                    await self._send_error(rpc_id, -32601, f"Method '{method_name}' not found")
                    continue

                # Проверка авторизации на основе конфигурационного префикса
                login_rpc = settings.security.get("login_rpc")
                if login_rpc and not self.authenticated and not method_name.startswith(login_rpc):
                    await self._send_error(rpc_id, -32001, "Unauthorized.")
                    continue

                task = asyncio.create_task(
                    self._run_rpc_handler(handler, method_name, rpc_id, params)
                )
                self._handler_tasks.add(task)
                task.add_done_callback(self._handler_tasks.discard)

        finally:
            # Гарантированная очистка ресурсов в одной точке
            await self.close()

    async def _run_rpc_handler(self, handler, method_name: str, rpc_id, params: dict):
        transport_token = current_transport_ctx.set(self)
        session_token = current_session_ctx.set(self.data)
        rpc_token = current_rpc_id_ctx.set(rpc_id)
        user_token = None
        if self.data and hasattr(self.data, "user_ctx"):
            user_token = current_user_ctx.set(self.data.user_ctx)
        try:
            session_arg = self.data if self.data else self
            result = await handler(session_arg, params)
            
            if self._closed or not self.ws:
                return

            payload_str = orjson.dumps({
                "jsonrpc": "2.0", "result": result, "id": rpc_id
            }).decode("utf-8")
            
            # Обход бага совместимости Python 3.13 с Granian
            awaitable = self.ws.send_str(payload_str)
            if not hasattr(awaitable, "cancelled"):
                try:
                    awaitable.cancelled = lambda: False
                except AttributeError:
                    pass
            await awaitable
            
        except RPCError as e:
            # Возвращаем ожидаемую ошибку RPC клиенту
            await self._send_error(rpc_id, -32000, e.message)
        except Exception as e:
            logger.error(f"[RPC Error] Ошибка в хендлере {method_name}: {e}")
            await self._send_error(rpc_id, -32603, "Internal server error")
        finally:
            if user_token is not None:
                current_user_ctx.reset(user_token)
            current_transport_ctx.reset(transport_token)
            current_session_ctx.reset(session_token)
            current_rpc_id_ctx.reset(rpc_token)

    async def send_request(self, method: str, params: dict = None, timeout: float = 5.0) -> dict:
        if not self.authenticated:
            raise ConnectionError("Session not authenticated")
            
        rpc_id = next(self._id_generator)
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": rpc_id}
        
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_requests[rpc_id] = fut
        
        payload_str = orjson.dumps(payload).decode("utf-8")
        
        awaitable = self.ws.send_str(payload_str)
        if not hasattr(awaitable, "cancelled"):
            try:
                awaitable.cancelled = lambda: False
            except AttributeError:
                pass
        await awaitable
        
        return await asyncio.wait_for(fut, timeout=timeout)

    async def _auth_timeout_loop(self):
        try:
            await asyncio.sleep(60.0)
            if not self.authenticated:
                logger.warning(f"[Защита] Таймаут авторизации (60с) для сессии {self.session_id}. Закрываем.")
                if self._main_task and not self._main_task.done():
                    self._main_task.cancel()
        except asyncio.CancelledError:
            pass

    async def _idle_timeout_loop(self):
        try:
            from core.lib.config import settings
            timeout = settings.security.get("session_idle_timeout", 900)
            if timeout <= 0:
                return

            while not self._closed:
                await asyncio.sleep(10.0)
                elapsed = time.time() - self.last_activity
                if elapsed >= timeout:
                    logger.warning(f"[Защита] Сессия {self.session_id} закрыта по неактивности ({int(elapsed)}с).")
                    try:
                        # Отправляем уведомление на фронтенд о том, что сессия истекла
                        payload_str = orjson.dumps({
                            "jsonrpc": "2.0", "method": "session.expired", "params": {}
                        }).decode("utf-8")
                        awaitable = self.ws.send_str(payload_str)
                        if not hasattr(awaitable, "cancelled"):
                            try:
                                awaitable.cancelled = lambda: False
                            except AttributeError:
                                pass
                        await awaitable
                    except Exception:
                        pass
                    
                    if self._main_task and not self._main_task.done():
                        self._main_task.cancel()
                    break
        except asyncio.CancelledError:
            pass

    async def send_stream_chunk(self, rpc_id, chunk_data):
        if self._closed or not self.ws:
            return
        try:
            payload_str = orjson.dumps({
                "jsonrpc": "2.0", "result": {"stream": True, "data": chunk_data}, "id": rpc_id
            }).decode("utf-8")
            awaitable = self.ws.send_str(payload_str)
            if not hasattr(awaitable, "cancelled"):
                try:
                    awaitable.cancelled = lambda: False
                except AttributeError:
                    pass
            await awaitable
        except Exception:
            pass

    async def _send_error(self, rpc_id, code: int, message: str):
        if self._closed or not self.ws:
            return
        try:
            payload_str = orjson.dumps({
                "jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": rpc_id
            }).decode("utf-8")
            
            awaitable = self.ws.send_str(payload_str)
            if not hasattr(awaitable, "cancelled"):
                try:
                    awaitable.cancelled = lambda: False
                except AttributeError:
                    pass
            await awaitable
        except Exception:
            pass

    async def close(self):
        if self._closed:
            return
        self._closed = True

        current_task = asyncio.current_task()

        # Безопасно завершаем таску таймаута без риска рекурсии
        if self._auth_timeout_task and self._auth_timeout_task != current_task and not self._auth_timeout_task.done():
            self._auth_timeout_task.cancel()
            
        if self._idle_timeout_task and self._idle_timeout_task != current_task and not self._idle_timeout_task.done():
            self._idle_timeout_task.cancel()
            
        for task in self._handler_tasks:
            if task != current_task and not task.done():
                task.cancel()
            
        self._handler_tasks.clear()
        
        for fut in self._pending_requests.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Session closed"))
        self._pending_requests.clear()
        
        if self._reset_timer_handle:
            self._reset_timer_handle.cancel()
            self._reset_timer_handle = None

        if self._main_task and self._main_task != current_task and not self._main_task.done():
            self._main_task.cancel()

        # Вызов зарегистрированных колбэков закрытия сессии
        for callback in self._on_close_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(self))
                else:
                    callback(self)
            except Exception as e:
                logger.error(f"[Сессия] Ошибка выполнения close-колбэка: {e}")

        ACTIVE_SESSIONS_SET.discard(self)
        self.ws = None

    def __del__(self):
        try:
            logger.info(f"[Сессия] Уничтожена: ID {self.session_id}")
        except Exception:
            pass
