# Core Reactive CRUD & Admin Architecture

## 1. Overview and Principles

The **`rsgi_wsrpc.plugins.crud`** plugin is an official battery of the `rsgi-wsrpc` framework providing a high-performance, reactive, and type-safe administration layer for SQLAlchemy 2.0 async models.

Key architectural highlights:
1. **Symmetric WSRPC Transport (JSON-RPC 2.0):**  
   Low-latency bidirectional WebSocket communication for schema inspection, data pagination, inline editing, and deletion.
2. **RFC 0002 Tabular Data Compression:**  
   List queries return matrix arrays (`fields` + `rows`), reducing JSON payload sizes by **40–70%**.
3. **Capability-Based Access Control:**  
   Zero hardcoded role names (`admin`, `editor`, etc.). Access is guarded purely by capability checks (`{model}:read`, `{model}:create`, `{model}:update`, `{model}:delete`, `{model}:transfer`, `*`) and SQL predicates.
4. **Environment Decoupling (`IdentityProvider`):**  
   The plugin has zero dependencies on specific user/team database schemas. All session context is ingested through a protocol.
5. **Unified Security Predicate (`AccessPolicy.scope`):**  
   Row-level security filters are applied directly at the database query level (`WHERE id = :id AND <scope>`).
6. **Reactive Events (`cache.patch`):**  
   Broadcasts lightweight metadata-only notifications upon data mutation without leaking column values across authorization boundaries.
7. **Built-in Standalone UI (Svelte 5 Runes):**  
   Turnkey administrative single-page application with light and dark themes served via native Rust RSGI Zero-Copy (`proto.response_file`).

---

## 2. Quick Start

### Step 1. Register Models and Import Plugin

```python
from rsgi_wsrpc import RsgiWsrpcApp
from rsgi_wsrpc.plugins.db import Base
import rsgi_wsrpc.plugins.crud as crud

# Auto-discover all mapped models
crud.ModelRegistry.auto_discover(Base)

app = RsgiWsrpcApp(
    database_url="postgresql+asyncpg://user:pass@localhost:5432/app_db",
    cors=True
)

# 4. Dev-helper route for instant admin access (bypassing Zero-Leakage 404 for local dev)
@app.route("/dev-admin")
async def dev_admin(scope, proto):
    token = crud.create_crud_session({"username": "admin", "role": "admin"})
    proto.response_str(
        status=302,
        headers=[
            ("location", "/crud/"),
            ("set-cookie", f"rsgi_crud_session={token}; path=/; max-age=86400; SameSite=Lax"),
            ("content-length", "0"),
        ],
        body=""
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
```

> **Important Security Note (Zero-Leakage 404):**  
> Direct access to `http://127.0.0.1:8080/crud/` returns `404 Not Found` for unauthenticated requests and non-admins to prevent exposure to scanners. Access requires an admin session cookie (`rsgi_crud_session=<token>` or `rsgi_session=<token>`). For comprehensive integration patterns and troubleshooting, see [docs/crud_panel_guide.md](crud_panel_guide.md).

---

## 3. Model Declaration (`class Crud:`)

```python
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from rsgi_wsrpc.plugins.db import Base

class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), info={"label": "Title"})
    price: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, info={"label": "Price", "widget": "money"})
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, info={"label": "Active"})

    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    class Crud:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        hidden = {"internal_notes"}
        readonly = {"created_at", "updated_at"}
        protected = {"owner_id", "team_id"}
```

Sensitive columns matching `*password*`, `*_hash`, `*secret*`, `*token*`, `*private_key*` are unconditionally hidden from schemas and payloads.

---

## 4. Custom Authorization (`IdentityProvider`)

```python
from typing import Optional, Set, Any
from sqlalchemy.ext.asyncio import AsyncSession
from rsgi_wsrpc.plugins.crud import IdentityProvider, set_identity_provider

class CustomIdentityProvider:
    def user_id(self, session: Any) -> Optional[int]:
        return getattr(session, "uid", None)

    def user_name(self, session: Any) -> str:
        return getattr(session, "user_name", "User")

    def is_superuser(self, user_id: Optional[int]) -> bool:
        return check_admin(user_id)

    def has_permission(self, user_id: Optional[int], perm: str) -> bool:
        return check_perm(user_id, perm)

    async def effective_user_ids(self, user_id: int, model_name: str, db: AsyncSession) -> Set[int]:
        return {user_id}.union(get_delegated_user_ids(user_id, model_name, db))

    async def user_team_ids(self, user_id: int, db: AsyncSession) -> Set[int]:
        return get_team_ids(user_id, db)

    async def primary_team_id(self, user_id: int, db: AsyncSession) -> Optional[int]:
        return get_primary_team(user_id, db)

set_identity_provider(CustomIdentityProvider())
```

---

## 5. WSRPC Methods Specification (`crud.*`)

- **`crud.schema`**: Retrieves introspection schema and computed permissions (`can_read`, `can_create`, `can_update`, `can_delete`, `row_level_only`).
- **`crud.list`**: Returns paginated, filtered, and sorted rows using RFC 0002 `$tabular: true` compression (`fields`, `rows`).
- **`crud.get`**: Fetches full record by ID with row-level security enforcement.
- **`crud.create`**: Creates a record with automatic population of audit fields (`creator_id`, `owner_id`, `created_at`).
- **`crud.update_cell`**: Atomic single-cell update with strict type coercion.
- **`crud.bulk_update`**: Batch update or archive of multiple records in a single transaction.
- **`crud.delete`**: Deletes record with RLS permission verification.
- **`cache.patch`**: Notification sent to connected sockets upon mutations.
