# -*- coding: utf-8 -*-
"""
Официальный плагин поддержки произвольных и бинарных WebSocket-обработчиков (plugins/raw_ws).
Позволяет изолированно обрабатывать сырые двунаправленные протоколы по выделенным HTTP URL.
"""

from .id_gen import generate_session_id
from .session import RawWebSocketSession
from .router import raw_ws_route, RAW_WS_ROUTES
from .manager import (
    dispatch_raw_ws,
    get_session,
    send_to_session,
    broadcast_raw,
    ACTIVE_RAW_SESSIONS,
)

__all__ = [
    "generate_session_id",
    "RawWebSocketSession",
    "raw_ws_route",
    "RAW_WS_ROUTES",
    "dispatch_raw_ws",
    "get_session",
    "send_to_session",
    "broadcast_raw",
    "ACTIVE_RAW_SESSIONS",
]
