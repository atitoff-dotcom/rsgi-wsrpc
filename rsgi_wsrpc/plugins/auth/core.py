# -*- coding: utf-8 -*-
"""
Базовые классы и контексты плагина авторизации (plugins/auth/core.py).
Обеспечивают Row-Level Security (RLS) на уровне ORM SQLAlchemy.
"""

from contextvars import ContextVar
from typing import Optional, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column, declared_attr
from sqlalchemy import Integer, DateTime, func

from rsgi_wsrpc.plugins.db import Base
from rsgi_wsrpc.core.session import current_user_ctx

# Контекстная переменная для обхода проверок прав системными операциями (Bypass)
system_bypass_ctx: ContextVar[bool] = ContextVar("system_bypass", default=False)


class BasicSecureModel(Base):
    """
    Базовый класс для моделей с проверкой прав на уровне модели (без row-level полей).
    """
    __abstract__ = True

    @declared_attr
    def __table_args__(cls):
        return {"extend_existing": True}


class RowSecureModel(BasicSecureModel):
    """
    Расширение с поддержкой row-level разграничения прав (содержит id, creator_id, team_id).
    """
    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc)
    )


# Совместимый алиас
SecureModelBase = RowSecureModel


class AuthSession:
    """
    Стандартный объект сессии пользователя, привязанный к WebSocket-соединению.
    """
    def __init__(
        self,
        uid: int,
        user: Any,
        user_name: str,
        user_role: Any,
        user_roles: list,
        session_db_id: int,
        user_ctx: Any = None,
        allowed_rpc_methods: Any = None,
        send_request_cb: Any = None,
        send_stream_cb: Any = None,
        close_cb: Any = None,
    ):
        self.uid = uid
        self.user = user
        self.user_name = user_name
        self.user_role = user_role
        self.user_roles = user_roles
        self.session_db_id = session_db_id
        self.user_ctx = user_ctx
        self.allowed_rpc_methods = set(allowed_rpc_methods) if allowed_rpc_methods else set()
        self._send_request_cb = send_request_cb
        self._send_stream_cb = send_stream_cb
        self._close_cb = close_cb

    @property
    def user_id(self) -> int:
        return self.uid

    @property
    def username(self) -> str:
        return self.user_name

    @property
    def role_name(self) -> Any:
        return self.user_role

    def has_rpc_permission(self, method_name: str) -> bool:
        """Проверяет право на вызов RPC-метода (O(1) in-memory)."""
        if self.user_ctx and getattr(self.user_ctx, "is_superadmin", False):
            return True
        if "admin" in self.user_roles or self.user_role == "admin":
            return True
        if "*" in self.allowed_rpc_methods or method_name in self.allowed_rpc_methods:
            return True
        for m in self.allowed_rpc_methods:
            if m.endswith(".*") and method_name.startswith(m[:-1]):
                return True
        return False

    async def send_request(self, method: str, params: dict = None, timeout: float = 5.0):
        if self._send_request_cb:
            return await self._send_request_cb(method, params, timeout=timeout)
        raise ConnectionError("No transport available")

    async def send_stream(self, rpc_id: Any, chunk: Any):
        if self._send_stream_cb:
            return await self._send_stream_cb(rpc_id, chunk)

    async def send_stream_chunk(self, rpc_id: Any, chunk: Any):
        """Алиас для send_stream для соответствия контракту session.send_stream_chunk."""
        return await self.send_stream(rpc_id, chunk)

    async def close(self):
        if self._close_cb:
            return await self._close_cb()


# Регистрируем SQLAlchemy event listeners для автоматического контроля прав на уровне ORM
from . import security  # noqa: F401
