# -*- coding: utf-8 -*-
"""
rsgi-wsrpc: High-performance reactive fullstack Python framework on Rust RSGI (Granian)
with symmetric WSRPC (JSON-RPC 2.0) and Tabular Data Compression (RFC 0002).
"""

# Автоматическая активация моста обратной совместимости для плоских импортов core и plugins
from rsgi_wsrpc.compat import install_compat
install_compat()

from rsgi_wsrpc.core.session import (
    rpc_method, RPCError, JsonRpcSession,
    current_user_ctx, current_session_ctx, current_rpc_id_ctx, current_transport_ctx,
    ACTIVE_SESSIONS_SET
)
from rsgi_wsrpc.core.tabular import pack_tabular, unpack_tabular, tabular_response, is_tabular
from rsgi_wsrpc.core.constants import UserRole
from rsgi_wsrpc.core.router import http_route, HTTP_ROUTES
from rsgi_wsrpc.core.lifecycle import (
    on_startup, on_shutdown, run_startup_callbacks, run_shutdown_callbacks
)
from rsgi_wsrpc.core.logger import logger, setup_logging
from rsgi_wsrpc.core.lib.config import configure, get_config

from rsgi_wsrpc import core
from rsgi_wsrpc import plugins

__version__ = "0.2.0"

__all__ = [
    "rpc_method",
    "RPCError",
    "JsonRpcSession",
    "current_user_ctx",
    "current_session_ctx",
    "current_rpc_id_ctx",
    "current_transport_ctx",
    "ACTIVE_SESSIONS_SET",
    "pack_tabular",
    "unpack_tabular",
    "tabular_response",
    "is_tabular",
    "UserRole",
    "http_route",
    "HTTP_ROUTES",
    "on_startup",
    "on_shutdown",
    "run_startup_callbacks",
    "run_shutdown_callbacks",
    "logger",
    "setup_logging",
    "configure",
    "get_config",
    "core",
    "plugins",
    "install_compat",
]
