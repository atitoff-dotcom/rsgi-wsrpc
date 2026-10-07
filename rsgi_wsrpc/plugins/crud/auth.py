# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.crud.auth: Аутентификация и управление сессиями для панели CRUD.
Обеспечивает бесшовную SSO-интеграцию с приложением и изоляцию панели (Zero-Leakage).
"""

from __future__ import annotations
import secrets
from typing import Dict, Any, Optional, Callable

# Реестр активных сессий администраторов CRUD: token -> {username, role, ...}
_ACTIVE_CRUD_SESSIONS: Dict[str, Dict[str, Any]] = {}

# Пользовательский верификатор сессионного токена из основного приложения: fn(token) -> Optional[dict]
_crud_session_validator: Optional[Callable[[str], Any]] = None


def set_crud_session_validator(func: Callable[[str], Any]) -> None:
    """Устанавливает функцию валидации сессионного токена из основного приложения fn(token) -> user_info."""
    global _crud_session_validator
    _crud_session_validator = func


def get_crud_session_validator() -> Optional[Callable[[str], Any]]:
    """Возвращает текущую функцию валидации сессий."""
    return _crud_session_validator


def create_crud_session(user_info: Dict[str, Any], token: Optional[str] = None) -> str:
    """Создает или регистрирует защищенный токен сессии администратора."""
    if not token:
        token = secrets.token_hex(24)
    _ACTIVE_CRUD_SESSIONS[token] = user_info
    return token


def get_crud_session(token: str) -> Optional[Dict[str, Any]]:
    """Возвращает информацию о сессии по токену через локальный кэш или системный SSO валидатор."""
    if not token:
        return None
    if token in _ACTIVE_CRUD_SESSIONS:
        return _ACTIVE_CRUD_SESSIONS[token]
    if _crud_session_validator:
        try:
            res = _crud_session_validator(token)
            if res:
                return res
        except Exception:
            pass
    return None


def revoke_crud_session(token: str) -> None:
    """Завершает сессию администратора."""
    if token:
        _ACTIVE_CRUD_SESSIONS.pop(token, None)
