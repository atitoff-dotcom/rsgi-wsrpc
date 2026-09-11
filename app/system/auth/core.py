from contextvars import ContextVar
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, Mapped, mapped_column, declared_attr
from sqlalchemy import Integer, DateTime, func

from app.system.db import Base

from core.session import current_user_ctx

# Context variable to bypass security checks for system operations
system_bypass_ctx: ContextVar[bool] = ContextVar("system_bypass", default=False)

from sqlalchemy import or_

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(), onupdate=lambda: datetime.now(timezone.utc))

# Совместимый алиас для старого названия
SecureModelBase = RowSecureModel

# Регистрируем SQLAlchemy event listeners для автоматического контроля прав на уровне ORM
import app.system.auth.security

