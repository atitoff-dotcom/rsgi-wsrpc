# -*- coding: utf-8 -*-
"""
Официальные системные плагины фреймворка rsgi-wsrpc (Official Batteries).
"""

from plugins import db
from plugins import auth
from plugins import broadcast
from plugins import smart_cache
from plugins import raw_ws

__all__ = [
    "db",
    "auth",
    "broadcast",
    "smart_cache",
    "raw_ws",
]
