# -*- coding: utf-8 -*-
"""
Протокол провайдера идентификации и контекст доступа для CRUD-плагина.
Позволяет отвязать плагин от конкретных моделей пользователей/команд проекта.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Set, Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession


class IdentityProvider(Protocol):
    """
    Интерфейс поставщика идентификации и полномочий.
    Плагин CRUD не зависит от конкретных моделей User, Team или структуры БД проекта.
    """
    def user_id(self, session: Any) -> Optional[int]:
        """Извлекает user_id из текущей сессии."""
        ...

    def user_name(self, session: Any) -> str:
        """Извлекает отображаемое имя пользователя из сессии."""
        ...

    def is_superuser(self, user_id: Optional[int]) -> bool:
        """Проверяет, обладает ли пользователь полным административным доступом."""
        ...

    def has_permission(self, user_id: Optional[int], perm: str) -> bool:
        """Проверяет наличие атомарного права (capability) или wildcard-маски."""
        ...

    async def effective_user_ids(self, user_id: int, model_name: str, db: AsyncSession) -> Set[int]:
        """
        Возвращает множество ID пользователей, чьи записи текущий пользователь
        имеет право обрабатывать (сам пользователь + активные замещения).
        """
        ...

    async def user_team_ids(self, user_id: int, db: AsyncSession) -> Set[int]:
        """Возвращает множество ID активных команд пользователя."""
        ...

    async def primary_team_id(self, user_id: int, db: AsyncSession) -> Optional[int]:
        """Возвращает ID основной команды пользователя."""
        ...


class DefaultIdentityProvider:
    """
    Стандартный провайдер идентификации на базе контекста сессий rsgi-wsrpc auth.
    Используется по умолчанию, если приложение не зарегистрировало свой провайдер.
    """
    def user_id(self, session: Any) -> Optional[int]:
        from rsgi_wsrpc.core.session import current_user_ctx
        user = current_user_ctx.get()
        if user:
            return getattr(user, "id", None) if not isinstance(user, dict) else user.get("id")
        user = getattr(session, "user", None)
        if user:
            return getattr(user, "id", None) if not isinstance(user, dict) else user.get("id")
        return None

    def user_name(self, session: Any) -> str:
        from rsgi_wsrpc.core.session import current_user_ctx
        user = current_user_ctx.get() or getattr(session, "user", None)
        if user:
            return getattr(user, "username", "") if not isinstance(user, dict) else user.get("username", "")
        return "anonymous"

    def is_superuser(self, user_id: Optional[int]) -> bool:
        from rsgi_wsrpc.core.session import current_user_ctx
        user = current_user_ctx.get()
        if user:
            role = getattr(user, "role", None) if not isinstance(user, dict) else user.get("role")
            if role in ("admin", "superuser", 1, "ADMIN"):
                return True
            if getattr(user, "is_superuser", False) if not isinstance(user, dict) else user.get("is_superuser", False):
                return True
        return False

    def has_permission(self, user_id: Optional[int], perm: str) -> bool:
        return self.is_superuser(user_id)

    async def effective_user_ids(self, user_id: int, model_name: str, db: AsyncSession) -> Set[int]:
        return {user_id} if user_id is not None else set()

    async def user_team_ids(self, user_id: int, db: AsyncSession) -> Set[int]:
        return set()

    async def primary_team_id(self, user_id: int, db: AsyncSession) -> Optional[int]:
        return None


@dataclass
class AccessContext:
    """
    Контекст доступа текущего запроса.
    Собирается один раз за вызов хендлера и предотвращает повторные обращения к БД.
    """
    user_id: Optional[int]
    user_name: str
    is_superuser: bool
    effective_user_ids: Set[int] = field(default_factory=set)
    user_team_ids: Set[int] = field(default_factory=set)
    primary_team_id: Optional[int] = None
    _provider: Optional[IdentityProvider] = None

    def has_permission(self, perm: str) -> bool:
        if self.is_superuser:
            return True
        if self._provider:
            return self._provider.has_permission(self.user_id, perm)
        return False


async def create_access_context(
    provider: IdentityProvider,
    session: Any,
    model_name: str,
    db: AsyncSession
) -> AccessContext:
    """Создает предвычисленный контекст доступа для текущего запроса."""
    uid = provider.user_id(session)
    u_name = provider.user_name(session)
    is_super = provider.is_superuser(uid)

    if is_super or uid is None:
        eff_ids = {uid} if uid is not None else set()
        t_ids = set()
        p_team = None
    else:
        eff_ids = await provider.effective_user_ids(uid, model_name, db)
        t_ids = await provider.user_team_ids(uid, db)
        p_team = await provider.primary_team_id(uid, db)

    return AccessContext(
        user_id=uid,
        user_name=u_name,
        is_superuser=is_super,
        effective_user_ids=eff_ids,
        user_team_ids=t_ids,
        primary_team_id=p_team,
        _provider=provider
    )
