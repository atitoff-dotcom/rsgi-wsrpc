# Core File & Upload Subsystem (rsgi-wsrpc)

## 1. Overview and Paradigm

In the **rsgi-wsrpc** reactive framework, file management is designed around a high-performance hybrid architecture:
1. **WSRPC (JSON-RPC 2.0)** acts as the orchestrator for transactions, access control, reactive progress, and metadata.
2. **HTTP POST (RSGI)** functions as a streaming data pipeline for transferring raw binary bytes.
3. **Nginx** handles high-throughput, zero-copy static distribution of committed files without burdening Python worker threads.

> **Core Architectural Principle:**  
> Never transmit Base64 blobs over WebSocket! Never leave orphaned files on disk upon network failure. Uploading files is strictly managed as an atomic **Two-Phase Commit (2PC)** transaction with guaranteed automatic **Rollback**.

---

## 2. Separation of Concerns (Core vs Platform vs Application)

The subsystem is decoupled into three clean abstraction layers:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. CORE LAYER (Transport & Transaction Coordination)                   │
│    • RSGI Streaming Handler: POST /upload (O(1) RAM chunk streaming)   │
│    • UploadTransaction & Coordinator (temp directory isolation)        │
│    • WSRPC Multi-return Stream (real-time progress & stage events)     │
│    • WebSocket Session Lifecycle Hook (auto-rollback on disconnect)    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 2. SYSTEM PLATFORM LAYER (app/system/files)                            │
│    • System File Registry: `file_metadata` database table              │
│    • User quotas, size limits & disk audit                             │
│    • Access Control: Public (Nginx direct) vs Protected (ACL / Token) │
│    • Garbage Collection (background cleaning of orphaned files)        │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 3. APPLICATION MODULES (app/forum, app/articles, app/tickets, ...)     │
│    • Business entities: binding folder_hash to topics, articles, jobs  │
│    • High-level create and delete handlers                             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core: Transaction Coordinator & Lifecycle

### 3.1. Two-Phase Commit (2PC) Lifecycle

```
[ Browser / Client ]                               [ Server (Core RSGI + WSRPC) ]
         │                                                        │
         │ 1. Transaction Init (WSRPC requestStream):             │
         │    rpc.requestStream('module.create_item', {           │
         │      files_count: 3, title: "..."                      │
         │    }) ────────────────────────────────────────────────►│ 
         │                                                        │ • Allocates folder_hash: 'a8F9cK2mX1zL'
         │                                                        │ • Creates /tmp/agrita_uploads/a8F9cK2mX1zL/
         │ ◄── Chunk 1: { stage: "ready", folder: "a8F9cK2mX1zL" }│ • Registers tx with WS session
         │                                                        │
         │ 2. Streaming Byte Upload (HTTP POST via RSGI):         │
         │    POST /upload?folder=a8F9cK2mX1zL&index=1 ──────────►│ • Streams 1.webp directly to disk
         │ ◄── Chunk 2: { stage: "progress", file_index: 1 } ─────│
         │                                                        │
         │    POST /upload?folder=a8F9cK2mX1zL&index=2 ──────────►│ • Streams 2.webp directly to disk
         │ ◄── Chunk 3: { stage: "progress", file_index: 2 } ─────│
         │                                                        │
         │ 3. COMMIT PHASE:                                       │
         │                                                        │ 1. Atomic rename/move:
         │                                                        │    /tmp/.../ -> /files/a8F9cK2mX1zL/ (0 ms)
         │                                                        │ 2. Register in file_metadata
         │                                                        │ 3. Write business entity to DB
         │ ◄── FINAL: { success: true, item_id: 10 } ─────────────│
```

### 3.2. Automatic Rollback on Disconnect

In the session management module (`core/session.py`), every active `JsonRpcSession` tracks pending `UploadTransaction` objects.

If the client closes the browser, loses network connectivity, or drops the connection:
1. The session termination hook `session.on_close` is executed.
2. The core queries uncommitted transactions.
3. The temporary folder `/tmp/agrita_uploads/<folder_hash>` is immediately removed:
   ```python
   shutil.rmtree(temp_folder_path, ignore_errors=True)
   ```
4. No broken or partially uploaded files ever enter the permanent `/files/` storage, keeping disk and database pristine.

---

## 4. Platform Layer: Universal File Registry (`file_metadata`)

All uploaded files across any module are registered in a single system table:

```sql
CREATE TABLE file_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_hash VARCHAR(64) NOT NULL,        -- 12-char bundle folder hash
    filename VARCHAR(255) NOT NULL,          -- Storage filename: '1.webp', 'chart.png'
    original_name TEXT,                      -- Original name: 'Report_2026.pdf'
    size INTEGER NOT NULL,                   -- File size in bytes
    mime_type VARCHAR(128),                  -- 'image/webp', 'application/pdf'
    sha256 VARCHAR(64),                      -- SHA-256 hash (deduplication & integrity)
    owner_id INTEGER NOT NULL,               -- User ID of the uploader
    is_public BOOLEAN NOT NULL DEFAULT 1,    -- 1: Nginx direct static, 0: access token required
    download_token VARCHAR(512),             -- Capability token for private download
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_file_folder ON file_metadata (folder_hash);
CREATE INDEX idx_file_owner ON file_metadata (owner_id);
```

---

## 5. Nginx Offloading (Download Flow)

### 5.1. Public Media (`is_public = 1`)
Public images and assets are served directly by Nginx without touching Python worker processes:

```nginx
location /files/ {
    alias /var/www/rsgi-wsrpc/files/;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    access_log off;
    sendfile on;
    tcp_nopush on;
}
```

### 5.2. Protected Documents (`is_public = 0`)
Private files leverage Nginx `X-Accel-Redirect`:
1. The client sends a download request with an access token to a lightweight RSGI endpoint.
2. The server verifies access permissions and responds with an empty HTTP response header:
   `X-Accel-Redirect: /internal_files/<folder_hash>/<filename>`
3. Nginx serves the file directly from disk at kernel-level speed.
