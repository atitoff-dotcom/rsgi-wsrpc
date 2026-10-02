# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.sitemap: Генератор карты сайта (sitemap.xml) с поддержкой
реестра провайдеров и TTL-кэширования в памяти.
"""

import html
import inspect
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Union

from rsgi_wsrpc.core.http import extract_header
from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.core.router import http_route
from .config import get_seo_config

# Список зарегистрированных провайдеров URL карты сайта
SITEMAP_PROVIDERS: List[Callable] = []

# Состояние кэша
_CACHED_SITEMAP_XML: Optional[str] = None
_CACHE_TIMESTAMP: float = 0.0


def register_sitemap_provider(func: Callable) -> Callable:
    """
    Декоратор для регистрации провайдера ссылок для sitemap.xml.
    Функция должна возвращать список словарей формата:
    [
        {
            "loc": "/articles/my-slug",
            "lastmod": datetime.now(),      # опционально
            "changefreq": "weekly",         # опционально
            "priority": 0.8                 # опционально
        }
    ]
    """
    SITEMAP_PROVIDERS.append(func)
    invalidate_sitemap_cache()
    logger.debug(f"[SITEMAP] Зарегистрирован провайдер ссылок: {func.__name__}")
    return func


def invalidate_sitemap_cache() -> None:
    """Принудительно сбрасывает закэшированный XML карты сайта."""
    global _CACHED_SITEMAP_XML, _CACHE_TIMESTAMP
    _CACHED_SITEMAP_XML = None
    _CACHE_TIMESTAMP = 0.0
    logger.debug("[SITEMAP] Кэш карты сайта инвалидирован.")


def _format_lastmod(val: Any) -> Optional[str]:
    """Форматирует дату для XML lastmod (YYYY-MM-DD или ISO-8601)."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, str) and val:
        return val
    return None


async def build_sitemap_xml(base_url: str) -> str:
    """Собирает полный sitemap.xml со всех зарегистрированных провайдеров."""
    urls: List[Dict[str, Any]] = []

    for provider in SITEMAP_PROVIDERS:
        try:
            if inspect.iscoroutinefunction(provider):
                res = await provider()
            else:
                res = provider()

            if isinstance(res, list):
                urls.extend(res)
        except Exception as e:
            logger.error(f"[SITEMAP] Ошибка при сборе URL из {provider.__name__}: {e}", exc_info=True)

    xml_lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for item in urls:
        if not isinstance(item, dict):
            continue

        raw_loc = item.get("loc", "")
        if not raw_loc:
            continue

        # Формируем абсолютный URL
        if raw_loc.startswith("http://") or raw_loc.startswith("https://"):
            loc = raw_loc
        else:
            loc = f"{base_url.rstrip('/')}/{raw_loc.lstrip('/')}"

        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{html.escape(loc)}</loc>")

        lastmod = _format_lastmod(item.get("lastmod"))
        if lastmod:
            xml_lines.append(f"    <lastmod>{html.escape(lastmod)}</lastmod>")

        changefreq = item.get("changefreq")
        if changefreq:
            xml_lines.append(f"    <changefreq>{html.escape(str(changefreq))}</changefreq>")

        priority = item.get("priority")
        if priority is not None:
            xml_lines.append(f"    <priority>{float(priority):.1f}</priority>")

        xml_lines.append("  </url>")

    xml_lines.append("</urlset>")
    return "\n".join(xml_lines)


@http_route("/sitemap.xml", ["GET"])
async def sitemap_xml_handler(scope: Any, proto: Any) -> None:
    """
    HTTP-обработчик /sitemap.xml с поддержкой TTL-кэширования.
    """
    global _CACHED_SITEMAP_XML, _CACHE_TIMESTAMP

    cfg = get_seo_config()
    now = time.time()

    # Проверяем актуальность кэша
    if _CACHED_SITEMAP_XML is not None and (now - _CACHE_TIMESTAMP) < cfg.sitemap_ttl:
        xml_body = _CACHED_SITEMAP_XML
    else:
        host = extract_header(scope, "host")
        base_url = cfg.site_url
        if host and not base_url.startswith("http"):
            base_url = f"https://{host}"

        logger.info(f"[SITEMAP] Генерация sitemap.xml для {base_url}...")
        xml_body = await build_sitemap_xml(base_url)
        _CACHED_SITEMAP_XML = xml_body
        _CACHE_TIMESTAMP = now

    proto.response_str(
        status=200,
        headers=[
            ("content-type", "application/xml; charset=utf-8"),
            ("cache-control", f"public, max-age={cfg.sitemap_ttl}"),
        ],
        body=xml_body
    )


__all__ = [
    "SITEMAP_PROVIDERS",
    "register_sitemap_provider",
    "invalidate_sitemap_cache",
    "build_sitemap_xml",
    "sitemap_xml_handler",
]
