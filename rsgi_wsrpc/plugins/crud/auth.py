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


_in_validator: bool = False


def get_crud_session(token: str) -> Optional[Dict[str, Any]]:
    """Возвращает информацию о сессии по токену через локальный кэш, системный SSO валидатор или нативный JWT."""
    global _in_validator
    if not token:
        return None
    if token in _ACTIVE_CRUD_SESSIONS:
        return _ACTIVE_CRUD_SESSIONS[token]

    # 1. Пользовательский SSO валидатор с защитой от рекурсии
    if _crud_session_validator and not _in_validator:
        _in_validator = True
        try:
            res = _crud_session_validator(token)
            if res:
                return res
        except Exception:
            pass
        finally:
            _in_validator = False

    # 2. Нативная валидация JWT токенов фреймворка rsgi-wsrpc из коробки
    try:
        from rsgi_wsrpc.core.security import decode_access_token
        payload = decode_access_token(token)
        if payload:
            roles = payload.get("roles", [])
            role = payload.get("role") or (roles[0] if roles else "user")
            is_superadmin = bool(
                "admin" in roles
                or "ADMIN" in roles
                or "superadmin" in roles
                or payload.get("is_superadmin")
                or role in ("admin", "ADMIN", "superadmin")
            )
            raw_sub = payload.get("sub", 1)
            uid = int(raw_sub) if str(raw_sub).isdigit() else 1
            return {
                "uid": uid,
                "user_id": uid,
                "username": payload.get("username", "admin" if is_superadmin else "user"),
                "role": "admin" if is_superadmin else role,
                "roles": roles if roles else [role],
                "is_superadmin": is_superadmin,
                "perms_dict": payload.get("permissions") or payload.get("perms_dict") or {},
                "allowed_rpc_methods": {"*"} if is_superadmin else set(payload.get("allowed_rpc_methods", [])),
            }
    except Exception:
        pass

    return None


def revoke_crud_session(token: str) -> None:
    """Завершает сессию администратора."""
    if token:
        _ACTIVE_CRUD_SESSIONS.pop(token, None)
