# RFC 0011: Dynamic Rendering, Sitemap, OpenGraph and IndexNow Subsystem (`plugins.seo`)

* **RFC Number:** 0011
* **Title:** Dynamic Rendering, Sitemap, OpenGraph and IndexNow Subsystem (`plugins.seo`)
* **Status:** ✅ Accepted & Enhanced (rsgi-wsrpc v0.3.2)
* **Author:** Architecture Team
* **Date:** October 2026

---

## 🧭 Table of Contents
1. [Summary](#1-summary)
2. [Motivation & Problem Statement](#2-motivation--problem-statement)
3. [Key Architectural Principles](#3-key-architectural-principles)
4. [Component Specifications](#4-component-specifications)
   * [4.1. Hybrid Two-Layer Bot Detector (`detector.py`)](#41-hybrid-two-layer-bot-detector-detectorpy)
   * [4.2. Data Schemas, HtmlBuilder & HTML Generator (`schemas.py`, `renderer.py`)](#42-data-schemas-htmlbuilder--html-generator-schemaspy-rendererpy)
   * [4.3. Parameterized Route Dispatcher (`router.py`)](#43-parameterized-route-dispatcher-routerpy)
   * [4.4. Sitemap Generator & Pagination (`sitemap.py`)](#44-sitemap-generator--pagination-sitemappy)
   * [4.5. Asynchronous IndexNow Protocol & File Batcher (`indexnow.py`)](#45-asynchronous-indexnow-protocol--file-batcher-indexnowpy)
   * [4.6. Core HTTP Request Utilities (`rsgi_wsrpc.core.http`)](#46-core-http-request-utilities-rsgi_wsrpccorehttp)
5. [End-to-End Application Example](#5-end-to-end-application-example)
6. [Security & Performance](#6-security--performance)

---

## 1. Summary

This RFC specifies the official **`rsgi_wsrpc.plugins.seo`** plugin for the `rsgi-wsrpc` framework.

The plugin solves the fundamental indexing and preview problems of modern WebSocket-based Single Page Applications (SPA/PWA) via the **Dynamic Rendering** architectural pattern:
* **For real human users:** The server serves the lightweight static SPA `index.html` and initiates high-speed bidirectional WSRPC (JSON-RPC 2.0) sessions.
* **For search engine crawlers, social bots, and AI agents:** The server transparently intercepts the HTTP GET request and generates semantic HTML with full OpenGraph, Twitter Cards, and Schema.org JSON-LD structured data in less than 2 milliseconds.
* **Sitemap (`sitemap.xml`):** Modular URL provider registry (`@register_sitemap_provider`) with in-memory TTL caching, automatic `<sitemapindex>` generation and chunk pagination for > 50,000 URLs.
* **Resilient Instant Indexing (IndexNow):** Persistent disk queue buffer, multi-worker atomic batching up to 10,000 URLs per request, and search engine rate-limit awareness.

---

## 2. Motivation & Problem Statement

WebSocket-centric SPA architectures face three major limitations:
1. **Search Crawlers Don't Use WebSockets:** Googlebot, YandexBot, Bingbot, and Baidu do not maintain WebSockets. Heavy client JS bundles frequently lead to timeout issues and indexing drops.
2. **Social Media & Messenger Previews (OpenGraph):** Telegram, VK, Twitter, WhatsApp, Discord, and Slack bots only inspect the first HTTP response and never execute client-side JavaScript.
3. **AI Search Engines:** Crawlers like Perplexity, ChatGPT Search, ClaudeBot, and Applebot index structured Schema.org markup and semantic server-rendered text.

`plugins.seo` resolves this with zero external template dependencies on pure Python within the same Granian RSGI worker process.

---

## 3. Key Architectural Principles

* **Zero External Dependencies:** No template engines (Jinja2) or heavy HTTP clients (httpx/requests). Built on Python standard library + `orjson`.
* **Zero Latency Overhead for Humans:** Real users bypass bot rendering completely.
* **Parameterized Routing:** `@bot_page("/path/{param:type}")` with automatic type conversion (`int`, `str`, `float`, `uuid`).
* **TTL In-Memory Caching & Resilient Queue:** Heavy operations like sitemap building are cached with configurable TTL, and IndexNow notifications are queued persistently on disk.

---

## 4. Component Specifications

### 4.1. Hybrid Two-Layer Bot Detector (`detector.py`)
`is_bot(scope_or_ua)` implements a 3-phase hybrid detection strategy:
* **Developer Customization:** Priority evaluation via `custom_detector` callback and `extra_bot_patterns: List[str]`.
* **Phase 1 (Known Bots, Social Previews & AI Agents):** Googlebot, YandexBot, Bingbot, Baiduspider, DuckDuckBot, Yahoo! Slurp, Mail.ru_bot, Ecosia, TelegramBot, vkShare, Twitterbot, facebookexternalhit, WhatsApp, Discordbot, Slackbot, LinkedInBot, Pinterest, Skype, Viber, OAI-SearchBot, ChatGPT-User, GPTBot, PerplexityBot, ClaudeBot, Applebot, ByteSpider, CCBot, Cohere, Diffbot, Amazonbot.
* **Phase 1.5 (CLI / Scrapers):** `curl`, `wget`, `python-requests`, `aiohttp`, `httpx`, `urllib`, `go-http-client`, `node-fetch`, `axios`, `scrapy`.
* **Phase 2 (Inverted Browser Engine Whitelist):** Requires Gecko, WebKit, Blink, or Trident engines. Clients lacking browser engines receive semantic HTML. Mobile In-App WebViews retain WebKit/Blink engines and receive the SPA.

### 4.2. Data Schemas, HtmlBuilder & HTML Generator (`schemas.py`, `renderer.py`)
* `SeoPageData` defines the data contract (title, description, canonical_url, og_image, og_type, schema_type, schema_data, body_html, lang, published_time, modified_time, author, breadcrumbs, robots).
* `HtmlBuilder`: fluent, zero-dependency semantic HTML builder with automatic HTML escaping to prevent XSS.
* `renderer.py` generates valid HTML5 documents with XSS-safe escaping and JSON-LD serialization via `orjson`.

### 4.3. Parameterized Route Dispatcher (`router.py`)
`@bot_page` registers bot views. `handle_bot_http(scope, proto)` intercepts GET/HEAD requests from bots (and `?bot=1` debug requests), returning 200 OK with `x-rendered-for: bot` or 404 Not Found if the handler returns `None`.

### 4.4. Sitemap Generator & Pagination (`sitemap.py`)
`@register_sitemap_provider` registers async/sync URL providers:
* If total URLs $\le 50,000$: standard `<urlset>` is served on `/sitemap.xml`.
* If total URLs $> 50,000$: `/sitemap.xml` automatically transitions to `<sitemapindex>` referencing child chunk files `/sitemap-1.xml`, `/sitemap-2.xml`...
* Provides `handle_sitemap_http(scope, proto)` and automatic registration in `HTTP_ROUTES`.

### 4.5. Asynchronous IndexNow Protocol & File Batcher (`indexnow.py`)
* `notify_indexnow(urls)` appends URLs to `data/indexnow_queue.txt` atomically (< 0.05 ms). Survives process restarts.
* Worker-safe atomic handoff via `os.replace` avoids duplicate network requests across multiple Granian workers.
* Periodic flusher drains the file every 30 minutes (configurable), deduplicates URLs, and dispatches batches of up to 10,000 URLs to Bing and Yandex with HTTP 429 rate limit backoff.
* Automatically exposes `GET /<key>.txt` for ownership verification.

### 4.6. Core HTTP Request Utilities (`rsgi_wsrpc.core.http`)
`extract_header` and `extract_query_params` provide robust, case-insensitive inspection of Granian RSGI scopes.


---

## 5. End-to-End Application Example

See [examples/seo_app.py](file:///home/alex/rsgi-wsrpc/examples/seo_app.py) for a complete working showcase.
