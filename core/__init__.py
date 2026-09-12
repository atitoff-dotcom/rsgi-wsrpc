"""
rsgi-wsrpc: High-performance reactive fullstack Python framework on Rust RSGI (Granian).
"""
import sys

# Обеспечиваем взаимную доступность пакета как rsgi_wsrpc, так и core
sys.modules.setdefault("rsgi_wsrpc", sys.modules[__name__])

from core.session import (
    rpc_method, RPCError, JsonRpcSession,
    current_user_ctx, current_session_ctx, current_transport_ctx
)
from core.tabular import pack_tabular, unpack_tabular, tabular_response, is_tabular
from core.logger import logger
from core.router import http_route
from core.lifecycle import on_startup, run_startup_callbacks

__all__ = [
    "rpc_method", "RPCError", "JsonRpcSession",
    "current_user_ctx", "current_session_ctx", "current_transport_ctx",
    "pack_tabular", "unpack_tabular", "tabular_response", "is_tabular",
    "logger", "http_route", "on_startup", "run_startup_callbacks"
]
