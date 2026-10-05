# -*- coding: utf-8 -*-
"""
RPC handlers for the rsgi-wsrpc Showcase demonstration application.
Demonstrates framework core features and plugins:
1. JSON-RPC 2.0 methods (@rpc_method / @app.rpc)
2. RFC 0002 Tabular Data Compression (@tabular_response)
3. RFC 0001 Smart Cache & Tag-based Invalidation (@invalidates, invalidate_tags)
4. Multi-return Streaming (stream: true, send_stream_chunk)
5. Symmetric Reverse RPC (server calls browser method via session.send_request)
6. Realtime Broadcast (broadcast_notification O(1))
7. RBAC & Security (roles GUEST, USER, ADMIN)
8. SEO & Bot Detector (plugins.seo.detector)
"""

import asyncio
import time
import platform
import sys
from typing import Dict, Any, List, Optional
import orjson
from sqlalchemy import select, delete, update

from rsgi_wsrpc.core.session import (
    rpc_method, JsonRpcSession, RPCError,
    ACTIVE_SESSIONS_SET, current_rpc_id_ctx, current_transport_ctx
)
from rsgi_wsrpc.core.tabular import tabular_response
from rsgi_wsrpc.core.constants import UserRole
from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.plugins.db import async_session
from rsgi_wsrpc.plugins.broadcast import broadcast_notification
from rsgi_wsrpc.plugins.smart_cache import invalidates, version_registry, invalidate_tags
from rsgi_wsrpc.plugins.seo import is_bot, is_search_bot

try:
    from .models import Task, Document
except ImportError:
    from models import Task, Document


class DemoSessionData:
    """Lightweight session context object for showcase demonstration."""
    def __init__(self, username: str = "guest_user", role: str = "guest", session_id: int = 1):
        self.username = username
        self.role_name = role
        self.session_id = session_id
        self.user_id = 1
        if role == "admin":
            self.user_role = UserRole.ADMIN
            self.user_roles = [UserRole.ADMIN, UserRole.USER]
        elif role == "user":
            self.user_role = UserRole.USER
            self.user_roles = [UserRole.USER]
        else:
            self.user_role = UserRole.GUEST
            self.user_roles = [UserRole.GUEST]


def get_current_role(session) -> str:
    """Safely extracts role string from session or session.data."""
    target = getattr(session, "data", None) or session
    role = getattr(target, "user_role", None) or getattr(session, "user_role", UserRole.GUEST)
    if hasattr(role, "value"):
        return role.value
    return str(role)


# --- 1. SYSTEM METHODS (HEALTH & PING) ---

@rpc_method("system.ping", public=True)
async def ping(session, params: dict):
    """Ultra-fast ping-pong to measure network Round Trip Time (RTT)."""
    return {
        "status": "pong",
        "server_time": time.time(),
        "granian": "rsgi"
    }


@rpc_method("system.info", public=True)
async def system_info(session, params: dict):
    """System information, active sessions, and environment metrics."""
    transport = current_transport_ctx.get() or session
    role_val = get_current_role(transport)
    sid = getattr(transport, "session_id", getattr(session, "session_id", 1))

    return {
        "framework": "rsgi-wsrpc",
        "rsgi_server": "Granian (Rust)",
        "python_version": sys.version.split()[0],
        "os_platform": platform.platform(),
        "active_sessions_count": len(ACTIVE_SESSIONS_SET),
        "your_session_id": sid,
        "your_current_role": role_val,
        "database": "SQLite (aiosqlite + SQLAlchemy 2.0)",
    }


# --- 2. TABULAR COMPRESSION (RFC 0002) & TASKS ---

@rpc_method("tasks.list", public=True)
@tabular_response(fields=["id", "title", "completed", "priority", "created_at"])
async def list_tasks(session: JsonRpcSession, params: dict):
    """
    Returns tasks in compressed tabular format RFC 0002 ($tabular: true).
    Column names are sent once in 'fields', rows are a 2D matrix in 'rows'.
    Reduces wire traffic by 50-70% for lists.
    """
    async with async_session() as db:
        result = await db.execute(select(Task).order_by(Task.id.desc()))
        tasks = result.scalars().all()
        return [t.to_dict() for t in tasks]


@rpc_method("tasks.list_raw_json", public=True)
async def list_tasks_raw_json(session: JsonRpcSession, params: dict):
    """
    Returns the exact same tasks WITHOUT tabular compression (regular list of dicts).
    Used on the client for live side-by-side wire size comparison.
    """
    async with async_session() as db:
        result = await db.execute(select(Task).order_by(Task.id.desc()))
        tasks = result.scalars().all()
        return [t.to_dict() for t in tasks]


@rpc_method("tasks.add", public=True)
@invalidates(tags=["tasks"])
async def add_task(session: JsonRpcSession, params: dict):
    """
    Creates a new task.
    The @invalidates(tags=["tasks"]) decorator automatically increments tag version
    and broadcasts a 'cache.invalidate' event to all connected clients.
    """
    title = (params.get("title") or "").strip()
    if not title:
        raise RPCError(-32602, "Task title cannot be empty")

    priority = params.get("priority", "normal")
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    async with async_session() as db:
        task = Task(title=title, priority=priority, completed=False)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_data = task.to_dict()

    await broadcast_notification("tasks.changed", {"action": "added", "id": task.id})
    return task_data


@rpc_method("tasks.toggle", public=True)
@invalidates(tags=["tasks", "task.{id}"])
async def toggle_task(session: JsonRpcSession, params: dict):
    """Toggles task completion status."""
    task_id = params.get("id")
    if not task_id:
        raise RPCError(-32602, "Task ID is required")

    async with async_session() as db:
        result = await db.execute(select(Task).where(Task.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            raise RPCError(404, f"Task #{task_id} not found")

        task.completed = not task.completed
        await db.commit()
        task_data = task.to_dict()

    await broadcast_notification("tasks.changed", {"action": "toggled", "id": task_id})
    return task_data


@rpc_method("tasks.delete", public=True)
@invalidates(tags=["tasks", "task.{id}"])
async def delete_task(session: JsonRpcSession, params: dict):
    """Deletes a task."""
    task_id = params.get("id")
    if not task_id:
        raise RPCError(-32602, "Task ID is required")

    async with async_session() as db:
        result = await db.execute(select(Task).where(Task.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            raise RPCError(404, f"Task #{task_id} not found")

        await db.delete(task)
        await db.commit()

    await broadcast_notification("tasks.changed", {"action": "deleted", "id": task_id})
    return {"deleted": True, "id": task_id}


# --- 3. SMART CACHE (RFC 0001) & TAG INVALIDATION ---

@rpc_method("cache.get_versions", public=True)
async def cache_get_versions(session: JsonRpcSession, params: dict):
    """Returns current monotonic cache tag versions directly from server memory."""
    return version_registry.get_all_versions()


@rpc_method("cache.manual_invalidate", public=True)
async def cache_manual_invalidate(session: JsonRpcSession, params: dict):
    """Manually invalidates specified tags for testing and UI demonstration."""
    tags = params.get("tags") or ["tasks"]
    if isinstance(tags, str):
        tags = [tags]
    new_versions = await invalidate_tags(tags, reason="manual_ui_trigger")
    return {"invalidated_tags": tags, "new_versions": new_versions}


# --- 4. MULTI-RETURN STREAMING ---

@rpc_method("stream.heavy_job", public=True)
async def heavy_job(session, params: dict):
    """
    Demonstrates multi-return streaming (stream: true).
    The server sends intermediate progress chunks to the client
    without blocking other requests in the same WebSocket connection!
    """
    rpc_id = current_rpc_id_ctx.get()
    transport = current_transport_ctx.get() or session
    steps = [
        (20, "1/4 Initializing structures and warming up cache..."),
        (45, "2/4 Scanning SQLite indices..."),
        (70, "3/4 Compressing deterministic tabular data (RFC 0002)..."),
        (90, "4/4 Calculating SHA-256 checksums..."),
    ]

    for pct, message in steps:
        await asyncio.sleep(0.4)
        if hasattr(transport, "send_stream_chunk"):
            await transport.send_stream_chunk(rpc_id, {
                "progress": pct,
                "message": message,
                "timestamp": time.strftime("%H:%M:%S")
            })

    await asyncio.sleep(0.3)
    # Final return completes the RPC request
    return {
        "progress": 100,
        "message": "Operation completed successfully!",
        "summary": "Processed 1,000 records in 1.5s.",
        "finished_at": time.strftime("%H:%M:%S")
    }


# --- 5. REVERSE RPC (SERVER CALLS CLIENT) ---

@rpc_method("reverse_rpc.ask_client", public=True)
async def ask_client_info(session, params: dict):
    """
    Symmetric JSON-RPC 2.0: The server initiates a request to the browser
    via session.send_request(...) and awaits the client's response!
    """
    transport = current_transport_ctx.get() or session
    if hasattr(transport, "data") and not transport.data:
        sid = getattr(transport, "session_id", 1)
        transport.data = DemoSessionData(username="showcase_user", role="guest", session_id=sid)

    try:
        client_response = await transport.send_request(
            method="client.get_env",
            params={"requested_by": "rsgi_wsrpc_server", "query_time": time.time()},
            timeout=4.0
        )
        return {
            "status": "success",
            "message": "Server successfully received response from your browser!",
            "client_payload": client_response.get("result") or client_response
        }
    except asyncio.TimeoutError:
        raise RPCError(-32000, "Timeout: Browser did not answer server request within 4 seconds")
    except Exception as e:
        raise RPCError(-32000, f"Reverse RPC call error: {e}")


# --- 6. REALTIME BROADCAST ---

@rpc_method("broadcast.send_announcement", public=True)
async def send_announcement(session, params: dict):
    """
    Broadcasts message to all active WebSocket sessions in O(1)
    with single memory serialization.
    """
    text = (params.get("text") or "").strip()
    if not text:
        raise RPCError(-32602, "Message text cannot be empty")

    transport = current_transport_ctx.get() or session
    sid = getattr(transport, "session_id", getattr(session, "session_id", 1))
    author = params.get("author") or f"Session #{sid}"
    payload = {
        "text": text,
        "author": author,
        "timestamp": time.strftime("%H:%M:%S"),
        "session_id": sid,
    }
    await broadcast_notification("community.alert", payload)
    return {"sent": True, "recipients_count": len(ACTIVE_SESSIONS_SET)}


# --- 7. ROLES & RBAC (DEMO AUTH) ---

DEMO_USERS = {
    "admin": {"password": "admin123", "role": "admin", "name": "Администратор"},
    "user": {"password": "user123", "role": "user", "name": "Пользователь"},
}

DEMO_TOKENS: Dict[str, dict] = {}


def authenticate_credentials(username: str, password: str) -> Optional[dict]:
    """Validates login/password against showcase demo credentials."""
    u = (username or "").strip().lower()
    if u in DEMO_USERS:
        expected = DEMO_USERS[u]
        if password == expected["password"] or password == u:
            return {"username": u, "role": expected["role"], "name": expected["name"]}
    return None


@rpc_method("auth.login", public=True)
async def auth_login(session, params: dict):
    """
    Аутентификация с проверкой логина и пароля.
    Доступны demo-аккаунты: admin / admin123 и user / user123.
    """
    username = params.get("username", "")
    password = params.get("password", "")

    user_info = authenticate_credentials(username, password)
    if not user_info:
        raise RPCError(-32602, "Неверный логин или пароль (используйте admin/admin123 или user/user123)")

    transport = current_transport_ctx.get() or session
    sid = getattr(transport, "session_id", getattr(session, "session_id", 1))

    import secrets
    token = secrets.token_hex(24)
    DEMO_TOKENS[token] = user_info

    # Если логинится администратор, регистрируем его также в сессиях CRUD-плагина
    if user_info["role"] == "admin":
        from rsgi_wsrpc.plugins.crud import create_crud_session
        create_crud_session(user_info)

    demo_data = DemoSessionData(
        username=user_info["username"],
        role=user_info["role"],
        session_id=sid
    )

    if hasattr(transport, "data"):
        transport.data = demo_data
    if hasattr(session, "data"):
        session.data = demo_data

    return {
        "success": True,
        "token": token,
        "username": user_info["username"],
        "name": user_info["name"],
        "role": user_info["role"],
    }


@rpc_method("auth.logout", public=True)
async def auth_logout(session, params: dict = None):
    """Выход из аккаунта и сброс роли до Guest."""
    token = (params or {}).get("token")
    if token and token in DEMO_TOKENS:
        DEMO_TOKENS.pop(token, None)

    transport = current_transport_ctx.get() or session
    sid = getattr(transport, "session_id", getattr(session, "session_id", 1))

    demo_data = DemoSessionData(username="guest_user", role="guest", session_id=sid)
    if hasattr(transport, "data"):
        transport.data = demo_data
    if hasattr(session, "data"):
        session.data = demo_data

    return {"success": True, "role": "guest"}


@rpc_method("auth.whoami", public=True)
async def auth_whoami(session, params: dict = None):
    """Возвращает информацию о текущей роли и сессии сокета."""
    transport = current_transport_ctx.get() or session
    data = getattr(transport, "data", None) or getattr(session, "data", None)
    if data and getattr(data, "role_name", None) in ("admin", "user"):
        return {
            "authenticated": True,
            "username": getattr(data, "username", ""),
            "role": getattr(data, "role_name", "guest"),
            "name": getattr(data, "username", "Пользователь"),
        }
    return {
        "authenticated": False,
        "username": "guest_user",
        "role": "guest",
        "name": "Гость",
    }


@rpc_method("auth.set_role", public=True)
async def set_role(session, params: dict):
    """
    Switches session role for RBAC inspection.
    Allowed roles: 'guest', 'user', 'admin'.
    """
    role_name = (params.get("role") or "guest").lower()
    transport = current_transport_ctx.get() or session
    sid = getattr(transport, "session_id", getattr(session, "session_id", 1))

    demo_data = DemoSessionData(
        username=f"user_{sid}",
        role=role_name,
        session_id=sid
    )

    if hasattr(transport, "data"):
        transport.data = demo_data
    if hasattr(session, "data"):
        session.data = demo_data

    role_val = get_current_role(transport)
    return {
        "session_id": sid,
        "role": role_val,
    }



@rpc_method("admin.system_info", role=UserRole.ADMIN)
async def admin_system_info(session: JsonRpcSession, params: dict):
    """
    Protected method: accessible ONLY with admin role.
    If unauthorized, framework automatically returns RPCError(-32003, Access denied).
    """
    import os
    return {
        "status": "authorized",
        "secret_system_data": {
            "pid": os.getpid(),
            "active_sockets": len(ACTIVE_SESSIONS_SET),
            "cpu_count": os.cpu_count(),
            "python_implementation": platform.python_implementation(),
            "security_guard": "RBAC Verified by rsgi_wsrpc decorator",
        }
    }


# --- 8. DOCUMENTS (SECOND MODEL FOR CRUD & TABULAR) ---

@rpc_method("documents.list", public=True)
@tabular_response(fields=["id", "title", "category", "views", "updated_at"])
async def list_documents(session: JsonRpcSession, params: dict):
    """Documents list demonstrating CRUD plugin and tabular compression."""
    async with async_session() as db:
        result = await db.execute(select(Document).order_by(Document.id.desc()))
        docs = result.scalars().all()
        return [d.to_dict() for d in docs]


# --- 9. SEO & BOT DETECTOR (PLUGINS.SEO) ---

@rpc_method("seo.simulate_bot", public=True)
async def simulate_bot_check(session: JsonRpcSession, params: dict):
    """
    Simulates User-Agent inspection using plugins.seo.detector.
    Determines whether a client is a search engine crawler or scraper.
    """
    user_agent = params.get("user_agent") or "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    is_a_bot = is_bot(user_agent)
    is_a_search_bot = is_search_bot(user_agent)

    return {
        "user_agent": user_agent,
        "is_bot": is_a_bot,
        "is_search_bot": is_a_search_bot,
        "recommendation": "Render Static HTML with OpenGraph tags" if is_a_bot else "Serve Single-Page App WebSockets",
    }
