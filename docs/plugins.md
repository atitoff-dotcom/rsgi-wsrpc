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

## 3. Application Facade Pattern

Applications (such as Agrita, CRM systems, or the Showcase demo) configure plugin access via domain facades or consume them directly:
```python
# Option 1: Direct imports from plugins
from plugins.db import Base, async_session
from plugins.auth.models import User

# Option 2: Application facade re-exports (app/system/)
# app/system/db.py
from plugins.db import *

# app/system/auth/models.py
from plugins.auth.models import *

# app/system/auth/handlers.py
from plugins.auth.handlers import *
```
This guarantees flexible composition between the core, official plugins, and domain modules with zero code duplication.

---

## 4. Live Reference Implementation

A fully functional showcase demonstrating `plugins.db` and the `plugins.auth` role model is available in:
- `examples/showcase/server.py`
- `examples/showcase/models.py`
- `examples/showcase/handlers.py`

