# -*- coding: utf-8 -*-
"""
Маршрутизатор сырых/бинарных WebSocket-роутов по URL путям.
"""

from typing import Callable, Dict, Optional, NamedTuple


class RawWSRoute(NamedTuple):
    path: str
    handler: Callable
    on_connect: Optional[Callable] = None
    on_disconnect: Optional[Callable] = None


RAW_WS_ROUTES: Dict[str, RawWSRoute] = {}


def raw_ws_route(path: str) -> Callable:
    """
    Декоратор для регистрации сырого WebSocket-обработчика по заданному URL пути.

    Пример использования:
    --------------------
    @raw_ws_route("/ws/telemetry")
    async def on_telemetry(session_id: int, data: bytes, session: RawWebSocketSession):
        await session.send_bytes(b"ack")

    @on_telemetry.on_connect
    async def on_connect(session: RawWebSocketSession):
        logger.info(f"Устройство подключено: {session.session_id}")

    @on_telemetry.on_disconnect
    async def on_disconnect(session: RawWebSocketSession):
        logger.info(f"Устройство отключилось: {session.session_id}")
    """
    def decorator(handler: Callable) -> Callable:
        RAW_WS_ROUTES[path] = RawWSRoute(path=path, handler=handler)

        def on_connect_dec(on_conn_fn: Callable) -> Callable:
            current = RAW_WS_ROUTES[path]
            RAW_WS_ROUTES[path] = current._replace(on_connect=on_conn_fn)
            return on_conn_fn

        def on_disconnect_dec(on_disc_fn: Callable) -> Callable:
            current = RAW_WS_ROUTES[path]
            RAW_WS_ROUTES[path] = current._replace(on_disconnect=on_disc_fn)
            return on_disc_fn

        handler.on_connect = on_connect_dec
        handler.on_disconnect = on_disconnect_dec
        return handler

    return decorator
