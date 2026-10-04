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
        files_path: Optional[str] = None,
        login_rpc: Optional[str] = None,
        session_idle_timeout: Optional[int] = None,
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
        # Плагины
        enable_seo: bool = False,
        custom_settings: Optional[Dict[str, Any]] = None,
        **extra_settings: Any
    ):
        # 1. Применяем конфигурацию к ядру
        config_kwargs: Dict[str, Any] = {}
        if secret_key is not None:
            config_kwargs["secret_key"] = secret_key
        if database_url is not None:
            config_kwargs["database_url"] = database_url
        if files_path is not None:
            config_kwargs["files_path"] = files_path
        if login_rpc is not None:
            config_kwargs["login_rpc"] = login_rpc
        if session_idle_timeout is not None:
            config_kwargs["session_idle_timeout"] = session_idle_timeout
        if password_iterations is not None:
            config_kwargs["password_iterations"] = password_iterations
        if token_expire_hours is not None:
            config_kwargs["token_expire_hours"] = token_expire_hours
        if max_message_size is not None:
            config_kwargs.setdefault("custom", {})["max_message_size"] = max_message_size

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

        # Граниан связывает __rsgi_init__ и __rsgi_del__ на самом объекте приложения
        self.__rsgi_init__ = self._rsgi_init_handler
        self.__rsgi_del__ = self._rsgi_del_handler

    # --- ДЕКОРАТОРЫ ---

    def rpc(self, name: Optional[str] = None, role: Optional[Any] = None, http: bool = False, public: bool = False):
        """Декоратор для регистрации JSON-RPC метода."""
        return rpc_method(name=name, role=role, http=http, public=public)

    def route(self, path: str, methods: Optional[List[str]] = None):
        """Декоратор для регистрации HTTP-обработчика."""
        return http_route(path=path, methods=methods)

    def on_startup(self, func: Callable):
        """Регистрирует хук запуска приложения."""
        return on_startup(func)

    def on_shutdown(self, func: Callable):
        """Регистрирует хук завершения приложения."""
        return on_shutdown(func)

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

        if proto_type == "websocket":
            await self._handle_websocket(scope, proto)
            return

        # Неизвестный протокол
        logger.warning(f"[RsgiWsrpcApp] Неизвестный тип протокола: {proto_type}")

    async def _handle_http(self, scope, proto):
        method = getattr(scope, "method", "GET")
        path = getattr(scope, "path", "/")

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
                from .plugins.seo.detector import is_search_bot
                from .plugins.seo.router import handle_bot_http
                user_agent = ""
                for k, v in getattr(scope, "headers", []):
                    if k.lower() == "user-agent":
                        user_agent = v
                        break
                if is_search_bot(user_agent):
                    if await handle_bot_http(scope, proto):
                        return
            except ImportError:
                pass
            except Exception as e:
                logger.error(f"[RsgiWsrpcApp] Ошибка SEO перехвата: {e}", exc_info=True)

        # 3. Маршрутизация по зарегистрированным HTTP_ROUTES
        for route_path, methods, handler in HTTP_ROUTES:
            if path == route_path and method in methods:
                await handler(scope, proto)
                return

        # 4. Отдача index.html на корневой GET /
        if method == "GET" and path == "/" and self.index_file and os.path.exists(self.index_file):
            self._serve_static_file(proto, self.index_file)
            return

        # 5. Раздача статики из static_dir
        if method == "GET" and self.static_dir:
            # Путь либо с префиксом (/static/css/app.css), либо прямой
            rel_path = None
            if path.startswith(self.static_prefix):
                rel_path = path[len(self.static_prefix):].lstrip("/")
            
            if rel_path:
                safe_full_path = os.path.abspath(os.path.join(self.static_dir, rel_path))
                # Защита от Path Traversal
                if safe_full_path.startswith(self.static_dir) and os.path.isfile(safe_full_path):
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

            session = JsonRpcSession(ws, session_id, ip=client_ip)
            await session.start()
        except asyncio.CancelledError:
            pass
        except Exception as e:
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
