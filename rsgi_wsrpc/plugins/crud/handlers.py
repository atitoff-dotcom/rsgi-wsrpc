# -*- coding: utf-8 -*-
"""
JSON-RPC 2.0 обработчики для CRUD-плагина rsgi-wsrpc (crud.*).
Предоставляет полнофункциональный API для интроспекции, выборки ($tabular),
детального просмотра, создания, обновления ячеек, пакетных действий и удаления.
"""

from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import select, update, delete, func, String, or_
from sqlalchemy.ext.asyncio import AsyncSession

from rsgi_wsrpc.core.session import rpc_method, RPCError, JsonRpcSession
from rsgi_wsrpc.plugins.db import async_session

try:
    from rsgi_wsrpc.plugins.auth.core import system_bypass_ctx
except ImportError:
    from contextvars import ContextVar
    system_bypass_ctx = ContextVar("system_bypass", default=False)

from .identity import IdentityProvider, DefaultIdentityProvider, AccessContext, create_access_context
from .meta import ModelMeta
from .registry import ModelRegistry
from .policy import AccessPolicy, DefaultAccessPolicy
from .coerce import coerce_value
from .events import notify_crud_change


# Глобальные провайдеры для CRUD-плагина
_identity_provider: IdentityProvider = DefaultIdentityProvider()
_access_policy: AccessPolicy = DefaultAccessPolicy()


def set_identity_provider(provider: IdentityProvider) -> None:
    """Устанавливает провайдер идентификации для CRUD-плагина."""
    global _identity_provider
    _identity_provider = provider


def set_access_policy(policy: AccessPolicy) -> None:
    """Устанавливает политику доступа для CRUD-плагина."""
    global _access_policy
    _access_policy = policy


def get_identity_provider() -> IdentityProvider:
    return _identity_provider


def get_access_policy() -> AccessPolicy:
    return _access_policy


def escape_like(s: str) -> str:
    """Экранирует спецсимволы LIKE (%, _, \\) для поиска по точным строкам."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _get_model_meta(model_name: str) -> ModelMeta:
    meta = ModelRegistry.get(model_name)
    if not meta:
        from rsgi_wsrpc.plugins.db import Base
        ModelRegistry.auto_discover(Base)
        meta = ModelRegistry.get(model_name)
    if not meta:
        raise RPCError(-32602, f"Модель '{model_name}' не найдена или не опубликована в CRUD")
    return meta


# -----------------------------------------------------------------------------
# Хендлеры логики CRUD
# -----------------------------------------------------------------------------

async def handle_crud_schema(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Возвращает схему одной или всех доступных пользователю моделей."""
    provider = get_identity_provider()
    uid = provider.user_id(session)
    is_super = provider.is_superuser(uid)

    from rsgi_wsrpc.core.constants import UserRole
    from rsgi_wsrpc.core.lib.config import settings

    if not settings.security.get("login_rpc"):
        is_super = True
    else:
        role = getattr(session, "user_role", None) or getattr(getattr(session, "data", None), "user_role", None)
        if hasattr(role, "value"):
            role = role.value
        if role in ("admin", "ADMIN", UserRole.ADMIN):
            is_super = True

    target_model = params.get("model")

    def make_perms(meta: ModelMeta) -> Dict[str, bool]:
        name = meta.key
        can_r = is_super or provider.has_permission(uid, f"{name}:read")
        can_c = is_super or provider.has_permission(uid, f"{name}:create")
        can_u = is_super or provider.has_permission(uid, f"{name}:update")
        can_d = is_super or provider.has_permission(uid, f"{name}:delete")
        row_level_only = not (is_super or provider.has_permission(uid, f"{name}:view_all"))
        return {
            "can_read": can_r,
            "can_create": can_c,
            "can_update": can_u,
            "can_delete": can_d,
            "row_level_only": row_level_only,
        }

    if target_model:
        meta = _get_model_meta(target_model)
        perms = make_perms(meta)
        return {"model": meta.to_schema_dict(perms)}

    if not ModelRegistry.all():
        from rsgi_wsrpc.plugins.db import Base
        ModelRegistry.auto_discover(Base)

    models_list = []
    for meta in ModelRegistry.all().values():
        perms = make_perms(meta)
        if perms["can_read"]:
            models_list.append(meta.to_schema_dict(perms))

    return {"models": models_list}


async def handle_crud_get(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Детальная карточка сущности с проверкой RLS."""
    model_name = params.get("model")
    record_id = params.get("id")

    if not model_name or record_id is None:
        raise RPCError(-32602, "Параметры 'model' и 'id' обязательны")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)
            scope = await policy.scope(ctx, meta, "read", db)

            stmt = select(cls).where(cls.id == record_id)
            if scope is not None:
                stmt = stmt.where(scope)

            res = await db.execute(stmt)
            obj = res.scalar_one_or_none()

            if not obj:
                raise RPCError(-32004, f"Запись #{record_id} не найдена или доступ ограничен")

            result = {}
            for f in meta.get_public_fields():
                val = getattr(obj, f.name, None)
                if hasattr(val, "isoformat"):
                    val = val.isoformat()
                result[f.name] = val

            return {"record": result}
    finally:
        system_bypass_ctx.reset(token)


async def handle_crud_list(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Выборка данных модели для DataGrid в сжатом формате $tabular."""
    model_name = params.get("model")
    if not model_name:
        raise RPCError(-32602, "Параметр 'model' обязателен")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    page = max(1, int(params.get("page", 1)))
    page_size = min(500, max(1, int(params.get("page_size", 50))))
    sort_field = params.get("sort_field")
    sort_dir = str(params.get("sort_dir", "asc")).lower()
    search = str(params.get("search", "")).strip()
    filters = params.get("filters", {})
    show_archived = bool(params.get("show_archived", False))

    public_fields = meta.get_public_fields()
    field_names = [f.name for f in public_fields]
    fields_dict = {f.name: f for f in public_fields}

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)
            scope = await policy.scope(ctx, meta, "read", db)

            # Выбираем только публичные колонки
            col_exprs = [getattr(cls, f.name) for f in public_fields]
            query = select(*col_exprs)

            if scope is not None:
                query = query.where(scope)

            # Фильтр архивации
            if meta.is_archivable and not show_archived:
                query = query.where(cls.is_archived == False)

            # Поиск
            if search:
                escaped = escape_like(search)
                search_conds = []
                for f in public_fields:
                    if f.searchable:
                        col = getattr(cls, f.name, None)
                        if col is not None:
                            search_conds.append(col.cast(String).ilike(f"%{escaped}%", escape="\\"))
                if search_conds:
                    query = query.where(or_(*search_conds))

            # Точные фильтры по полям схемы
            if filters and isinstance(filters, dict):
                for k, v in filters.items():
                    if v is not None and k in fields_dict:
                        col = getattr(cls, k)
                        coerced_v = coerce_value(fields_dict[k], v)
                        query = query.where(col == coerced_v)

            # Сортировка
            if sort_field and sort_field in fields_dict:
                col = getattr(cls, sort_field)
                query = query.order_by(col.desc() if sort_dir == "desc" else col.asc())
            elif hasattr(cls, "id"):
                query = query.order_by(cls.id.desc())

            # Общее количество строк (Count)
            count_stmt = select(func.count()).select_from(query.order_by(None).subquery())
            total = (await db.execute(count_stmt)).scalar() or 0

            # Пагинация
            query = query.offset((page - 1) * page_size).limit(page_size)
            res = await db.execute(query)
            raw_rows = res.all()

            # Сериализация ячеек
            rows = []
            for row in raw_rows:
                r_vals = []
                for val in row:
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    r_vals.append(val)
                rows.append(r_vals)

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "$tabular": True,
                "fields": field_names,
                "rows": rows,
            }
    finally:
        system_bypass_ctx.reset(token)


async def handle_crud_update_cell(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Точечное атомарное редактирование одной ячейки с валидацией типов."""
    model_name = params.get("model")
    record_id = params.get("id")
    field = params.get("field")
    value = params.get("value")

    if not all([model_name, record_id is not None, field]):
        raise RPCError(-32602, "Параметры 'model', 'id' и 'field' обязательны")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)
            allowed = policy.allowed_fields(ctx, meta, "update")

            if field not in allowed:
                if field in meta.protected_fields:
                    raise RPCError(-32003, f"Поле '{field}' защищено от изменения (требуется право transfer)")
                if field in meta.readonly_fields:
                    raise RPCError(-32602, f"Поле '{field}' защищено от записи (read-only)")
                raise RPCError(-32602, f"Поле '{field}' недоступно для редактирования")

            field_meta = meta.fields[field]
            coerced_value = coerce_value(field_meta, value)
            scope = await policy.scope(ctx, meta, "update", db)

            stmt = update(cls).where(cls.id == record_id)
            if scope is not None:
                stmt = stmt.where(scope)

            values_to_update: Dict[str, Any] = {field: coerced_value}
            if hasattr(cls, "updated_at"):
                values_to_update["updated_at"] = datetime.now(timezone.utc)

            stmt = stmt.values(**values_to_update)
            result = await db.execute(stmt)
            await db.commit()

            if result.rowcount == 0:
                raise RPCError(-32004, f"Запись #{record_id} не найдена или доступ ограничен")

        # Безопасное оповещение без значений полей
        await notify_crud_change(
            model=model_name,
            record_id=record_id,
            kind="updated",
            by_user=ctx.user_name,
            exclude_session=session
        )

        return {"success": True, "field": field, "value": coerced_value}
    finally:
        system_bypass_ctx.reset(token)


async def handle_crud_bulk_update(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Пакетное обновление или архивация набора строк с проверкой RLS."""
    model_name = params.get("model")
    record_ids = params.get("ids", [])
    patch = params.get("patch", {})

    if not model_name or not record_ids or not patch:
        raise RPCError(-32602, "Параметры 'model', 'ids' и 'patch' обязательны")

    if len(record_ids) > 500:
        raise RPCError(-32602, "Пакетное обновление ограничено 500 записями за один вызов")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)
            allowed = policy.allowed_fields(ctx, meta, "update")

            coerced_patch = {}
            for k, v in patch.items():
                if k not in allowed:
                    if k in meta.protected_fields:
                        raise RPCError(-32003, f"Поле '{k}' защищено от изменения (требуется право transfer)")
                    raise RPCError(-32602, f"Поле '{k}' недоступно для изменения")
                coerced_patch[k] = coerce_value(meta.fields[k], v)

            if not coerced_patch:
                raise RPCError(-32602, "Нет допустимых полей для обновления")

            # Архивация
            if coerced_patch.get("is_archived") is True and hasattr(cls, "archived_at"):
                coerced_patch["archived_at"] = datetime.now(timezone.utc)
            elif coerced_patch.get("is_archived") is False and hasattr(cls, "archived_at"):
                coerced_patch["archived_at"] = None

            if hasattr(cls, "updated_at"):
                coerced_patch["updated_at"] = datetime.now(timezone.utc)

            scope = await policy.scope(ctx, meta, "update", db)

            stmt = update(cls).where(cls.id.in_(record_ids))
            if scope is not None:
                stmt = stmt.where(scope)

            stmt = stmt.values(**coerced_patch)
            result = await db.execute(stmt)
            await db.commit()

            updated_count = result.rowcount

        await notify_crud_change(
            model=model_name,
            record_id=record_ids,
            kind="updated",
            by_user=ctx.user_name,
            exclude_session=session
        )

        return {"success": True, "updated_count": updated_count}
    finally:
        system_bypass_ctx.reset(token)


async def handle_crud_delete(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Удаление сущности с проверкой прав."""
    model_name = params.get("model")
    record_id = params.get("id")

    if not model_name or record_id is None:
        raise RPCError(-32602, "Параметры 'model' и 'id' обязательны")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)
            scope = await policy.scope(ctx, meta, "delete", db)

            stmt = delete(cls).where(cls.id == record_id)
            if scope is not None:
                stmt = stmt.where(scope)

            result = await db.execute(stmt)
            await db.commit()

            if result.rowcount == 0:
                raise RPCError(-32004, f"Запись #{record_id} не найдена или доступ ограничен")

        await notify_crud_change(
            model=model_name,
            record_id=record_id,
            kind="deleted",
            by_user=ctx.user_name,
            exclude_session=session
        )

        return {"success": True, "id": record_id}
    finally:
        system_bypass_ctx.reset(token)


async def handle_crud_create(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    """Создание новой записи с проверкой полномочий и валидацией замещений."""
    model_name = params.get("model")
    data = params.get("data", {})
    acting_for_id = params.get("acting_for_user_id")

    if not model_name:
        raise RPCError(-32602, "Параметр 'model' обязателен")

    meta = _get_model_meta(model_name)
    cls = meta.model_cls
    provider = get_identity_provider()
    policy = get_access_policy()

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db:
            ctx = await create_access_context(provider, session, model_name, db)

            # Проверка полномочия на создание
            if not (ctx.is_superuser or ctx.has_permission(f"{model_name}:create")):
                raise RPCError(-32003, f"Создание записей в модели '{model_name}' запрещено")

            # Валидация acting_for_user_id
            if acting_for_id is not None and acting_for_id != ctx.user_id:
                can_transfer = ctx.is_superuser or ctx.has_permission(f"{model_name}:transfer")
                if not (can_transfer or (acting_for_id in ctx.effective_user_ids)):
                    raise RPCError(-32003, "Запрещено создавать запись от чужого имени без полномочий замещения")

            allowed = policy.allowed_fields(ctx, meta, "create")
            filtered_data = {}
            for k, v in data.items():
                if k in allowed:
                    filtered_data[k] = coerce_value(meta.fields[k], v)

            # Авто-заполнение creator_id и owner_id
            if meta.is_row_secure:
                if hasattr(cls, "creator_id"):
                    filtered_data["creator_id"] = ctx.user_id
                if hasattr(cls, "owner_id") and "owner_id" not in filtered_data:
                    filtered_data["owner_id"] = acting_for_id or ctx.user_id
                if hasattr(cls, "team_id") and "team_id" not in filtered_data:
                    if ctx.primary_team_id:
                        filtered_data["team_id"] = ctx.primary_team_id

            now = datetime.now(timezone.utc)
            if hasattr(cls, "created_at") and "created_at" not in filtered_data:
                filtered_data["created_at"] = now
            if hasattr(cls, "updated_at") and "updated_at" not in filtered_data:
                filtered_data["updated_at"] = now

            obj = cls(**filtered_data)
            db.add(obj)
            await db.commit()
            await db.refresh(obj)
            new_id = getattr(obj, "id", None)

        await notify_crud_change(
            model=model_name,
            record_id=new_id,
            kind="created",
            by_user=ctx.user_name,
            exclude_session=session
        )

        return {"success": True, "id": new_id}
    finally:
        system_bypass_ctx.reset(token)


# -----------------------------------------------------------------------------
# Регистрация стандартных WSRPC RPC-методов crud.*
# -----------------------------------------------------------------------------

@rpc_method("crud.schema")
async def crud_schema(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_schema(session, params)


@rpc_method("crud.get")
async def crud_get(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_get(session, params)


@rpc_method("crud.list")
async def crud_list(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_list(session, params)


@rpc_method("crud.create")
async def crud_create(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_create(session, params)


@rpc_method("crud.update_cell")
async def crud_update_cell(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_update_cell(session, params)


@rpc_method("crud.bulk_update")
async def crud_bulk_update(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_bulk_update(session, params)


@rpc_method("crud.delete")
async def crud_delete(session: JsonRpcSession, params: Dict[str, Any]) -> Dict[str, Any]:
    return await handle_crud_delete(session, params)
