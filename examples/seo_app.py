# -*- coding: utf-8 -*-
"""
Пример использования плагина rsgi_wsrpc.plugins.seo.
Демонстрирует:
1. Dynamic Rendering для поисковых ботов и соцсетей (@bot_page).
2. Автоматическую генерацию карты сайта (@register_sitemap_provider -> /sitemap.xml).
3. Интеграцию с протоколом IndexNow (notify_indexnow).
"""

import asyncio
from datetime import datetime
from typing import Optional

from rsgi_wsrpc import http_route, HTTP_ROUTES, logger
from rsgi_wsrpc.plugins.seo import (
    SeoPageData,
    bot_page,
    configure_seo,
    handle_bot_http,
    notify_indexnow,
    register_sitemap_provider,
)

# 1. Базовая настройка SEO плагина
configure_seo(
    site_url="https://example.com",
    site_name="Мой крутой SPA-проект",
    indexnow_key="my-secret-indexnow-key-12345",
    default_lang="ru",
    sitemap_ttl=1800,
)

# Фейковая база данных для демонстрации
ARTICLES_DB = {
    "hello-world": {
        "title": "Привет, Мир WSRPC!",
        "summary": "Первая статья о реактивном фреймворке rsgi-wsrpc.",
        "content": "<p>Это полный текст статьи. Боты увидят этот семантический HTML без выполнения JS!</p>",
        "cover": "https://example.com/images/hello.png",
        "author": "Алексей",
        "created_at": datetime(2026, 10, 1, 10, 0),
    },
    "seo-optimization": {
        "title": "Dynamic Rendering в SPA",
        "summary": "Как подружить Single Page Applications с поисковыми ботами.",
        "content": "<p>Боты получают статический HTML с OpenGraph и JSON-LD, а браузеры — сокеты!</p>",
        "cover": "https://example.com/images/seo.png",
        "author": "Разработчик",
        "created_at": datetime(2026, 10, 2, 14, 30),
    },
}


# 2. Рендеринг для ботов (Яндекс, Googlebot, Telegram, Discord, GPTBot)
@bot_page("/articles/{slug}")
async def article_bot_view(slug: str) -> Optional[SeoPageData]:
    article = ARTICLES_DB.get(slug)
    if not article:
        return None  # Отдаст чистый 404 HTML для краулера

    return SeoPageData(
        title=article["title"],
        description=article["summary"],
        og_image=article["cover"],
        og_type="article",
        schema_type="Article",
        author=article["author"],
        published_time=article["created_at"],
        breadcrumbs=[("Главная", "/"), ("Статьи", "/articles"), (article["title"], f"/articles/{slug}")],
        body_html=f"<h1>{article['title']}</h1><article>{article['content']}</article>",
    )


# 3. Провайдер карты сайта (sitemap.xml)
@register_sitemap_provider
async def articles_sitemap():
    return [
        {
            "loc": f"/articles/{slug}",
            "lastmod": data["created_at"],
            "changefreq": "weekly",
            "priority": 0.8,
        }
        for slug, data in ARTICLES_DB.items()
    ]


# 4. Уведомление поисковых систем при публикации новой статьи
async def publish_article(slug: str, title: str, summary: str, content: str):
    ARTICLES_DB[slug] = {
        "title": title,
        "summary": summary,
        "content": content,
        "cover": None,
        "author": "Admin",
        "created_at": datetime.now(),
    }
    # Фоновое уведомление Яндекса и Bing через IndexNow
    notify_indexnow([f"https://example.com/articles/{slug}"])


# 5. Главный RSGI Application Handler
async def app(scope, proto):
    if scope.proto == "http":
        # Шаг А: Проверяем, не бот ли это (Dynamic Rendering перехватчик)
        if await handle_bot_http(scope, proto):
            return

        # Шаг Б: Проверяем стандартные HTTP-роуты (включая /sitemap.xml и /<key>.txt)
        for route_path, methods, handler in HTTP_ROUTES:
            if scope.path == route_path and scope.method in methods:
                await handler(scope, proto)
                return

        # Шаг В: Обычные живые пользователи получают статический SPA index.html
        proto.response_str(
            status=200,
            headers=[("content-type", "text/html; charset=utf-8")],
            body="""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>rsgi-wsrpc SEO Showcase</title>
  <style>
    body { font-family: system-ui, -apple-system, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px; margin: 0; line-height: 1.6; }
    .card { background: #1e293b; border-radius: 12px; padding: 24px; margin-bottom: 24px; border: 1px solid #334155; max-width: 800px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.3); }
    h1 { color: #38bdf8; margin-top: 0; }
    h2 { color: #818cf8; font-size: 1.25rem; }
    a.btn { display: inline-block; background: #0284c7; color: white; padding: 8px 16px; border-radius: 6px; text-decoration: none; margin-right: 10px; margin-top: 8px; font-weight: 500; }
    a.btn:hover { background: #0369a1; }
    a.btn-bot { background: #10b981; }
    a.btn-bot:hover { background: #059669; }
    code { background: #334155; padding: 2px 6px; border-radius: 4px; font-family: monospace; }
    .badge { background: #38bdf8; color: #0f172a; font-size: 0.75rem; font-weight: bold; padding: 2px 8px; border-radius: 9999px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🚀 rsgi-wsrpc &bull; Dynamic Rendering Showcase</h1>
    <p>Вы открыли страницу как <strong>обычный пользователь (браузер)</strong>. Вам отдается этот клиентский интерфейс, готовый для инициализации WebSockets (JSON-RPC 2.0).</p>
  </div>

  <div class="card">
    <h2>🧪 Тестирование Dynamic Rendering (версия для ботов)</h2>
    <p>Боты (Googlebot, Яндекс, Telegram, Discord, GPTBot) при запросе тех же URL прозрачно получают семантический HTML со всеми метатегами (OpenGraph, Twitter Cards, Schema.org JSON-LD).</p>
    
    <p><strong>Статья 1:</strong> Привет, Мир WSRPC!</p>
    <a class="btn" href="/articles/hello-world">Обычный переход (SPA)</a>
    <a class="btn btn-bot" href="/articles/hello-world?bot=1" target="_blank">🤖 Как видит бот (?bot=1)</a>

    <div style="margin-top: 20px;"></div>
    <p><strong>Статья 2:</strong> Dynamic Rendering в SPA</p>
    <a class="btn" href="/articles/seo-optimization">Обычный переход (SPA)</a>
    <a class="btn btn-bot" href="/articles/seo-optimization?bot=1" target="_blank">🤖 Как видит бот (?bot=1)</a>
  </div>

  <div class="card">
    <h2>🗺️ Карта сайта и IndexNow</h2>
    <p>Автоматически сгенерированная карта сайта и проверочный ключ:</p>
    <a class="btn" href="/sitemap.xml" target="_blank">📄 /sitemap.xml</a>
    <a class="btn" href="/my-secret-indexnow-key-12345.txt" target="_blank">🔑 Ключ IndexNow</a>
  </div>
</body>
</html>"""
        )
        return

    if scope.proto == "websocket":
        ws = await proto.accept()
        # Стандартная обработка WSRPC сессии...
        pass


if __name__ == "__main__":
    from granian import Granian
    host = "127.0.0.1"
    port = 8080

    print("=" * 65)
    print(" 🚀 rsgi-wsrpc SEO Showcase Server")
    print(f" 🌐 Web UI:         http://{host}:{port}/")
    print(f" 🤖 Bot View Demo:  http://{host}:{port}/articles/hello-world?bot=1")
    print(f" 🗺️  Sitemap:        http://{host}:{port}/sitemap.xml")
    print(f" 🔑 IndexNow Key:   http://{host}:{port}/my-secret-indexnow-key-12345.txt")
    print("=" * 65)

    Granian("examples.seo_app:app", address=host, port=port, interface="rsgi").serve()

