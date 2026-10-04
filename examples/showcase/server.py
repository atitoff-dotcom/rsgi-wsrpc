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
from rsgi_wsrpc import RsgiWsrpcApp
from core.logger import setup_logging, logger

# Путь к директории статики
PUBLIC_DIR = os.path.join(SHOWCASE_DIR, "public")

# Создание приложения Showcase на базе RsgiWsrpcApp
app = RsgiWsrpcApp(
    secret_key=os.getenv("SECRET_KEY", "showcase-demo-secret-key-12345"),
    database_url=os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{os.path.join(SHOWCASE_DIR, 'showcase.db')}"),
    login_rpc="",  # Открытый доступ для демонстрационного стенда
    static_dir=PUBLIC_DIR,
    index_file="index.html",
    cors=True
)

# Импорты плагина БД и моделей showcase
from plugins.db import engine, Base
from models import Task
import handlers  # Регистрация RPC-методов showcase

# Инициализация логирования
setup_logging()


@app.on_startup
async def init_database():
    """Асинхронно создает таблицы БД (SQLite) при старте сервера."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[Showcase] База данных SQLite успешно инициализирована.")
    except Exception as e:
        logger.error(f"[Showcase] Ошибка инициализации базы данных: {e}", exc_info=True)


@app.route("/health", ["GET"])
async def health_handler(scope, proto):
    """Healthcheck endpoint."""
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"ok","framework":"rsgi-wsrpc","showcase":"ready"}'
    )


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
