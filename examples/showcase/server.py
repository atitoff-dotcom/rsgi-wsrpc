# -*- coding: utf-8 -*-
"""
Main entry point for the Showcase demonstration server (rsgi-wsrpc).
Run:
    python server.py
    or
    granian --rsgi server:app --host 127.0.0.1 --port 8080 --workers 1

Server available at: http://127.0.0.1:8080
"""

import os
import sys
import asyncio
from datetime import datetime, timezone

# Ensure framework root and showcase directory are importable
SHOWCASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAMEWORK_ROOT = os.path.abspath(os.path.join(SHOWCASE_DIR, "..", ".."))

if os.path.isdir(os.path.join(FRAMEWORK_ROOT, "rsgi_wsrpc")) and FRAMEWORK_ROOT not in sys.path:
    sys.path.insert(0, FRAMEWORK_ROOT)
if SHOWCASE_DIR not in sys.path:
    sys.path.insert(0, SHOWCASE_DIR)

# Framework core imports
from rsgi_wsrpc import RsgiWsrpcApp
from rsgi_wsrpc.core.logger import setup_logging, logger
from rsgi_wsrpc.plugins.db import engine, Base, async_session
from rsgi_wsrpc.plugins.smart_cache import version_registry
from rsgi_wsrpc.plugins.crud import ModelRegistry

# Compatibility patch: Granian RSGI passes scope.proto == "ws"
_orig_rsgi_call = RsgiWsrpcApp.__call__
async def _compatible_rsgi_call(self, scope, proto):
    if getattr(scope, "proto", "") == "ws":
        await self._handle_websocket(scope, proto)
        return
    return await _orig_rsgi_call(self, scope, proto)

RsgiWsrpcApp.__call__ = _compatible_rsgi_call

# Static directory and SQLite DB path
PUBLIC_DIR = os.path.join(SHOWCASE_DIR, "public")
DB_PATH = os.path.join(SHOWCASE_DIR, "showcase.db")

# Create RsgiWsrpcApp application instance (SQLite + Zero-Copy Granian Static)
app = RsgiWsrpcApp(
    secret_key=os.getenv("SECRET_KEY", "showcase-demo-secret-key-12345"),
    database_url=os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}"),
    login_rpc="",  # Public access for interactive showcase
    static_dir=PUBLIC_DIR,
    index_file="index.html",
    cors=True
)

# Model imports & CRUD Registry registration
from models import Task, Document
ModelRegistry.register(Task)
ModelRegistry.register(Document)

# Register showcase RPC handlers and plugins
import handlers  # noqa: F401
import rsgi_wsrpc.plugins.files  # Registers HTTP /upload and RPC files.*

# Initialize logging
setup_logging()


@app.on_startup
async def init_database():
    """Asynchronously creates SQLite database tables and seeds demo data on server startup."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[Showcase] SQLite database initialized successfully.")

        # Initialize Smart Cache tag version registry
        await version_registry.initialize()

        # Seed initial demo tasks and documents if tables are empty
        from sqlalchemy import select, func
        async with async_session() as db:
            count_tasks = (await db.execute(select(func.count(Task.id)))).scalar_one()
            if count_tasks == 0:
                demo_tasks = [
                    Task(title="Start rsgi-wsrpc showcase server", priority="high", completed=True),
                    Task(title="Inspect traffic savings with RFC 0002 ($tabular)", priority="high", completed=False),
                    Task(title="Test Smart Cache tag invalidation across tabs", priority="normal", completed=False),
                    Task(title="Run multi-return streaming task with live chunks", priority="normal", completed=False),
                    Task(title="Trigger symmetric Reverse RPC call from server", priority="low", completed=False),
                ]
                db.add_all(demo_tasks)

            count_docs = (await db.execute(select(func.count(Document.id)))).scalar_one()
            if count_docs == 0:
                demo_docs = [
                    Document(title="rsgi-wsrpc Architecture Manifesto", category="architecture", views=142, content="Granian RSGI + JSON-RPC 2.0 full duplex"),
                    Document(title="RFC 0002 Tabular Compression Specification", category="specs", views=98, content="40-70% wire traffic reduction"),
                    Document(title="Universal Reactive CRUD Guide", category="guides", views=64, content="Declarative class Crud: mapping"),
                ]
                db.add_all(demo_docs)

            await db.commit()
            logger.info("[Showcase] Initial demo records seeded successfully.")

    except Exception as e:
        logger.error(f"[Showcase] Database initialization error: {e}", exc_info=True)


@app.route("/health", ["GET"])
async def health_handler(scope, proto):
    """Healthcheck endpoint."""
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"ok","framework":"rsgi-wsrpc","showcase":"ready","database":"sqlite"}'
    )


def find_available_port(preferred_host: str, preferred_port: int) -> int:
    """Probes if preferred_port is available; if blocked or occupied, finds a free alternative."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((preferred_host, preferred_port))
            return preferred_port
        except OSError:
            pass

    # Common alternative development ports
    candidate_ports = [8000, 8081, 8088, 3000, 5000, 8888] + list(range(8082, 8100))
    for p in candidate_ports:
        if p == preferred_port:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((preferred_host, p))
                return p
            except OSError:
                continue

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((preferred_host, 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    import argparse
    from granian import Granian

    parser = argparse.ArgumentParser(description="rsgi-wsrpc Showcase Server")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"), help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="Port to bind (default: 8080)")
    args, _ = parser.parse_known_args()

    host = args.host
    requested_port = args.port
    port = find_available_port(host, requested_port)

    print("=" * 70)
    print(" ⚡ rsgi-wsrpc Showcase: Interactive Demo & Living Documentation")
    if port != requested_port:
        print(f" [!] Notice: Port {requested_port} is busy or restricted by OS (error 10013).")
        print(f" [!] Automatically selected available port: {port}")
    print(f" 🌐 Web UI:       http://{host}:{port}/")
    print(f" 🗄️  CRUD Admin:   http://{host}:{port}/crud")
    print(f" 🔌 WSRPC Socket: ws://{host}:{port}/")
    print(f" 💾 Database:     SQLite ({DB_PATH})")
    print(" 📖 Press Ctrl+C to stop the server")
    print("=" * 70)

    server = Granian(
        "server:app",
        address=host,
        port=port,
        interface="rsgi",
        reload=False,
        workers=1,
    )
    server.serve()
