# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo: Официальный плагин SEO, Dynamic Rendering и Sitemap для rsgi-wsrpc.
"""

from .config import configure_seo, get_seo_config, SeoConfig
from .detector import (
    is_bot,
    BOT_USER_AGENT_PATTERN,
    CLI_SCRAPERS_PATTERN,
    BROWSER_ENGINE_PATTERN,
)
from .indexnow import (
    notify_indexnow,
    register_indexnow_key_route,
    enqueue_indexnow_urls,
    flush_indexnow_queue,
    start_indexnow_file_flusher,
    INDEXNOW_ENDPOINTS,
)
from .renderer import render_seo_page, render_404_html, HtmlBuilder
from .router import bot_page, handle_bot_http, BOT_ROUTES, BotRoute
from .schemas import SeoPageData
from .sitemap import (
    register_sitemap_provider,
    invalidate_sitemap_cache,
    collect_all_sitemap_urls,
    build_sitemap_xml,
    sitemap_xml_handler,
    sitemap_chunk_xml_handler,
    handle_sitemap_http,
)

__all__ = [
    # Конфигурация
    "configure_seo",
    "get_seo_config",
    "SeoConfig",
    # Детектор ботов
    "is_bot",
    "BOT_USER_AGENT_PATTERN",
    "CLI_SCRAPERS_PATTERN",
    "BROWSER_ENGINE_PATTERN",
    # Данные и рендерер
    "SeoPageData",
    "render_seo_page",
    "render_404_html",
    "HtmlBuilder",
    # Маршрутизация ботов
    "bot_page",
    "handle_bot_http",
    "BOT_ROUTES",
    "BotRoute",
    # Карта сайта
    "register_sitemap_provider",
    "invalidate_sitemap_cache",
    "collect_all_sitemap_urls",
    "build_sitemap_xml",
    "sitemap_xml_handler",
    "sitemap_chunk_xml_handler",
    "handle_sitemap_http",
    # IndexNow
    "notify_indexnow",
    "register_indexnow_key_route",
    "enqueue_indexnow_urls",
    "flush_indexnow_queue",
    "start_indexnow_file_flusher",
    "INDEXNOW_ENDPOINTS",
]

