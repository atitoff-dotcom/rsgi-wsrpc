# -*- coding: utf-8 -*-
"""
Главная точка входа демонстрационного сервера Showcase (rsgi-wsrpc).
Запуск:
    python server.py
Сервер будет доступен по адресу: http://127.0.0.1:8080
"""

import os
import sys
import asyncio
from itertools import count

# Гарантируем, что корень rsgi-wsrpc и директория showcase доступны для импорта
SHOWCASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.abspath(os.path.join(SHOWCASE_DIR, "..", ".."))

if FRAMEWORK_ROOT not in sys.path:
    sys.path.insert(0, FRAMEWORK_ROOT)
if SHOWCASE_DIR not in sys.path:
    sys.path.insert(0, SHOWCASE_DIR)

# Импорты ядра rsgi-wsrpc
from core.session import JsonRpcSession, rpc_method
from core.router import http_route, HTTP_ROUTES
from core.logger import setup_logging, logger
from core.lifecycle import on_startup, run_startup_callbacks

# Импорты плагина БД и моделей showcase
from plugins.db import engine, Base
from models import Task
import handlers  # Регистрация RPC-методов showcase

# Инициализация логирования
setup_logging()

# Сессионный счетчик сокетов
GLOBAL_SESSION_COUNTER = count()

# Путь к директории статики
PUBLIC_DIR = os.path.join(SHOWCASE_DIR, "public")


@on_startup
async def init_database():
    """Асинхронно создает таблицы БД (SQLite) при старте сервера."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[Showcase] База данных SQLite успешно инициализирована.")
    except Exception as e:
        logger.error(f"[Showcase] Ошибка инициализации базы данных: {e}", exc_info=True)


@http_route("/", ["GET"])
async def index_handler(scope, proto):
    """Отдает интерфейс демонстрационной панели управления."""
    index_file = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            html_content = f.read()
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "text/html; charset=utf-8"),
                ("cache-control", "no-cache")
            ],
            body=html_content
        )
    else:
        proto.response_str(
            status=404,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body="index.html not found"
        )


@http_route("/health", ["GET"])
async def health_handler(scope, proto):
    """Healthcheck endpoint."""
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"ok","framework":"rsgi-wsrpc","showcase":"ready"}'
    )


def __rsgi_init__(loop):
    """Вызывается Granian при старте рабочего процесса."""
    try:
        loop.run_until_complete(run_startup_callbacks())
    except Exception as e:
        logger.critical(f"[Showcase] Сбой при инициализации: {e}", exc_info=True)
        sys.exit(1)


async def app(scope, proto):
    """
    Главный асинхронный RSGI-обработчик запросов Granian.
    Разделяет входящие потоки на HTTP и WebSocket (WSRPC).
    """
    # 1. Обработка HTTP-запросов
    if scope.proto == "http":
        if scope.method == "OPTIONS":
            proto.response_str(
                status=204,
                headers=[
                    ("access-control-allow-origin", "*"),
                    ("access-control-allow-methods", "GET, POST, OPTIONS"),
                    ("access-control-allow-headers", "content-type"),
                ],
                body=""
            )
            return

        for route_path, methods, handler in HTTP_ROUTES:
            if scope.path == route_path and scope.method in methods:
                await handler(scope, proto)
                return

        proto.response_str(
            status=404,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body="404 Not Found"
        )
        return

    # 2. Обработка WSRPC WebSocket-соединений
    if scope.proto == "websocket":
        try:
            ws = await proto.accept()
            session_id = next(GLOBAL_SESSION_COUNTER)
            session = JsonRpcSession(ws, session_id)
            await session.start()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[Showcase WS] Ошибка сокет-сессии: {e}", exc_info=True)
        return


app.__rsgi_init__ = __rsgi_init__


if __name__ == "__main__":
    from granian import Granian
    host = "127.0.0.1"
    port = 8080

    print("=" * 65)
    print(" 🚀 rsgi-wsrpc Showcase Server")
    print(f" 🌐 Web UI:   http://{host}:{port}/")
    print(f" 🔌 WSRPC:    ws://{host}:{port}/")
    print(" 📖 Нажмите Ctrl+C для остановки сервера")
    print("=" * 65)

    server = Granian(
        "server:app",
        address=host,
        port=port,
        interface="rsgi",
        reload=False,
        workers=1,
    )
    server.serve()
