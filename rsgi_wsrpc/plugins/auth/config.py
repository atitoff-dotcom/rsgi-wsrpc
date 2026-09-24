# -*- coding: utf-8 -*-
"""
Конфигурация плагина авторизации (plugins/auth).
Позволяет приложению переопределять параметры через app_settings.yaml / settings.yaml.
"""

from typing import Any, Dict


def get_auth_settings() -> Dict[str, Any]:
    """
    Возвращает словарь настроек auth из конфигурации приложения.
    """
    try:
        from app.config import settings
        auth_conf = getattr(settings, "auth", None)
        if auth_conf and isinstance(auth_conf, dict):
            return auth_conf
        if hasattr(auth_conf, "__dict__"):
            return {k: v for k, v in auth_conf.__dict__.items() if not k.startswith("_")}
    except Exception:
        pass

    try:
        from rsgi_wsrpc.core.lib.config import settings as core_settings
        auth_conf = getattr(core_settings, "auth", None)
        if auth_conf and isinstance(auth_conf, dict):
            return auth_conf
    except Exception:
        pass

    return {}


def get_session_lifetime_days() -> int:
    """
    Срок действия скользящей сессии RefreshToken в днях (по умолчанию 30).
    """
    conf = get_auth_settings()
    try:
        return int(conf.get("session_lifetime_days", 30))
    except (ValueError, TypeError):
        return 30


def get_max_active_sessions() -> int:
    """
    Максимальное количество активных токенов на одного пользователя (по умолчанию 10).
    """
    conf = get_auth_settings()
    try:
        return int(conf.get("max_active_sessions", 10))
    except (ValueError, TypeError):
        return 10
