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
        await engine.dispose()


@pytest.mark.asyncio
async def test_crud_schema_open_mode():
    from unittest.mock import MagicMock
    from rsgi_wsrpc.core.lib.config import configure

    # In open mode (login_rpc=""), schema returns all registered models
    configure(login_rpc="")
    mock_ws = MagicMock()
    mock_ws.data = None
    mock_ws.user_role = None

    res = await handle_crud_schema(mock_ws, {})
    assert "models" in res
    model_keys = [m["key"] for m in res["models"]]
    assert "DummyTask" in model_keys
    task_schema = next(m for m in res["models"] if m["key"] == "DummyTask")
    assert task_schema["permissions"]["can_read"] is True
    assert task_schema["permissions"]["can_create"] is True
    assert task_schema["permissions"]["can_update"] is True
    assert task_schema["permissions"]["can_delete"] is True

