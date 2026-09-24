# -*- coding: utf-8 -*-
"""
Официальный плагин авторизации и пользователей rsgi-wsrpc (plugins/auth).
Предоставляет модели User/Role, сессии, токены, Row-Level Security и RPC-методы авторизации.
"""

from .core import (
    current_user_ctx,
    system_bypass_ctx,
    BasicSecureModel,
    RowSecureModel,
    SecureModelBase,
)
from .models import (
    User,
    Role,
    RolePermission,
    RefreshToken,
    ActiveSession,
    OAuthAccount,
    Team,
    SystemData,
)
from .permissions import (
    check_permissions,
    prefill_ownership,
)
from .config import (
    get_session_lifetime_days,
    get_max_active_sessions,
)
from .handlers import (
    issue_refresh_token,
    notify_session_change,
    cleanup_app_session,
    handle_ws_disconnect,
)

__all__ = [
    # Контексты и базовые классы RLS
    "current_user_ctx",
    "system_bypass_ctx",
    "BasicSecureModel",
    "RowSecureModel",
    "SecureModelBase",
    # Модели ORM
    "User",
    "Role",
    "RolePermission",
    "RefreshToken",
    "ActiveSession",
    "OAuthAccount",
    "Team",
    "SystemData",
    # Проверки прав
    "check_permissions",
    "prefill_ownership",
    # Настройки
    "get_session_lifetime_days",
    "get_max_active_sessions",
    # Хендлеры и сессии
    "issue_refresh_token",
    "notify_session_change",
    "cleanup_app_session",
    "handle_ws_disconnect",
]
