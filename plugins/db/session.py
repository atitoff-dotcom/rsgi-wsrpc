# -*- coding: utf-8 -*-
"""
Официальный плагин базы данных фреймворка rsgi-wsrpc (plugins/db).
Поддерживает асинхронную SQLAlchemy 2.0 (SQLite, PostgreSQL, MySQL) и orjson сериализацию.
"""

import os
import orjson
from typing import Any, Dict
from sqlalchemy import event, Select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# Базовый класс для декларативных ORM-моделей
class Base(DeclarativeBase):
    pass

# Определение URL подключения: env переменная или настройки приложения
_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    try:
        from app.config import settings as app_settings
        _db_url = getattr(app_settings, "database_url", None)
    except Exception:
        pass

if not _db_url:
    try:
        from core.lib.config import settings as core_settings
        _db_url = getattr(core_settings, "database_url", None)
    except Exception:
        pass

if not _db_url:
    _db_url = "sqlite:///./data/app.db"

DATABASE_URL = _db_url

# Адаптируем протоколы под асинхронные драйверы SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
elif DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+asyncmy://")
elif DATABASE_URL.startswith("sqlite://"):
    DATABASE_URL = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://")
    sqlite_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    dir_path = os.path.dirname(sqlite_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def orjson_dumps(val: Any) -> str:
    return orjson.dumps(val).decode("utf-8")


engine_kwargs: Dict[str, Any] = {
    "echo": False,
    "json_serializer": orjson_dumps,
    "json_deserializer": orjson.loads,
}

if "postgresql" in DATABASE_URL:
    pool_size = int(os.environ.get("DB_POOL_SIZE", "5"))
    max_overflow = int(os.environ.get("DB_MAX_OVERFLOW", "3"))
    pool_timeout = int(os.environ.get("DB_POOL_TIMEOUT", "30"))
    pool_recycle = int(os.environ.get("DB_POOL_RECYCLE", "1800"))
    engine_kwargs.update({
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
        "pool_recycle": pool_recycle,
        "pool_pre_ping": True,
    })

engine = create_async_engine(DATABASE_URL, **engine_kwargs)


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if "sqlite" in DATABASE_URL:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


# Создаем фабрику асинхронных сессий
async_session = async_sessionmaker(engine, expire_on_commit=False)


def apply_pagination(stmt: Select, args: Dict[str, Any]) -> Select:
    """
    Применяет пагинацию к запросу SQLAlchemy.
    Ожидает параметры внутри ключа '_pagination':
      {
        "_pagination": {
          "offset": int,
          "limit": int,
          "from": int,
          "to": int
        }
      }
    """
    pagination = args.get("_pagination")
    if not isinstance(pagination, dict):
        pagination = args

    offset_val = pagination.get("offset")
    limit_val = pagination.get("limit")

    if offset_val is None:
        offset_val = pagination.get("from")

    if limit_val is None and "to" in pagination:
        try:
            to_val = int(pagination["to"])
            off = int(offset_val) if offset_val is not None else 0
            limit_val = to_val - off
        except (ValueError, TypeError):
            pass

    if offset_val is not None:
        try:
            stmt = stmt.offset(int(offset_val))
        except (ValueError, TypeError):
            pass

    if limit_val is not None:
        try:
            stmt = stmt.limit(int(limit_val))
        except (ValueError, TypeError):
            pass

    return stmt
