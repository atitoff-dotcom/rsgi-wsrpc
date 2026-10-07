# rsgi-wsrpc Architecture Guide & Capabilities Showcase

> **Note:** This document is automatically generated from the Single Source of Truth of the interactive showcase (`examples/showcase/content/showcase_docs.json`). All examples and RPC contracts are verified and functional.

---

## Table of Contents

- [1. Rust RSGI Architecture & JSON-RPC 2.0 Protocol](#overview)
- [2. Tabular Data Compression (RFC 0002)](#tabular)
- [3. Smart Cache & Tag Invalidation (RFC 0001)](#cache)
- [4. Universal Reactive CRUD & Admin Panel](#crud)
- [5. Multi-return Streaming (stream: true)](#stream)
- [6. Symmetric Reverse RPC (Server → Browser)](#reverse-rpc)
- [7. Realtime Broadcast (Zero-Copy Push)](#broadcast)
- [8. File Upload: Two-Phase Commit (2PC)](#files)
- [9. RBAC & Row-Level Security (RLS)](#rbac)
- [10. SEO & Dynamic Rendering for Bots](#seo)

---

<a id="overview"></a>
## ⚡ 1. Rust RSGI Architecture & JSON-RPC 2.0 Protocol

> **Specification:** `Granian RSGI • Zero-Overhead`

High-performance native Granian RSGI handling without WSGI/ASGI overhead. Single persistent WebSocket connection for all requests.

**Architectural Concept:**
Unlike legacy REST requiring repeated TCP handshakes, TLS negotiations, and heavy HTTP headers on every request, the browser maintains a single persistent connection. RPC calls resolve in 0.2–1 ms latency.

### Backend (Python)
```python
@app.rpc("system.ping", public=True)
async def ping():
    return {"status": "pong", "server_time": time.time()}
```

### Client (TypeScript / JavaScript)
```typescript
import { rpc } from '@wsrpc/wsrpc';

const response = await rpc.call('system.ping');
console.log(response); // { status: 'pong', server_time: ... }
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
--> {"jsonrpc": "2.0", "id": 1, "method": "system.ping", "params": {}}
<-- {"jsonrpc": "2.0", "id": 1, "result": {"status": "pong", "server_time": 1775546000.12}}
```

---

<a id="tabular"></a>
## 📊 2. Tabular Data Compression (RFC 0002)

> **Specification:** `RFC 0002 • 40–70% Compression`

Eliminates repetitive JSON object keys in lists. Column names transfer once, while rows are delivered as a compact 2D matrix.

**Architectural Concept:**
The @tabular_response decorator cuts network traffic by 40–70%. The client SDK unpacks tabular payloads transparently via unpackTabular().

### Backend (Python)
```python
@app.rpc("tasks.list", public=True)
@tabular_response(fields=["id", "title", "completed", "priority"])
async def list_tasks():
    # Возвращает стандартный список словарей или ORM моделей
    return await fetch_tasks_from_db()
```

### Client (TypeScript / JavaScript)
```typescript
const res = await rpc.call('tasks.list');
// Клиент распаковывает матрицу в привычные объекты:
const items = unpackTabular(res.result);
// [{ id: 1, title: 'Задача 1', completed: true, ... }]
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
--> {"jsonrpc": "2.0", "id": 2, "method": "tasks.list"}
<-- {"jsonrpc": "2.0", "id": 2, "result": {"$tabular": true, "fields": ["id", "title", "completed"], "rows": [[1, "Task 1", true], [2, "Task 2", false]]}}
```

---

<a id="cache"></a>
## 🔄 3. Smart Cache & Tag Invalidation (RFC 0001)

> **Specification:** `RFC 0001 • Invalidation Bus`

Monotonic entity tag versions in memory and DB. Server proactively invalidates client cache slices on data mutations.

**Architectural Concept:**
Methods decorated with @invalidates increment entity tag versions and broadcast cache.invalidate. Clients instantly drop stale slices and fetch fresh data.

### Backend (Python)
```python
@app.rpc("tasks.complete")
@invalidates(tags=["tasks.list", "task.{task_id}"])
async def complete_task(task_id: int):
    await mark_completed(task_id)
    return {"status": "ok", "task_id": task_id}
```

### Client (TypeScript / JavaScript)
```typescript
rpc.on('cache.invalidate', (data) => {
  console.log('Инвалидированы теги:', data.tags);
  // Очистка локального стора и рефетч
});
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
<-- {"jsonrpc": "2.0", "method": "cache.invalidate", "params": {"tags": ["tasks.list", "task.42"], "version": 105}}
```

---

<a id="crud"></a>
## 🗄️ 4. Universal Reactive CRUD & Admin Panel

> **Specification:** `Svelte 5 • Capability Access`

Automated CRUD API generation and embedded Svelte 5 admin panel. Supports Many-to-Many, ForeignKeys, and deep filtering.

**Architectural Concept:**
Simply register your SQLAlchemy model via ModelRegistry.register(MyModel), and crud.schema, crud.list ($tabular), crud.get, crud.create, crud.update_cell, and crud.delete work out of the box.

### Backend (Python)
```python
from rsgi_wsrpc.plugins.crud import ModelRegistry

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))

ModelRegistry.register(Task)
```

### Client (TypeScript / JavaScript)
```typescript
const schema = await rpc.call('crud.schema', { model: 'Task' });
const list = await rpc.call('crud.list', { model: 'Task', page: 1, page_size: 50 });
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
--> {"jsonrpc": "2.0", "id": 4, "method": "crud.update_cell", "params": {"model": "Task", "id": 1, "field": "completed", "value": true}}
<-- {"jsonrpc": "2.0", "id": 4, "result": {"success": true, "id": 1}}
```

---

<a id="stream"></a>
## 🌊 5. Multi-return Streaming (stream: true)

> **Specification:** `Multi-Return • Non-Blocking`

Stream intermediate progress chunks for long-running operations without blocking the socket or polling.

**Architectural Concept:**
session.send_stream_chunk(rpc_id, chunk) sends intermediate payloads marked with stream: true. The final return resolves the original RPC promise.

### Backend (Python)
```python
@app.rpc("analytics.generate")
async def generate_analytics(session):
    rpc_id = current_rpc_id_ctx.get()
    for i in range(1, 4):
        await asyncio.sleep(0.5)
        await session.send_stream_chunk(rpc_id, {"step": i, "progress": i * 25})
    return {"progress": 100, "report_url": "/reports/summary.pdf"}
```

### Client (TypeScript / JavaScript)
```typescript
await rpc.call('analytics.generate', {}, {
  onChunk: (chunk) => console.log('Прогресс:', chunk.progress)
});
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
<-- {"jsonrpc": "2.0", "id": 5, "stream": true, "result": {"step": 1, "progress": 25}}
<-- {"jsonrpc": "2.0", "id": 5, "result": {"progress": 100, "report_url": "/reports/summary.pdf"}}
```

---

<a id="reverse-rpc"></a>
## 🪞 6. Symmetric Reverse RPC (Server → Browser)

> **Specification:** `Full Duplex • Browser RPC`

WSRPC is fully symmetric: the backend can initiate JSON-RPC calls into the browser and await response.

**Architectural Concept:**
The server calls a browser method via session.send_request('client.inspect', timeout=3.0). The browser executes logic and replies with a standard JSON-RPC response.

### Backend (Python)
```python
@app.rpc("admin.inspect_client")
async def inspect_client(session):
    browser_env = await session.send_request("client.get_env", timeout=5.0)
    return {"inspected": browser_env}
```

### Client (TypeScript / JavaScript)
```typescript
rpc.register('client.get_env', () => {
  return { userAgent: navigator.userAgent, screen: `${screen.width}x${screen.height}` };
});
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
<-- {"jsonrpc": "2.0", "id": "srv-1", "method": "client.get_env", "params": {}}
--> {"jsonrpc": "2.0", "id": "srv-1", "result": {"userAgent": "Mozilla..."}}
```

---

<a id="broadcast"></a>
## 📢 7. Realtime Broadcast (Zero-Copy Push)

> **Specification:** `O(1) Broadcast • Zero-Copy`

Instant O(1) notification fan-out to all connected sockets. Payload serializes into JSON exactly once in memory.

**Architectural Concept:**
broadcast_notification() serializes the message once via orjson, after which the native Rust engine broadcasts raw frame bytes across all active sockets.

### Backend (Python)
```python
from rsgi_wsrpc.plugins.broadcast import broadcast_notification

@app.rpc("alerts.publish")
async def publish_alert(message: str):
    await broadcast_notification("system.alert", {"message": message, "time": time.time()})
    return {"status": "broadcast_sent"}
```

### Client (TypeScript / JavaScript)
```typescript
rpc.on('system.alert', (data) => {
  console.warn('Получено системное оповещение:', data.message);
});
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
<-- {"jsonrpc": "2.0", "method": "system.alert", "params": {"message": "Server maintenance in 5 min", "time": 1775546200}}
```

---

<a id="files"></a>
## 📁 8. File Upload: Two-Phase Commit (2PC)

> **Specification:** `Granian RSGI • Streaming 2PC`

Streaming file upload without RAM buffering and atomic commit via WSRPC.

**Architectural Concept:**
Phase 1: Chunks stream straight to disk into a temporary folder via POST /upload with O(1) RAM. Phase 2: files.commit atomically commits files to persistent storage.

### Backend (Python)
```python
# Фаза 1: HTTP-стриминг чанков на диск
# POST /upload?folder_hash=abc123

# Фаза 2: WSRPC атомарный коммит
@app.rpc("files.commit")
async def commit_files(folder_hash: str):
    saved_files = await finalize_folder_upload(folder_hash)
    return {"status": "committed", "files": saved_files}
```

### Client (TypeScript / JavaScript)
```typescript
// 1. Загрузка через FormData стримом
await fetch(`/upload?folder_hash=${hash}`, { method: 'POST', body: formData });
// 2. Атомарная фиксация через WebSocket
const res = await rpc.call('files.commit', { folder_hash: hash });
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
--> POST /upload?folder_hash=abc123 (Binary Stream)
<-- HTTP/1.1 200 OK {"uploaded": 3}
--> {"jsonrpc": "2.0", "id": 8, "method": "files.commit", "params": {"folder_hash": "abc123"}}
```

---

<a id="rbac"></a>
## 🔐 9. RBAC & Row-Level Security (RLS)

> **Specification:** `RLS Engine • SQLAlchemy 2.0`

Hybrid access control: dynamic DB roles, separate CRUD & RPC permissions, and Row-Level Security by teams and owners.

**Architectural Concept:**
By default, unauthenticated guests only access login.* (Default Deny). RowSecureModel enforces team_id and creator_id scoping so users only see their team records.

### Backend (Python)
```python
class Task(RowSecureModel):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(100))
    # id, creator_id, team_id, created_at встроены в RowSecureModel!

# В handlers.py:
@rpc_method("tasks.create")
async def create_task(session, title: str):
    check_permissions("create", "Task")
    # Права проверяются на уровне ORM
```

### Client (TypeScript / JavaScript)
```typescript
const me = await rpc.call('auth.me');
console.log(me.role, me.permissions);
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
--> {"jsonrpc": "2.0", "id": 9, "method": "tasks.list", "params": {"only_mine": true}}
<-- {"jsonrpc": "2.0", "id": 9, "result": {"$tabular": true, "rows": [...]}}
```

---

<a id="seo"></a>
## 🤖 10. SEO & Dynamic Rendering for Bots

> **Specification:** `Bot Detector • SSR Crawler`

Automatic crawler detection and server-side HTML rendering with OpenGraph and JSON-LD meta tags.

**Architectural Concept:**
Search crawlers (Googlebot, Yandex, Telegram, Discord) receive clean SSR HTML, while real users get the lightning-fast reactive SPA.

### Backend (Python)
```python
from rsgi_wsrpc.plugins.seo import bot_page, render_seo_page

@bot_page("/tasks/{task_id}")
async def task_seo(task_id: int):
    task = await get_task_by_id(task_id)
    return render_seo_page(
        title=task.title,
        description="Просмотр задачи на rsgi-wsrpc",
        og_image="/static/og.png"
    )
```

### Client (TypeScript / JavaScript)
```typescript
// Браузер работает как обычный SPA:
window.history.pushState({}, '', '/tasks/42');
```

### Protocol Frame (JSON-RPC 2.0 Wire Format)
```json
GET /tasks/42 User-Agent: Googlebot/2.1
HTTP/1.1 200 OK Content-Type: text/html
<html><head><title>Task 42</title><meta property="og:title" content="Task 42"></head>...
```

---
