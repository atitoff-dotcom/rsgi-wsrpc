# Modular Backend Test Framework (Client Test Harness)

The **rsgi-wsrpc** platform includes a professional, modular asynchronous testing framework (`tests/`) that validates backend behavior **from a real client perspective** (black-box) over **WSRPC (WebSocket)** and **HTTP**.

It resolves the core issues of manual and ad-hoc script testing:
* **Eliminates repetitive authentication failures**: built-in personas (`Admin`, `User`, `Guest`) authenticate over WebSockets automatically without manual password hashing or token juggling.
* **Understands WSRPC specifics**: natively tests multi-return streaming (`stream: true`), intercepts server-side push notifications (`cache.invalidate`, `cache.patch`), and measures real millisecond network latencies.
* **Includes stress & load testing**: benchmarks RPS, latency percentiles (p50, p95, p99), and broadcast reliability (Fan-out) across dozens or hundreds of concurrent WebSocket connections.

---

## 🚀 Quick Start

Run tests using the unified CLI runner:

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all test suites against local server (default)
python tests/run.py

# Run specific suite (e.g. smart cache or forum)
python tests/run.py smart_cache
python tests/run.py forum auth

# Run load and stress tests
python tests/run.py load

# Run tests against remote Stage deployment
python tests/run.py --target=stage
```

### Example Runner Output:
```text
=== Agrita Backend Test Harness ===
  Цель:      LOCAL (http://127.0.0.1:8080 | ws://127.0.0.1:8080/)
  Сьюты:     auth, smart_cache, forum, files, load

▶ Сьют: auth (4 тестов)
  ✔ PASS  auth::test_guest_public_access  (2.3 ms)
  ✔ PASS  auth::test_login_and_whoami  (202.6 ms)
  ✔ PASS  auth::test_login_invalid_password  (4.6 ms)
  ✔ PASS  auth::test_token_refresh  (27.8 ms)

▶ Сьют: smart_cache (3 тестов)
  ✔ PASS  smart_cache::test_cache_get_versions  (2.8 ms)
  ✔ PASS  smart_cache::test_cache_sync_check_stale_detection  (3.1 ms)
  ✔ PASS  smart_cache::test_live_cache_invalidation_notification  (69.8 ms)

▶ Сьют: forum (3 тестов)
  ✔ PASS  forum::test_get_topics_guest  (4.9 ms)
  ✔ PASS  forum::test_topic_creation_and_cache_invalidation  (80.6 ms)
  ✔ PASS  forum::test_unauthorized_deletion_prevented  (44.2 ms)

▶ Сьют: files (1 тестов)
  ✔ PASS  files::test_two_phase_file_upload  (21.4 ms)

▶ Сьют: load (2 тестов)
  ⚡ [FAN-OUT STATS] Рассылка на 25 активных WebSocket-клиентов за 3.3ms
  ✔ PASS  load::test_concurrent_broadcast_fanout  (312.1 ms)
  📊 [LOAD STATS] 200 запросов за 0.06s | 3540.1 RPS
  ⏱️  Задержки: p50=4.1ms, p95=6.2ms, p99=6.6ms
  ✔ PASS  load::test_concurrent_rpc_throughput  (56.6 ms)

=== Итоги тестирования ===
Всего: 13, Успешно: 13, Провалено: 0 (0.84 s)
```

---

## 🏗 Test Harness Architecture (`tests/`)

```
tests/
├── framework/              # Core harness infrastructure
│   ├── config.py           # Target host configuration (local, stage, ports)
│   ├── client.py           # Asynchronous WSRPC + HTTP client (TestClient)
│   ├── personas.py         # Role management (Admin, User, Guest) & DB seeding
│   └── assertions.py       # Custom assertions for RPC responses, errors, and push events
├── suites/                 # Modular test suites
│   ├── test_auth.py        # Authentication, tokens, RLS profile
│   ├── test_smart_cache.py # Tag versioning, sync_check handshake, push invalidation
│   ├── test_forum.py       # Business logic, topic creation, deletion permission checks
│   ├── test_files.py       # Two-phase file upload (/upload)
│   └── test_load.py        # Load testing, RPS, latency percentiles p50/p95/p99
└── run.py                  # CLI test runner with formatting and timing metrics
```

---

## 🔑 Persona Management (`PersonaManager`)

To eliminate boilerplate authentication in individual tests, use `PersonaManager`:

```python
from tests.framework import PersonaManager

# 1. Unauthenticated client (Guest)
async with await PersonaManager.as_guest() as client:
    res = await client.call("system.echo", {"hello": "world"})

# 2. Regular user (automatically logs in as 'test_user')
async with await PersonaManager.as_user() as client:
    res = await client.call("forum.create_topic", {...})

# 3. Administrator (superuser privileges)
async with await PersonaManager.as_admin() as admin:
    res = await admin.call("cache.invalidate", {"tags": ["forum.topics"]})
```

> [!TIP]
> When executing against local server (`--target=local`), `PersonaManager` automatically verifies the existence of test users in the SQLite/PostgreSQL database. If a user is missing or the password changed, it creates or updates the user bypassing RLS (`system_bypass_ctx`). No manual database pre-population is needed!

---

## 📡 Capabilities of `TestClient`

The `TestClient` encapsulates all interactions with WebSocket and HTTP services:

### 1. Single Requests (`call`)
```python
# Returns 'result' payload from JSON-RPC response or raises RPCClientError
res = await client.call("forum.get_topic", {"id": 42})
```

### 2. Awaiting Push Notifications (`wait_for_notification`)
Perfect for verifying cache invalidation and live entity updates:
```python
# Launch waiting task in background
wait_task = asyncio.create_task(client.wait_for_notification("cache.invalidate", timeout=5.0))

# Second client triggers mutation
await other_client.call("forum.create_topic", {...})

# Receive and validate incoming push event
notif = await wait_task
assert "forum.topics" in notif["params"]["tags"]
```

### 3. Streaming Multi-Returns (`stream`)
```python
# Iterate over incremental chunks until stream finishes
async for chunk in client.stream("reports.generate", {"year": 2026}):
    print(f"Incremental progress: {chunk}")
```

### 4. Streaming File Uploads (`upload_file`)
```python
# Streams raw bytes via HTTP POST /upload without Base64 overhead
result = await client.upload_file(
    filename="avatar.png",
    content=b"RAW_IMAGE_BYTES",
    content_type="image/png"
)
print("Uploaded folder hash:", result["folder_hash"])
```

---

## ⚡ Load & Stress Testing (`test_load.py`)

Load tests expose hidden architectural bottlenecks that cannot be caught with single unit tests:

### 1. What `test_load` verifies:
1. **RPS & Latency Distribution** (`test_concurrent_rpc_throughput`):
   - Dozens of concurrent clients hammer the server over active WebSockets.
   - Measures key metrics: **RPS** (requests per second), median **p50**, tail latencies **p95** and **p99**.
2. **Broadcast Stress (Fan-out)** (`test_concurrent_broadcast_fanout`):
   - Connects a pool of dozens of active listening clients.
   - Author client triggers `cache.invalidate`.
   - Verifies 100% notification delivery, zero socket stalls, and delivery timing in single-digit milliseconds (~3 ms for 25 clients).

### 2. Typical bugs revealed by load tests:
* **Database lock contention (`database is locked` in SQLite)**: when multiple sockets write concurrently. Resolution: WAL mode (`PRAGMA journal_mode=WAL`) and async write queues.
* **Leaking tasks (`Task was destroyed but it is pending`)**: when client drops connection during active execution.
* **Event Loop Starvation**: heavy synchronous CPU blocks or synchronous disk I/O in the asyncio loop causing p99 to jump from 4 ms to hundreds of milliseconds.
* **Memory & Session Leaks**: accumulation of orphaned WebSocket session instances upon abrupt network dropouts.

---

## 📝 Creating a Custom Test Suite

Adding a test suite for a new plugin or feature module is straightforward:

1. Create `tests/suites/test_my_feature.py`:
```python
from tests.framework import PersonaManager, assert_rpc_success

async def test_my_action():
    async with await PersonaManager.as_user() as client:
        res = await client.call("my_feature.do_something", {"param": 1})
        assert_rpc_success(res, expected_keys=["status", "result_id"])
```

2. Register the suite in the `SUITES` dictionary of [tests/run.py](file:///home/alex/hydro_calc/tests/run.py):
```python
from tests.suites import test_my_feature

SUITES = {
    ...
    "my_feature": test_my_feature,
}
```

3. Run it:
```bash
python tests/run.py my_feature
```
