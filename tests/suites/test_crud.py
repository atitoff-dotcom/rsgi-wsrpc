# -*- coding: utf-8 -*-
"""
Тест-сьют: Универсальный CRUD-плагин (plugins/crud).
Проверяет:
1. Интроспекцию моделей и декларативные настройки class Crud:.
2. Сокрытие конфиденциальных полей (password, hash, secret, token).
3. Валидацию и приведение типов ячеек (coerce_value).
4. Capability-based политику доступа (DefaultAccessPolicy).
5. Полный цикл операций (schema, create, list с $tabular, get, update_cell, delete).
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy import Integer, String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from rsgi_wsrpc.core.session import RPCError, JsonRpcSession
from rsgi_wsrpc.plugins.db import Base
from rsgi_wsrpc.plugins.crud import (
    ModelRegistry,
    ModelMeta,
    FieldMeta,
    build_model_meta,
    is_sensitive_field,
    coerce_value,
    DefaultIdentityProvider,
    DefaultAccessPolicy,
    AccessContext,
    set_identity_provider,
    set_access_policy,
    handle_crud_schema,
    handle_crud_create,
    handle_crud_list,
    handle_crud_get,
    handle_crud_update_cell,
    handle_crud_delete,
)


class DummyTask(Base):
    __tablename__ = "test_crud_dummy_tasks"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str] = mapped_column(String(200), default="secret123")
    owner_id: Mapped[int] = mapped_column(Integer, nullable=True)

    class Crud:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        protected = {"owner_id"}


def test_sensitive_field_detection():
    assert is_sensitive_field("password")
    assert is_sensitive_field("password_hash")
    assert is_sensitive_field("api_token")
    assert is_sensitive_field("secret_key")
    assert is_sensitive_field("client_private_key")
    assert not is_sensitive_field("title")
    assert not is_sensitive_field("owner_id")


def test_model_meta_introspection():
    meta = build_model_meta(DummyTask)
    assert meta.key == "DummyTask"
    assert meta.verbose_name == "Задача"
    assert meta.verbose_name_plural == "Задачи"
    assert meta.is_row_secure is True

    # password_hash должно быть автоматически скрыто
    assert meta.fields["password_hash"].hidden is True
    public_fields = [f.name for f in meta.get_public_fields()]
    assert "password_hash" not in public_fields
    assert "title" in public_fields
    assert "owner_id" in meta.protected_fields


def test_coerce_value():
    f_int = FieldMeta(name="count", type="integer", label="Количество")
    assert coerce_value(f_int, "42") == 42
    assert coerce_value(f_int, 42) == 42
    with pytest.raises(RPCError):
        coerce_value(f_int, "not-an-int")

    f_bool = FieldMeta(name="is_done", type="boolean", label="Выполнено")
    assert coerce_value(f_bool, "true") is True
    assert coerce_value(f_bool, 1) is True
    assert coerce_value(f_bool, "0") is False

    f_enum = FieldMeta(name="status", type="enum", label="Статус", options=["open", "closed"])
    assert coerce_value(f_enum, "open") == "open"
    with pytest.raises(RPCError):
        coerce_value(f_enum, "unknown_status")


class MockSession:
    def __init__(self, user_id=1, username="admin", is_admin=True):
        self.session_id = 999
        self.user = {"id": user_id, "username": username, "role": "admin" if is_admin else "user", "is_superuser": is_admin}
        self.ws = None


class MockIdentityProvider:
    def __init__(self, user_id=1, is_admin=True, permissions=None):
        self.uid = user_id
        self.is_admin = is_admin
        self.perms = set(permissions or ["*"])

    def user_id(self, session):
        return self.uid

    def user_name(self, session):
        return "test_user"

    def is_superuser(self, user_id):
        return self.is_admin

    def has_permission(self, user_id, perm):
        if self.is_admin or "*" in self.perms:
            return True
        return perm in self.perms

    async def effective_user_ids(self, user_id, model_name, db):
        return {user_id}

    async def user_team_ids(self, user_id, db):
        return set()

    async def primary_team_id(self, user_id, db):
        return None


@pytest.mark.asyncio
async def test_crud_lifecycle_in_memory():
    """Тестирует полный цикл CRUD на in-memory SQLite базе."""
    from rsgi_wsrpc.plugins.db import async_session
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session.configure(bind=engine)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        ModelRegistry.clear()
        ModelRegistry.register(DummyTask)

        provider = MockIdentityProvider(user_id=1, is_admin=True)
        set_identity_provider(provider)
        set_access_policy(DefaultAccessPolicy())

        mock_ws = MockSession(user_id=1, is_admin=True)

        # 1. crud.schema
        schema_res = await handle_crud_schema(mock_ws, {"model": "DummyTask"})
        assert "model" in schema_res
        assert schema_res["model"]["key"] == "DummyTask"

        # 2. crud.create
        create_res = await handle_crud_create(mock_ws, {
            "model": "DummyTask",
            "data": {"title": "Протестировать CRUD", "count": 5}
        })
        assert create_res["success"] is True
        rec_id = create_res["id"]
        assert rec_id is not None

        # 3. crud.list
        list_res = await handle_crud_list(mock_ws, {
            "model": "DummyTask",
            "page": 1,
            "page_size": 10
        })
        assert list_res["$tabular"] is True
        assert list_res["total"] == 1
        assert len(list_res["rows"]) == 1

        # 4. crud.get
        get_res = await handle_crud_get(mock_ws, {
            "model": "DummyTask",
            "id": rec_id
        })
        assert get_res["record"]["title"] == "Протестировать CRUD"
        assert get_res["record"]["count"] == 5

        # 5. crud.update_cell
        update_res = await handle_crud_update_cell(mock_ws, {
            "model": "DummyTask",
            "id": rec_id,
            "field": "is_done",
            "value": True
        })
        assert update_res["success"] is True
        assert update_res["value"] is True

        # 6. crud.delete
        del_res = await handle_crud_delete(mock_ws, {
            "model": "DummyTask",
            "id": rec_id
        })
        assert del_res["success"] is True

        # Проверка, что записи больше нет
        list_after = await handle_crud_list(mock_ws, {"model": "DummyTask"})
        assert list_after["total"] == 0
    finally:
        set_identity_provider(DefaultIdentityProvider())
        await engine.dispose()
        from rsgi_wsrpc.plugins.db import engine as orig_engine
        async_session.configure(bind=orig_engine)


@pytest.mark.asyncio
async def test_crud_schema_strict_admin_isolation():
    from unittest.mock import MagicMock
    from rsgi_wsrpc.plugins.crud.auth import create_crud_session, revoke_crud_session

    set_identity_provider(DefaultIdentityProvider())

    # 1. Гость (без роли админа) не видит моделей
    guest_ws = MagicMock()
    guest_ws.data = None
    guest_ws.user_role = None
    guest_ws.user_roles = []
    guest_ws.cookies = {}

    res_guest = await handle_crud_schema(guest_ws, {})
    assert res_guest["models"] == []

    # 2. Администратор (роль admin) получает полный доступ
    admin_ws = MagicMock()
    admin_ws.data = None
    admin_ws.user_role = "admin"
    admin_ws.user_roles = ["admin"]
    admin_ws.cookies = {}

    res_admin = await handle_crud_schema(admin_ws, {})
    model_keys = [m["key"] for m in res_admin["models"]]
    assert "DummyTask" in model_keys
    task_schema = next(m for m in res_admin["models"] if m["key"] == "DummyTask")
    assert task_schema["permissions"]["can_read"] is True
    assert task_schema["permissions"]["can_create"] is True
    assert task_schema["permissions"]["can_update"] is True
    assert task_schema["permissions"]["can_delete"] is True

    # 3. Аутентификация через Cookie сессии (rsgi_crud_session)
    token = create_crud_session({"username": "admin", "role": "admin"})
    cookie_ws = MagicMock()
    cookie_ws.data = None
    cookie_ws.user_role = None
    cookie_ws.user_roles = []
    cookie_ws.cookies = {"rsgi_crud_session": token}

    res_cookie = await handle_crud_schema(cookie_ws, {})
    cookie_model_keys = [m["key"] for m in res_cookie["models"]]
    assert "DummyTask" in cookie_model_keys
    revoke_crud_session(token)


@pytest.mark.asyncio
async def test_crud_sso_and_zero_leakage_404():
    from rsgi_wsrpc.plugins.crud.static_handler import serve_crud_static
    from rsgi_wsrpc.plugins.crud.auth import set_crud_session_validator, create_crud_session

    class MockRsgiProto:
        def __init__(self):
            self.status = None
            self.headers = []
            self.body = None
            self.file_path = None

        def response_str(self, status, headers, body):
            self.status = status
            self.headers = headers
            self.body = body

        def response_file(self, status, headers, file):
            self.status = status
            self.headers = headers
            self.file_path = file

    class MockScope:
        def __init__(self, path="/crud/", method="GET", cookie=""):
            self.path = path
            self.method = method
            self.headers = [("cookie", cookie)]

    # 1. Запрос гостя без сессии -> 404 Not Found (Zero-Leakage)
    scope_guest = MockScope(path="/crud/")
    proto_guest = MockRsgiProto()
    await serve_crud_static(scope_guest, proto_guest)
    assert proto_guest.status == 404

    # 2. Запрос обычного пользователя (не admin) -> 404 Not Found
    user_token = create_crud_session({"username": "user", "role": "user"})
    scope_user = MockScope(path="/crud/", cookie=f"rsgi_crud_session={user_token}")
    proto_user = MockRsgiProto()
    await serve_crud_static(scope_user, proto_user)
    assert proto_user.status == 404

    # 3. Запрос админа -> 200 OK (отдает index.html)
    admin_token = create_crud_session({"username": "admin", "role": "admin"})
    scope_admin = MockScope(path="/crud/", cookie=f"rsgi_crud_session={admin_token}")
    proto_admin = MockRsgiProto()
    await serve_crud_static(scope_admin, proto_admin)
    assert proto_admin.status == 200
    assert proto_admin.file_path is not None and "index.html" in proto_admin.file_path

    # 4. Проверка внешнего SSO валидатора
    set_crud_session_validator(lambda t: {"username": "sso_admin", "role": "admin"} if t == "valid_sso" else None)
    scope_sso = MockScope(path="/crud/", cookie="rsgi_crud_session=valid_sso")
    proto_sso = MockRsgiProto()
    await serve_crud_static(scope_sso, proto_sso)
    assert proto_sso.status == 200


@pytest.mark.asyncio
async def test_crud_m2m_update_cell():
    """Тестирует редактирование ячейки M2M связи (User -> roles) через crud.update_cell."""
    from rsgi_wsrpc.plugins.db import async_session
    from rsgi_wsrpc.plugins.auth.models import User, Role
    from rsgi_wsrpc.plugins.auth.models import _register_internal_auth_models

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async_session.configure(bind=engine)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        ModelRegistry.clear()
        _register_internal_auth_models()
        ModelRegistry.register(User)
        ModelRegistry.register(Role)

        provider = MockIdentityProvider(user_id=1, is_admin=True)
        set_identity_provider(provider)
        set_access_policy(DefaultAccessPolicy())
        mock_ws = MockSession(user_id=1, is_admin=True)

        # Создаем роли
        await handle_crud_create(mock_ws, {
            "model": "Role",
            "data": {"name": "moderator", "description": "Moderator role"}
        })
        await handle_crud_create(mock_ws, {
            "model": "Role",
            "data": {"name": "editor", "description": "Editor role"}
        })

        # Создаем пользователя
        u_res = await handle_crud_create(mock_ws, {
            "model": "User",
            "data": {"login": "testuser", "name": "Test User", "password": "password123"}
        })
        user_id = u_res["id"]

        # Назначаем M2M роль через crud.update_cell
        update_res = await handle_crud_update_cell(mock_ws, {
            "model": "User",
            "id": user_id,
            "field": "roles",
            "value": ["moderator"]
        })
        assert update_res["success"] is True
        assert "moderator" in update_res["value"]

        # Проверяем получение через crud.get
        get_res = await handle_crud_get(mock_ws, {"model": "User", "id": user_id})
        roles = [r["label"] for r in get_res["record"]["roles"]]
        assert "moderator" in roles
    finally:
        set_identity_provider(DefaultIdentityProvider())
        await engine.dispose()
        from rsgi_wsrpc.plugins.db import engine as orig_engine
        async_session.configure(bind=orig_engine)




