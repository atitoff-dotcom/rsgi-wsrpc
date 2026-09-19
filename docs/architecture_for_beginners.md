# Architecture for Beginners: Core ↔ Plugins ↔ Application ↔ Database

This guide explains the architectural design of the `rsgi-wsrpc` framework in plain language, using intuitive diagrams and real-world analogies.

---

## 1. The Big Picture

```text
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │                      CLIENT (Browser / Mobile / Frontend)                   │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │  WebSocket (WSRPC JSON-RPC 2.0)
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 1. CORE (rsgi-wsrpc / core) — «Dispatcher & Network Engine»                 │
 │                                                                             │
 │  • Receives raw network frames via RSGI / WebSocket.                        │
 │  • Parses JSON-RPC: {"method": "login.submit", "params": {...}, "id": 1}    │
 │  • Manages active socket connections (`JsonRpcSession`).                   │
 │  • Knows NOTHING about users, passwords, agronomy, or domain logic.         │
 │  • Looks up registered RPC handlers in the routing table and invokes them.  │
 └──────────────────────┬───────────────────────────────┬──────────────────────┘
                        │                               │
      dispatches system │                               │ dispatches domain
      methods (auth)    │                               │ methods (agrita)
                        ▼                               ▼
 ┌──────────────────────────────────────┐  ┌───────────────────────────────────┐
 │ 2. PLUGINS (rsgi-wsrpc / plugins)    │  │ 3. APPLICATION (App / agrita)     │
 │    «Official Batteries»              │  │    «Domain Business Logic»        │
 │                                      │  │                                   │
 │ ┌──────────────────────────────────┐ │  │ ┌───────────────────────────────┐ │
 │ │ plugins.auth                     │ │  │ │ Fertilizer Calculators        │ │
 │ │  • Models: User, Role, Session   │ │  │ │ Crop Diaries, Sensors         │ │
 │ │  • Handlers: login.*, auth.*     │ │  │ │ Forum, Articles, Chats        │ │
 │ │  • RSA password encryption       │ │  │ └───────────────┬───────────────┘ │
 │ │  • Sliding tokens (30 days)      │ │  │                 │                 │
 │ │  • Row-Level Security (RLS)      │ │  │                 │                 │
 │ └────────────────┬─────────────────┘ │  │                 │                 │
 │                  │                   │  │                 │                 │
 │ ┌────────────────▼─────────────────┐ │  │                 │                 │
 │ │ plugins.db                       │◄┼──┼─────────────────┘                 │
 │ │  • Shared Base (Declarative)     │ │  │  (App imports `Base` and          │
 │ │  • Session maker `async_session` │ │  │  `async_session` from DB plugin!) │
 │ │  • Connection pool               │ │  │                                   │
 │ └────────────────┬─────────────────┘ │  │                                   │
 └──────────────────┼───────────────────┘  └───────────────────────────────────┘
                    │
                    │ Executes SQL queries via SQLAlchemy
                    ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 4. DATABASE (PostgreSQL / SQLite) — «Persistent State Store»                │
 │                                                                             │
 │  • Auth Tables (from Auth Plugin):                                          │
 │      auth_user, auth_roles, auth_tokens, active_sessions                     │
 │  • Domain Tables (from Application):                                        │
 │      cult_diaries, calc_fertilizers, forum_topics                           │
 │                                                                             │
 │  *Note:* Application foreign keys point directly to `auth_user.id`          │
 │  seamlessly, sharing one unified SQLAlchemy metadata registry!              │
 └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Real-World Analogy: The Automobile

To make layer separation easy to remember, consider the analogy of a car:

| Layer | In Our Code | In an Automobile | Purpose |
| :--- | :--- | :--- | :--- |
| **Core** | `rsgi-wsrpc/core` | **Chassis, drivetrain & wiring** | The base platform. Transmits signals, drives wheels, routes voltage. Doesn't care who is driving or what cargo is carried. |
| **Plugins** | `plugins/auth`<br>`plugins/db` | **Ignition lock, alarm & fuel tank** | Standard modular units ("batteries"). The ignition lock validates the driver's key (`auth`), fuel system pumps fuel (`db`). |
| **Application**| `App/agrita` | **Car body & specialized tools** | Transforms the chassis into a tractor for an agronomist, an ambulance, or a sports car. All domain-specific logic lives here. |
| **Database**| PostgreSQL | **Garage & warehouse** | The physical location where parts and logbooks are permanently stored. |

---

## 3. Step-by-Step Request Flow

Here is what happens under the hood when a user clicks **«Log In»** in the frontend:

```text
1. BROWSER (Client)
   Sends a WSRPC message over the open WebSocket:
   --> {"jsonrpc": "2.0", "method": "login.submit", "params": {"username": "alex", "password": "123"}, "id": 1}

2. CORE (core)
   - Receives network frames from the socket via RSGI.
   - Parses the JSON-RPC packet.
   - Consults its internal handler registry: who registered the "login.submit" method?
   - Finds the `handle_login` function registered via `@rpc_method("login.submit")`.
   - Invokes the function.

3. AUTH PLUGIN (plugins.auth)
   - Obtains an async database session from the companion plugin:
     `async with plugins.db.async_session() as db:`
   - Queries the user table:
     `SELECT * FROM auth_user WHERE login = 'alex'`
   - Verifies the password hash (PBKDF2-SHA256).
   - Issues a sliding RefreshToken (configured via YAML `session_lifetime_days`).
   - Attaches context: binds user ID, roles, and permissions to the active socket session.
   - Returns result data to the core.

4. CORE (core)
   - Serializes the result into a standard JSON-RPC response:
     <-- {"jsonrpc": "2.0", "result": {"token": "xyz...", "role": "admin"}, "id": 1}
   - Transmits the response over the socket back to the client.

5. SUBSEQUENT DOMAIN REQUESTS (App/agrita)
   When the authenticated user requests fertilizer calculations:
   --> {"jsonrpc": "2.0", "method": "calc.solve", "params": {...}, "id": 2}
   - Core dispatches the call to the application module `App/agrita/backend/app/calculator`.
   - The calculator module checks `current_user_ctx.get()`.
   - It immediately receives the user identity and permission set without writing any custom auth boilerplate!
```

---

## 4. Why the Database Stays Unified

A common question: *«If plugins and the application are decoupled, do they use separate databases?»*

**Answer: No, they share the same database and engine, which is a major advantage!**
* The database plugin `plugins.db` defines a single declarative base:
  ```python
  class Base(AsyncAttrs, DeclarativeBase):
      pass
  ```
* Auth plugin models inherit from this `Base`:
  ```python
  class User(Base):
      __tablename__ = "auth_user"
  ```
* Application models inherit from the very same `Base`:
  ```python
  from plugins.db import Base

  class CultDiary(Base):
      __tablename__ = "cult_diaries"
      user_id = Column(Integer, ForeignKey("auth_user.id"))  # Foreign keys work seamlessly!
  ```
SQLAlchemy tracks all relationships in a unified metadata schema. Foreign keys and cascade rules function naturally.

---

## 5. Configuring Plugins from the Application (Code-First)

Plugins do not hardcode parameters; they are configured directly in application code via `configure(...)` or environment variables:

```python
from core.lib.config import configure

configure(
    auth={
        "session_lifetime_days": 30,   # Active session sliding lifetime in days
        "max_active_sessions": 10,     # Maximum concurrent active sessions per user
    },
    oauth={
        "vk": {"enabled": True, "client_id": "12345", "client_secret": "secret"},
        "yandex": {"enabled": True, "client_id": "67890", "client_secret": "secret"}
    }
)
```

If the `auth` section is omitted, the plugin automatically falls back to safe defaults (30 days, 10 sessions).

---

## 6. Architecture Layer Summary

```text
 1. CORE (core/)          — Protocol, WebSocket sessions, routing. Zero domain dependencies.
 2. PLUGINS (plugins/)    — Reusable building blocks: DB, Auth, Files, Smart Cache. Depends only on Core.
 3. APPLICATION (App/)    — Product business logic (Agrita). Depends on Core and Plugins.
```
