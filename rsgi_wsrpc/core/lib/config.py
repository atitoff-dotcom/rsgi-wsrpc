# -*- coding: utf-8 -*-
"""
Конфигурация ядра платформы rsgi-wsrpc (Code-First).
Полный отказ от обязательных YAML-файлов: настройки задаются в коде,
через переменные окружения (12-Factor App) или используют безопасные dev-дефолты.
"""

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("core.config")


def deep_merge(dict1: dict, dict2: dict) -> dict:
    """
    Рекурсивно объединяет два словаря. Значения из dict2 перезаписывают dict1.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Settings:
    """
    Древовидная обертка над словарем настроек с доступом через атрибуты и ключи.
    """
    def __init__(self, data: dict):
        self._data = data

    def __getattr__(self, name: str) -> Any:
        if name in self._data:
            val = self._data[name]
            if isinstance(val, dict):
                return Settings(val)
            return val
        raise AttributeError(f"Настройка '{name}' не найдена в конфигурации")

    def get(self, name: str, default: Any = None) -> Any:
        val = self._data.get(name, default)
        if isinstance(val, dict):
            return Settings(val)
        return val

    def __getitem__(self, name: str) -> Any:
        if name in self._data:
            val = self._data[name]
            if isinstance(val, dict):
                return Settings(val)
            return val
        raise KeyError(name)

    def to_dict(self) -> dict:
        return self._data.copy()

    def update(self, new_data: dict) -> None:
        self._data = deep_merge(self._data, new_data)

    def __repr__(self) -> str:
        return f"Settings({self._data!r})"


def _build_default_settings() -> dict:
    """
    Формирует словарь дефолтных настроек ядра с чтением переменных окружения.
    """
    idle_timeout_raw = os.getenv("SESSION_IDLE_TIMEOUT", "900")
    try:
        session_idle_timeout = int(idle_timeout_raw)
    except ValueError:
        session_idle_timeout = 900

    pwd_iter_raw = os.getenv("PASSWORD_ITERATIONS", "10000")
    try:
        password_iterations = int(pwd_iter_raw)
    except ValueError:
        password_iterations = 10000

    token_expire_raw = os.getenv("TOKEN_EXPIRE_HOURS", "24")
    try:
        token_expire_hours = int(token_expire_raw)
    except ValueError:
        token_expire_hours = 24

    return {
        "security": {
            "secret_key": os.getenv("SECRET_KEY", "dev-insecure-secret-key-change-in-production"),
            "session_idle_timeout": session_idle_timeout,
            "password_iterations": password_iterations,
            "token_expire_hours": token_expire_hours,
            "login_rpc": os.getenv("LOGIN_RPC", ""),
        },
        "database_url": os.getenv("DATABASE_URL", "sqlite:///./data/app.db"),
        "files_path": os.getenv("FILES_PATH", "./files"),
    }


# Глобальный синглтон настроек
settings = Settings(_build_default_settings())


def configure(
    secret_key: Optional[str] = None,
    session_idle_timeout: Optional[int] = None,
    password_iterations: Optional[int] = None,
    token_expire_hours: Optional[int] = None,
    login_rpc: Optional[str] = None,
    database_url: Optional[str] = None,
    files_path: Optional[str] = None,
    custom: Optional[Dict[str, Any]] = None,
    **kwargs: Any
) -> Settings:
    """
    Программное конфигурирование ядра rsgi-wsrpc в коде (Code-First).

    Пример использования в main.py:
        from core.lib.config import configure
        configure(
            secret_key=os.getenv("MY_SECRET", "prod-secret-abc"),
            session_idle_timeout=1800,
            database_url="sqlite+aiosqlite:///data/agrita.db"
        )
    """
    updates: Dict[str, Any] = {}
    sec_updates: Dict[str, Any] = {}

    if secret_key is not None:
        sec_updates["secret_key"] = secret_key
    if session_idle_timeout is not None:
        sec_updates["session_idle_timeout"] = session_idle_timeout
    if password_iterations is not None:
        sec_updates["password_iterations"] = password_iterations
    if token_expire_hours is not None:
        sec_updates["token_expire_hours"] = token_expire_hours
    if login_rpc is not None:
        sec_updates["login_rpc"] = login_rpc

    if sec_updates:
        updates["security"] = sec_updates

    if database_url is not None:
        updates["database_url"] = database_url
    if files_path is not None:
        updates["files_path"] = files_path

    if custom:
        updates = deep_merge(updates, custom)
    if kwargs:
        updates = deep_merge(updates, kwargs)

    if updates:
        settings.update(updates)
        logger.debug(f"[CONFIG] Ядро обновлено параметрами: {list(updates.keys())}")

    return settings


def get_config() -> Settings:
    """Возвращает текущий синглтон настроек ядра Settings."""
    return settings


def get_settings() -> Settings:
    """Алиас для get_config()."""
    return settings

