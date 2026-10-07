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

# Определение URL подключения: env переменная или настройки ядра rsgi-wsrpc
_db_url = os.environ.get("DATABASE_URL")
if not _db_url:
    try:
        from rsgi_wsrpc.core.lib.config import settings as core_settings
        _db_url = getattr(core_settings, "database_url", None)
    except Exception:
        pass

if not _db_url:
    _db_url = "sqlite:///./data/app.db"

def _normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://")
    elif url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://")
    elif url.startswith("mysql://"):
        return url.replace("mysql://", "mysql+asyncmy://")
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://")
        sqlite_path = url.replace("sqlite+aiosqlite:///", "")
        dir_path = os.path.dirname(sqlite_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
    return url


def orjson_dumps(val: Any) -> str:
    return orjson.dumps(val).decode("utf-8")


_db_echo = os.environ.get("DB_ECHO", "").lower() in ("true", "1", "yes")
if not _db_echo:
    try:
        from rsgi_wsrpc.core.lib.config import settings as core_settings
        _db_echo = bool(getattr(core_settings, "db_echo", False))
    except Exception:
        pass


def _build_engine(raw_url: str, echo: bool = False):
    norm_url = _normalize_database_url(raw_url)
    engine_kwargs: Dict[str, Any] = {
        "echo": echo,
        "json_serializer": orjson_dumps,
        "json_deserializer": orjson.loads,
    }
    if "postgresql" in norm_url:
        engine_kwargs.update({
            "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
            "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "3")),
            "pool_timeout": int(os.environ.get("DB_POOL_TIMEOUT", "30")),
            "pool_recycle": int(os.environ.get("DB_POOL_RECYCLE", "1800")),
            "pool_pre_ping": True,
        })
    eng = create_async_engine(norm_url, **engine_kwargs)
    if "sqlite" in norm_url:
        @event.listens_for(eng.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return eng


DATABASE_URL = _normalize_database_url(_db_url)
_active_engine = _build_engine(DATABASE_URL, _db_echo)


class AsyncEngineProxy:
    """Динамический прокси для AsyncEngine, устраняющий зависимость от порядка импортов."""
    def __getattr__(self, name: str) -> Any:
        return getattr(_active_engine, name)

    def __repr__(self) -> str:
        return repr(_active_engine)


engine: Any = AsyncEngineProxy()

# Создаем фабрику асинхронных сессий
async_session = async_sessionmaker(_active_engine, expire_on_commit=False)


def configure_db(database_url: Optional[str] = None, echo: Optional[bool] = None) -> None:
    """
    Динамически переконфигурирует движок и фабрику сессий SQLAlchemy.
    Вызывается автоматически при создании RsgiWsrpcApp(database_url=...) или configure().
    """
    global DATABASE_URL, _active_engine, async_session
    if database_url:
        DATABASE_URL = _normalize_database_url(database_url)
        os.environ["DATABASE_URL"] = DATABASE_URL
    current_echo = echo if echo is not None else _db_echo
    _active_engine = _build_engine(DATABASE_URL, current_echo)
    async_session.configure(bind=_active_engine)


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
