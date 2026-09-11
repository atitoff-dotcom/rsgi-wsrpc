# -*- coding: utf-8 -*-

import orjson
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# База данных и ORM используются на уровне бизнес-логики приложения.
# Настройки подключения (database_url) импортируются из app.config.
from app.config import settings

DATABASE_URL = settings.database_url
if not DATABASE_URL:
    raise ValueError("Критическая ошибка: database_url не задан в конфигурации!")

# Адаптируем протоколы под асинхронные драйверы SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://")
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
elif DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+asyncmy://")
elif DATABASE_URL.startswith("sqlite://"):
    DATABASE_URL = DATABASE_URL.replace("sqlite://", "sqlite+aiosqlite://")
    import os
    sqlite_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
    dir_path = os.path.dirname(sqlite_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def orjson_dumps(val):
    return orjson.dumps(val).decode('utf-8')

# Создаем асинхронный движок подключения к БД
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    json_serializer=orjson_dumps,
    json_deserializer=orjson.loads
)

from sqlalchemy import event

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

# Базовый класс для декларативных ORM-моделей
class Base(DeclarativeBase):
    pass


from typing import Any, Dict
from sqlalchemy import Select

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
    # 1. Извлекаем словарь пагинации
    pagination = args.get("_pagination")
    if not isinstance(pagination, dict):
        # Обратная совместимость: если _pagination нет, ищем в корне
        pagination = args

    # 2. Получаем значения
    offset_val = pagination.get("offset")
    limit_val = pagination.get("limit")
    
    # 3. Поддержка legacy from/to
    if offset_val is None:
        offset_val = pagination.get("from")
        
    if limit_val is None and "to" in pagination:
        try:
            to_val = int(pagination["to"])
            off = int(offset_val) if offset_val is not None else 0
            limit_val = to_val - off
        except (ValueError, TypeError):
            pass

    # 4. Применяем к запросу
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

