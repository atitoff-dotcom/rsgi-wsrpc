# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock
from sqlalchemy import select

from rsgi_wsrpc.core.session import (
    JsonRpcSession, rpc_method, RPC_REGISTRY, RPCError,
    PUBLIC_RPC_METHODS, register_public_method, unregister_public_method, is_public_rpc_method
)
from rsgi_wsrpc.core.constants import ADMIN_ROLE, DEFAULT_USER_ROLE, SYSTEM_ROLES
from rsgi_wsrpc.plugins.auth.models import Role, RpcPermission, User
from rsgi_wsrpc.plugins.auth.core import AuthSession
from rsgi_wsrpc.plugins.auth.discovery import sync_rpc_permissions, reload_public_rpc_cache
from rsgi_wsrpc.plugins.crud.handlers import handle_crud_delete, handle_crud_update_cell
from rsgi_wsrpc.plugins.db import async_session, Base, engine


class MockTransport:
    def __init__(self, data=None):
        self.data = data
        self.sent = []
        self._closed = False
        self.ws = MagicMock()

    async def _send_error(self, rpc_id, code, message):
        self.sent.append({"id": rpc_id, "error": {"code": code, "message": message}})

    @property
    def authenticated(self) -> bool:
        return self.data is not None

    @property
    def user_role(self):
        if self.data and hasattr(self.data, "user_role"):
            return self.data.user_role
        return None

    @property
    def user_roles(self):
        if self.data and hasattr(self.data, "user_roles"):
            return self.data.user_roles
        return []


@pytest.mark.asyncio
async def test_public_rpc_methods_cache():
    register_public_method("catalog.list")
    register_public_method("public_api.*")

    assert is_public_rpc_method("catalog.list") is True
    assert is_public_rpc_method("public_api.items") is True
    assert is_public_rpc_method("public_api.details") is True
    assert is_public_rpc_method("secret.data") is False

    unregister_public_method("catalog.list")
    assert is_public_rpc_method("catalog.list") is False


@pytest.mark.asyncio
async def test_auth_session_rpc_permissions():
    # 1. Admin has bypass to everything
    admin_sess = AuthSession(
        uid=1, user=None, user_name="admin", user_role="admin", user_roles=["admin"],
        session_db_id=1, allowed_rpc_methods=set()
    )
    assert admin_sess.has_rpc_permission("orders.dispatch") is True
    assert admin_sess.has_rpc_permission("any.random.method") is True

    # 2. Regular user with wildcard and specific permissions
    user_sess = AuthSession(
        uid=2, user=None, user_name="operator", user_role="user", user_roles=["user"],
        session_db_id=2, allowed_rpc_methods={"orders.*", "reports.view"}
    )
    assert user_sess.has_rpc_permission("orders.list") is True
    assert user_sess.has_rpc_permission("orders.dispatch") is True
    assert user_sess.has_rpc_permission("reports.view") is True
    assert user_sess.has_rpc_permission("reports.export") is False
    assert user_sess.has_rpc_permission("admin.cleanup") is False


@pytest.mark.asyncio
async def test_crud_immutable_roles_protection():
    from rsgi_wsrpc.plugins.crud import ModelRegistry
    from rsgi_wsrpc.plugins.auth.core import system_bypass_ctx
    ModelRegistry.register(Role)
    token = system_bypass_ctx.set(True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as db:
            # Убеждаемся в наличии ролей
            for r_name in (ADMIN_ROLE, DEFAULT_USER_ROLE):
                stmt = select(Role).where(Role.name == r_name)
                if not (await db.execute(stmt)).scalar_one_or_none():
                    db.add(Role(name=r_name, description=f"Builtin {r_name}"))

            # Создаем кастомную роль
            stmt_custom = select(Role).where(Role.name == "manager")
            if not (await db.execute(stmt_custom)).scalar_one_or_none():
                db.add(Role(name="manager", description="Custom manager"))

            await db.commit()

            # Получаем id
            admin_id = (await db.execute(select(Role.id).where(Role.name == ADMIN_ROLE))).scalar_one()
            user_id = (await db.execute(select(Role.id).where(Role.name == DEFAULT_USER_ROLE))).scalar_one()
            manager_id = (await db.execute(select(Role.id).where(Role.name == "manager"))).scalar_one()
    finally:
        system_bypass_ctx.reset(token)

    # Сессия администратора
    admin_session = MagicMock()
    admin_session.user_role = "admin"
    admin_session.user_roles = ["admin"]
    admin_session.cookies = {}
    admin_session.data = None

    # Попытка удалить admin -> RPCError
    with pytest.raises(RPCError) as exc_admin:
        await handle_crud_delete(admin_session, {"model": "auth_role", "id": admin_id})
    assert "не может быть удалена" in str(exc_admin.value)

    # Попытка удалить user -> RPCError
    with pytest.raises(RPCError) as exc_user:
        await handle_crud_delete(admin_session, {"model": "auth_role", "id": user_id})
    assert "не может быть удалена" in str(exc_user.value)

    # Попытка переименовать admin -> RPCError
    with pytest.raises(RPCError) as exc_rename:
        await handle_crud_update_cell(admin_session, {
            "model": "auth_role", "id": admin_id, "field": "name", "value": "super_admin"
        })
    assert "не может быть переименована" in str(exc_rename.value)

    # Кастомная роль manager удаляется успешно
    res = await handle_crud_delete(admin_session, {"model": "auth_role", "id": manager_id})
    assert res == {"success": True, "id": manager_id}


@pytest.mark.asyncio
async def test_user_personal_permissions_merging():
    from rsgi_wsrpc.plugins.auth.models import RolePermission, UserPermission, UserRpcPermission

    # 1. Роль с базовыми правами: чтение Task (только свои) и RPC reports.view
    role = Role(id=10, name="operator", description="Operator role")
    role_perm = RolePermission(
        model_name="Task",
        can_read=True,
        can_create=False,
        can_update=False,
        can_delete=False,
        row_level_only=True
    )
    role.permissions = [role_perm]
    rpc_view = RpcPermission(id=101, name="reports.view", description="View reports")
    role.rpc_permissions = [rpc_view]

    # 2. Пользователь с ролью
    user = User(id=5, name="John Doe", login="johnd")
    user.roles = [role]
    user.permissions = []
    user.rpc_permissions = []

    # Проверка базовых ролевых прав
    perms = user._get_permissions_dict()
    assert perms["Task"]["can_read"] is True
    assert perms["Task"]["read_global"] is False
    assert perms["Task"]["can_delete"] is False
    assert user.get_allowed_rpc_methods() == {"reports.view"}

    # 3. Добавляем персональные права пользователю:
    # - CRUD надбавка: удаление Task глобально
    user_perm = UserPermission(
        model_name="Task",
        can_read=False,
        can_create=False,
        can_update=False,
        can_delete=True,
        row_level_only=False
    )
    user.permissions = [user_perm]

    # - Персональное RPC право: orders.dispatch
    rpc_dispatch = RpcPermission(id=102, name="orders.dispatch", description="Dispatch orders")
    user.rpc_permissions = [rpc_dispatch]

    # Проверяем итоговое объединение
    merged_perms = user._get_permissions_dict()
    assert merged_perms["Task"]["can_read"] is True  # из роли
    assert merged_perms["Task"]["read_global"] is False  # из роли
    assert merged_perms["Task"]["can_delete"] is True  # персональная надбавка
    assert merged_perms["Task"]["delete_global"] is True  # персональная надбавка

    allowed_rpcs = user.get_allowed_rpc_methods()
    assert allowed_rpcs == {"reports.view", "orders.dispatch"}


@pytest.mark.asyncio
async def test_permissions_api_flow():
    from rsgi_wsrpc.plugins.auth.permission_handlers import (
        handle_permissions_get_schema,
        handle_permissions_get,
        handle_permissions_save
    )
    from rsgi_wsrpc.plugins.auth.core import system_bypass_ctx

    admin_session = MagicMock()
    admin_session.user_role = "admin"
    admin_session.user_roles = ["admin"]
    admin_session.cookies = {}

    guest_session = MagicMock()
    guest_session.user_role = "user"
    guest_session.user_roles = ["user"]
    guest_session.data = None
    guest_session.cookies = {}

    # 1. Non-admin is rejected
    with pytest.raises(RPCError) as exc:
        await handle_permissions_get_schema(guest_session)
    assert "требуются права администратора" in str(exc.value)

    # 2. Admin gets schema
    schema = await handle_permissions_get_schema(admin_session)
    assert "models" in schema
    assert "rpc_methods" in schema
    assert isinstance(schema["models"], list)

    token = system_bypass_ctx.set(True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with async_session() as db:
            # Создаем или находим тестовую роль и пользователя
            role = (await db.execute(select(Role).where(Role.name == "tester_role"))).scalar_one_or_none()
            if not role:
                role = Role(name="tester_role", description="Test Role")
                db.add(role)
                await db.commit()
                await db.refresh(role)

            user = (await db.execute(select(User).where(User.login == "test_user_perm"))).scalar_one_or_none()
            if not user:
                user = User(name="Test User", login="test_user_perm", roles=[role])
                db.add(user)
                await db.commit()
                await db.refresh(user)

            role_id = role.id
            user_id = user.id
    finally:
        system_bypass_ctx.reset(token)

    # 3. Save permissions for role
    crud_cfg = {
        "Task": {
            "can_read": True,
            "can_create": True,
            "can_update": False,
            "can_delete": False,
            "row_level_only": True
        }
    }
    save_res = await handle_permissions_save(
        admin_session,
        target_type="role",
        target_id=role_id,
        crud_permissions=crud_cfg,
        rpc_permissions=[]
    )
    assert save_res["success"] is True

    # 4. Get permissions for role
    role_perms = await handle_permissions_get(admin_session, target_type="role", target_id=role_id)
    assert role_perms["target_name"] == "tester_role"
    assert role_perms["crud_permissions"]["Task"]["can_read"] is True
    assert role_perms["crud_permissions"]["Task"]["can_create"] is True
    assert role_perms["crud_permissions"]["Task"]["row_level_only"] is True

    # 5. Save personal permissions for user
    user_crud_cfg = {
        "Task": {
            "can_delete": True,
            "row_level_only": False
        }
    }
    user_save_res = await handle_permissions_save(
        admin_session,
        target_type="user",
        target_id=user_id,
        crud_permissions=user_crud_cfg,
        rpc_permissions=[]
    )
    assert user_save_res["success"] is True

    # 6. Get permissions for user
    user_perms = await handle_permissions_get(admin_session, target_type="user", target_id=user_id)
    assert user_perms["target_name"] == "test_user_perm"
    # Inherited from role:
    assert user_perms["inherited_crud"]["Task"]["can_read"] is True
    # Personal override:
    assert user_perms["personal_crud"]["Task"]["can_delete"] is True
    # Effective merged:
    assert user_perms["effective_crud"]["Task"]["can_read"] is True
    assert user_perms["effective_crud"]["Task"]["can_delete"] is True
    assert user_perms["effective_crud"]["Task"]["delete_global"] is True

    # 7. Save and get permissions for guest
    guest_save_res = await handle_permissions_save(
        admin_session,
        target_type="guest",
        target_id=0,
        crud_permissions={},
        rpc_permissions=["system.ping", "catalog.items"]
    )
    assert guest_save_res["success"] is True

    guest_perms = await handle_permissions_get(admin_session, target_type="guest", target_id=0)
    assert guest_perms["target_name"] == "Гости"
    assert "catalog.items" in guest_perms["rpc_permissions"]
    assert is_public_rpc_method("catalog.items") is True

