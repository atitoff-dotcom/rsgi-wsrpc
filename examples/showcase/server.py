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


# Static directory and SQLite DB path
PUBLIC_DIR = os.path.join(SHOWCASE_DIR, "public")
DB_PATH = os.path.join(SHOWCASE_DIR, "showcase.db")

# Create RsgiWsrpcApp application instance (SQLite + Zero-Copy Granian Static)
# dev_admin=True: автоматический роут /dev-admin для быстрого перехода в панель CRUD
# auto_auth_ws=True (по умолчанию): сокеты автоматически авторизуются по Cookie
# auto_auth_models=True (по умолчанию): User, Role, RpcPermission регистрируются в CRUD автоматически
app = RsgiWsrpcApp(
    secret_key=os.getenv("SECRET_KEY", "showcase-demo-secret-key-1234567890-secure-seed"),
    database_url=os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}"),
    login_rpc="",  # Public access for interactive showcase
    static_dir=PUBLIC_DIR,
    index_file="index.html",
    dev_admin=True,
    cors=True
)

# Регистрация бизнес-моделей в CRUD
from models import Task, Document
ModelRegistry.register(Task)
ModelRegistry.register(Document)

# Регистрация RPC-хендлеров и плагинов
import handlers  # noqa: F401
import rsgi_wsrpc.plugins.files  # Registers HTTP /upload and RPC files.*
import rsgi_wsrpc.plugins.crud as crud  # noqa: F401

# Initialize logging
setup_logging()


@app.on_startup
async def init_database():
    """Asynchronously creates SQLite database tables and seeds demo data on server startup."""
    from rsgi_wsrpc.plugins.auth import system_bypass_ctx, User, Role
    token = system_bypass_ctx.set(True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Safe migration for existing SQLite database if owner_id column is absent
            try:
                from sqlalchemy import text
                await conn.execute(text("ALTER TABLE showcase_tasks ADD COLUMN owner_id INTEGER"))
            except Exception:
                pass
        logger.info("[Showcase] SQLite database initialized successfully.")

        # Initialize Smart Cache tag version registry
        await version_registry.initialize()

        # Seed initial demo tasks and documents if tables are empty
        from sqlalchemy import select, func, update
        async with async_session() as db:
            # Update existing tasks owner_id if NULL
            await db.execute(update(Task).where(Task.id == 1, Task.owner_id == None).values(owner_id=1))
            await db.execute(update(Task).where(Task.id.in_([2, 3]), Task.owner_id == None).values(owner_id=2))
            await db.execute(update(Task).where(Task.id >= 4, Task.owner_id == None).values(owner_id=3))

            count_tasks = (await db.execute(select(func.count(Task.id)))).scalar_one()
            if count_tasks == 0:
                demo_tasks = [
                    Task(title="Start rsgi-wsrpc showcase server (Admin)", priority="high", completed=True, owner_id=1),
                    Task(title="Inspect traffic savings with RFC 0002 ($tabular) (Alice)", priority="high", completed=False, owner_id=2),
                    Task(title="Test Smart Cache tag invalidation across tabs (Alice)", priority="normal", completed=False, owner_id=2),
                    Task(title="Run multi-return streaming task with live chunks (Bob)", priority="normal", completed=False, owner_id=3),
                    Task(title="Trigger symmetric Reverse RPC call from server (Bob)", priority="low", completed=False, owner_id=3),
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

            # Seed demo roles and users
            count_roles = (await db.execute(select(func.count(Role.id)))).scalar_one()
            if count_roles == 0:
                role_admin = Role(name="admin", description="Full administrator access")
                role_user = Role(name="user", description="Regular user with basic access")
                role_editor = Role(name="editor", description="Content editor")
                db.add_all([role_admin, role_user, role_editor])
                await db.flush()

            count_users = (await db.execute(select(func.count(User.id)))).scalar_one()
            if count_users == 0:
                user_admin = User(login="admin", name="Administrator", first_name="Admin", last_name="System", email="admin@example.com")
                user_alice = User(login="alice", name="Alice Wonderland", first_name="Alice", last_name="Wonderland", email="alice@example.com")
                user_bob = User(login="bob", name="Bob Builder", first_name="Bob", last_name="Builder", email="bob@example.com")
                db.add_all([user_admin, user_alice, user_bob])
                await db.flush()

                r_admin = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one_or_none()
                r_user = (await db.execute(select(Role).where(Role.name == "user"))).scalar_one_or_none()
                if r_admin:
                    user_admin.roles.append(r_admin)
                if r_user:
                    user_alice.roles.append(r_user)
                    user_bob.roles.append(r_user)

            await db.commit()
            logger.info("[Showcase] Initial demo records seeded successfully.")

    except Exception as e:
        logger.error(f"[Showcase] Database initialization error: {e}", exc_info=True)
    finally:
        system_bypass_ctx.reset(token)


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
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((preferred_host, p))
                return p
            except OSError:
                continue

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((preferred_host, 0))
        return s.getsockname()[1]


def get_local_ip() -> str:
    """Определяет локальный IP-адрес машины в сети."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    import argparse
    from granian import Granian

    parser = argparse.ArgumentParser(description="rsgi-wsrpc Showcase Server")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"), help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="Port to bind (default: 8080)")
    args, _ = parser.parse_known_args()

    host = args.host
    requested_port = args.port
    port = find_available_port(host, requested_port)
    lan_ip = get_local_ip()

    print("=" * 70)
    print(" ⚡ rsgi-wsrpc Showcase: Interactive Demo & Living Documentation")
    if port != requested_port:
        print(f" [!] Notice: Port {requested_port} is busy or restricted by OS.")
        print(f" [!] Automatically selected available port: {port}")
    print(f" 🌐 Web UI (Local): http://127.0.0.1:{port}/")
    if host in ("0.0.0.0", "::"):
        print(f" 🌐 Web UI (LAN):   http://{lan_ip}:{port}/")
        print(f" 🗄️  CRUD Admin:    http://{lan_ip}:{port}/crud")
    else:
        print(f" 🗄️  CRUD Admin:    http://{host}:{port}/crud")
    print(f" 🔌 WSRPC Socket:   ws://{host}:{port}/")
    print(f" 💾 Database:       SQLite ({DB_PATH})")
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
