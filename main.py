# -*- coding: utf-8 -*-
"""
rsgi-wsrpc starter application entrypoint.
Runs on Granian RSGI:
    granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
Or directly:
    python main.py
"""

import sys
import asyncio
from itertools import count

from core.session import JsonRpcSession, rpc_method
from core.logger import setup_logging, logger
from core.lifecycle import run_startup_callbacks
from core.router import http_route, HTTP_ROUTES
from core.lib.config import config

# Initialize logging system
setup_logging()

GLOBAL_SESSION_COUNTER = count()


@http_route("/health", ["GET"])
async def health_check(scope, proto):
    """
    Standard HTTP health check.
    """
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"ok","framework":"rsgi-wsrpc"}'
    )


@http_route("/", ["GET"])
async def root_index(scope, proto):
    """
    Root informational endpoint.
    """
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"framework":"rsgi-wsrpc","status":"running","docs":"https://github.com/atitoff-dotcom/rsgi-wsrpc"}'
    )


@rpc_method("system.echo")
async def echo_handler(session: JsonRpcSession, params):
    """
    Simple echo method verifying symmetric JSON-RPC communication.
    """
    return {"status": "ok", "echo": params}


@rpc_method("system.status")
async def status_handler(session: JsonRpcSession, params):
    """
    System status and diagnostics method.
    """
    return {
        "status": "healthy",
        "framework": "rsgi-wsrpc",
        "session_id": session.session_id,
        "is_authenticated": session.is_authenticated,
        "user_id": session.user_id,
    }


async def app(scope, proto):
    """
    Granian RSGI interface entrypoint.
    Routes HTTP requests and upgrades WebSocket connections to WSRPC sessions.
    """
    if scope.proto == "http":
        if scope.method == "OPTIONS":
            try:
                proto.response_str(
                    status=204,
                    headers=[
                        ("access-control-allow-origin", "*"),
                        ("access-control-allow-methods", "POST, GET, OPTIONS"),
                        ("access-control-allow-headers", "content-type, authorization"),
                    ],
                    body=""
                )
            except Exception:
                pass
            return

        matched_handler = None
        for route_path, methods, handler in HTTP_ROUTES:
            if scope.path == route_path and scope.method in methods:
                matched_handler = handler
                break

        if matched_handler:
            await matched_handler(scope, proto)
            return

        try:
            proto.response_str(
                status=404,
                headers=[("content-type", "text/plain")],
                body="404 Not Found"
            )
        except Exception:
            pass
        return

    # WebSocket connection upgrade
    try:
        ws = await proto.accept()
        session_id = next(GLOBAL_SESSION_COUNTER)
        session = JsonRpcSession(ws, session_id)
        await session.start()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"[WSRPC] Connection exception: {e}", exc_info=True)


def __rsgi_init__(loop):
    """
    Executes eager startup callbacks on Granian worker initialization.
    """
    try:
        loop.run_until_complete(run_startup_callbacks())
    except Exception as e:
        logger.error(f"[Startup] Critical initialization error: {e}", exc_info=True)
        sys.exit(1)


app.__rsgi_init__ = __rsgi_init__


if __name__ == "__main__":
    import granian
    server_conf = config.get("server", {})
    host = server_conf.get("host", "127.0.0.1")
    port = int(server_conf.get("port", 8080))
    logger.info(f"Starting rsgi-wsrpc server on {host}:{port} via Granian...")
    granian.Granian("main:app", interface="rsgi", address=host, port=port).serve()
