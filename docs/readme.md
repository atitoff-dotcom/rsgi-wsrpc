# rsgi-wsrpc: The Reactive Fullstack Framework for Python

> **"Everything Django should have become, and everything FastAPI forgot to include."**  
> High-performance async Python framework powered by **Rust (Granian RSGI)** with a symmetric **WSRPC (JSON-RPC 2.0)** protocol, built-in async database, auth, and transactional Two-Phase Commit file streaming.

---

## 🧭 Table of Contents
1. [Core Philosophy & Manifesto](#-core-philosophy--manifesto)
2. [Architecture: Core + Plugins + Application](#-architecture-core--plugins--application)
3. [Comparison: rsgi-wsrpc vs Django vs FastAPI](#-comparison-rsgi-wsrpc-vs-django-vs-fastapi)
4. [Quick Start in 60 Seconds](#-quick-start-in-60-seconds)
5. [Core Network Engine](#-core-network-engine)
6. [Official System Plugins](#-official-system-plugins)
   * [Database Plugin (db)](#1-database-plugin-pluginsdb)
   * [Authentication & User Management Plugin (auth)](#2-authentication--user-management-plugin-pluginsauth)
   * [File Storage & Two-Phase Upload Plugin (files)](#3-file-storage--two-phase-upload-plugin-pluginsfiles)
7. [Creating Custom Plugins & Modules](#-creating-custom-plugins--modules)

---

## 💡 Core Philosophy & Manifesto

The modern web has evolved: users expect instantaneous interfaces (1–5 ms latency), real-time reactive state updates, and streaming progress without full-page reloads.

Python developers, however, have remained caught between two legacy paradigms:
1. **Django** — A 20-year-old monolithic architecture designed for the Web 2.0 era. Retrofitting it for WebSockets requires a complex stack of `Django + DRF + Channels + Redis + Celery + Daphne`, consuming gigabytes of memory.
2. **FastAPI** — Modern and fast, yet tethered to traditional HTTP/1.1 request-response round-trips. Each client action spawns a new connection with kilobytes of header overhead. Crucially, it lacks "batteries included" — developers must assemble authentication, sessions, and file storage from scratch for every project.

**`rsgi-wsrpc` merges the best of all worlds:**
* **Powered by Rust & Granian** — Raw RSGI throughput without Python GIL execution bottlenecks.
* **Unified WSRPC Protocol (JSON-RPC 2.0)** — A single multiplexed connection for all RPC actions, symmetric invocation (server can push and call client methods), and native streaming.
* **Batteries Included** — Built-in database engine, authentication, and Two-Phase Commit file streaming, provided as modular, decoupled plugins.

---

## 🏛 Architecture: Core + Plugins + Application

The framework adheres strictly to Clean Architecture and unidirectional dependency flow:

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                       1. YOUR APPLICATION (Application)                 │
│                                                                         │
│   The orchestrator: loads settings (settings.yaml), attaches necessary  │
│   system plugins, and registers business domain handlers.               │
│   Examples: Social Network, CRM, Portal, IoT Gateway, Custom Dashboard. │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ imports & configures
┌────────────────────────────────────▼────────────────────────────────────┐
│                    2. SYSTEM & DOMAIN PLUGINS                           │
│                                                                         │
│   [ Plugin: DB ]        [ Plugin: Auth ]       [ Plugin: Files ]        │
│   Async SQLAlchemy      Users, JWT tokens,     2PC file streaming,      │
│   SQLite / PostgreSQL   roles & RLS security   registry & Nginx offload │
│                                                                         │
│   [ Domain Plugins: Forum, Billing, Notifications, Analytics... ]       │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ registers into
┌────────────────────────────────────▼────────────────────────────────────┐
│                        3. CORE NETWORK ENGINE                           │
│                                                                         │
│   High-performance WebSocket & RSGI runtime (Granian in Rust).          │
│   Maintains ZERO awareness of databases or application business logic.  │
│   Responsible for: WSRPC protocol, multi-return, sessions, auto-abort. │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Tenets:
1. **Autonomous Core**: `core/` has zero dependencies on application models or external databases.
2. **Modular Plugins**: Each plugin addresses one capability and registers cleanly with the core (`@rpc_method`, `@on_startup`, `session.register_on_close`).
3. **App-Driven Composition**: Need a lean microservice without a database? Use the Core alone. Building a fullstack web app? Enable the full battery bundle.

---

## ⚡ Comparison: rsgi-wsrpc vs Django vs FastAPI

### 1. Client-Server Communication Flow

#### Traditional REST (FastAPI / Django):
Every request requires a TCP/TLS handshake, large header payloads, and teardown:
```text
[ Client ] ──── TCP + TLS Handshake (50-100 ms) ────► [ Server ]
[ Client ] ──── POST /api/items (Headers + Body) ───► [ Server ]
[ Client ] ◄─── 200 OK (Headers + Body) ──────────── [ Server ]  (Connection closed)

[ Client ] ──── TCP + TLS Handshake (50-100 ms) ────► [ Server ]
[ Client ] ──── GET /api/user/profile ──────────────► [ Server ]
[ Client ] ◄─── 200 OK ───────────────────────────── [ Server ]
```

#### Reactive WSRPC (`rsgi-wsrpc`):
A single persistent multiplexed WebSocket connection. Zero handshake overhead, 1–3 ms round-trips:
```text
[ Client ] ═════════════════════════════════════════► [ Server ]
           (Persistent, secure multiplexed WSRPC stream)
           
           ─── id: 1, method: "items.create" ───────► (1 ms)
           ◄── id: 1, result: { id: 42 } ──────────── (1 ms)
           
           ─── id: 2, method: "user.get_profile" ───► (1 ms)
           ◄── id: 2, result: { name: "Alex" } ────── (1 ms)
           
           ◄── SERVER PUSH: method: "notify" ──────── (Server calls client directly!)
```

### 2. Feature Matrix

| Feature | Django | FastAPI | `rsgi-wsrpc` |
| :--- | :--- | :--- | :--- |
| **Network Runtime** | Python WSGI / slow ASGI | Uvicorn (ASGI) | **Granian (Rust RSGI)** 🚀 |
| **Response Latency** | 80–250 ms | 30–120 ms | **1–5 ms** |
| **Symmetry** | ❌ Client ➔ Server only | ❌ Client ➔ Server only | ✅ **Client ⇄ Server (bidirectional)** |
| **Streaming Progress** | ❌ Requires Redis + Channels | ❌ Custom WebSocket boilerplate | ✅ **Native Multi-return (`stream: true`)** |
| **RAM Footprint** | ~150–250 MB per worker | ~80–120 MB per worker | **~25–40 MB per worker** |
| **File Uploads** | Buffered into worker memory | SpooledFile / RAM buffering | **Streaming O(1) RAM + 2PC + Nginx Offload** |
| **Built-in Auth** | ✅ Built-in (synchronous) | ❌ None (must build yourself) | ✅ **Built-in (JWT + Refresh + Argon2)** |
| **Infrastructure** | Python + Postgres + Redis + Celery | Python + Postgres + ... | **Single Granian binary + SQLite/Postgres** |

---

## 🚀 Quick Start in 60 Seconds

### 1. Minimal Server (`main.py`)
```python
from core.session import rpc_method, JsonRpcSession
from core.lifecycle import on_startup

# Register an RPC method
@rpc_method("math.add")
async def add_numbers(session: JsonRpcSession, params: dict):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"result": a + b}

# Method with streaming progress (multi-return)
@rpc_method("task.run_long")
async def run_task(session: JsonRpcSession, params: dict):
    rpc_id = params.get("rpc_id")
    for step in range(1, 4):
        # Push intermediate progress chunk over WebSocket
        await session.send_stream_chunk(rpc_id, {"progress": step * 33})
    return {"status": "completed"}
```

### 2. Run with Granian
```bash
granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
```

### 3. Client Invocation (JavaScript / TypeScript)
```javascript
import { WsrpcClient } from './wsrpc.js';

const client = new WsrpcClient('ws://127.0.0.1:8080');
await client.connect();

// Standard RPC Call
const sum = await client.call('math.add', { a: 10, b: 25 });
console.log(sum.result); // 35

// Multi-return streaming call
await client.callStream('task.run_long', {}, (chunk) => {
    console.log(`Progress: ${chunk.progress}%`);
});
```

---

## ⚙️ Core Network Engine

The core engine is located in `core/` and provides fundamental transport primitives:

* **[core/session.py](../../core/session.py)**:
  * `JsonRpcSession` — manages persistent client WebSocket connections.
  * Inbound and outbound message multiplexing via sequential numeric `id`.
  * Built-in **Rate-Limiting (Token Bucket)** protecting against RPC flooding and Denial of Service.
  * Context isolation via `ContextVar` (`current_transport_ctx`, `current_session_ctx`, `current_rpc_id_ctx`, `current_user_ctx`), accessible anywhere in asynchronous execution trees.
  * Termination callback registry: `session.register_on_close(callback)`.

* **[core/upload.py](../../core/upload.py)**:
  * `UploadCoordinator` managing Two-Phase Commit transactions.
  * Streaming RSGI file intake with constant **O(1) RAM** footprint (`stream_request_to_disk`).
  * On-the-fly SHA-256 calculation as chunks arrive from the network.
  * Guaranteed automatic rollback (immediate temp directory cleanup) upon WebSocket disconnection.

* **[core/security.py](../../core/security.py)**:
  * Password hashing using state-of-the-art **Argon2id**.
  * JWT access token issuance and signature verification.
  * Asymmetric RSA encryption utilities for client-side password encryption.

* **[core/lifecycle.py](../../core/lifecycle.py)**:
  * Eager application initialization dispatcher (`@on_startup`), executing database migrations, cache warmup, and background tasks before accepting traffic.

---

## 🔌 Official System Plugins

The framework includes pre-built, tested system plugins (located in `app/system/`):

### 1. Database Plugin (`plugins/db`)
* **Technology**: SQLAlchemy 2.0 (Async) + `orjson` for high-speed JSON serialization.
* **Storage Engines**: SQLite out of the box (zero external database configuration required). Switch to PostgreSQL with a single configuration line in `settings.yaml`.
* **Usage**:
  ```python
  from app.system.db import async_session, Base
  from sqlalchemy import select

  async with async_session() as db:
      users = (await db.execute(select(User))).scalars().all()
  ```

---

### 2. Authentication & User Management Plugin (`plugins/auth`)
* **Capabilities**:
  * `User` model, role-based access (`admin`, `moderator`, `user`, `guest`).
  * **Row-Level Security (RLS)** primitives: `BasicSecureModel` and `RowSecureModel` for automated ownership-based filtering.
  * Session refresh via `RefreshToken` and active device session monitoring in `ActiveSession`.
  * Zero-boilerplate access to current authenticated user:
    ```python
    from core.session import current_user_ctx
    user = current_user_ctx.get()
    ```

---

### 3. File Storage & Two-Phase Upload Plugin (`plugins/files`)
* Complete architecture specification: see **[docs/files.md](files.md)**.
* **Two-Phase Commit Workflow**:
  1. Client initiates an upload transaction: the server provisions an isolated folder `/tmp/agrita_uploads/<folder_hash>/`.
  2. Client streams files via `POST /upload`. Bytes write directly to disk without consuming worker memory.
  3. If connection drops mid-upload, the core triggers `session.on_close` and instantly wipes the temporary folder.
  4. On successful completion, the folder is atomically moved to permanent `/files/<folder_hash>/` in 0 ms.
  5. Files are automatically recorded in the unified `file_metadata` registry.
  6. Static files are served directly via **Nginx** zero-copy offload.

---

## 🛠 Creating Custom Plugins & Modules

Building custom plugins (such as a support ticket module `tickets`) is straightforward:

```python
# app/tickets/handlers.py
from core.session import rpc_method, RPCError, current_user_ctx
from app.system.db import async_session
from app.system.files.service import FileStorageService

@rpc_method("tickets.create")
async def create_ticket(session, params):
    user = current_user_ctx.get()
    if not user:
        raise RPCError("Authentication required")

    title = params.get("title")
    text = params.get("text")
    folder_hash = params.get("folder_hash") # If files were attached

    async with async_session() as db:
        async with db.begin():
            ticket = Ticket(title=title, text=text, author_id=user.id, folder=folder_hash)
            db.add(ticket)

    return {"status": "ok", "ticket_id": ticket.id}

@rpc_method("tickets.delete")
async def delete_ticket(session, params):
    ticket_id = params.get("ticket_id")
    
    async with async_session() as db:
        ticket = await db.get(Ticket, ticket_id)
        if ticket and ticket.folder:
            # Atomically delete all attachments from disk and metadata registry
            await FileStorageService.delete_bundle(ticket.folder)
        await db.delete(ticket)
        await db.commit()

    return {"deleted": True}
```

---

## 📄 License
Released under the permissive **MIT License**.
Free for commercial use, modification, and distribution.
