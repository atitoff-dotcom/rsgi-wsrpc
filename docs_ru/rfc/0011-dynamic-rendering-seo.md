# RFC 0011: Подсистема Dynamic Rendering, Sitemap, OpenGraph и IndexNow (`plugins.seo`)

* **Номер RFC:** 0011
* **Название:** Подсистема Dynamic Rendering, Sitemap, OpenGraph и IndexNow (`plugins.seo`)
* **Статус:** ✅ Принят и реализован (rsgi-wsrpc v0.3.0)
* **Автор:** Архитектурная команда
* **Дата:** Октябрь 2026

---

## 🧭 Содержание
1. [Краткое резюме](#1-краткое-резюме)
2. [Мотивация и проблематика](#2-мотивация-и-проблематика)
3. [Ключевые архитектурные принципы](#3-ключевые-архитектурные-принципы)
4. [Детальная спецификация компонентов](#4-детальная-спецификация-компонентов)
   * [4.1. Детектор ботов (`detector.py`)](#41-детектор-ботов-detectorpy)
   * [4.2. Схемы данных и семантический генератор HTML (`schemas.py`, `renderer.py`)](#42-схемы-данных-и-семантический-генератор-html-schemaspy-rendererpy)
   * [4.3. Параметризованный диспетчер маршрутов (`router.py`)](#43-параметризованный-диспетчер-маршрутов-routerpy)
   * [4.4. Генератор карты сайта с TTL-кэшированием (`sitemap.py`)](#44-генератор-карты-сайта-с-ttl-кэшированием-sitemappy)
   * [4.5. Асинхронный протокол IndexNow (`indexnow.py`)](#45-асинхронный-протокол-indexnow-indexnowpy)
   * [4.6. Базовые утилиты ядра (`rsgi_wsrpc.core.http`)](#46-базовые-утилиты-ядра-rsgi_wsrpccorehttp)
5. [Пример интеграции в приложение](#5-пример-интеграции-в-приложение)
6. [Производительность и безопасность](#6-производительность-и-безопасность)

---

## 1. Краткое резюме

Настоящий RFC специфицирует официальный плагин **`rsgi_wsrpc.plugins.seo`** для фреймворка `rsgi-wsrpc`. 

Плагин решает фундаментальную проблему индексации современных реактивных веб-приложений (SPA/PWA) на базе WebSocket и RSGI через архитектурный паттерн **Dynamic Rendering (гибридный рендеринг)**:
* **Для обычных пользователей:** сервер отдает статический легковесный SPA `index.html` и устанавливает высокоскоростное WebSocket-соединение WSRPC (JSON-RPC 2.0).
* **Для поисковых роботов, соцсетей и ИИ-краулеров:** сервер прозрачно перехватывает GET-запрос и генерирует за доли миллисекунды чистый семантический HTML с полным набором метатегов OpenGraph, Twitter Cards и микроразметкой Schema.org JSON-LD.
* **Карта сайта (`sitemap.xml`):** модульный реестр провайдеров ссылок (`@register_sitemap_provider`) с поддержкой TTL-кэширования в памяти и ручной инвалидацией.
* **Мгновенная индексация (IndexNow):** асинхронные фоновые уведомления поисковых систем (Яндекс, Bing) и раздача текстового ключа верификации.

---

## 2. Мотивация и проблематика

SPA-приложения на базе WebSockets сталкиваются с тремя ограничениями традиционной веб-индексации:

1. **Поисковые краулеры не работают с WebSockets:**
   * Ни один современный поисковый робот (Googlebot, Яндекс, Bing, Baidu) не открывает постоянные WebSocket-соединения для получения данных.
   * Тяжелый JavaScript-бандл часто приводит к таймаутам рендеринга на стороне поисковика («Googlebot deferred JS rendering»), что выбрасывает страницы из поисковой выдачи или понижает их рейтинг.
2. **Превью в соцсетях и мессенджерах (OpenGraph):**
   * Боты Telegram, VK, Twitter/X, Discord, WhatsApp и Slack парсят **только первый HTTP-ответ** и никогда не запускают клиентский JS. При шаринге ссылки без серверного HTML пользователь видит пустое превью без картинки, заголовка и описания.
3. **ИИ-поисковики нового поколения:**
   * Краулеры Perplexity, ChatGPT Search, ClaudeBot и Applebot индексируют чистый текст и структурированные данные Schema.org.

**Традиционные решения и их недостатки:**
* *Server-Side Rendering (SSR) через Node.js:* чудовищный оверхед по памяти, сложный стек поддержки двух сред исполнения (Python + Node.js) и усложнение деплоя.
* *Headless Chrome (Prerender/Puppeteer):* задержки от 1 до 5 секунд на каждый запрос бота, нестабильность и утечки памяти браузерных процессов.

`plugins.seo` решает задачу на чистом Python внутри того же воркера Granian с нулевыми накладными расходами памяти и временем ответа **менее 2 миллисекунд**.

---

## 3. Ключевые архитектурные принципы

1. **Zero External Dependencies:** Полное отсутствие сторонних шаблонизаторов (без Jinja2) и HTTP-клиентов (без httpx/requests/aiohttp). Вся кодовая база опирается исключительно на стандартную библиотеку Python 3.11+ и встроенный `orjson`.
2. **Zero Overhead for Humans:** Обычные пользователи продолжают мгновенно получать закэшированный SPA `index.html`. Никакого серверного рендеринга для браузеров не происходит.
3. **Parameterized Dynamic Routes:** Простой декларативный синтаксис `@bot_page("/path/{param:type}")` с автоматической валидацией и приведением типов (`int`, `str`, `float`, `uuid`).
4. **TTL In-Memory Cache:** Тяжелые операции (генерация sitemap на тысячи URL) кэшируются в памяти с настраиваемым TTL и методом принудительного сброса.

---

## 4. Детальная спецификация компонентов

### 4.1. Детектор ботов (`detector.py`)

Функция `is_bot(scope_or_ua)` проверяет входящий запрос по единому скомпилированному регистронезависимому регулярному выражению:
* **Поисковые роботы:** `googlebot`, `yandex` (включая специализированные `yandeximages`, `yandexvideo`), `bingbot`, `baiduspider`, `duckduckbot`, `yahoo! slurp`, `mail.ru_bot`, `ecosia`.
* **Мессенджеры и соцсети:** `telegrambot`, `vkshare`, `twitterbot`, `facebookexternalhit`, `whatsapp`, `discordbot`, `slackbot`, `linkedinbot`, `pinterest`, `skypeuripreview`, `viber`.
* **ИИ-краулеры:** `oai-searchbot`, `chatgpt-user`, `gptbot`, `perplexitybot`, `claudebot`, `applebot-extended`, `ccbot`.

Функция универсальна: принимает как строку `User-Agent`, так и объект RSGI `scope` или словарь.

### 4.2. Схемы данных и семантический генератор HTML (`schemas.py`, `renderer.py`)

Датакласс `SeoPageData`:
```python
@dataclass
class SeoPageData:
    title: str
    description: str = ""
    canonical_url: Optional[str] = None
    og_image: Optional[str] = None
    og_type: str = "website"              # "website", "article", "profile"
    schema_type: str = "WebPage"          # "Article", "BreadcrumbList", etc.
    schema_data: Optional[Dict[str, Any]] = None
    body_html: str = ""                   # Семантический контент (h1, p, article)
    lang: str = "ru"
    published_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    author: Optional[str] = None
    breadcrumbs: Optional[List[Tuple[str, str]]] = None  # [("Главная", "/"), ("Статьи", "/articles")]
    robots: str = "index, follow"
```

Модуль `renderer.py` компилирует валидный HTML5-документ:
* Автоматическое экранирование атрибутов через `html.escape(..., quote=True)` для защиты от XSS.
* Генерация метатегов OpenGraph и Twitter Cards (`summary_large_image` при наличии картинки).
* Формирование валидного блока `<script type="application/ld+json">` через `orjson.dumps()`. Если переданы `breadcrumbs`, они автоматически включаются в JSON-LD в формате `BreadcrumbList`.
* Тело `<body>` включает визуальную навигацию по крошкам и семантический блок `<main class="seo-content">`.

### 4.3. Параметризованный диспетчер маршрутов (`router.py`)

Декоратор `@bot_page` регистрирует маршруты для ботов:
```python
@bot_page("/forum/{topic_id:int}/topic/{slug:str}")
async def get_topic_seo(topic_id: int, slug: str) -> Optional[SeoPageData]:
    ...
```

* Шаблоны путей преобразуются в регулярные выражения один раз при инициализации.
* Функция `handle_bot_http(scope, proto) -> bool`:
  1. Проверяет метод (обрабатываются только `GET` и `HEAD`).
  2. Проверяет `is_bot(scope)` (также поддерживается флаг отладки `?bot=1` для ручного тестирования из браузера).
  3. Если совпал зарегистрированный маршрут:
     * Вызывает хендлер с типизированными аргументами (`int`, `str`, `float`, `UUID`).
     * Если возвращен `None`: отдает чистый `404 Not Found` с тегом `<meta name="robots" content="noindex, nofollow">`.
     * Если возвращен `SeoPageData`: рендерит HTML и отдает `200 OK` с заголовком `x-rendered-for: bot`.
     * Возвращает `True` (запрос полностью обработан).
  4. Если запрос от обычного человека или маршрут не зарегистрирован — возвращает `False`.

### 4.4. Генератор карты сайта с TTL-кэшированием (`sitemap.py`)

* Декоратор `@register_sitemap_provider` подключает функции-провайдеры (синхронные или асинхронные):
  ```python
  @register_sitemap_provider
  async def provide_articles():
      return [{"loc": "/articles/1", "lastmod": datetime.now(), "changefreq": "daily", "priority": 0.8}]
  ```
* Автоматически регистрирует маршрут `@http_route("/sitemap.xml", ["GET"])`.
* Генерирует XML в стандарте `http://www.sitemaps.org/schemas/sitemap/0.9`.
* Кэширует результат в оперативной памяти согласно `sitemap_ttl` (по умолчанию 3600 сек).
* Функция `invalidate_sitemap_cache()` позволяет мгновенно сбросить кэш (например, по сигналу шины событий).

### 4.5. Асинхронный протокол IndexNow (`indexnow.py`)

* Функция `notify_indexnow(urls: List[str])`:
  * Запускает фоновую задачу (`asyncio.create_task`), возвращая управление вызывающему коду мгновенно.
  * Выполняет отправку JSON-пакета на эндпоинты `https://api.indexnow.org/indexnow` и `https://yandex.com/indexnow`.
  * Использует стандартную библиотеку `urllib.request` в пуле потоков через `asyncio.to_thread`.
* Автоматическая отдача проверочного файла: `@http_route(f"/{key}.txt", ["GET"])` отдает текстовый ключ верификации.

### 4.6. Базовые утилиты ядра (`rsgi_wsrpc.core.http`)

Для работы с RSGI HTTP-запросами в ядре реализован модуль [rsgi_wsrpc.core.http](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/http.py):
* `extract_header(scope, header_name, default=None)`: надежное извлечение заголовка независимо от регистра из объектов Granian Headers, словарей и списков байтовых кортежей.
* `extract_query_params(scope)`: быстрое декодирование строки запроса в словарь.

---

## 5. Пример интеграции в приложение

```python
from rsgi_wsrpc import http_route, HTTP_ROUTES, configure
from rsgi_wsrpc.plugins.seo import (
    configure_seo, bot_page, register_sitemap_provider,
    handle_bot_http, notify_indexnow, SeoPageData
)

# 1. Конфигурация
configure_seo(
    site_url="https://example.com",
    site_name="Мой Реактивный Проект",
    indexnow_key="my-key-abc12345",
    sitemap_ttl=3600,
)

# 2. Описание бот-страниц
@bot_page("/articles/{slug}")
async def article_view(slug: str):
    article = await db.get_article(slug)
    if not article:
        return None
    return SeoPageData(
        title=article.title,
        description=article.summary,
        body_html=f"<h1>{article.title}</h1><article>{article.html}</article>",
        og_image=article.cover_url,
        schema_type="Article",
        breadcrumbs=[("Главная", "/"), ("Статьи", "/articles")],
    )

# 3. Провайдер карты сайта
@register_sitemap_provider
async def articles_sitemap():
    items = await db.get_all_slugs()
    return [{"loc": f"/articles/{item.slug}", "lastmod": item.updated_at} for item in items]

# 4. Хук публикации
async def on_new_article(slug: str):
    notify_indexnow([f"https://example.com/articles/{slug}"])

# 5. Главный диспетчер RSGI
async def app(scope, proto):
    if scope.proto == "http":
        # Перехват для ботов (Dynamic Rendering)
        if await handle_bot_http(scope, proto):
            return

        # Стандартные HTTP роуты (/sitemap.xml, /<key>.txt и др.)
        for route_path, methods, handler in HTTP_ROUTES:
            if scope.path == route_path and scope.method in methods:
                await handler(scope, proto)
                return

        # Живые пользователи получают SPA index.html
        proto.response_str(200, [("content-type", "text/html; charset=utf-8")], SPA_INDEX_HTML)
        return
```

---

## 6. Производительность и безопасность

1. **Безопасность XSS:** Метатеги принудительно экранируются через `html.escape`. JSON-LD генерируется через безопасный энкодер `orjson`, предотвращающий разрыв тега `<script>`.
2. **Изоляция сбоев:** Ошибки сети при обращении к эндпоинтам IndexNow обособлены в фоновой задаче и логируются в предупреждения, не затрагивая основной поток приложения.
3. **Защита от сканирования параметров:** Невалидные значения параметров (например, строка вместо `{id:int}`) не приводят к `ValueError` в хендлере, а отсекаются на уровне регулярного выражения роутера.
