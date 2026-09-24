# -*- coding: utf-8 -*-
"""
Официальный плагин умного реактивного кэширования rsgi-wsrpc (plugins/smart_cache).
Реализует RFC 0001: Event-Driven Feedback Caching.
"""

from .engine import (
    CacheTagVersion,
    VersionRegistry,
    version_registry,
    invalidates,
    invalidate_tags,
    patch_tag,
)
from . import handlers  # Регистрация RPC-методов

__all__ = [
    "CacheTagVersion",
    "VersionRegistry",
    "version_registry",
    "invalidates",
    "invalidate_tags",
    "patch_tag",
]
