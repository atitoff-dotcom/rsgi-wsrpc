# -*- coding: utf-8 -*-
"""
Главный класс приложения RsgiWsrpcApp.
Предоставляет готовую точку входа для Granian RSGI, инкапсулирует конфигурацию,
маршрутизацию HTTP/WebSocket, раздачу статики, CORS и управление жизненным циклом.
"""

import os
import sys
import asyncio
import inspect
import mimetypes
from itertools import count
from typing import Optional, List, Dict, Any, Union, Callable

from .core.lib.config import configure, settings, Settings
from .core.session import JsonRpcSession, rpc_method, RPC_REGISTRY, ACTIVE_SESSIONS_SET
from .core.router import http_route, HTTP_ROUTES
from .core.lifecycle import on_startup, on_shutdown, run_startup_callbacks, run_shutdown_callbacks
from .core.logger import logger, setup_logging


class RsgiWsrpcApp:
    """
    Полнофункциональное RSGI-приложение rsgi-wsrpc.
    """

    def __init__(
        self,
        *,
        # Безопасность и ядро
        secret_key: Optional[str] = None,
        database_url: Optional[str] = None,
        db_echo: bool = False,
        files_path: Optional[str] = None,
        max_upload_size: Optional[int] = None,
        login_rpc: Optional[str] = None,
        auth_timeout: Optional[int] = None,
        guest_idle_timeout: Optional[int] = None,
        user_idle_timeout: Optional[int] = None,
        session_idle_timeout: Optional[int] = None,
        allow_guests: Optional[bool] = None,
        password_iterations: Optional[int] = None,
        token_expire_hours: Optional[int] = None,
        max_message_size: Optional[int] = None,
        # HTTP и CORS
        cors: bool = True,
        cors_origins: Union[str, List[str]] = "*",
        cors_headers: str = "content-type, authorization",
        cors_methods: str = "GET, POST, PUT, DELETE, OPTIONS",
        # Статика и UI
        static_dir: Optional[str] = None,
        static_prefix: str = "/static",
        index_file: Optional[str] = None,
        # Внешняя авторизация и плагины
        oauth: Optional[Union[List[Any], Dict[str, Any]]] = None,
        backplane_url: Optional[str] = None,
        enable_seo: bool = False,
        sitemap_host: Optional[str] = None,
        dev_admin: bool = False,
        auto_auth_ws: bool = True,
        auto_auth_models: bool = True,
        custom_settings: Optional[Dict[str, Any]] = None,
        **extra_settings: Any
    ):
        # 1. Применяем конфигурацию к ядру
        config_kwargs: Dict[str, Any] = {}
        if secret_key is not None:
            config_kwargs["secret_key"] = secret_key
        if database_url is not None:
            config_kwargs["database_url"] = database_url
        if db_echo:
            config_kwargs["db_echo"] = db_echo
        if files_path is not None:
            config_kwargs["files_path"] = files_path
        if max_upload_size is not None:
            config_kwargs["max_upload_size"] = max_upload_size
        if backplane_url is not None:
            config_kwargs["backplane_url"] = backplane_url
        if sitemap_host is not None:
            config_kwargs["sitemap_host"] = sitemap_host
        if login_rpc is not None:
            config_kwargs["login_rpc"] = login_rpc
        if auth_timeout is not None:
            config_kwargs["auth_timeout"] = auth_timeout
        if guest_idle_timeout is not None:
            config_kwargs["guest_idle_timeout"] = guest_idle_timeout
        if user_idle_timeout is not None:
            config_kwargs["user_idle_timeout"] = user_idle_timeout
        if session_idle_timeout is not None:
            config_kwargs["session_idle_timeout"] = session_idle_timeout
        if allow_guests is not None:
            config_kwargs["allow_guests"] = allow_guests
        if password_iterations is not None:
            config_kwargs["password_iterations"] = password_iterations
        if token_expire_hours is not None:
            config_kwargs["token_expire_hours"] = token_expire_hours
        if max_message_size is not None:
            config_kwargs.setdefault("custom", {})["max_message_size"] = max_message_size

        if oauth:
            oauth_dict: Dict[str, Any] = {}
            if isinstance(oauth, list):
                for prov in oauth:
                    p_name = getattr(prov, "provider_name", None) or prov.__class__.__name__.lower().replace("oauth", "")
                    oauth_dict[p_name] = {
                        k: v for k, v in prov.__dict__.items() if not k.startswith("_")
                    }
            elif isinstance(oauth, dict):
                oauth_dict = oauth
            config_kwargs["oauth"] = oauth_dict

        if custom_settings:
            config_kwargs.setdefault("custom", {}).update(custom_settings)
        if extra_settings:
            config_kwargs.setdefault("custom", {}).update(extra_settings)

        self.settings: Settings = configure(**config_kwargs)

        # 2. Настройки HTTP / CORS
        self.cors_enabled = cors
        self.cors_origins = cors_origins if isinstance(cors_origins, str) else ", ".join(cors_origins)
        self.cors_headers = cors_headers
        self.cors_methods = cors_methods

        # 3. Настройки статических файлов
        self.static_dir = os.path.abspath(static_dir) if static_dir else None
        self.static_prefix = "/" + static_prefix.strip("/") if static_prefix else "/static"
        self.index_file = None
        if index_file:
            if os.path.isabs(index_file):
                self.index_file = index_file
            elif self.static_dir:
                self.index_file = os.path.join(self.static_dir, index_file)
            else:
                self.index_file = os.path.abspath(index_file)

        self.enable_seo = enable_seo
        self._session_counter = count()
        self._on_connect_callbacks: List[Callable] = []

        self.dev_admin = dev_admin
        self.auto_auth_ws = auto_auth_ws

        # Автоматическая регистрация стандартных моделей в CRUD
        if auto_auth_models:
            try:
                from rsgi_wsrpc.plugins.crud.registry import ModelRegistry
                ModelRegistry.register_auth_models()
            except Exception:
                pass

        if self.dev_admin:
            self._register_dev_admin()

        # Граниан связывает __rsgi_init__ и __rsgi_del__ на самом объекте приложения
        self.__rsgi_init__ = self._rsgi_init_handler
        self.__rsgi_del__ = self._rsgi_del_handler

    def _register_dev_admin(self) -> None:
        """Регистрирует роут /dev-admin и начальный сидинг админа для локальной разработки."""
        @self.route("/dev-admin", methods=["GET"])
        async def _dev_admin_route(scope, proto):
            from rsgi_wsrpc.plugins.crud import create_crud_session
            token = create_crud_session({"username": "admin", "role": "admin"})
            proto.response_str(
                status=302,
                headers=[
                    ("location", "/admin/"),
                    ("set-cookie", f"rsgi_crud_session={token}; path=/; max-age=86400; SameSite=Lax"),
                    ("content-length", "0"),
                ],
                body=""
            )

        async def _seed_dev_admin():
            try:
                from rsgi_wsrpc.plugins.db import async_session
                from rsgi_wsrpc.plugins.auth import User, Role, system_bypass_ctx
                from sqlalchemy import select
                token = system_bypass_ctx.set(True)
                try:
                    async with async_session() as db:
                        admin_user = (await db.execute(select(User).where(User.login == "admin"))).scalar_one_or_none()
                        if not admin_user:
                            admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
                            if not admin_role:
                                admin_role = Role(name="admin", description="Системный администратор (Superadmin)")
                                db.add(admin_role)
                                await db.flush()
                            user = User(
                                login="admin",
                                name="Администратор (Dev)",
                                password_hash=User._hash_password("admin123")
                            )
                            user.roles.append(admin_role)
                            db.add(user)
                            await db.commit()
                            logger.info("[DevAdmin] Создан суперпользователь 'admin' (пароль: admin123)")
                finally:
                    system_bypass_ctx.reset(token)
            except Exception as e:
                logger.debug(f"[DevAdmin] Пропущен сидинг dev admin: {e}")

        self.on_startup(_seed_dev_admin)

    def _auto_authenticate_ws(self, session: JsonRpcSession) -> None:
        """Автоматически авторизует WebSocket по Cookie (rsgi_crud_session, rsgi_session, rpc_jwt)."""
        if session.data is not None:
            return
        cookies = session.cookies
        if not cookies:
            return
        token = (
            cookies.get("rsgi_crud_session")
            or cookies.get("rsgi_session")
            or cookies.get("rpc_jwt")
            or cookies.get("token")
        )
        if not token:
            return

        user_info = None
        try:
            from rsgi_wsrpc.plugins.crud.auth import get_crud_session
            user_info = get_crud_session(token)
        except Exception:
            pass

        if not user_info:
            try:
                from rsgi_wsrpc.core.security import decode_access_token
                payload = decode_access_token(token)
                if payload:
                    roles = payload.get("roles", [])
                    role = payload.get("role") or (roles[0] if roles else "user")
                    is_admin = bool("admin" in roles or "ADMIN" in roles or "superadmin" in roles or payload.get("is_superadmin") or role in ("admin", "ADMIN", "superadmin"))
                    raw_sub = payload.get("sub", "1")
                    uid = int(raw_sub) if str(raw_sub).isdigit() else 1
                    user_info = {
                        "uid": uid,
                        "user_id": uid,
                        "username": payload.get("username", "admin" if is_admin else "user"),
                        "role": "admin" if is_admin else role,
                        "roles": roles if roles else [role],
                        "is_superadmin": is_admin,
                        "perms_dict": payload.get("permissions") or payload.get("perms_dict") or {},
                        "allowed_rpc_methods": {"*"} if is_admin else set(payload.get("allowed_rpc_methods", [])),
                    }
            except Exception:
                pass

        if user_info:
            uid = user_info.get("uid") or user_info.get("user_id", 1)
            role = user_info.get("role", "user")
            roles = user_info.get("roles") or [role]
            is_superadmin = bool(
                role in ("admin", "ADMIN", "superadmin")
                or "admin" in roles
                or "ADMIN" in roles
                or "superadmin" in roles
                or user_info.get("is_superadmin")
            )
            user_ctx = type("UserCtx", (), {
                "is_superadmin": is_superadmin,
                "user_id": uid,
                "team_ids": user_info.get("team_ids", []),
                "perms_dict": user_info.get("perms_dict", {}),
                "allowed_rpc_methods": {"*"} if is_superadmin else set(user_info.get("allowed_rpc_methods", [])),
            })()

            from rsgi_wsrpc.plugins.auth.core import AuthSession
            session.data = AuthSession(
                uid=uid,
                user=None,
                user_name=user_info.get("username", "user"),
                user_role=role,
                user_roles=roles,
                session_db_id=0,
                user_ctx=user_ctx,
                allowed_rpc_methods={"*"} if is_superadmin else set(user_info.get("allowed_rpc_methods", [])),
                send_request_cb=getattr(session, "send_request", None),
                send_stream_cb=getattr(session, "send_stream_chunk", None),
                close_cb=getattr(session, "close", None),
            )
            logger.info(f"[AutoAuth] WebSocket #{session.session_id} автоматически авторизован по Cookie как {user_info.get('username')} ({role})")

    # --- ДЕКОРАТОРЫ ---

    def rpc(self, name: Optional[str] = None, role: Optional[Any] = None, http: bool = False, public: bool = False, description: Optional[str] = None):
        """Декоратор для регистрации JSON-RPC метода."""
        return rpc_method(name=name, role=role, http=http, public=public, description=description)

    def route(self, path: str, methods: Optional[List[str]] = None):
        """Декоратор для регистрации HTTP-обработчика."""
        return http_route(path=path, methods=methods)

    def on_startup(self, func: Callable):
        """Регистрирует хук запуска приложения."""
        return on_startup(func)

    def on_shutdown(self, func: Callable):
        """Регистрирует хук завершения приложения."""
        return on_shutdown(func)

    def on_connect(self, func: Callable):
        """Регистрирует асинхронный хук при подключении новой WebSocket-сессии (session: JsonRpcSession)."""
        self._on_connect_callbacks.append(func)
        return func

    # --- ЖИЗНЕННЫЙ ЦИКЛ RSGI ---

    def _rsgi_init_handler(self, loop):
        """Инициализация при старте воркера Granian."""
        try:
            loop.run_until_complete(run_startup_callbacks())
        except Exception as e:
            logger.critical(f"[RsgiWsrpcApp] Сбой при startup: {e}", exc_info=True)
            sys.exit(1)

    def _rsgi_del_handler(self, loop):
        """Очистка при завершении воркера Granian."""
        try:
            # Закрываем оставшиеся WebSocket-сессии
            async def _cleanup():
                await run_shutdown_callbacks()
                close_tasks = [s.close() for s in list(ACTIVE_SESSIONS_SET)]
                if close_tasks:
                    await asyncio.gather(*close_tasks, return_exceptions=True)

            loop.run_until_complete(_cleanup())
            logger.info("[RsgiWsrpcApp] Корректно завершен (graceful shutdown).")
        except Exception as e:
            logger.error(f"[RsgiWsrpcApp] Ошибка при shutdown: {e}", exc_info=True)

    # --- ОБРАБОТКА RSGI ВХОДЯЩИХ ЗАПРОСОВ ---

    async def __call__(self, scope, proto):
        """
        Главный диспетчер Granian RSGI: разделение HTTP и WebSocket.
        """
        proto_type = getattr(scope, "proto", "")

        if proto_type == "http":
            await self._handle_http(scope, proto)
            return

        if proto_type in ("websocket", "ws"):
            await self._handle_websocket(scope, proto)
            return

        # Неизвестный протокол
        logger.warning(f"[RsgiWsrpcApp] Неизвестный тип протокола: {proto_type}")

    async def _handle_http(self, scope, proto):
        method = getattr(scope, "method", None) or (scope.get("method", "GET") if isinstance(scope, dict) else "GET")
        path = getattr(scope, "path", None) or (scope.get("path", "/") if isinstance(scope, dict) else "/")

        # 1. CORS Preflight (OPTIONS)
        if self.cors_enabled and method == "OPTIONS":
            proto.response_str(
                status=204,
                headers=[
                    ("access-control-allow-origin", self.cors_origins),
                    ("access-control-allow-methods", self.cors_methods),
                    ("access-control-allow-headers", self.cors_headers),
                    ("access-control-max-age", "86400"),
                ],
                body=""
            )
            return

        # 2. Опциональный перехват SEO-ботов
        if self.enable_seo:
            try:
                from .plugins.seo.router import handle_bot_http
                if await handle_bot_http(scope, proto):
                    return
            except ImportError:
                pass
            except Exception as e:
                logger.error(f"[RsgiWsrpcApp] Ошибка SEO перехвата: {e}", exc_info=True)

        # 3. Маршрутизация по зарегистрированным HTTP_ROUTES
        for route_path, methods, handler in HTTP_ROUTES:
            if method in methods:
                if path == route_path:
                    await handler(scope, proto)
                    return
                elif route_path.endswith("/*"):
                    prefix = route_path[:-1]  # e.g. "/crud/"
                    if path.startswith(prefix) or path == route_path[:-2]:  # "/crud/" or "/crud"
                        await handler(scope, proto)
                        return
                elif path.rstrip("/") == route_path.rstrip("/"):
                    await handler(scope, proto)
                    return

        # 4. Отдача index.html на корневой GET /
        if method == "GET" and path == "/" and self.index_file and os.path.exists(self.index_file):
            self._serve_static_file(proto, self.index_file)
            return

        # 5. Раздача статики из static_dir
        if method == "GET" and self.static_dir:
            # 1. Попытка с префиксом static_prefix (если он задан)
            if self.static_prefix and path.startswith(self.static_prefix):
                rel_path = path[len(self.static_prefix):].lstrip("/")
                if rel_path:
                    safe_full_path = os.path.abspath(os.path.join(self.static_dir, rel_path))
                    # Защита от Path Traversal
                    if (safe_full_path == self.static_dir or safe_full_path.startswith(self.static_dir + os.sep)) and os.path.isfile(safe_full_path):
                        self._serve_static_file(proto, safe_full_path)
                        return

            # 2. Прямая раздача из static_dir (например, /assets/..., /favicon.ico)
            rel_path = path.lstrip("/")
            if rel_path:
                safe_full_path = os.path.abspath(os.path.join(self.static_dir, rel_path))
                # Защита от Path Traversal
                if (safe_full_path == self.static_dir or safe_full_path.startswith(self.static_dir + os.sep)) and os.path.isfile(safe_full_path):
                    self._serve_static_file(proto, safe_full_path)
                    return

        # 6. 404 Not Found
        proto.response_str(
            status=404,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body="404 Not Found"
        )

    def _serve_static_file(self, proto, file_path: str):
        """Отдает статический файл через нативный proto.response_file (Zero-Copy)."""
        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        
        headers = [
            ("content-type", content_type),
            ("cache-control", "public, max-age=3600"),
        ]
        if self.cors_enabled:
            headers.append(("access-control-allow-origin", self.cors_origins))

        if hasattr(proto, "response_file"):
            proto.response_file(status=200, headers=headers, file=file_path)
        else:
            # Fallback для тестовых моков
            with open(file_path, "rb") as f:
                data = f.read()
            if hasattr(proto, "response_bytes"):
                proto.response_bytes(status=200, headers=headers, body=data)
            else:
                proto.response_str(status=200, headers=headers, body=data.decode("utf-8", errors="replace"))

    async def _handle_websocket(self, scope, proto):
        """Принимает входящее WebSocket-соединение и запускает WSRPC JsonRpcSession."""
        try:
            ws = await proto.accept()
            session_id = next(self._session_counter)
            
            # Извлекаем IP адрес клиента из scope
            client_ip = "0.0.0.0"
            client = getattr(scope, "client", None)
            if client and isinstance(client, (list, tuple)) and len(client) > 0:
                client_ip = str(client[0])

            session = JsonRpcSession(ws, session_id, ip=client_ip, scope=scope)
            if self.auto_auth_ws:
                self._auto_authenticate_ws(session)
            for cb in self._on_connect_callbacks:
                try:
                    if inspect.iscoroutinefunction(cb):
                        await cb(session)
                    else:
                        cb(session)
                except Exception as e:
                    logger.error(f"[RsgiWsrpcApp on_connect] Ошибка в хуке подключения: {e}", exc_info=True)
            await session.start()
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception as e:
            if "RSGI transport is closed" in str(e) or "ProtocolClosed" in type(e).__name__:
                logger.debug(f"[RsgiWsrpcApp WS] Клиент отключился (сессия #{session.session_id})")
            else:
                logger.error(f"[RsgiWsrpcApp WS] Ошибка сокет-сессии: {e}", exc_info=True)

    def run(self, host: str = "127.0.0.1", port: int = 8080, workers: int = 1, **granian_kwargs: Any):
        """
        Удобный запуск сервера через Granian в коде.
        """
        if workers > 1:
            from .core.backplane import get_backplane, MemoryBackplane
            if isinstance(get_backplane(), MemoryBackplane):
                logger.warning(
                    f"[Multi-Worker] Внимание: сервер запускается с workers={workers}, "
                    "но используется локальный MemoryBackplane. "
                    "WebSocket-сессии и Smart Cache изолированы внутри каждого процесса воркера! "
                    "Для синхронизации подключите распределенный Backplane (Redis/PG) или используйте workers=1."
                )

        try:
            from granian import Granian
        except ImportError:
            raise RuntimeError("Для запуска через app.run() установите granian: pip install granian")

        server = Granian(
            target=self,
            address=host,
            port=port,
            interface="rsgi",
            workers=workers,
            **granian_kwargs
        )
        server.serve()
