# ⚙️ Core Engine: Developer Guide

The `rsgi-wsrpc` network core is located in the `core/` directory. It is a high-performance asynchronous socket runtime running on top of the **Rust Granian RSGI** protocol.

The core is engineered following Clean Architecture principles:
* **Zero external dependencies on business logic**: The core has no awareness of databases, data models, or specific application users.
* **Strict isolation**: All interaction with higher application layers occurs via clean abstractions (`@rpc_method`, `@on_startup`, `ContextVar` context variables, and session termination hooks).

---

## 🧭 Table of Contents
1. [Architecture & Core Components](#1-architecture--core-components)
2. [Sessions & RPC: core/session.py](#2-sessions--rpc-coresessionpy)
   * [Method Registration (@rpc_method)](#method-registration-rpc_method)
   * [Context Variables (ContextVars)](#context-variables-contextvars)
   * [Error Handling (RPCError)](#error-handling-rpcerror)
   * [Multi-Return Streaming](#multi-return-streaming)
   * [Symmetric RPC (Server Calls Client)](#symmetric-rpc-server-calls-client)
   * [Session Termination Hooks (session.register_on_close)](#session-termination-hooks-sessionregister_on_close)
   * [Built-in Guardrails (Rate Limiting & Timeouts)](#built-in-guardrails-rate-limiting--timeouts)
3. [Routing & RSGI Protocol: core/router.py](#3-routing--rsgi-protocol-corerouterpy)
4. [Tabular Payload Compression (RFC 0002): core/tabular.py](#4-tabular-payload-compression-rfc-0002-coretabularpy)
5. [Server Lifecycle: core/lifecycle.py](#5-server-lifecycle-corelifecyclepy)
6. [Security & Cryptography: core/security.py](#6-security--cryptography-coresecuritypy)
7. [Configuration: core/lib/config.py](#7-configuration-corelibconfigpy)
8. [TypeScript/JavaScript Client: client/wsrpc.ts](#8-typescriptjavascript-client-clientwsrpcts)

---

## 1. Architecture & Core Components

```text
                     ┌──────────────────────────────────────┐
                     │          Granian RSGI Server         │
                     │          (Rust Event Loop)           │
                     └──────────────────┬───────────────────┘
                                        │ scope, proto
                     ┌──────────────────▼───────────────────┐
                     │           main:app (RSGI Entry)      │
                     └──────────┬───────────────────┬───────┘
            scope.proto == "http"                   scope.proto == "websocket"
                                │                   │
       ┌────────────────────────▼────────┐ ┌────────▼───────────────────────┐
       │         core/router.py          │ │          core/session.py       │
       │   @http_route(path, methods)    │ │   JsonRpcSession, WSRPC Engine │
       │   - Streaming endpoints         │ │   - @rpc_method registry       │
       │   - Health checks (/health)     │ │   - ContextVars (user, session)│
       │   - Direct binary endpoints     │ │   - Rate Limiting (Token Bucket│
       └─────────────────────────────────┘ │   - Multi-return streaming     │
                                           │   - Symmetric Client Calls     │
                                           │   - register_on_close (2PC)    │
                                           └────────────────┬───────────────┘
                                                            │
                                  ┌─────────────────────────┴───────────────┐
                                  │                                         │
                   ┌──────────────▼──────────────┐           ┌──────────────▼──────────────┐
                   │       core/tabular.py       │           │      core/lifecycle.py      │
                   │   RFC 0002 Compression     │           │   @on_startup, __rsgi_init__│
                   │   - pack_tabular / unpack   │           │   - Async Schema Migrations │
                   │   - 50-70% traffic saving   │           │   - Cache Warming           │
                   └─────────────────────────────┘           └─────────────────────────────┘
```

---

## 2. Sessions & RPC: `core/session.py`

The `core/session.py` module is the foundation of the framework. It upgrades raw WebSocket connections into persistent, secure WSRPC (JSON-RPC 2.0) sessions.

### Method Registration (`@rpc_method`)

Each RPC method is registered using the `@rpc_method` decorator:

```python
from core.session import rpc_method, JsonRpcSession, RPCError

# Basic method
@rpc_method("calculator.add")
async def calculate_sum(session: JsonRpcSession, params: dict):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"sum": a + b}

# Method restricted by user role
from core.constants import UserRole

@rpc_method("admin.restart_service", role=UserRole.ADMIN)
async def restart_service(session: JsonRpcSession, params: dict):
    # If the session lacks admin privileges, the core automatically
    # returns a standard JSON-RPC error: "Access denied: requires role admin"
    return {"status": "restarting"}
```

### Custom Roles & Extending the Role Model

The framework core imposes no rigid or closed set of roles. The `UserRole` class is explicitly subclassed from Python's standard `str`, enabling applications to define arbitrary domain roles:

```python
# 1. Declare custom application roles (app/roles.py)
from core.constants import UserRole

class AppRole(UserRole):
    MODERATOR = "moderator"
    OPERATOR  = "operator"
    MANAGER   = "manager"

@rpc_method("content.moderate", role=AppRole.MODERATOR)
async def moderate_content(session: JsonRpcSession, params: dict):
    return {"status": "approved"}

# 2. Use plain string literals directly
@rpc_method("orders.dispatch", role="operator")
async def dispatch_order(session: JsonRpcSession, params: dict):
    return {"status": "dispatched"}
```

> **Superadmin Bypass Rule**: A user holding the `admin` role is treated as the core superuser and is granted unconditional access to all role-restricted RPC methods, regardless of the specific role specified in `role=` (e.g. an admin can invoke methods restricted to `moderator` or `operator`).

### Context Variables (`ContextVars`)

During RPC handler execution, the core automatically assigns asynchronous context variables. You **never** need to pass the session or user object down through internal call stacks:

```python
from core.session import (
    current_user_ctx,
    current_session_ctx,
    current_rpc_id_ctx,
    current_transport_ctx
)

async def internal_audit_log(action: str):
    # Access the active authenticated user from any depth of async execution!
    user = current_user_ctx.get()
    user_id = user.id if user else "anonymous"
    rpc_id = current_rpc_id_ctx.get()
    print(f"[AUDIT] User {user_id} performed {action} in RPC call #{rpc_id}")
```

### Error Handling (`RPCError`)

Instead of uncaught exceptions and 500 errors, use `RPCError`. The message is cleanly packaged into a standard JSON-RPC 2.0 error envelope (`error: {code: -32000, message: "..."}`):

```python
@rpc_method("order.cancel")
async def cancel_order(session: JsonRpcSession, params: dict):
    order_id = params.get("order_id")
    if not order_id:
        raise RPCError("Parameter order_id is required")

    order = await get_order(order_id)
    if not order:
        raise RPCError("Order not found")

    if order.is_shipped:
        raise RPCError("Cannot cancel an order that has already shipped")

    await order.cancel()
    return {"success": True}
```

### Multi-Return Streaming

Unlike standard REST or flat JSON-RPC, `rsgi-wsrpc` provides native multi-return streaming: for a single client request, the server can emit intermediate progress chunks before returning the final `result`:

```python
@rpc_method("reports.generate")
async def generate_large_report(session: JsonRpcSession, params: dict):
    rpc_id = params.get("rpc_id")
    total_steps = 5

    for step in range(1, total_steps + 1):
        await asyncio.sleep(0.5) # Simulated computation
        
        # Send intermediate progress chunk to the socket
        await session.send_stream_chunk(rpc_id, {
            "step": step,
            "total": total_steps,
            "percent": int((step / total_steps) * 100),
            "status": f"Processing batch {step}..."
        })

    # Final result completes the RPC call
    return {"report_url": "/files/reports/report_2026.pdf", "status": "done"}
```

### Symmetric RPC (Server Calls Client)

Because the WSRPC socket is bidirectional and symmetrical, the server can initiate an RPC call to the client at any time and await the user's response:

```python
@rpc_method("security.transfer_funds")
async def transfer_funds(session: JsonRpcSession, params: dict):
    amount = params.get("amount")
    
    # Server requests confirmation from the frontend (e.g. 2FA modal)
    client_response = await session.send_request(
        method="ui.request_confirmation",
        params={
            "title": "Confirm Wire Transfer",
            "message": f"Are you sure you want to transfer ${amount}?",
            "timeout_sec": 30
        },
        timeout=30.0
    )
    
    if not client_response.get("result", {}).get("confirmed"):
        raise RPCError("Operation rejected by user")
        
    return {"status": "funds_transferred"}
```

### Session Termination Hooks (`session.register_on_close`)

Prevent memory leaks and dangling background processes when connections terminate (tab close, network drop):

```python
@rpc_method("live.subscribe")
async def subscribe_to_telemetry(session: JsonRpcSession, params: dict):
    device_id = params.get("device_id")
    
    async def cleanup(closed_session):
        print(f"Session closed, unsubscribing from device {device_id}")
        await telemetry_hub.unsubscribe(device_id, closed_session)
        
    session.register_on_close(cleanup)
    await telemetry_hub.subscribe(device_id, session)
    return {"subscribed": True}
```

### Built-in Guardrails (Rate Limiting & Timeouts)

Every `JsonRpcSession` includes hardware-level protection:
1. **Rate Limiter (Token Bucket)**: Automatically resets counters every second without spawning heavy asyncio tasks (`loop.call_later`). If a socket transmits over 30 req/sec, the connection is instantly terminated with code `-32005 Too many requests`.
2. **Auth Timeout**: If an unauthenticated socket fails to authenticate within 60 seconds, the connection is closed.
3. **Idle Timeout**: If an authenticated session has no activity for longer than configured (default 900 seconds), it is gracefully terminated with a `session.expired` notification.

---

## 3. Routing & RSGI Protocol: `core/router.py`

The `core/router.py` module registers direct HTTP endpoints on top of RSGI. This is required for high-throughput streaming file transfers, webhooks, and health checks.

```python
from core.router import http_route

@http_route("/health", methods=["GET"])
async def health_check(scope, proto):
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"healthy","engine":"rsgi-wsrpc"}'
    )

@http_route("/webhook/payment", methods=["POST"])
async def payment_webhook(scope, proto):
    # Read raw request body from RSGI protocol
    body_bytes = bytearray()
    while True:
        chunk = await proto.receive()
        if not chunk:
            break
        body_bytes.extend(chunk)
        
    # Process webhook...
    proto.response_str(status=200, headers=[], body="OK")
```

---

## 4. Tabular Payload Compression: `core/tabular.py` (RFC 0002)

The `core/tabular.py` module provides deterministic serialization of collection payloads into the `$tabular: true` format, eliminating dictionary key redundancy and cutting 50–70% of network payload size.

```python
from core.tabular import pack_tabular, tabular_response

# 1. Automatic response serialization via decorator
@rpc_method("tasks.list")
@tabular_response(fields=["id", "title", "completed", "priority"])
async def list_tasks(session, params):
    tasks = await fetch_tasks()
    return [t.to_dict() for t in tasks]

# 2. Raw SQL cursor optimization (zero dictionary allocations)
@rpc_method("logs.get_recent")
async def get_recent_logs(session, params):
    async with db.execute("SELECT id, level, message FROM logs") as cursor:
        rows = await cursor.fetchall()  # Raw tuples
        return pack_tabular(rows, fields=["id", "level", "message"])
```

### Socket Transaction Support & Rollback (2PC Lifecycle Hooks)

The `rsgi-wsrpc` network core is strictly decoupled from the filesystem and contains no hardcoded temporary paths (`/tmp/...`). For two-phase transactions (such as file uploads or distributed tasks), the core exposes a universal session termination hook: `session.register_on_close`:

```python
# Bind transaction rollback to the WebSocket session lifetime:
session.register_on_close(lambda s: my_transaction.rollback())
```

If the client closes the browser tab or disconnects midway through an operation, the registered callback is automatically executed by the core, preventing leaked temp files or orphaned resources.

> For a complete guide to building two-phase file ingestion, see [docs/files.md](files.md).

---

## 5. Server Lifecycle: `core/lifecycle.py`

Registers asynchronous startup tasks that run **before** the Granian worker begins accepting incoming traffic:

```python
from core.lifecycle import on_startup

@on_startup
async def init_cache_and_db():
    print("[Startup] Verifying database schema...")
    await migrate_schema()
    
    print("[Startup] Warming L1 cache...")
    await warm_up_memory_cache()
```

In `main.py`, hooks are invoked via Granian's native worker initialization:
```python
def __rsgi_init__(loop):
    loop.run_until_complete(run_startup_callbacks())

app.__rsgi_init__ = __rsgi_init__
```

---

## 6. Security & Cryptography: `core/security.py`

Built-in modern authentication and cryptographic utilities:

```python
from core.security import hash_password, verify_password, create_jwt_token, decode_jwt_token

# Argon2id hashing
hashed = hash_password("super_secret_password")
is_valid = verify_password("super_secret_password", hashed) # True

# JWT tokens
token = create_jwt_token(payload={"sub": 105, "role": "admin"}, expires_in_seconds=3600)
data = decode_jwt_token(token)
```

---

## 7. Configuration: `core/lib/config.py`

Project settings parsed from `settings.yaml` and accessible anywhere via the global `settings` object:

```python
from core.lib.config import settings

# Access properties
db_url = settings.db.get("url")
upload_dir = settings.storage.get("upload_dir", "/files")
```

---

## 8. TypeScript/JavaScript Client: `client/wsrpc.ts`

The official `BinaryWSRPC` client provides a reactive environment for connecting to the WSRPC server in modern web applications (Svelte, React, Vue, Angular, or Vanilla JS/Node.js).

### Client Capabilities:
* **Single Persistent Socket** for all RPC transactions, streams, and server events.
* **Automatic Reconnection** upon network disruption while preserving subscriptions.
* **Native Multi-Return (`callStream`)**: Live progress indicators, streamed computations, and log streaming without secondary WebSockets.
* **Server Push & Event Notifications** (`rpc.on(...)`).
* **Symmetric RPC**: The server can invoke client-side methods and await the user's return value (`rpc.registerMethod(...)`).
* **Session Gatekeeper (`authInterceptor`)**: Automatic bootstrap synchronization. Outgoing business calls automatically await session authentication (`login.refresh`) upon cold start (F5) or reconnection, eliminating race conditions.
* **Reactive State Stores**: Reactive network state tracking (`wsConnected`, `wsStatus`).

---

### 1. Connection & Network Lifecycle Management

```typescript
import { BinaryWSRPC, wsConnected, wsStatus } from './wsrpc';

// Instantiate client (or import singleton: import { rpc } from './wsrpc')
export const rpc = new BinaryWSRPC('wss://api.example.com/ws');

// Set auto-reconnect interval (in seconds). Default is 3s (0 to disable)
rpc.reconnectWs = 3;

// Connection lifecycle hooks
rpc.onConnect = () => {
    console.log('[App] WebSocket connection ready');
};

rpc.onStatusChange = (isConnected: boolean) => {
    console.log('[App] Network state:', isConnected ? 'ONLINE' : 'OFFLINE');
};

// Initiate connection
await rpc.connect();
```

#### Reactive Offline Banner in UI:
```typescript
// Svelte:
// {#if !$wsConnected}
//    <div class="offline-banner">Connection lost. Reconnecting to server...</div>
// {/if}

// React / Vue / Vanilla JS:
wsConnected.subscribe((connected) => {
    document.getElementById('status-indicator').textContent = connected ? 'Online' : 'Reconnecting...';
});
```

---

### 2. Standard RPC Call (`call`)

`rpc.call<T>(method, params, timeoutMs)` returns a typed `Promise<T>`:

```typescript
interface UserProfile {
    id: number;
    name: string;
    email: string;
    role: string;
}

try {
    // Invoke typed RPC method
    const profile = await rpc.call<UserProfile>('user.get_profile', { user_id: 42 });
    console.log(`Welcome back, ${profile.name}! Role: ${profile.role}`);
} catch (error) {
    // If the server raises RPCError("..."), 
    // it will be caught here with a clean, descriptive message
    console.error('Failed to retrieve user profile:', error);
}
```

---

### 3. Multi-Return: Progress Streaming (`callStream`)

A hallmark feature of `rsgi-wsrpc`: the client calls a long-running process (e.g. database dump, PDF compilation, AI model evaluation), the server emits sequential chunks tagged with `stream: true`, and the final return payload resolves the primary promise!

#### Backend Implementation (Python):
```python
# app/reports/handlers.py
@rpc_method("reports.generate")
async def generate_report(session, params):
    rpc_id = params.get("rpc_id")
    total_stages = 4
    
    stages = [
        "Analyzing historical transactions",
        "Calculating tax withholdings",
        "Generating summary charts",
        "Compiling final PDF bundle"
    ]
    
    for i, title in enumerate(stages, 1):
        await asyncio.sleep(1.0) # Work simulation
        
        # Emit progress chunk to active client request
        await session.send_stream_chunk(rpc_id, {
            "stage": i,
            "total_stages": total_stages,
            "percent": int((i / total_stages) * 100),
            "message": title
        })
        
    # Final return completes the RPC request
    return {
        "status": "ready",
        "download_url": "/files/reports/report_q3_2026.pdf",
        "file_size": 2481020
    }
```

#### Frontend Consumer (TypeScript):
```typescript
interface ProgressChunk {
    stage: number;
    total_stages: number;
    percent: number;
    message: string;
}

interface ReportResult {
    status: string;
    download_url: string;
    file_size: number;
}

// Invoke streamed calculation and observe intermediate chunks
const finalReport = await rpc.callStream<ReportResult>(
    'reports.generate',
    { period: '2026-Q3', format: 'pdf' },
    (chunk: ProgressChunk) => {
        // Callback invoked on each intermediate progress packet:
        console.log(`[${chunk.percent}%] Step ${chunk.stage}/${chunk.total_stages}: ${chunk.message}`);
        
        // Update UI progress bar
        updateProgressBar(chunk.percent, chunk.message);
    }
);

// Executed only after the entire operation completes successfully
console.log('Report available for download:', finalReport.download_url);
window.open(finalReport.download_url, '_blank');
```

---

### 4. Receiving Notifications & Server Push (`on`)

The server can push unsolicited events to clients at any time (e.g., chat messages, order status changes, cache invalidation events, or system-wide maintenance notices).

#### Server Dispatcher (Python):
```python
# Unicast notification to a specific session:
await session.send_request("notification.alert", {
    "level": "warning",
    "text": "Server maintenance scheduled in 5 minutes."
})

# Multicast / Broadcast across all active connected sessions (app/system/broadcast.py):
from app.system.broadcast import broadcast_event

await broadcast_event("forum.new_topic", {
    "topic_id": 158,
    "title": "Announcing rsgi-wsrpc 1.0!",
    "author": "Alex"
})
```

#### Client Listener Subscription (TypeScript):
```typescript
// 1. Subscribe to system alerts
rpc.on('notification.alert', (data) => {
    uiNotification.show({
        type: data.level,
        message: data.text,
        duration: 10000
    });
});

// 2. Real-time feed synchronization
// on() returns an unsubscription callback:
const unsubscribe = rpc.on('forum.new_topic', (topic) => {
    console.log('New forum discussion:', topic.title);
    topicsStore.update(list => [topic, ...list]);
});

// Component unmount / cleanup (Svelte onDestroy / React useEffect):
// onDestroy(unsubscribe); // or useEffect(() => () => unsubscribe(), [])

// 3. Handle idle session expiration
rpc.on('session.expired', () => {
    uiDialog.alert('Your session has timed out due to inactivity. Please sign in again.');
    userStore.set(null);
    openLoginModal();
});
```

---

### 5. Symmetric RPC: Server Awaits Client Actions

Under WSRPC, server and client are peers. The server can invoke a registered client method and **await the client's return value**:

#### Frontend Registration:
```typescript
// Register client-side method ui.confirm
rpc.registerMethod('ui.confirm', async (params: { title: string; message: string }) => {
    // Render confirmation modal dialog
    const isUserAgreed = await openConfirmationDialog({
        title: params.title,
        message: params.message
    });

    // Return value is transmitted back to the server!
    return { confirmed: isUserAgreed };
});
```

#### Server Invocation (Python):
```python
@rpc_method("wallet.withdraw")
async def withdraw_money(session: JsonRpcSession, params: dict):
    amount = params.get("amount")
    account = params.get("account")
    
    # Server requests interactive confirmation from the user's browser
    try:
        response = await session.send_request(
            method="ui.confirm",
            params={
                "title": "Confirm Withdrawal",
                "message": f"Authorize withdrawal of ${amount} to account {account}?"
            },
            timeout=30.0 # Wait up to 30 seconds for user action
        )
    except TimeoutError:
        raise RPCError("Confirmation timed out")

    if not response.get("result", {}).get("confirmed"):
        raise RPCError("Transaction declined by user")

    # User confirmed — proceed with fund transfer
    await execute_withdrawal(amount, account)
    return {"status": "success", "transferred": amount}
```

---

### 6. Session Gatekeeper (`authInterceptor`)

WebSocket connections are stateful: when a user performs a cold page refresh (F5) or reconnects after network loss, the physical socket connects as an anonymous guest until the client issues a session renewal handshake (`login.refresh`). 

To prevent race conditions where early component mounting triggers protected calls before authentication finishes, `BinaryWSRPC` includes a built-in **Session Gatekeeper**:

```typescript
// Register the gatekeeper hook during app bootstrap (e.g. in auth.ts):
rpc.authInterceptor = async () => {
    const token = localStorage.getItem('rpc_token');
    if (!token) return;
    await restoreSession();
};
```

#### How it works:
1. **Automatic Request Queueing**: When UI components invoke protected methods (such as `admin.list_users` or `messages.get_conversations`), the client automatically holds all outgoing non-auth calls until `authInterceptor` finishes validating the session.
2. **Deadlock Prevention**: Authentication and system methods (`login.*`, `auth.*`, `system.*`) automatically bypass the gatekeeper.
3. **Seamless Reconnection**: After network drops, the first subsequent RPC request automatically triggers re-authentication before sending payload data, preventing `401 / Forbidden` errors across the entire UI.


