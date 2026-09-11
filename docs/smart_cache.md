# ⚡ Smart Cache: Event-Driven Feedback Caching

Official system plugin for the `rsgi-wsrpc` framework (`plugins/smart_cache` + `client/smartCache.ts`).

> **"The server knows when data changes. The client caches everything locally and updates with 0 ms latency only when the server explicitly commands it to do so."**

---

## 🧭 Table of Contents
1. [Core Concept & Benefits](#1-core-concept--benefits)
2. [Architecture & Data Flow](#2-architecture--data-flow)
3. [Server-Side Plugin (Python)](#3-server-side-plugin-python)
   * [The @invalidates Decorator](#the-invalidates-decorator)
   * [Live Granular Deltas: patch_tag](#live-granular-deltas-patch_tag)
   * [Programmatic Invalidation: invalidate_tags](#programmatic-invalidation-invalidate_tags)
4. [Client-Side Module (TypeScript: smartCache.ts)](#4-client-side-module-typescript-smartcachets)
   * [getOrFetch (0 ms Instant Access)](#getorfetch-0-ms-instant-access)
   * [Silent Background Revalidation](#silent-background-revalidation)
   * [Component Subscription: observe](#component-subscription-observe)
5. [Reconnection Version Handshake (Sync Handshake)](#5-reconnection-version-handshake-sync-handshake)
6. [End-to-End Example: Discussion Forum](#6-end-to-end-example-discussion-forum)

---

## 1. Core Concept & Benefits

Conventional web applications are caught between two undesirable extremes:
* **Blank screens and layout shifts**: Every page transition triggers a 100–300 ms database query before rendering.
* **Blind Polling (SWR / TanStack Query)**: Thousands of clients continuously hammer endpoints every few seconds (*"anything new yet?"*), saturating databases and depleting client batteries.

**Smart Cache completely resolves both dilemmas:**
1. **0 ms Perceived Latency**: Views render synchronously from L1 RAM (or L2 IndexedDB) without network blocking.
2. **Zero Polling Traffic**: The socket remains completely silent until a mutation actually occurs on the server.
3. **100% Data Freshness**: The moment an entity mutates, the server pushes an invalidation frame or pre-calculated patch.

---

## 2. Architecture & Data Flow

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (smartCache.ts)                        │
│                                                                        │
│   1. getOrFetch() ──────► [ L1 RAM Map (0 ms) ] ───► Instant Return    │
│                                   │ (if miss)                          │
│                                   ▼                                    │
│                           [ L2 Storage (IndexedDB) ]                   │
│                                   │ (if miss)                          │
│                                   ▼                                    │
│   2. RPC Call ──────────► [ WSRPC Socket ]                             │
│                                   ▲                                    │
│   3. Push Invalidate ─────────────┤ (cache.invalidate / cache.patch)   │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │ WebSocket (JSON-RPC 2.0)
┌───────────────────────────────────┼────────────────────────────────────┐
│                        BACKEND (Python)                                │
│                                   │                                    │
│   @invalidates(tags=...) ─────────┤ 1. Increments tag version in RAM   │
│                                   │ 2. Broadcasts push to sockets      │
│   VersionRegistry ────────────────┤ Monotonic storage (RAM + SQLite)   │
│   cache.sync_check ───────────────┘ Version verification handshake     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Server-Side Plugin (Python)

### The `@invalidates` Decorator

Decorates any mutating RPC method. Supports declarative string templates with automatic variable substitution from `params` and `result`:

```python
from core.session import rpc_method
from app.system.smart_cache import invalidates

# Static and dynamic string templates:
@rpc_method("forum.create_topic")
@invalidates(tags=["forum.topics", "forum.category.{category_id}"])
async def create_topic(session, params):
    ...
    return {"id": topic.id, "category_id": category_id}

# Invalidate topic list, category, and specific topic thread:
@rpc_method("forum.create_reply")
@invalidates(tags=["forum.topics", "forum.category.{category_id}", "forum.topic.{topic_id}"])
async def create_reply(session, params):
    ...
    return {"id": reply.id, "topic_id": topic_id, "category_id": topic.category_id}

# Alternative fallback placeholders {topic_id|id}:
@rpc_method("forum.delete_topic")
@invalidates(tags=["forum.topics", "forum.category.{category_id}", "forum.topic.{topic_id|id}"])
async def delete_topic(session, params):
    ...
```

### Live Granular Deltas: `patch_tag`

For counters, likes, and chat streams, patch the client cache directly without re-querying the database:

```python
from app.system.smart_cache import patch_tag

@rpc_method("forum.like_post")
async def like_post(session, params):
    post_id = params.get("post_id")
    topic_id = params.get("topic_id")
    
    # Commit like in database...
    
    # Broadcast atomic delta patch to all open client sessions:
    await patch_tag(
        tag=f"topic:{topic_id}",
        action="inc",
        field="likes_count",
        data={"amount": 1}
    )
    return {"status": "ok"}
```

### Programmatic Invalidation: `invalidate_tags`

For out-of-band mutations (e.g. background workers, async tasks, webhooks):

```python
from app.system.smart_cache import invalidate_tags

# Invalidate orders after payment gateway webhook
await invalidate_tags(["orders.list", f"order:{order_id}"])
```

---

## 4. Client-Side Module (TypeScript: `smartCache.ts`)

### `getOrFetch` (0 ms Instant Access)

```typescript
import { smartCache } from '$lib/smartCache';
import { rpc } from '$lib/wsrpc';

// Request thread listing
const topics = await smartCache.getOrFetch(
    'forum.topics', // Unique cache key
    () => rpc.call('forum.get_topics', {}), // Fetcher on cache miss
    {
        tags: ['forum.topics'], // Associated tags
        persist: true,          // Persist in IndexedDB across reloads
        ttlSec: 3600            // Fallback safety TTL
    }
);
```

### Component Subscription: `observe`

Automatically update mounted components when server signals arrive:

```typescript
import { onDestroy } from 'svelte';
import { smartCache } from '$lib/smartCache';

let topics = [];

// Subscribe to reactive key updates
const unsubscribe = smartCache.observe('forum.topics', (data) => {
    topics = data;
});

onDestroy(unsubscribe);
```

---

## 5. Reconnection Version Handshake (Sync Handshake)

When a client resumes connectivity after being offline:
1. `smartCache` aggregates a version manifest of stored tags:
   `{"forum.topics": 105, "profile": 12}`.
2. Invokes `cache.sync_check`.
3. The server compares versions and flags **only tags that actually mutated**.
4. The client refetches only the active views whose data changed. If nothing changed, zero payload bytes are transferred!

---

## 6. End-to-End Example: Discussion Forum

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { smartCache } from '$lib/smartCache';
    import { rpc } from '$lib/wsrpc';

    let topics = [];
    let unobserve;

    onMount(async () => {
        // Instant synchronous render (0 ms)
        topics = await smartCache.getOrFetch(
            'forum.topics',
            () => rpc.call('forum.get_topics'),
            { tags: ['forum.topics'] }
        );

        // Subscribe to live invalidation and patches
        unobserve = smartCache.observe('forum.topics', (freshTopics) => {
            topics = freshTopics;
        });
    });

    onDestroy(() => {
        if (unobserve) unobserve();
    });

    async function addTopic(title: string) {
        await rpc.call('forum.create_topic', { title });
        // No manual reload needed! The server invalidates 'forum.topics'
        // and smartCache updates the UI automatically!
    }
</script>
```
