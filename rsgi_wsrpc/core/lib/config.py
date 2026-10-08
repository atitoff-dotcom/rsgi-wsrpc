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
    Формирует словарь дефолтных настроек ядра rsgi-wsrpc (Code-First).
    Все настройки задаются в коде приложения (RsgiWsrpcApp / configure).
    """
    return {
        "security": {
            "secret_key": "dev-insecure-secret-key-change-in-production",
            "auth_timeout": 0,
            "guest_idle_timeout": 900,
            "user_idle_timeout": 1800,
            "session_idle_timeout": 900,
            "allow_guests": True,
            "password_iterations": 600000,
            "token_expire_hours": 24,
            "login_rpc": "login.",
        },
        "database_url": "sqlite+aiosqlite:///app.db",
        "files_path": "./files",
    }


# Глобальный синглтон настроек
settings = Settings(_build_default_settings())


def configure(
    secret_key: Optional[str] = None,
    auth_timeout: Optional[int] = None,
    guest_idle_timeout: Optional[int] = None,
    user_idle_timeout: Optional[int] = None,
    session_idle_timeout: Optional[int] = None,
    allow_guests: Optional[bool] = None,
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
            guest_idle_timeout=900,
            user_idle_timeout=1800,
            allow_guests=True,
            database_url="sqlite+aiosqlite:///data/agrita.db"
        )
    """
    updates: Dict[str, Any] = {}
    sec_updates: Dict[str, Any] = {}

    if secret_key is not None:
        sec_updates["secret_key"] = secret_key
    if auth_timeout is not None:
        sec_updates["auth_timeout"] = auth_timeout
    if guest_idle_timeout is not None:
        sec_updates["guest_idle_timeout"] = guest_idle_timeout
    if user_idle_timeout is not None:
        sec_updates["user_idle_timeout"] = user_idle_timeout
    if session_idle_timeout is not None:
        sec_updates["session_idle_timeout"] = session_idle_timeout
        if user_idle_timeout is None:
            sec_updates["user_idle_timeout"] = session_idle_timeout
    if allow_guests is not None:
        sec_updates["allow_guests"] = allow_guests
        if not allow_guests and auth_timeout is None:
            sec_updates["auth_timeout"] = 60
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
        try:
            import sys
            if "rsgi_wsrpc.plugins.db" in sys.modules or "rsgi_wsrpc.plugins.db.session" in sys.modules:
                from rsgi_wsrpc.plugins.db.session import configure_db
                configure_db(database_url, echo=kwargs.get("db_echo"))
        except Exception as e:
            logger.debug(f"[CONFIG] Авто-настройка БД: {e}")
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

