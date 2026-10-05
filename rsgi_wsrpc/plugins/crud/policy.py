# -*- coding: utf-8 -*-
"""
Политики доступа (AccessPolicy) для CRUD-плагина rsgi-wsrpc.
Декларативное управление предикатами RLS и правами на колонки без привязки к жестким ролям.
"""

from __future__ import annotations
from typing import Protocol, Set, Optional, Literal
from sqlalchemy import or_, false, ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from rsgi_wsrpc.core.session import RPCError
from .identity import AccessContext
from .meta import ModelMeta


Action = Literal["read", "create", "update", "delete", "transfer"]


class AccessPolicy(Protocol):
    """Интерфейс политики доступа (RLS и поля)."""
    async def scope(
        self,
        ctx: AccessContext,
        meta: ModelMeta,
        action: Action,
        db: AsyncSession
    ) -> Optional[ColumnElement[bool]]:
        """
        Возвращает предикат доступа для SQL WHERE.
        None = полный доступ; false() = доступ запрещен; ColumnElement = фильтр строк.
        """
        ...

    def allowed_fields(
        self,
        ctx: AccessContext,
        meta: ModelMeta,
        action: Action
    ) -> Set[str]:
        """Возвращает множество разрешенных полей для указанного действия."""
        ...


class DefaultAccessPolicy:
    """
    Стандартная политика доступа на базе полномочий (Capability-Based).
    Полностью свободна от жестких ролей в коде.
    """

    async def scope(
        self,
        ctx: AccessContext,
        meta: ModelMeta,
        action: Action,
        db: AsyncSession
    ) -> Optional[ColumnElement[bool]]:
        model_name = meta.key
        cls = meta.model_cls

        # 1. Проверка базового полномочия на модель
        if not ctx.is_superuser:
            perm_needed = f"{model_name}:{action}"
            if not ctx.has_permission(perm_needed):
                raise RPCError(-32003, f"Доступ запрещен: действие '{action}' для модели '{model_name}' не разрешено")

        # 2. Если суперпользователь или модель без владения — полный доступ без фильтрации
        if ctx.is_superuser or not meta.is_row_secure:
            return None

        # 3. Чтение (read)
        if action == "read":
            if ctx.has_permission(f"{model_name}:view_all"):
                return None

            conditions = []
            if hasattr(cls, "owner_id") and ctx.effective_user_ids:
                conditions.append(cls.owner_id.in_(ctx.effective_user_ids))
            elif hasattr(cls, "creator_id") and ctx.effective_user_ids:
                conditions.append(cls.creator_id.in_(ctx.effective_user_ids))

            if hasattr(cls, "team_id") and ctx.user_team_ids:
                conditions.append(cls.team_id.in_(ctx.user_team_ids))

            return or_(*conditions) if conditions else false()

        # 4. Обновление (update)
        if action == "update":
            if ctx.has_permission(f"{model_name}:view_all") or ctx.has_permission(f"{model_name}:update_all"):
                return None

            conditions = []
            if hasattr(cls, "owner_id") and ctx.effective_user_ids:
                conditions.append(cls.owner_id.in_(ctx.effective_user_ids))
            elif hasattr(cls, "creator_id") and ctx.effective_user_ids:
                conditions.append(cls.creator_id.in_(ctx.effective_user_ids))

            if hasattr(cls, "team_id") and ctx.user_team_ids:
                conditions.append(cls.team_id.in_(ctx.user_team_ids))

            return or_(*conditions) if conditions else false()

        # 5. Удаление (delete)
        if action == "delete":
            if ctx.has_permission(f"{model_name}:delete_all"):
                return None

            conditions = []
            if hasattr(cls, "owner_id") and ctx.effective_user_ids:
                conditions.append(cls.owner_id.in_(ctx.effective_user_ids))
            elif hasattr(cls, "creator_id") and ctx.effective_user_ids:
                conditions.append(cls.creator_id.in_(ctx.effective_user_ids))

            return or_(*conditions) if conditions else false()

        return None

    def allowed_fields(
        self,
        ctx: AccessContext,
        meta: ModelMeta,
        action: Action
    ) -> Set[str]:
        model_name = meta.key

        if action == "read":
            return {f.name for f in meta.get_public_fields()}

        if action in ("create", "update"):
            public = meta.get_public_fields()
            editable = {f.name for f in public if not f.read_only}

            # Поля с защитой (owner_id, team_id, creator_id) требуют права transfer
            can_transfer = ctx.is_superuser or ctx.has_permission(f"{model_name}:transfer")
            if not can_transfer:
                editable = editable - meta.protected_fields

            return editable

        return set()
