# -*- coding: utf-8 -*-
"""
Официальный плагин авторизации и пользователей rsgi-wsrpc (plugins/auth).
Предоставляет модели User/Role, сессии, токены, Row-Level Security и RPC-методы авторизации.
"""

from plugins.auth.core import (
    current_user_ctx,
    system_bypass_ctx,
    BasicSecureModel,
    RowSecureModel,
    SecureModelBase,
)
from plugins.auth.models import (
    User,
    Role,
    RolePermission,
    RefreshToken,
    ActiveSession,
    OAuthAccount,
    Team,
    SystemData,
)
from plugins.auth.permissions import (
    check_permissions,
    prefill_ownership,
)
from plugins.auth.config import (
    get_session_lifetime_days,
    get_max_active_sessions,
)
from plugins.auth.handlers import (
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
