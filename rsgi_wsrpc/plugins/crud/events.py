# -*- coding: utf-8 -*-
"""
Уведомления об изменении данных (cache.patch) для реактивного CRUD в rsgi-wsrpc.
"""

from __future__ import annotations
from typing import Any, List, Optional, Union
import orjson
from rsgi_wsrpc.core.session import ACTIVE_SESSIONS_SET


async def notify_crud_change(
    model: str,
    record_id: Union[int, List[int]],
    kind: str,  # "created" | "updated" | "deleted"
    by_user: str,
    exclude_session: Optional[Any] = None
) -> None:
    """
    Безопасная рассылка уведомления об изменении данных (cache.patch).
    Передает только факт события и идентификаторы, без раскрытия значений колонок.
    """
    params: dict[str, Any] = {
        "model": model,
        "kind": kind,
        "by_user": by_user
    }
    if isinstance(record_id, list):
        params["ids"] = record_id
    else:
        params["id"] = record_id

    # Для обратной совместимости с фронтендом:
    if kind == "created":
        params["created"] = True
    elif kind == "deleted":
        params["deleted"] = True

    payload_str = orjson.dumps({
        "jsonrpc": "2.0",
        "method": "cache.patch",
        "params": params
    }).decode("utf-8")

    exclude_id = None
    if exclude_session:
        exclude_id = getattr(exclude_session, "session_id", None)

    for session in list(ACTIVE_SESSIONS_SET):
        if exclude_id is not None and getattr(session, "session_id", None) == exclude_id:
            continue

        try:
            if hasattr(session, "send_str"):
                await session.send_str(payload_str)
            elif hasattr(session, "ws") and session.ws and not getattr(session, "_closed", False):
                awaitable = session.ws.send_str(payload_str)
                if not hasattr(awaitable, "cancelled"):
                    try:
                        awaitable.cancelled = lambda: False
                    except AttributeError:
                        pass
                await awaitable
        except Exception:
            pass
