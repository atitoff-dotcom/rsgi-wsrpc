# -*- coding: utf-8 -*-
"""
tests/suites/test_seo.py: Модульные тесты для плагина rsgi_wsrpc.plugins.seo.
"""

import asyncio
from datetime import datetime
from uuid import uuid4

import pytest

from rsgi_wsrpc.plugins.seo import (
    SeoPageData,
    bot_page,
    build_sitemap_xml,
    configure_seo,
    get_seo_config,
    handle_bot_http,
    invalidate_sitemap_cache,
    is_bot,
    register_indexnow_key_route,
    register_sitemap_provider,
    render_seo_page,
)
from rsgi_wsrpc.plugins.seo.router import BOT_ROUTES, BotRoute


class MockRSGIProto:
    """Мок RSGI протокола для тестирования ответов."""

    def __init__(self):
        self.status = None
        self.headers = None
        self.body = None

    def response_str(self, status: int, headers: list, body: str):
        self.status = status
        self.headers = dict(headers)
        self.body = body


# -----------------------------------------------------------------------------
# 1. Тесты детектора ботов
# -----------------------------------------------------------------------------

@pytest.mark.parametrize("user_agent,expected", [
    # Поисковые системы
    ("Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", True),
    ("Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)", True),
    ("Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)", True),
    ("Baiduspider+(+http://www.baidu.com/search/spider.htm)", True),
    ("DuckDuckBot/1.0; (+http://duckduckgo.com/duckduckbot.html)", True),
    # Соцсети и мессенджеры
    ("TelegramBot (like TwitterBot)", True),
    ("vkShare; +http://vk.com/dev/Share", True),
    ("Twitterbot/1.0", True),
    ("facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)", True),
    ("WhatsApp/2.21.12.21 A", True),
    ("Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)", True),
    # ИИ-краулеры
    ("Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)", True),
    ("Mozilla/5.0 (compatible; ClaudeBot/1.0; +claudebot@anthropic.com)", True),
    ("Mozilla/5.0 (compatible; PerplexityBot/1.0; +https://perplexity.ai/bot)", True),
    ("Applebot-Extended/0.1", True),
    # Обычные пользовательские браузеры (не боты)
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", False),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15", False),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148", False),
    ("", False),
    (None, False),
])
def test_is_bot_user_agents(user_agent, expected):
    assert is_bot(user_agent) is expected


def test_is_bot_from_scope():
    scope_bot = {"headers": [(b"user-agent", b"Googlebot/2.1")]}
    scope_user = {"headers": [(b"user-agent", b"Mozilla/5.0 Chrome")]}
    scope_empty = {"headers": []}

    assert is_bot(scope_bot) is True
    assert is_bot(scope_user) is False
    assert is_bot(scope_empty) is False


# -----------------------------------------------------------------------------
# 2. Тесты маршрутизации и извлечения параметров
# -----------------------------------------------------------------------------

def test_bot_route_param_parsing():
    route = BotRoute("/forum/{topic_id:int}/post/{slug:str}", lambda topic_id, slug: None)

    # Успешный матчинг с типами
    params = route.match("/forum/42/post/my-first-topic")
    assert params == {"topic_id": 42, "slug": "my-first-topic"}
    assert isinstance(params["topic_id"], int)

    # Несовпадение типа (topic_id не int)
    assert route.match("/forum/abc/post/my-first-topic") is None

    # Несовпадение пути
    assert route.match("/other/path") is None


def test_bot_route_uuid_param():
    uid = uuid4()
    route = BotRoute("/items/{item_id:uuid}", lambda item_id: None)

    params = route.match(f"/items/{uid}")
    assert params == {"item_id": uid}
    assert route.match("/items/not-a-uuid") is None


def test_handle_bot_http_interceptor():
    async def _run():
        BOT_ROUTES.clear()

        @bot_page("/test-topic/{topic_id:int}")
        async def sample_view(topic_id: int):
            if topic_id == 404:
                return None
            return SeoPageData(
                title=f"Тема #{topic_id}",
                description="Описание темы",
                body_html=f"<h1>Тема {topic_id}</h1>"
            )

        proto = MockRSGIProto()

        # 1. Запрос от обычного пользователя (не бота) -> перехватчик возвращает False
        user_scope = {
            "proto": "http",
            "method": "GET",
            "path": "/test-topic/1",
            "headers": [(b"user-agent", b"Mozilla/5.0 Safari")],
        }
        handled = await handle_bot_http(user_scope, proto)
        assert handled is False
        assert proto.status is None

        # 2. Запрос от Googlebot на существующую страницу -> 200 OK, HTML
        bot_scope_200 = {
            "proto": "http",
            "method": "GET",
            "path": "/test-topic/1",
            "headers": [(b"user-agent", b"Googlebot/2.1")],
        }
        handled = await handle_bot_http(bot_scope_200, proto)
        assert handled is True
        assert proto.status == 200
        assert "text/html" in proto.headers["content-type"]
        assert "x-rendered-for" in proto.headers
        assert "Тема #1" in proto.body
        assert "<h1>Тема 1</h1>" in proto.body

        # 3. Запрос от бота на несуществующую страницу (возврат None) -> 404
        bot_scope_404 = {
            "proto": "http",
            "method": "GET",
            "path": "/test-topic/404",
            "headers": [(b"user-agent", b"TelegramBot")],
        }
        handled_404 = await handle_bot_http(bot_scope_404, proto)
        assert handled_404 is True
        assert proto.status == 404
        assert "404 Not Found" in proto.body

    asyncio.run(_run())


# -----------------------------------------------------------------------------
# 3. Тесты генерации HTML, OpenGraph, Twitter Cards и JSON-LD
# -----------------------------------------------------------------------------

def test_render_seo_page():
    now = datetime(2026, 10, 2, 12, 0, 0)
    page = SeoPageData(
        title="Тестовая статья & Гайд",
        description="Подробный разбор <тест>",
        canonical_url="https://example.com/guide",
        og_image="https://example.com/cover.jpg",
        og_type="article",
        schema_type="Article",
        author="Иван Иванов",
        published_time=now,
        breadcrumbs=[("Главная", "/"), ("Статьи", "/articles")],
        body_html="<article><p>Полезный контент</p></article>"
    )

    html_out = render_seo_page(page, current_path="/guide")

    # Проверка базовой структуры и экранирования
    assert "<!DOCTYPE html>" in html_out
    assert "<title>Тестовая статья &amp; Гайд</title>" in html_out
    assert 'meta name="description" content="Подробный разбор &lt;тест&gt;"' in html_out
    assert 'link rel="canonical" href="https://example.com/guide"' in html_out

    # OpenGraph
    assert 'meta property="og:title" content="Тестовая статья &amp; Гайд"' in html_out
    assert 'meta property="og:image" content="https://example.com/cover.jpg"' in html_out
    assert 'meta property="og:type" content="article"' in html_out
    assert 'meta property="article:author" content="Иван Иванов"' in html_out
    assert 'meta property="article:published_time" content="2026-10-02T12:00:00"' in html_out

    # Twitter Cards
    assert 'meta name="twitter:card" content="summary_large_image"' in html_out
    assert 'meta name="twitter:image" content="https://example.com/cover.jpg"' in html_out

    # Schema.org JSON-LD
    assert 'application/ld+json' in html_out
    assert '"@type": "Article"' in html_out
    assert '"author":' in html_out
    assert '"name": "Иван Иванов"' in html_out
    assert '"BreadcrumbList"' in html_out

    # Body
    assert '<article><p>Полезный контент</p></article>' in html_out
    assert '<nav aria-label="breadcrumbs"' in html_out


# -----------------------------------------------------------------------------
# 4. Тесты генерации карты сайта (sitemap.xml) и кэша
# -----------------------------------------------------------------------------

def test_sitemap_xml_generation():
    async def _run():
        invalidate_sitemap_cache()
        configure_seo(site_url="https://example.com")

        @register_sitemap_provider
        async def async_provider():
            return [
                {"loc": "/news", "changefreq": "daily", "priority": 0.9},
                {"loc": "https://example.com/static-page", "priority": 0.5},
            ]

        @register_sitemap_provider
        def sync_provider():
            return [
                {"loc": "/about", "lastmod": "2026-10-01", "changefreq": "monthly"}
            ]

        xml = await build_sitemap_xml("https://example.com")

        assert '<?xml version="1.0" encoding="UTF-8"?>' in xml
        assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in xml

        # Проверка URL и нормализации
        assert '<loc>https://example.com/news</loc>' in xml
        assert '<changefreq>daily</changefreq>' in xml
        assert '<priority>0.9</priority>' in xml

        assert '<loc>https://example.com/static-page</loc>' in xml
        assert '<priority>0.5</priority>' in xml

        assert '<loc>https://example.com/about</loc>' in xml
        assert '<lastmod>2026-10-01</lastmod>' in xml

    asyncio.run(_run())
