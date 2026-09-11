# -*- coding: utf-8 -*-
"""
WSRPC хендлеры для плагина Smart Cache (рукопожатие версий и инспекция кэша).
"""

from typing import Any, Dict
from core.session import rpc_method, JsonRpcSession, RPCError
from app.system.smart_cache.engine import version_registry, invalidate_tags


@rpc_method("cache.sync_check")
async def cache_sync_check(session: JsonRpcSession, params: Dict[str, Any]):
    """
    Рукопожатие версий кэша при подключении / реконнекте клиента (Sync Handshake).
    Клиент передает словарь сохраненных у него версий тегов:
    params = {"tags": {"forum.topics": 105, "profile": 12}}
    Сервер сравнивает с актуальными и возвращает список тех, которые устарели.
    """
    client_tags = params.get("tags", {})
    if not isinstance(client_tags, dict):
        raise RPCError("Параметр 'tags' должен быть словарем {tag_name: version}")

    diff = version_registry.compare_versions(client_tags)
    return diff


@rpc_method("cache.get_versions")
async def cache_get_versions(session: JsonRpcSession, params: Dict[str, Any]):
    """
    Возвращает актуальные версии для переданного списка тегов или для всех известных тегов.
    """
    requested_tags = params.get("tags")
    if requested_tags is not None and not isinstance(requested_tags, list):
        raise RPCError("Параметр 'tags' должен быть списком строк")

    versions = version_registry.get_all_versions(requested_tags)
    return {"versions": versions}


@rpc_method("cache.invalidate")
async def cache_invalidate_endpoint(session: JsonRpcSession, params: Dict[str, Any]):
    """
    Ручная инвалидация тегов кэша через RPC (для админ-панели или внутренних служб).
    """
    tags = params.get("tags")
    if not tags or not isinstance(tags, list):
        raise RPCError("Параметр 'tags' обязателен и должен быть непустым списком")

    reason = params.get("reason", "manual_rpc")
    new_versions = await invalidate_tags(tags, reason=reason)
    return {"status": "ok", "invalidated_tags": tags, "new_versions": new_versions}
