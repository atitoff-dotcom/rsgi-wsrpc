# Official Plugins (Batteries Included)

The `rsgi-wsrpc` framework adheres to a strict 3-tier architectural design:
1. **Core (`core/`)**: Lean, high-performance, asynchronous RSGI/WSRPC protocol engine, session router, security primitives, and transport lifecycle.
2. **Plugins (`plugins/`)**: Official modular extensions ("batteries") that plug into core interfaces: database session lifecycle, enterprise authentication, RLS, and caching.
3. **Applications (`App/`)**: Specific business logic consuming framework core and selected plugins.

---

## 1. Database Plugin (`plugins.db`)

Provides asynchronous SQLAlchemy 2.0 database session management, connection engine, metadata registry, and pagination utilities.

### Key Components
- `Base`: Central declarative base (`DeclarativeBase`) providing shared metadata across all plugins and application tables.
- `engine`: Asynchronous SQLAlchemy engine configured from `app_settings.yaml` (PostgreSQL / SQLite).
- `async_session`: Asynchronous session maker factory (`async_sessionmaker[AsyncSession]`) supporting context managers (`async with async_session() as db:`).
- `apply_pagination(stmt, page, limit)`: Standard pagination utility.

### Usage Example
```python
from plugins.db import Base, async_session
from sqlalchemy import select

async def get_records():
    async with async_session() as db:
        result = await db.execute(select(MyModel))
        return result.scalars().all()
```

---

## 2. Authentication & Authorization Plugin (`plugins.auth`)

Enterprise-ready authentication and authorization system supporting Row-Level Security (RLS), RSA-encrypted transport, OAuth2, and sliding sessions.

### Features
- **Sliding Session Expiration**:
  - Configurable session lifetime via `app_settings.yaml` (default: 30 days).
  - Every valid token refresh extends the token expiration window by `session_lifetime_days`.
  - Stale refresh tokens are cleaned up automatically.
  - Active session limit enforcement (`max_active_sessions`, default: 10 per user).
- **Dynamic Database Roles & Permissions (`auth_role`, `auth_role_permission`)**:
  - Roles are never hardcoded: the `auth_role` table allows provisioning arbitrary domain roles (`moderator`, `operator`, `manager`, `inspector`).
  - Many-to-Many association: users can hold multiple active roles simultaneously.
  - Granular permission matrix: `auth_role_permission` defines CRUD capabilities per model (`can_create`, `can_read`, `can_update`, `can_delete`, `create_global`, `read_global`).
  - Upon login, user roles bind directly to the active socket session for instant `@rpc_method(role=...)` validation.
- **Row-Level Security (RLS)**:
  - `BasicSecureModel` and `RowSecureModel` mixins.
  - Session event listeners filter queries automatically based on `current_user_ctx`.
  - `system_bypass_ctx`: Context manager to elevate execution privileges for background/system tasks.
- **RPC Handlers**:
  - `login.get_key`: Generates ephemeral RSA public key for client-side password encryption.
  - `login.secure`: Decrypts password via private key and authenticates user.
  - `login.submit`: Direct username/password authentication (PBKDF2-SHA256).
  - `login.refresh`: Issues fresh access tokens and slides refresh token expiry forward.
  - `login.whoami`: Inspects current socket user, permissions, and roles.
  - `login.register`: Standard user registration with validation.
  - `login.get_oauth_providers`: Discovers enabled OAuth2 providers from configuration.
  - `login.oauth_vk`: VK ID OAuth 2.0 PKCE authentication and profile linking.
  - `login.oauth_yandex`: Yandex ID OAuth 2.0 authentication and profile linking.
  - `auth.logout`: Terminates active WebSocket session and invalidates bound refresh token.
  - `auth.get_sessions`: Lists all active user sessions with IP and device info.
  - `auth.terminate_session`: Remote session termination.
  - `auth.active_sessions_stream`: Real-time reactive stream of user session changes.

### Configuration (`app_settings.yaml`)
```yaml
auth:
  session_lifetime_days: 30
  max_active_sessions: 10

oauth:
  vk:
    enabled: true
    client_id: "..."
    client_secret: "..."
  yandex:
    enabled: true
    client_id: "..."
    client_secret: "..."
```

---

## 4. Raw & Binary WebSocket Sessions Plugin (`plugins.raw_ws`)

Provides dedicated support for low-level, binary, and bidirectional WebSocket protocols (e.g. controller telemetry, Protobuf, audio/video streaming) over custom HTTP URL paths, bypassing standard WSRPC JSON-RPC parsing.

### Features
- **Strict Isolation & Zero Overhead**: Dedicated URLs are intercepted prior to WSRPC without incurring JSON serialization penalties.
- **64-bit Unique Session IDs (Snowflake-style)**: 100% collision-free across multiple Granian worker processes (`--workers N`) and server restarts.
- **Explicit `session_id` in Message Handlers**: Signature `(session_id, data, session)` gives immediate access to the session identity without context lookup overhead.
- **Bidirectional Streaming**: `send_bytes(data: bytes)` and `send_str(data: str)`.
- **Reliable Disconnect Tracking**: `@handler.on_connect`, `@handler.on_disconnect`, and `session.on_close(...)` hooks executed deterministically.
- **Session Registry & Broadcasting**: `send_to_session(session_id, data)` and `broadcast_raw(data, path=None)`.

### Usage Example
```python
from plugins.raw_ws import raw_ws_route, RawWebSocketSession
from core.logger import logger

@raw_ws_route("/ws/telemetry")
async def on_telemetry(session_id: int, data: bytes, session: RawWebSocketSession):
    # Explicit session_id and raw bytes from the client
    logger.info(f"[Telemetry] Frame from session {session_id}, bytes: {len(data)}")
    # Bidirectional response
    await session.send_bytes(b"ACK")

@on_telemetry.on_connect
async def on_connect(session: RawWebSocketSession):
    logger.info(f"[Telemetry] Device connected: {session.session_id}")

@on_telemetry.on_disconnect
async def on_disconnect(session: RawWebSocketSession):
    logger.warning(f"[Telemetry] Connection lost: {session.session_id}")
```

### Integration in Server Entrypoint (`main.py`)
```python
from plugins.raw_ws import dispatch_raw_ws

async def app(scope, proto):
    if scope.proto == "websocket":
        # Dispatch to raw_ws plugin routes (/ws/telemetry etc.)
        if await dispatch_raw_ws(scope, proto):
            return

        # Fallback to standard WSRPC for default endpoints
        ws = await proto.accept()
        session = JsonRpcSession(ws, next(GLOBAL_SESSION_COUNTER))
        await session.start()
```

---

## 5. Application Facade Pattern

Domain applications (Agrita, CRM, Showcase) organize access to framework plugins via internal facades or import them directly:
```python
# Option 1: Direct import of framework plugins
from plugins.db import Base, async_session
from plugins.auth.models import User
from plugins.raw_ws import raw_ws_route

# Option 2: Internal domain facade re-exports (app/system/)
# app/system/db.py
from plugins.db import *

# app/system/auth/models.py
from plugins.auth.models import *

# app/system/auth/handlers.py
from plugins.auth.handlers import *
```
This guarantees flexible composition between the core, official plugins, and domain modules with zero code duplication.

---

## 6. Live Reference Implementation

A fully functional showcase demonstrating `plugins.db` and the `plugins.auth` role model is available in:
- `examples/showcase/server.py`
- `examples/showcase/models.py`
- `examples/showcase/handlers.py`

---

## 7. Official Plugin Roadmap & RFC Registry

The following table tracks official framework plugins and their standardized architectural specifications:

| Plugin Name | Status | RFC Specification | Description |
| :--- | :--- | :--- | :--- |
| **`plugins.db`** | ✅ Stable | Core Framework | Asynchronous SQLAlchemy 2.0 connection pool & declarative Base |
| **`plugins.auth`** | ✅ Stable | Core Framework | RBAC, RLS (`RowSecureModel`), OAuth2, sliding session lifecycle |
| **`plugins.raw_ws`** | ✅ Stable | Core Framework | Raw & binary bidirectional WebSocket sessions with 64-bit IDs |
| **`plugins.smart_cache`**| ⚡ In Progress | [RFC 0001](rfc/0001-smart-cache.md) | Event-driven feedback cache with 0 ms perceived latency |
| **`plugins.admin`** | 📝 In Review | [RFC 0003](rfc/0003-reactive-admin-plugin.md) | Reactive enterprise administration & CRUD engine |
| **`plugins.files`** | 📝 In Review | [RFC 0005](rfc/0005-file-storage-and-upload-subsystem.md) | Two-phase commit (2PC) streaming uploads & Nginx offload |
| **`plugins.broadcast`** | 📝 In Review | [RFC 0006](rfc/0006-websocket-broadcast-and-event-bus.md) | High-throughput zero-copy WebSocket push & targeting |
| **`plugins.gateway`** | 📝 In Review | [RFC 0007](rfc/0007-http-api-gateway-and-documentation.md) | HTTP API gateway for WSRPC & auto-generated Swagger UI |
| **`plugins.discussions`**| 📝 In Review | [RFC 0008](rfc/0008-threaded-discussions-and-forum.md) | Hierarchical forum, nested threads & emoji reactions |
| **`plugins.messages`** | 📝 In Review | [RFC 0009](rfc/0009-direct-messaging-and-chat.md) | 1-on-1 direct messaging, chat & polymorphic context |
| **`plugins.articles`** | 📝 In Review | [RFC 0010](rfc/0010-knowledge-base-and-articles-cms.md) | Markdown knowledge base, FAQ & article CMS |

