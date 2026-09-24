# -*- coding: utf-8 -*-
"""
Smart Cache Engine: Реестр версий сущностей, инвалидация и патчи в реальном времени.
Официальный плагин rsgi-wsrpc (plugins/smart_cache).
Реализует RFC 0001: Event-Driven Feedback Caching.
"""

import asyncio
import inspect
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from sqlalchemy import Column, DateTime, Integer, String, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from rsgi_wsrpc.plugins.db import Base, async_session, engine
from rsgi_wsrpc.plugins.broadcast import broadcast_notification
from rsgi_wsrpc.core.lifecycle import on_startup
from rsgi_wsrpc.core.logger import logger


class CacheTagVersion(Base):
    """
    Модель персистентного хранения версий тегов кэша в базе данных.
    Позволяет сохранять монотонность версий после перезапуска сервера.
    """
    __tablename__ = "cache_tag_versions"

    tag = Column(String(128), primary_key=True)
    version = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class VersionRegistry:
    """
    Потокобезопасный реестр версий тегов кэша в оперативной памяти с поддержкой персистентности.
    """

    def __init__(self):
        self._versions: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """
        Инициализация таблицы в БД и загрузка текущих версий в оперативную память.
        Вызывается при старте сервера через @on_startup.
        """
        if self._initialized:
            return

        try:
            # Создаем таблицу, если ее еще нет в базе
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all, tables=[CacheTagVersion.__table__])

            # Загружаем существующие версии в память
            async with async_session() as db:
                result = await db.execute(select(CacheTagVersion.tag, CacheTagVersion.version))
                for tag, version in result.all():
                    self._versions[tag] = version

            self._initialized = True
            logger.info(f"[SmartCache] Реестр версий инициализирован. Загружено тегов: {len(self._versions)}")
        except Exception as e:
            logger.error(f"[SmartCache] Ошибка инициализации реестра версий: {e}", exc_info=True)

    def get_version(self, tag: str) -> int:
        """Получить текущую версию тега (синхронно, 0 мс из памяти)."""
        return self._versions.get(tag, 1)

    def get_all_versions(self, tags: Optional[List[str]] = None) -> Dict[str, int]:
        """Получить словарь версий для списка тегов или для всех известных тегов."""
        if tags is None:
            return dict(self._versions)
        return {t: self._versions.get(t, 1) for t in tags}

    async def bump_versions(self, tags: List[str]) -> Dict[str, int]:
        """
        Монотонно инкрементирует версию для указанных тегов и сохраняет изменения в БД.
        Возвращает обновленный словарь {tag: new_version}.
        """
        if not tags:
            return {}

        new_versions: Dict[str, int] = {}
        async with self._lock:
            for tag in tags:
                current_ver = self._versions.get(tag, 1)
                new_ver = current_ver + 1
                self._versions[tag] = new_ver
                new_versions[tag] = new_ver

        # Асинхронно сохраняем новые версии в БД
        asyncio.create_task(self._persist_versions(new_versions))
        return new_versions

    async def _persist_versions(self, versions: Dict[str, int]):
        """Сохранение версий в базу данных (upsert)."""
        try:
            async with async_session() as db:
                for tag, ver in versions.items():
                    try:
                        # Попытка через SQLite dialect insert on_conflict
                        stmt = sqlite_insert(CacheTagVersion).values(
                            tag=tag,
                            version=ver,
                            updated_at=datetime.now(timezone.utc)
                        ).on_conflict_do_update(
                            index_elements=["tag"],
                            set_={"version": ver, "updated_at": datetime.now(timezone.utc)}
                        )
                        await db.execute(stmt)
                    except Exception:
                        # Универсальный fallback для других СУБД (PostgreSQL / MySQL)
                        existing = await db.get(CacheTagVersion, tag)
                        if existing:
                            existing.version = ver
                            existing.updated_at = datetime.now(timezone.utc)
                        else:
                            db.add(CacheTagVersion(tag=tag, version=ver, updated_at=datetime.now(timezone.utc)))
                await db.commit()
        except Exception as e:
            logger.warning(f"[SmartCache] Предупреждение при сохранении версий тегов в БД: {e}")

    def compare_versions(self, client_manifest: Dict[str, int]) -> Dict[str, Any]:
        """
        Сравнивает версии тегов клиента с актуальными версиями сервера.
        Возвращает список устаревших тегов и актуальные версии.
        """
        stale_tags = []
        current_versions = {}

        for tag, client_ver in client_manifest.items():
            server_ver = self.get_version(tag)
            current_versions[tag] = server_ver
            if server_ver > client_ver:
                stale_tags.append(tag)

        return {
            "stale_tags": stale_tags,
            "current_versions": current_versions,
        }


# Глобальный реестр версий
version_registry = VersionRegistry()


@on_startup
async def _init_smart_cache():
    """Хук стартапа сервера rsgi-wsrpc."""
    await version_registry.initialize()


async def invalidate_tags(
    tags: List[str],
    reason: str = "mutation",
    exclude_current: bool = False,
) -> Dict[str, int]:
    """
    Программная инвалидация тегов кэша:
    1. Инкрементирует монотонные версии тегов.
    2. Рассылает всем клиентам событие cache.invalidate.
    """
    if not tags:
        return {}

    new_versions = await version_registry.bump_versions(tags)
    logger.info(f"[SmartCache] Инвалидация тегов: {tags}, новые версии: {new_versions}")

    await broadcast_notification(
        method="cache.invalidate",
        params={
            "tags": tags,
            "versions": new_versions,
            "reason": reason,
        },
        exclude_current=exclude_current,
    )
    return new_versions


async def patch_tag(
    tag: str,
    action: str,
    data: Any,
    field: Optional[str] = None,
    exclude_current: bool = False,
) -> int:
    """
    Отправляет клиентам точечный патч данных (append, update, remove, increment):
    Данные встраиваются в локальный кэш браузера без повторного сетевого запроса к БД.
    """
    new_versions = await version_registry.bump_versions([tag])
    new_version = new_versions.get(tag, 1)

    logger.info(f"[SmartCache] Патч тега '{tag}' (действие: {action}, версия: {new_version})")

    await broadcast_notification(
        method="cache.patch",
        params={
            "tag": tag,
            "action": action,
            "field": field,
            "data": data,
            "version": new_version,
        },
        exclude_current=exclude_current,
    )
    return new_version


def _resolve_tag_template(template: str, context: Dict[str, Any]) -> Optional[str]:
    """
    Разрешает плейсхолдеры вида {var}, {obj.field} или {a|b} в шаблоне тега.
    Примеры:
      'forum.topics' -> 'forum.topics'
      'forum.category.{category_id}' -> 'forum.category.5'
      'forum.topic.{topic_id|id}' -> 'forum.topic.42'
      'articles.{slug}' -> 'articles.tomato-guide'
    Если какой-либо обязательный плейсхолдер не найден или пуст, возвращает None (тег пропускается).
    """
    if not isinstance(template, str):
        return None
    if "{" not in template:
        return template

    pattern = re.compile(r"\{([a-zA-Z0-9_.:|-]+)\}")
    matches = pattern.findall(template)
    formatted = template

    for var_expr in matches:
        candidates = [c.strip() for c in var_expr.split("|")]
        val = None
        for c in candidates:
            curr = context
            for part in c.split("."):
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                elif hasattr(curr, part):
                    curr = getattr(curr, part)
                else:
                    curr = None
                    break
            if curr is not None and curr != "":
                val = curr
                break

        if val is None or val == "":
            return None

        formatted = formatted.replace(f"{{{var_expr}}}", str(val))

    return formatted


def invalidates(
    tags: Union[List[str], str, Callable[..., List[str]]],
    exclude_current: bool = False,
    reason: str = "mutation",
):
    """
    Декоратор для RPC-хендлеров, автоматически инвалидирующий кэш при успешном выполнении.
    Поддерживает декларативные строковые шаблоны с автоматической подстановкой из params и result.
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)

            # Извлекаем params из аргументов хендлера (сессия обычно args[0], params args[1])
            params = {}
            if len(args) > 1 and isinstance(args[1], dict):
                params = args[1]
            elif kwargs.get("params") and isinstance(kwargs["params"], dict):
                params = kwargs["params"]
            elif len(args) > 0 and isinstance(args[0], dict):
                params = args[0]

            # Формируем контекст разрешения шаблонов из params и result
            context: Dict[str, Any] = {"params": params, "result": result}
            if isinstance(params, dict):
                for k, v in params.items():
                    if k not in context:
                        context[k] = v
            if isinstance(result, dict):
                for k, v in result.items():
                    context[f"result.{k}"] = v
                    if k not in context:
                        context[k] = v

            # Вычисляем список сырых тегов для инвалидации
            raw_tags: List[str] = []
            if callable(tags):
                try:
                    sig = inspect.signature(tags)
                    if len(sig.parameters) >= 2:
                        res_tags = tags(params, result)
                    else:
                        res_tags = tags(params)

                    if isinstance(res_tags, list):
                        raw_tags = res_tags
                    elif isinstance(res_tags, str):
                        raw_tags = [res_tags]
                except Exception as e:
                    logger.error(f"[SmartCache] Ошибка вычисления тегов инвалидации в {func.__name__}: {e}")
            elif isinstance(tags, list):
                raw_tags = list(tags)
            elif isinstance(tags, str):
                raw_tags = [tags]

            # Разрешаем строковые шаблоны тегов
            resolved_tags: List[str] = []
            seen = set()
            for t in raw_tags:
                tag_str = _resolve_tag_template(t, context)
                if tag_str and tag_str not in seen:
                    seen.add(tag_str)
                    resolved_tags.append(tag_str)

            if resolved_tags:
                await invalidate_tags(
                    tags=resolved_tags,
                    reason=reason,
                    exclude_current=exclude_current,
                )

            return result

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


__all__ = [
    "CacheTagVersion",
    "VersionRegistry",
    "version_registry",
    "invalidate_tags",
    "patch_tag",
    "invalidates",
]
