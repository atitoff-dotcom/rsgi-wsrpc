# RFC 0011: Dynamic Rendering, Sitemap, OpenGraph and IndexNow Subsystem (`plugins.seo`)

* **RFC Number:** 0011
* **Title:** Dynamic Rendering, Sitemap, OpenGraph and IndexNow Subsystem (`plugins.seo`)
* **Status:** ✅ Accepted & Implemented (rsgi-wsrpc v0.3.0)
* **Author:** Architecture Team
* **Date:** October 2026

---

## 🧭 Table of Contents
1. [Summary](#1-summary)
2. [Motivation & Problem Statement](#2-motivation--problem-statement)
3. [Key Architectural Principles](#3-key-architectural-principles)
4. [Component Specifications](#4-component-specifications)
   * [4.1. Bot Detector (`detector.py`)](#41-bot-detector-detectorpy)
   * [4.2. Data Schemas & HTML Generator (`schemas.py`, `renderer.py`)](#42-data-schemas--html-generator-schemaspy-rendererpy)
   * [4.3. Parameterized Route Dispatcher (`router.py`)](#43-parameterized-route-dispatcher-routerpy)
   * [4.4. Sitemap Generator with In-Memory TTL Cache (`sitemap.py`)](#44-sitemap-generator-with-in-memory-ttl-cache-sitemappy)
   * [4.5. Asynchronous IndexNow Protocol (`indexnow.py`)](#45-asynchronous-indexnow-protocol-indexnowpy)
   * [4.6. Core HTTP Request Utilities (`rsgi_wsrpc.core.http`)](#46-core-http-request-utilities-rsgi_wsrpccorehttp)
5. [End-to-End Application Example](#5-end-to-end-application-example)
6. [Security & Performance](#6-security--performance)

---

## 1. Summary

This RFC specifies the official **`rsgi_wsrpc.plugins.seo`** plugin for the `rsgi-wsrpc` framework.

The plugin solves the fundamental indexing and preview problems of modern WebSocket-based Single Page Applications (SPA/PWA) via the **Dynamic Rendering** architectural pattern:
* **For real human users:** The server serves the lightweight static SPA `index.html` and initiates high-speed bidirectional WSRPC (JSON-RPC 2.0) sessions.
* **For search engine crawlers, social bots, and AI agents:** The server transparently intercepts the HTTP GET request and generates semantic HTML with full OpenGraph, Twitter Cards, and Schema.org JSON-LD structured data in less than 2 milliseconds.
* **Sitemap (`sitemap.xml`):** Modular URL provider registry (`@register_sitemap_provider`) with in-memory TTL caching and manual invalidation.
* **Instant indexing (IndexNow):** Non-blocking background notifications to search engines (Yandex, Bing) and automatic key verification.

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
* **TTL In-Memory Caching:** Heavy operations like sitemap building are cached with configurable TTL and atomic invalidation.

---

## 4. Component Specifications

### 4.1. Bot Detector (`detector.py`)
`is_bot(scope_or_ua)` uses a precompiled, case-insensitive regular expression matching:
* **Search Engines:** Googlebot, YandexBot, Bingbot, Baiduspider, DuckDuckBot, Yahoo! Slurp, Mail.ru_bot, Ecosia.
* **Social Media & Messengers:** TelegramBot, vkShare, Twitterbot, facebookexternalhit, WhatsApp, Discordbot, Slackbot, LinkedInBot, Pinterest, Skype, Viber.
* **AI Crawlers:** OAI-SearchBot, ChatGPT-User, GPTBot, PerplexityBot, ClaudeBot, Applebot-Extended, CCBot.

### 4.2. Data Schemas & HTML Generator (`schemas.py`, `renderer.py`)
`SeoPageData` defines the data contract (title, description, canonical_url, og_image, og_type, schema_type, schema_data, body_html, lang, published_time, modified_time, author, breadcrumbs, robots).
`renderer.py` generates valid HTML5 documents with XSS-safe escaping and JSON-LD serialization via `orjson`.

### 4.3. Parameterized Route Dispatcher (`router.py`)
`@bot_page` registers bot views. `handle_bot_http(scope, proto)` intercepts GET/HEAD requests from bots (and `?bot=1` debug requests), returning 200 OK with `x-rendered-for: bot` or 404 Not Found if the handler returns `None`.

### 4.4. Sitemap Generator (`sitemap.py`)
`@register_sitemap_provider` registers async/sync URL providers. Standard XML is served on `/sitemap.xml` with in-memory TTL caching and `invalidate_sitemap_cache()`.

### 4.5. IndexNow Protocol (`indexnow.py`)
`notify_indexnow(urls)` triggers non-blocking background tasks dispatching JSON payloads to `https://api.indexnow.org/indexnow` and `https://yandex.com/indexnow` via `urllib.request` in a threadpool. Automatically exposes `GET /<key>.txt`.

### 4.6. Core HTTP Request Utilities (`rsgi_wsrpc.core.http`)
`extract_header` and `extract_query_params` provide robust, case-insensitive inspection of Granian RSGI scopes.

---

## 5. End-to-End Application Example

See [examples/seo_app.py](file:///home/alex/rsgi-wsrpc/examples/seo_app.py) for a complete working showcase.
