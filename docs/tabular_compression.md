# 📊 Tabular Payload Compression (RFC 0002)

Deterministic collection serialization for the `rsgi-wsrpc` framework (`app/system/tabular.py` + `wsrpc.ts`).

> **"Field schemas belong in the contract, not repeated thousands of times in network packets. Tabular compression eliminates dict redundancy, saves 50–70% of bandwidth, and relieves Python GC pressure."**

---

## 🧭 Table of Contents
1. [Core Concept & Benefits](#1-core-concept--benefits)
2. [Wire Format ($tabular: true)](#2-wire-format-tabular-true)
3. [Server-Side Usage (Python)](#3-server-side-usage-python)
   * [pack_tabular](#pack_tabular)
   * [Direct SQL Tuple Optimization](#direct-sql-tuple-optimization)
   * [The @tabular_response Decorator](#the-tabular_response-decorator)
4. [Client-Side Transparency (TypeScript / wsrpc.ts)](#4-client-side-transparency-typescript--wsrpcts)
5. [Project Rules & Best Practices](#5-project-rules--best-practices)

---

## 1. Core Concept & Benefits

When modern web apps query collections of entities (forum topics, catalog items, table rows, user lists), traditional JSON serializes each row as a standalone key-value dictionary:

```json
[
  {"id": "1", "title": "Topic A", "views": 42},
  {"id": "2", "title": "Topic B", "views": 10}
]
```

### Why This Hurts Performance:
1. **Garbage Collection (GC) Overhead**: Creating 1,000 dicts per request consumes excessive RAM and spikes CPU pause times during GC cycles.
2. **Network Inefficiency**: Over 50% of the JSON string consists of repeated field keys (`"id"`, `"title"`, `"views"`).
3. **Serialization Cost**: Python's JSON encoder must parse each dictionary's keys independently.

### The Solution:
Tabular payload compression separates the schema from the data:
* Schema names are declared **once** in `"fields"`.
* Record values are sent as an array of rows in `"rows"`.
* The frontend transport layer unfolds rows back into objects transparently.

---

## 2. Wire Format ($tabular: true)

```json
{
  "$tabular": true,
  "fields": ["id", "title", "views"],
  "rows": [
    ["1", "Topic A", 42],
    ["2", "Topic B", 10]
  ]
}
```

* **`$tabular`**: Marker flag (`boolean`).
* **`fields`**: Ordered array of property names (`string[]`).
* **`rows`**: Array of arrays representing record values in column order (`any[][]`).

---

## 3. Server-Side Usage (Python)

All tabular helpers reside in `app.system.tabular`:

### `pack_tabular`
```python
from app.system.tabular import pack_tabular

@rpc_method("forum.get_topics")
async def get_topics(session, params):
    topics = await fetch_topics()
    return pack_tabular(topics)
```

### Direct SQL Tuple Optimization (Zero Dicts)
To completely bypass Python dictionary allocation, pass SQL cursor tuples directly:
```python
@rpc_method("logs.get_recent")
async def get_recent_logs(session, params):
    async with db.execute("SELECT id, level, message, timestamp FROM logs") as cursor:
        rows = await cursor.fetchall()  # List of raw tuples
        return pack_tabular(rows, fields=["id", "level", "message", "timestamp"])
```

### The `@tabular_response` Decorator
```python
from app.system.tabular import tabular_response

@rpc_method("admin.list_users")
@tabular_response()
async def list_users(session, params):
    return await query_users()
```

---

## 4. Client-Side Transparency (TypeScript / wsrpc.ts)

The client network transport automatically unpacks `$tabular` payloads upon receipt:
* Root RPC results
* Streaming chunks (`stream: true`)
* Server-side push notifications
* Nested fields within response objects

Developers interact with plain objects:
```typescript
const topics = await wsrpc.call('forum.get_topics');
topics.forEach(t => console.log(t.title, t.views));
```

---

## 5. Project Rules & Best Practices

1. **Mandatory for Collections**: If an RPC method can return $>1$ record, it **must** return `$tabular: true`.
2. **Transparent UI**: Application and UI components never handle raw column index mapping.
3. **Tests Compatibility**: The test runner client transparently unfolds tabular responses by default (`raw=False`), while allowing `raw=True` for wire validation.
