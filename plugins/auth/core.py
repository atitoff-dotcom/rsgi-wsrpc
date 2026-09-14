# -*- coding: utf-8 -*-
"""
Базовые классы и контексты плагина авторизации (plugins/auth/core.py).
Обеспечивают Row-Level Security (RLS) на уровне ORM SQLAlchemy.
"""

from contextvars import ContextVar
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, DateTime, func

from plugins.db import Base
from core.session import current_user_ctx

# Контекстная переменная для обхода проверок прав системными операциями (Bypass)
system_bypass_ctx: ContextVar[bool] = ContextVar("system_bypass", default=False)


class BasicSecureModel(Base):
    """
    Базовый класс для моделей с проверкой прав на уровне модели (без row-level полей).
    """
    __abstract__ = True


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

# Регистрируем SQLAlchemy event listeners для автоматического контроля прав на уровне ORM
import plugins.auth.security  # noqa: F401
