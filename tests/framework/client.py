# -*- coding: utf-8 -*-
"""
WSRPC + HTTP Асинхронный клиент для тестирования бэкенда Agrita.
Реализует полнофункциональный JSON-RPC 2.0 клиент с поддержкой:
- Одиночных запросов (call)
- Потоковых мультиретурнов (stream: true)
- Серверных push-уведомлений (cache.invalidate, cache.patch)
- Двухфазной HTTP-загрузки файлов (/upload)
"""

import asyncio
from typing import Dict, Any, Optional, AsyncGenerator, List
import aiohttp
import orjson

from tests.framework.config import TargetConfig, get_target


class RPCClientError(Exception):
    """Ошибка, возвращенная сервером по протоколу JSON-RPC 2.0."""
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"RPC Error [{code}]: {message} (data: {data})")
        self.code = code
        self.message = message
        self.data = data


class TestClient:
    def __init__(self, target: Optional[TargetConfig] = None):
        self.target = target or get_target()
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._next_id = 1
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._stream_queues: Dict[int, asyncio.Queue] = {}
        self._notifications: asyncio.Queue = asyncio.Queue()
        self._listen_task: Optional[asyncio.Task] = None
        self.user_info: Optional[Dict[str, Any]] = None
        self.token: Optional[str] = None

    async def connect(self):
        """Устанавливает HTTP-сессию и WebSocket-соединение с сервером."""
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        
        if self._ws is None or self._ws.closed:
            self._ws = await self._http_session.ws_connect(self.target.ws_url)
            self._listen_task = asyncio.create_task(self._listen_loop())

    async def close(self):
        """Корректно закрывает WebSocket и HTTP сессии."""
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
            self._http_session = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _listen_loop(self):
        """Фоновый цикл чтения сообщений из WebSocket."""
        try:
            async for msg in self._ws:
                if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
                    raw = msg.data if isinstance(msg.data, (bytes, bytearray)) else msg.data.encode("utf-8")
                    data = orjson.loads(raw)
                    self._dispatch_message(data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            pass

    def _dispatch_message(self, data: Dict[str, Any]):
        """Маршрутизация входящего сообщения: ответ на вызов или нотификация."""
        req_id = data.get("id")

        # 1. Ответ на запрос с ID
        if req_id is not None:
            # Если это стрим
            if req_id in self._stream_queues:
                self._stream_queues[req_id].put_nowait(data)
                return

            fut = self._pending_requests.get(req_id)
            if fut and not fut.done():
                if "error" in data:
                    err = data["error"]
                    fut.set_exception(RPCClientError(
                        code=err.get("code", -1),
                        message=err.get("message", "Unknown error"),
                        data=err.get("data")
                    ))
                else:
                    fut.set_result(data.get("result"))
            return

        # 2. Нотификация от сервера (без ID)
        method = data.get("method")
        if method:
            self._notifications.put_nowait(data)

    async def call(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0, raw: bool = False) -> Any:
        """
        Вызывает RPC-метод и ожидает финальный результат (result).
        При ошибке вызывает RPCClientError.
        Если raw=False (по умолчанию), автоматически распаковывает $tabular ответы.
        """
        await self.connect()
        req_id = self._next_id
        self._next_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id
        }

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_requests[req_id] = fut

        try:
            await self._ws.send_bytes(orjson.dumps(payload))
            res = await asyncio.wait_for(fut, timeout=timeout)
            if raw:
                return res
            try:
                from app.system.tabular import unpack_tabular
                return unpack_tabular(res)
            except ImportError:
                return res
        finally:
            self._pending_requests.pop(req_id, None)

    async def stream(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 30.0) -> AsyncGenerator[Any, None]:
        """
        Вызывает RPC-метод с мультиретурном (stream: true)
        и возвращает асинхронный генератор промежуточных результатов.
        """
        await self.connect()
        req_id = self._next_id
        self._next_id += 1

        queue = asyncio.Queue()
        self._stream_queues[req_id] = queue

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": req_id
        }

        try:
            await self._ws.send_bytes(orjson.dumps(payload))
            while True:
                msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                if "error" in msg:
                    err = msg["error"]
                    raise RPCClientError(code=err.get("code", -1), message=err.get("message", "Stream error"), data=err.get("data"))
                
                is_stream = msg.get("stream", False)
                yield msg.get("result")
                if not is_stream:
                    break
        finally:
            self._stream_queues.pop(req_id, None)

    async def wait_for_notification(self, method: str, timeout: float = 5.0) -> Dict[str, Any]:
        """
        Ожидает входящую push-нотификацию с указанным методом (например, 'cache.invalidate').
        """
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Таймаут ожидания нотификации '{method}' ({timeout}s)")
            
            notif = await asyncio.wait_for(self._notifications.get(), timeout=remaining)
            if notif.get("method") == method:
                return notif

    async def upload_file(self, filename: str, content: bytes, content_type: str = "image/png") -> Dict[str, Any]:
        """
        Потоковая загрузка файла на HTTP /upload (Two-Phase Commit).
        """
        await self.connect()
        headers = {
            "X-File-Name": filename,
            "Content-Type": content_type,
        }
        async with self._http_session.post(self.target.upload_url, data=content, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"Upload failed with HTTP {resp.status}: {body}")
            return await resp.json()
