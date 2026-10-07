# -*- coding: utf-8 -*-
"""
Тест-сьют: Mission Control Cockpit (/admin/system RPC Handlers).
Проверяет системные методы управления:
1. admin.sessions_list и admin.session_kill (Kick/Kill)
2. system.cache_stats и system.cache_invalidate (RFC 0001)
3. system.broadcast (Zero-copy broadcast)
4. system.recent_logs (Live Log Streamer из оперативной памяти)
5. system.get_config (Runtime Config с маскированием секретов)
6. Защиту прав доступа (доступ только администратору)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from rsgi_wsrpc.core.session import (
    JsonRpcSession,
    ACTIVE_SESSIONS_SET,
    RPC_REGISTRY,
    RPCError,
)
from rsgi_wsrpc.core.logger import logger, get_recent_logs
from rsgi_wsrpc.plugins.crud.admin_handlers import (
    list_active_sessions,
    kill_session,
    get_cache_stats,
    invalidate_cache_tags,
    send_system_broadcast,
    stream_recent_logs,
    get_system_config,
)


class MockAdminSession:
    session_id = 999
    ip = "127.0.0.1"
    data = {"username": "admin", "role": "admin"}


class MockUserSession:
    session_id = 111
    ip = "192.168.1.50"
    data = {"username": "vasya", "role": "user"}


@pytest.mark.asyncio
async def test_admin_handlers_access_control():
    """Проверяет строгую защиту системных методов от не-администраторов."""
    guest_session = None
    user_session = MockUserSession()

    # 1. Гость не может вызывать системные методы
    with pytest.raises(RPCError) as exc:
        await list_active_sessions(guest_session)
    assert exc.value.code == -32000

    # 2. Обычный пользователь (не admin) получает ошибку доступа
    with pytest.raises(RPCError) as exc:
        await list_active_sessions(user_session)
    assert exc.value.code == -32003

    with pytest.raises(RPCError) as exc:
        await get_cache_stats(user_session)
    assert exc.value.code == -32003

    with pytest.raises(RPCError) as exc:
        await send_system_broadcast(user_session, message="Hello")
    assert exc.value.code == -32003


@pytest.mark.asyncio
async def test_admin_sessions_list_and_kill():
    """Проверяет мониторинг активных сессий и kick/kill."""
    admin = MockAdminSession()
    
    # Создаем фейковую клиентскую сессию
    ws_mock = MagicMock()
    ws_mock.receive = AsyncMock()
    client_session = JsonRpcSession(ws_mock, session_id=777, ip="10.0.0.1")
    client_session.data = {"username": "client_test", "role": "user"}
    
    try:
        # Список сессий
        sessions = await list_active_sessions(admin)
        assert isinstance(sessions, list)
        found = next((s for s in sessions if s["session_id"] == 777), None)
        assert found is not None
        assert found["username"] == "client_test"
        assert found["ip"] == "10.0.0.1"

        # Попытка кикнуть самого себя (администратора) должна завершиться ошибкой
        with pytest.raises(RPCError) as exc:
            await kill_session(admin, session_id=admin.session_id)
        assert exc.value.code == -32602

        # Успешный kick клиентской сессии
        res = await kill_session(admin, session_id=777)
        assert res["status"] == "ok"
        assert res["session_id"] == 777
        assert client_session._closed is True
    finally:
        ACTIVE_SESSIONS_SET.discard(client_session)


@pytest.mark.asyncio
async def test_system_cache_stats_and_invalidate():
    """Проверяет инспекцию и сброс тегов Smart Cache."""
    admin = MockAdminSession()

    # Инспекция тегов
    stats = await get_cache_stats(admin)
    assert isinstance(stats, list)

    # Инвалидация
    res = await invalidate_cache_tags(admin, tags=["admin_test_tag"])
    assert res["status"] == "ok"
    assert "admin_test_tag" in res["invalidated_tags"]
    assert res["invalidated_tags"]["admin_test_tag"] >= 2


@pytest.mark.asyncio
async def test_system_broadcast():
    """Проверяет отправку системного оповещения."""
    admin = MockAdminSession()

    res = await send_system_broadcast(admin, message="Внимание! Рестарт через 5 минут", level="warning")
    assert res["status"] == "ok"
    assert "delivered_count" in res


@pytest.mark.asyncio
async def test_system_recent_logs():
    """Проверяет чтение логов из оперативной памяти сервера."""
    admin = MockAdminSession()

    logger.info("Test admin log entry for memory buffer")
    logs = await stream_recent_logs(admin, limit=50)
    assert isinstance(logs, list)
    assert len(logs) > 0
    
    last = logs[-1]
    assert "message" in last
    assert "timestamp" in last
    assert "level" in last


@pytest.mark.asyncio
async def test_system_get_config_masks_secrets():
    """Проверяет получение настроек ядра и маскирование секретов."""
    admin = MockAdminSession()

    conf = await get_system_config(admin)
    assert isinstance(conf, dict)
    assert "security" in conf
    secret_key = conf["security"].get("secret_key", "")
    assert "••••••••" in secret_key, "Secret key must be masked!"
