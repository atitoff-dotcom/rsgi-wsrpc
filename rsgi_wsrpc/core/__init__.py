"""
rsgi-wsrpc: High-performance reactive fullstack Python framework on Rust RSGI (Granian).
"""

from .session import (
    rpc_method, RPCError, JsonRpcSession,
    current_user_ctx, current_session_ctx, current_transport_ctx
)
from .tabular import pack_tabular, unpack_tabular, tabular_response, is_tabular
from .logger import logger
from .router import http_route
from .lifecycle import on_startup, run_startup_callbacks

__all__ = [
    "rpc_method", "RPCError", "JsonRpcSession",
    "current_user_ctx", "current_session_ctx", "current_transport_ctx",
    "pack_tabular", "unpack_tabular", "tabular_response", "is_tabular",
    "logger", "http_route", "on_startup", "run_startup_callbacks"
]
