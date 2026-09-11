# -*- coding: utf-8 -*-
"""
Модуль для широковещательных рассылок (Broadcast) через WebSockets активным клиентам.
Не изменяет ядро core/, использует экспортируемый ACTIVE_SESSIONS_SET.
"""

import asyncio
from typing import List, Dict, Any, Optional
import orjson

from core.session import ACTIVE_SESSIONS_SET, current_transport_ctx
from core.logger import logger


async def _safe_send(session, payload_str: str) -> bool:
    try:
        if getattr(session, "_closed", True) or not getattr(session, "ws", None):
            return False
        awaitable = session.ws.send_str(payload_str)
        if not hasattr(awaitable, "cancelled"):
            try:
                awaitable.cancelled = lambda: False
            except AttributeError:
                pass
        await awaitable
        return True
    except Exception as e:
        logger.debug(f"[Broadcast] Ошибка отправки в сессию {getattr(session, 'session_id', '?')}: {e}")
        return False


async def broadcast_notification(
    method: str,
    params: Optional[Dict[str, Any]] = None,
    exclude_current: bool = False,
) -> int:
    """
    Рассылает JSON-RPC нотификацию (без 'id') всем активным WebSocket клиентам.
    Оверхед близок к 0: данные сериализуются один раз и отправляются в память сокетов.
    """
    if not ACTIVE_SESSIONS_SET:
        return 0

    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {}
    }
    payload_str = orjson.dumps(payload).decode("utf-8")

    current_transport = current_transport_ctx.get() if exclude_current else None

    # Делаем снимок текущих сессий
    sessions = list(ACTIVE_SESSIONS_SET)
    tasks = []
    for s in sessions:
        if current_transport and s == current_transport:
            continue
        tasks.append(_safe_send(s, payload_str))

    if not tasks:
        return 0

    results = await asyncio.gather(*tasks, return_exceptions=True)
    sent_count = sum(1 for r in results if r is True)
    logger.debug(f"[Broadcast] {method} отправлен {sent_count} клиентам")
    return sent_count


async def broadcast_cache_invalidate(
    tags: List[str],
    reason: str = "mutation",
    exclude_current: bool = False,
) -> int:
    """
    Оповещает клиентов о необходимости инвалидировать кэш по тегам.
    Например: tags = ["forum.topics", "forum.category.2"]
    """
    return await broadcast_notification(
        method="cache.invalidate",
        params={
            "tags": tags,
            "reason": reason,
        },
        exclude_current=exclude_current,
    )


async def broadcast_cache_patch(
    key: str,
    action: str,
    data: Dict[str, Any],
    exclude_current: bool = False,
) -> int:
    """
    Оповещает клиентов о точечном изменении данных сущности без перезагрузки всей страницы.
    Например: key = "forum.topic.15", action = "append_reply", data = {...}
    """
    return await broadcast_notification(
        method="cache.patch",
        params={
            "key": key,
            "action": action,
            "data": data,
        },
        exclude_current=exclude_current,
    )
