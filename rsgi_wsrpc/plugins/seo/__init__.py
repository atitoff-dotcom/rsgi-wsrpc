# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo: Официальный плагин SEO, Dynamic Rendering и Sitemap для rsgi-wsrpc.
"""

from .config import configure_seo, get_seo_config, SeoConfig
from .detector import is_bot, BOT_USER_AGENT_PATTERN
from .indexnow import notify_indexnow, register_indexnow_key_route
from .renderer import render_seo_page, render_404_html
from .router import bot_page, handle_bot_http, BOT_ROUTES, BotRoute
from .schemas import SeoPageData
from .sitemap import (
    register_sitemap_provider,
    invalidate_sitemap_cache,
    build_sitemap_xml,
    sitemap_xml_handler,
)

__all__ = [
    # Конфигурация
    "configure_seo",
    "get_seo_config",
    "SeoConfig",
    # Детектор ботов
    "is_bot",
    "BOT_USER_AGENT_PATTERN",
    # Данные и рендерер
    "SeoPageData",
    "render_seo_page",
    "render_404_html",
    # Маршрутизация ботов
    "bot_page",
    "handle_bot_http",
    "BOT_ROUTES",
    "BotRoute",
    # Карта сайта
    "register_sitemap_provider",
    "invalidate_sitemap_cache",
    "build_sitemap_xml",
    "sitemap_xml_handler",
    # IndexNow
    "notify_indexnow",
    "register_indexnow_key_route",
]
