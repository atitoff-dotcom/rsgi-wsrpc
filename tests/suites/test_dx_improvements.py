# -*- coding: utf-8 -*-
"""
Тесты улучшений Developer Experience (DX):
1. Динамический ре-бинд базы данных (AsyncEngineProxy, configure_db).
2. Нативная бесшовная интеграция CRUD с JWT токенами фреймворка.
3. Защита от циклической рекурсии в get_crud_session.
4. Встроенный режим dev_admin=True.
5. Автоматическая авторизация сокетов auto_auth_ws.
6. send_stream_chunk alias в AuthSession.
"""

import pytest
import os
from unittest.mock import AsyncMock, MagicMock
from rsgi_wsrpc import RsgiWsrpcApp, configure
from rsgi_wsrpc.plugins.db import engine, async_session
from rsgi_wsrpc.plugins.db.session import configure_db
from rsgi_wsrpc.plugins.crud.auth import (
    get_crud_session, create_crud_session, set_crud_session_validator
)
from rsgi_wsrpc.plugins.auth.core import AuthSession
from rsgi_wsrpc.core.security import create_access_token


@pytest.mark.asyncio
async def test_async_engine_proxy_and_rebind():
    """Проверяет, что engine и async_session динамически переконфигурируются без смены ссылок."""
    # Запоминаем текущий url
    orig_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./data/app.db")
    
    # 1. Проверяем, что прокси имеет атрибуты AsyncEngine
    assert hasattr(engine, "begin")
    assert hasattr(engine, "connect")
    assert hasattr(engine, "sync_engine")
    
    try:
        # 2. Переконфигурируем движок
        configure_db("sqlite+aiosqlite:///:memory:")
        assert "memory" in str(engine.url) or "sqlite" in str(engine.url)
        
        # 3. Фабрика сессий успешно привязана к новому движку
        from sqlalchemy import text
        async with async_session() as db:
            res = await db.execute(text("SELECT 42"))
            assert res.scalar() == 42
    finally:
        configure_db("sqlite+aiosqlite:///app.db")


def test_crud_jwt_native_fallback():
    """Проверяет, что get_crud_session из коробки декодирует и признает валидные JWT-токены фреймворка."""
    # Генерируем JWT токен для админа
    token, _, _ = create_access_token(
        user_id=10,
        username="super_alex",
        user_agent="pytest-client",
        roles=["admin"]
    )
    
    # get_crud_session должен нативно валидировать JWT без всяких ручных валидаторов
    sdata = get_crud_session(token)
    assert sdata is not None
    assert sdata["role"] == "admin"
    assert sdata["username"] == "super_alex"
    assert sdata["uid"] == 10
    assert sdata["is_superadmin"] is True


def test_crud_session_recursion_guard():
    """Проверяет, что вызов get_crud_session внутри пользовательского валидатора не вызывает RecursionError."""
    # Симулируем наивный пользовательский валидатор, вызывающий get_crud_session
    def naive_validator(tok: str):
        # Этот вызов не должен зацикливаться
        cached = get_crud_session(tok)
        if cached:
            return cached
        return None

    set_crud_session_validator(naive_validator)
    try:
        # Для неизвестного токена не должно быть переполнения стека
        res = get_crud_session("unknown-fake-token")
        assert res is None
    finally:
        set_crud_session_validator(None)


@pytest.mark.asyncio
async def test_auth_session_send_stream_chunk_alias():
    """Проверяет наличие алиаса send_stream_chunk на AuthSession."""
    mock_cb = AsyncMock()
    sess = AuthSession(
        uid=1,
        user=None,
        user_name="admin",
        user_role="admin",
        user_roles=["admin"],
        session_db_id=0,
        send_stream_cb=mock_cb
    )
    await sess.send_stream_chunk(rpc_id=123, chunk={"chunk": 1})
    mock_cb.assert_awaited_once_with(123, {"chunk": 1})


@pytest.mark.asyncio
async def test_set_admin_password_and_cli():
    """Проверяет утилиту смены пароля администратора и отсутствие бэкдора /dev-admin."""
    from rsgi_wsrpc.plugins.db import async_session, engine, Base
    from rsgi_wsrpc.plugins.auth import User, Role, system_bypass_ctx
    from sqlalchemy import select

    # Инициализация тестовой БД
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            user = (await db.execute(select(User).where(User.login == "admin"))).scalar_one_or_none()
            if not user:
                user = User(login="admin", name="Admin", password_hash=User._hash_password("oldpass"))
                db.add(user)
                await db.commit()
    finally:
        system_bypass_ctx.reset(token)

    app = RsgiWsrpcApp()

    # 1. Проверяем, что роут /dev-admin больше не существует (возвращает 404)
    proto = MagicMock()
    scope = {"proto": "http", "method": "GET", "path": "/dev-admin", "headers": {}}
    await app._handle_http(scope, proto)
    assert proto.response_str.called
    assert proto.response_str.call_args.kwargs["status"] == 404

    # 2. Проверяем программную смену пароля
    pwd = await app.set_admin_password(login="admin", password="new_strong_password")
    assert pwd == "new_strong_password"

    t = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            user_check = (await db.execute(select(User).where(User.login == "admin"))).scalar_one()
            assert user_check.verify_password("new_strong_password") is True
            assert user_check.verify_password("oldpass") is False
    finally:
        system_bypass_ctx.reset(t)

    # 3. Проверяем ошибку при попытке смены пароля несуществующего пользователя (без DDL создания)
    with pytest.raises(ValueError) as exc_info:
        await app.set_admin_password(login="unknown_ghost_user")
    assert "не найден в базе данных" in str(exc_info.value)


def test_handle_cli():
    """Проверяет обработку CLI-флагов handle_cli."""
    from unittest.mock import patch, AsyncMock
    app = RsgiWsrpcApp()
    # 1. Нецелевые флаги возвращают False
    assert app.handle_cli(["--host", "0.0.0.0"]) is False
    assert app.handle_cli([]) is False

    # 2. Флаг --set-admin-password вызывает set_admin_password
    with patch.object(app, "set_admin_password", new_callable=AsyncMock) as mock_set:
        mock_set.return_value = "new_pass_123"
        handled = app.handle_cli(["--set-admin-password", "my_pass", "--login", "admin"])
        assert handled is True
        mock_set.assert_called_once_with(login="admin", password="my_pass")



@pytest.mark.asyncio
async def test_auto_auth_ws_on_connect():
    """Проверяет автоматическую авторизацию сокета по кукам при auto_auth_ws=True."""
    app = RsgiWsrpcApp(auto_auth_ws=True)
    
    # Создаем токен админа в памяти CRUD
    token = create_crud_session({"username": "boss", "role": "admin"})
    
    # Мок WebSocket handshake scope с кукой
    scope = {
        "proto": "websocket",
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"cookie", f"rsgi_crud_session={token}".encode("latin1"))
        ]
    }
    
    proto = MagicMock()
    ws_mock = AsyncMock()
    ws_mock.receive = AsyncMock(side_effect=Exception("RSGI transport is closed"))
    proto.accept = AsyncMock(return_value=ws_mock)
    
    connected_session = None
    @app.on_connect
    def hook(session):
        nonlocal connected_session
        connected_session = session

    await app._handle_websocket(scope, proto)
    
    assert connected_session is not None
    assert connected_session.data is not None
    assert connected_session.data.user_role == "admin"
    assert connected_session.data.user_name == "boss"
    assert connected_session.data.has_rpc_permission("any.method") is True
    await connected_session.close()
