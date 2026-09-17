# -*- coding: utf-8 -*-
"""
Менеджер активных сырых WebSocket-сессий и диспетчер Granian RSGI соединений.
"""

import asyncio
import inspect
from typing import Dict, Optional, Union
from core.logger import logger

from .id_gen import generate_session_id
from .session import RawWebSocketSession
from .router import RAW_WS_ROUTES

# Глобальный O(1) реестр активных сырых сессий текущего воркера
ACTIVE_RAW_SESSIONS: Dict[int, RawWebSocketSession] = {}


def get_session(session_id: int) -> Optional[RawWebSocketSession]:
    """Возвращает активную сессию по ее целочисленному ID."""
    return ACTIVE_RAW_SESSIONS.get(session_id)


async def send_to_session(session_id: int, data: Union[bytes, str]) -> bool:
    """
    Отправляет бинарные или строковые данные в конкретную сессию по ее ID.
    Возвращает True, если отправка успешна.
    """
    session = ACTIVE_RAW_SESSIONS.get(session_id)
    if not session or session.is_closed:
        return False

    if isinstance(data, bytes):
        return await session.send_bytes(data)
    elif isinstance(data, str):
        return await session.send_str(data)
    else:
        logger.error(f"[RawWS] Неподдерживаемый тип данных для отправки: {type(data)}")
        return False


async def broadcast_raw(data: Union[bytes, str], path: Optional[str] = None, batch_size: int = 500) -> int:
    """
    Широковещательная рассылка сырых данных активным сессиям.
    Если указан path, рассылка выполняется только сессиям, подключенным к этому URL.
    """
    if not ACTIVE_RAW_SESSIONS:
        return 0

    is_binary = isinstance(data, bytes)
    sent_count = 0

    # Создаем срез сессий
    target_sessions = [
        s for s in list(ACTIVE_RAW_SESSIONS.values())
        if not s.is_closed and (path is None or s.scope.get("path") == path)
    ]

    for s in target_sessions:
        try:
            if is_binary:
                await s.send_bytes(data)
            else:
                await s.send_str(data)
            sent_count += 1
        except Exception:
            pass

        if sent_count % batch_size == 0:
            await asyncio.sleep(0)  # Уступаем квант времени планировщику

    return sent_count


async def dispatch_raw_ws(scope: dict, proto) -> bool:
    """
    Главный диспетчер плагина raw_ws.
    Вызывается в точке входа RSGI app(scope, proto) при scope.proto == 'websocket'.
    Если scope.path зарегистрирован в RAW_WS_ROUTES:
      1. Принимает сокетное соединение через proto.accept().
      2. Генерирует уникальный 64-битный session_id.
      3. Регистрирует сессию и запускает обработчик.
      4. Возвращает True (запрос полностью обработан плагином).
    Если роут не найден — возвращает False (управление передается стандартному WSRPC).
    """
    path = scope.get("path", "")
    route = RAW_WS_ROUTES.get(path)
    if not route:
        return False

    try:
        ws = await proto.accept()
        session_id = generate_session_id()
        session = RawWebSocketSession(ws=ws, session_id=session_id, scope=scope)

        # Регистрация в реестре текущего воркера
        ACTIVE_RAW_SESSIONS[session_id] = session

        # Автоматическая очистка реестра при обрыве/завершении
        def _cleanup(s):
            ACTIVE_RAW_SESSIONS.pop(s.session_id, None)

        session.on_close(_cleanup)

        # Если задан hook on_disconnect у маршрута
        if route.on_disconnect:
            session.on_close(route.on_disconnect)

        # Если задан hook on_connect у маршрута
        if route.on_connect:
            try:
                res = route.on_connect(session)
                if inspect.iscoroutinefunction(route.on_connect) or hasattr(res, "__await__"):
                    await res
            except Exception as conn_err:
                logger.error(f"[RawWS] Ошибка в on_connect хуке сессии {session_id}: {conn_err}", exc_info=True)

        # Запуск сокетного цикла обработки сообщений
        await session.run(route.handler)
        return True

    except asyncio.CancelledError:
        return True
    except Exception as e:
        logger.error(f"[RawWS] Сбой диспетчеризации сокета для {path}: {e}", exc_info=True)
        return True
