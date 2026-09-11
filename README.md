# rsgi-wsrpc

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![RSGI: Granian](https://img.shields.io/badge/engine-Rust%20Granian%20RSGI-orange.svg)](https://github.com/emmett-framework/granian)

[🇷🇺 Читать на русском языке (README_RU.md)](README_RU.md)

> **"Everything Django should have become, and everything FastAPI forgot to include."**  
> A lightning-fast, reactive fullstack Python framework powered by **Rust (Granian RSGI)** with a symmetric **WSRPC (JSON-RPC 2.0)** bus, built-in async database, auth, and Two-Phase Commit file streaming.

---

## ⚡ Why rsgi-wsrpc?

* **Sub-Millisecond Response Times**: 1–3 ms latency over a single multiplexed WebSocket connection instead of HTTP/1.1 REST handshake roundtrips.
* **Rust RSGI Engine**: Powered by Granian — raw performance without Python GIL execution bottlenecks.
* **Symmetric Protocol**: Both client and server can invoke RPC methods and stream real-time push events.
* **Native Multi-Return (`stream: true`)**: Stream long-running operation progress directly without external Redis queues.
* **Two-Phase Commit File Upload**: Chunk streaming with constant **O(1) RAM** footprint, automatic rollback on disconnect, and Nginx zero-copy offloading.
* **Batteries Included**: Pre-configured Async SQLAlchemy (SQLite/PostgreSQL), JWT + RefreshToken auth, Role & Row-Level Security (RLS).

---

## 🚀 Quick Start

### 1. Installation
```bash
git clone https://github.com/atitoff-dotcom/rsgi-wsrpc.git
cd rsgi-wsrpc
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Run the Server
```bash
granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
```

### 3. Connect from Client (TypeScript / JavaScript)
```typescript
import { WsrpcClient } from './client/wsrpc';

const client = new WsrpcClient('ws://127.0.0.1:8080');
await client.connect();

// Call an RPC method
const res = await client.call('system.echo', { message: 'Hello WSRPC!' });
console.log(res);
```

---

## 📚 Documentation

Comprehensive architectural documentation, deep dives, and tutorials are available in:
* **[English Documentation](docs/readme.md)**
  * [Two-Phase Upload & File Architecture](docs/files.md)
* **[Русская документация (Russian Documentation)](docs_ru/readme.md)**
  * [Архитектура загрузки и хранения файлов](docs_ru/files.md)

---

## 📄 License
Released under the permissive [MIT License](LICENSE).
