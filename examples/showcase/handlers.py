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
    ACTIVE_SESSIONS_SET, current_rpc_id_ctx
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
    def __init__(self, username: str = "guest_user", role: str = "guest"):
        self.username = username
        self.role = role
        self.user_id = 1


# --- 1. SYSTEM METHODS (HEALTH & PING) ---

@rpc_method("system.ping", public=True)
async def ping(session: JsonRpcSession, params: dict):
    """Ultra-fast ping-pong to measure network Round Trip Time (RTT)."""
    return {
        "status": "pong",
        "server_time": time.time(),
        "granian": "rsgi"
    }


@rpc_method("system.info", public=True)
async def system_info(session: JsonRpcSession, params: dict):
    """System information, active sessions, and environment metrics."""
    role_val = session.user_role.value if hasattr(session.user_role, "value") else str(session.user_role)
    return {
        "framework": "rsgi-wsrpc",
        "rsgi_server": "Granian (Rust)",
        "python_version": sys.version.split()[0],
        "os_platform": platform.platform(),
        "active_sessions_count": len(ACTIVE_SESSIONS_SET),
        "your_session_id": session.session_id,
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
async def heavy_job(session: JsonRpcSession, params: dict):
    """
    Demonstrates multi-return streaming (stream: true).
    The server sends intermediate progress chunks to the client
    without blocking other requests in the same WebSocket connection!
    """
    rpc_id = current_rpc_id_ctx.get()
    steps = [
        (20, "1/4 Initializing structures and warming up cache..."),
        (45, "2/4 Scanning SQLite indices..."),
        (70, "3/4 Compressing deterministic tabular data (RFC 0002)..."),
        (90, "4/4 Calculating SHA-256 checksums..."),
    ]

    for pct, message in steps:
        await asyncio.sleep(0.4)
        await session.send_stream_chunk(rpc_id, {
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
async def ask_client_info(session: JsonRpcSession, params: dict):
    """
    Symmetric JSON-RPC 2.0: The server initiates a request to the browser
    via session.send_request(...) and awaits the client's response!
    """
    if not session.authenticated:
        session.data = DemoSessionData(username="showcase_user", role="guest")

    try:
        client_response = await session.send_request(
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
async def send_announcement(session: JsonRpcSession, params: dict):
    """
    Broadcasts message to all active WebSocket sessions in O(1)
    with single memory serialization.
    """
    text = (params.get("text") or "").strip()
    if not text:
        raise RPCError(-32602, "Message text cannot be empty")

    author = params.get("author") or f"Session #{session.session_id}"
    payload = {
        "text": text,
        "author": author,
        "timestamp": time.strftime("%H:%M:%S"),
        "session_id": session.session_id,
    }
    await broadcast_notification("community.alert", payload)
    return {"sent": True, "recipients_count": len(ACTIVE_SESSIONS_SET)}


# --- 7. ROLES & RBAC ---

@rpc_method("auth.set_role", public=True)
async def set_role(session: JsonRpcSession, params: dict):
    """
    Switches session role for RBAC inspection.
    Allowed roles: 'guest', 'user', 'admin'.
    """
    role_name = (params.get("role") or "guest").lower()
    if role_name == "admin":
        session.user_role = UserRole.ADMIN
    elif role_name == "user":
        session.user_role = UserRole.USER
    else:
        session.user_role = UserRole.GUEST

    session.data = DemoSessionData(
        username=f"user_{session.session_id}",
        role=role_name
    )

    return {
        "session_id": session.session_id,
        "role": session.user_role.value if hasattr(session.user_role, "value") else str(session.user_role),
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
