# -*- coding: utf-8 -*-
"""
Официальный плагин умного реактивного кэширования rsgi-wsrpc (plugins/smart_cache).
Реализует RFC 0001: Event-Driven Feedback Caching.
"""

from plugins.smart_cache.engine import (
    CacheTagVersion,
    VersionRegistry,
    version_registry,
    invalidates,
    invalidate_tags,
    patch_tag,
)
import plugins.smart_cache.handlers  # Регистрация RPC-методов

__all__ = [
    "CacheTagVersion",
    "VersionRegistry",
    "version_registry",
    "invalidates",
    "invalidate_tags",
    "patch_tag",
]
