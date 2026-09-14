# -*- coding: utf-8 -*-
"""
ORM-модели пользователей, ролей, сессий и токенов (plugins/auth/models.py).
"""

from typing import List, Optional
import hashlib  
import os
import base64
from datetime import datetime, timezone

from sqlalchemy import String, Integer, Boolean, Text, ForeignKey, Table, Column, DateTime, func, JSON, select
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from plugins.db import Base
from plugins.auth.core import RowSecureModel, BasicSecureModel, system_bypass_ctx

# Many-to-Many association tables
user_role_association = Table(
    "auth_user_auth_role",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("auth_user.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("auth_role.id", ondelete="CASCADE"), primary_key=True),
)

user_team_association = Table(
    "auth_user_auth_team",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("auth_user.id", ondelete="CASCADE"), primary_key=True),
    Column("team_id", Integer, ForeignKey("auth_team.id", ondelete="CASCADE"), primary_key=True),
)


class Team(RowSecureModel):
    __tablename__ = "auth_team"

    name: Mapped[str] = mapped_column(String(100))

    users: Mapped[List["User"]] = relationship(
        "User", secondary=user_team_association, back_populates="teams"
    )


class Role(RowSecureModel):
    __tablename__ = "auth_role"

    name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str] = mapped_column(Text)

    permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission", back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[List["User"]] = relationship(
        "User", secondary=user_role_association, back_populates="roles"
    )
    
    def __str__(self):
        return f"Роль пользователя {self.name} [{self.id}]"


class RolePermission(RowSecureModel):
    __tablename__ = "auth_role_permission"

    role_id: Mapped[int] = mapped_column(ForeignKey("auth_role.id", ondelete="CASCADE"), index=True)
    role: Mapped["Role"] = relationship("Role", back_populates="permissions")

    model_name: Mapped[str] = mapped_column(String(100))
    
    can_create: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    can_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    can_update: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    can_delete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    
    row_level_only: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")


class RefreshToken(Base):
    """
    Модель для хранения токенов обновления (RefreshToken).
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_user.id", ondelete="CASCADE"))
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
    
    token: Mapped[str] = mapped_column(String(512), unique=True, index=True, comment="Сам токен обновления")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="Дата и время истечения срока действия токена")

    def __str__(self) -> str:
        if self.user and self.user.login:
            return f"Refresh Token for {self.user.login}"
        return f"Refresh Token for User ID {self.user_id}"


class ActiveSession(Base):
    """
    Модель для отслеживания активных WebSocket-сессий.
    """
    __tablename__ = "active_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_user.id", ondelete="CASCADE"))
    user: Mapped["User"] = relationship("User", back_populates="active_sessions")
    
    ip_address: Mapped[str] = mapped_column(String(45), comment="IP-адрес клиента")
    user_agent: Mapped[str] = mapped_column(String(500), comment="User-Agent клиента")
    
    refresh_token_id: Mapped[Optional[int]] = mapped_column(ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True)
    refresh_token: Mapped[Optional["RefreshToken"]] = relationship("RefreshToken")
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), 
        comment="Дата и время начала активной сессии"
    )

    def __str__(self) -> str:
        if self.user and self.user.login:
            return f"Active Session {self.id} for {self.user.login}"
        return f"Active Session {self.id} for User ID {self.user_id}"


class User(RowSecureModel):
    __tablename__ = "auth_user"

    name: Mapped[str] = mapped_column(String(100))
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    middle_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    login: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, unique=True)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    primary_team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    roles: Mapped[List["Role"]] = relationship(
        "Role", secondary=user_role_association, back_populates="users"
    )
    teams: Mapped[List["Team"]] = relationship(
        "Team", secondary=user_team_association, back_populates="users"
    )
    
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    active_sessions: Mapped[List["ActiveSession"]] = relationship("ActiveSession", back_populates="user", cascade="all, delete-orphan")
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")

    def __str__(self):
        return f"Пользователь {self.login or self.name} [{self.id}]"

    def get_team_ids(self) -> list:
        team_ids = [t.id for t in self.teams]
        if self.primary_team_id:
            if self.primary_team_id in team_ids:
                team_ids.remove(self.primary_team_id)
            team_ids.insert(0, self.primary_team_id)
        return team_ids

    def _get_permissions_dict(self) -> dict:
        merged_perms = {}
        for role in self.roles:
            for p in role.permissions:
                m = p.model_name
                if m not in merged_perms:
                    merged_perms[m] = {
                        "can_read": False, "read_global": False,
                        "can_update": False, "update_global": False,
                        "can_delete": False, "delete_global": False,
                        "can_create": False, "create_global": False,
                    }
                
                if p.can_read:
                    merged_perms[m]["can_read"] = True
                    if not p.row_level_only:
                        merged_perms[m]["read_global"] = True
                
                if p.can_update:
                    merged_perms[m]["can_update"] = True
                    if not p.row_level_only:
                        merged_perms[m]["update_global"] = True
                
                if p.can_create:
                    merged_perms[m]["can_create"] = True
                    if not p.row_level_only:
                        merged_perms[m]["create_global"] = True

                if p.can_delete:
                    merged_perms[m]["can_delete"] = True
                    if not p.row_level_only:
                        merged_perms[m]["delete_global"] = True
                        
        return merged_perms

    @property
    def is_superadmin(self) -> bool:
        return any(role.id == 1 or role.name == "admin" for role in self.roles)

    def get_permissions(self):
        return type("UserContext", (), {
            "user_id": self.id,
            "team_ids": self.get_team_ids(),
            "perms_dict": self._get_permissions_dict(),
            "is_superadmin": self.is_superadmin
        })()


    def check_permission(self, model_name: str, perm_name: str = None) -> tuple[bool, bool]:
        perm_dict = self._get_permissions_dict()
        if model_name not in perm_dict:
            return False, False
        if perm_name is None:
            return perm_dict[model_name]["can_read"], perm_dict[model_name]["can_read"] and perm_dict[model_name]["read_global"]
        if perm_name == "create":
            perm_key = "can_create"
            return perm_dict[model_name][perm_key], perm_dict[model_name][perm_key]
        elif perm_name == "read":
            perm_key = "can_read"
            glob_key = "read_global"
        elif perm_name == "update":
            perm_key = "can_update"
            glob_key = "update_global"
        elif perm_name == "delete":
            perm_key = "can_delete"
            glob_key = "delete_global"
        else:
            return False, False
        return perm_dict[model_name][perm_key], perm_dict[model_name][perm_key] and perm_dict[model_name][glob_key]

    @classmethod
    async def get_permissions_by_id(cls, db_session, user_id: int):
        token = system_bypass_ctx.set(True)
        try:
            stmt = select(cls).options(
                selectinload(cls.roles).selectinload(Role.permissions),
                selectinload(cls.teams)
            ).where(cls.id == user_id)
            result = await db_session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                return None
            return user.get_permissions()
        finally:
            system_bypass_ctx.reset(token)

    def verify_password(self, password: str) -> bool:
        if not password:
            return False
        if not self.password_hash:
            return False

        if self.password_hash.startswith("pbkdf2_sha256$"):
            try:
                db_parts = self.password_hash.split("$")
                if len(db_parts) != 4:
                    return False
                algorithm, iterations_str, salt_b64, key_b64 = db_parts
                salt = base64.b64decode(salt_b64)
                iterations = int(iterations_str)
                db_hash = base64.b64decode(key_b64)
            
                user_hash = self._hash_password(password, salt, iterations)
                algorithm, iterations_str, salt_b64, key_b64 = user_hash.split("$")
                user_hash = base64.b64decode(key_b64)
                return db_hash == user_hash
            except Exception:
                return False
        else:
            from core.logger import logger
            logger.warning(f"Используется устаревший алгоритм хэширования SHA-256 для пользователя {self.login}")
            try:
                hashed_simple = hashlib.sha256(password.encode("utf-8")).hexdigest()
                return hashed_simple == self.password_hash
            except Exception:
                return False

    def verify_raw_password(self, raw_password: str) -> bool:
        return self.verify_password(raw_password)

    @classmethod
    def _hash_password(cls, password: str, salt: bytes = None, iterations: int = None) -> str:
        if salt is None:
            salt = os.urandom(16)
        if iterations is None:
            from core.lib.config import settings
            try:
                iterations = settings.security.password_iterations
            except AttributeError:
                iterations = 10000
        key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode('utf-8')}${base64.b64encode(key).decode('utf-8')}"


class SystemData(Base):
    """
    Таблица для хранения произвольных системных данных в формате JSON.
    """
    __tablename__ = "system_data"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), 
        comment="Время последнего обновления"
    )

    def __str__(self) -> str:
        return f"SystemData({self.key})"


class OAuthAccount(Base):
    """
    Модель для привязки внешних аккаунтов авторизации (VK ID, Yandex ID и др.).
    """
    __tablename__ = "oauth_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth_user.id", ondelete="CASCADE"), index=True)
    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts")

    provider: Mapped[str] = mapped_column(String(50), index=True, comment="Имя провайдера (например, vk)")
    provider_user_id: Mapped[str] = mapped_column(String(100), index=True, comment="Идентификатор пользователя у провайдера")
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    extra_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, comment="Дополнительные данные профиля")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(), 
        comment="Дата привязки внешнего аккаунта"
    )

    def __str__(self) -> str:
        return f"OAuthAccount({self.provider}:{self.provider_user_id} -> User #{self.user_id})"
