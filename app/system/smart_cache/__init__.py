# -*- coding: utf-8 -*-
"""
Официальный плагин умного реактивного кэширования rsgi-wsrpc (plugins/smart_cache).
"""

from app.system.smart_cache.engine import (
    CacheTagVersion,
    VersionRegistry,
    version_registry,
    invalidates,
    invalidate_tags,
    patch_tag,
)
import app.system.smart_cache.handlers  # Регистрация RPC-методов

__all__ = [
    "CacheTagVersion",
    "VersionRegistry",
    "version_registry",
    "invalidates",
    "invalidate_tags",
    "patch_tag",
]
