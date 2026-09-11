# -*- coding: utf-8 -*-
"""
rsgi-wsrpc starter application entrypoint.
Runs on Granian RSGI:
    granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
"""

import asyncio
from itertools import count

# Register system database models and handlers
import app.system.auth.models  # noqa: F401
import app.system.files.models  # noqa: F401
import app.system.login.handlers  # noqa: F401
import app.system.auth.handlers  # noqa: F401
import app.system.admin.handlers  # noqa: F401
import app.system.files.handlers  # noqa: F401

from core.session import JsonRpcSession, rpc_method
from core.logger import setup_logging
from core.lifecycle import run_startup_callbacks
from core.router import http_route, HTTP_ROUTES

# Initialize logging system
setup_logging()

GLOBAL_SESSION_COUNTER = count()


@http_route("/health", ["GET"])
async def health_check(scope, proto):
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"ok","framework":"rsgi-wsrpc"}'
    )


@rpc_method("system.echo")
async def echo_handler(session: JsonRpcSession, params):
    """
    Simple echo method verifying symmetric JSON-RPC communication.
    """
    return {"status": "ok", "echo": params}


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
                        ("access-control-allow-headers", "content-type, authorization, x-file-name, x-folder-hash"),
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
        import traceback
        print(f"[WSRPC] Connection exception: {e}")
        traceback.print_exc()


def __rsgi_init__(loop):
    """
    Executes eager startup callbacks on Granian worker initialization.
    """
    try:
        loop.run_until_complete(run_startup_callbacks())
    except Exception as e:
        import sys
        print(f"[Startup] Critical initialization error: {e}")
        sys.exit(1)
