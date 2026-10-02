# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.sitemap: Генератор карты сайта (sitemap.xml) с поддержкой
реестра провайдеров, пагинации (sitemapindex / sitemap-N.xml) и TTL-кэширования.
"""

import html
import inspect
import math
import re
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Union

from rsgi_wsrpc.core.http import extract_header
from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.core.router import HTTP_ROUTES, http_route
from .config import get_seo_config

# Список зарегистрированных провайдеров URL карты сайта
SITEMAP_PROVIDERS: List[Callable] = []

# Состояние кэша: словарь { "index": str, 1: str, 2: str, ... }
_CACHED_SITEMAPS: Dict[Union[str, int], str] = {}
_CACHE_TIMESTAMP: float = 0.0

SITEMAP_PATH_RE = re.compile(r"^/sitemap(?:-(\d+))?\.xml$")


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
    global _CACHED_SITEMAPS, _CACHE_TIMESTAMP
    _CACHED_SITEMAPS.clear()
    _CACHE_TIMESTAMP = 0.0
    logger.debug("[SITEMAP] Кэш карты сайта инвалидирован.")


def _format_lastmod(val: Any) -> Optional[str]:
    """Форматирует дату для XML lastmod (YYYY-MM-DD или ISO-8601)."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, str) and val:
        return val
    return None


async def collect_all_sitemap_urls() -> List[Dict[str, Any]]:
    """Собирает полный список ссылок со всех зарегистрированных провайдеров."""
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

    return urls


def _render_urlset_xml(base_url: str, urls: List[Dict[str, Any]]) -> str:
    """Генерирует стандартный <urlset> XML документ."""
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


def _render_sitemap_index_xml(base_url: str, total_chunks: int, latest_mod: Optional[str] = None) -> str:
    """Генерирует стандартный <sitemapindex> XML документ."""
    xml_lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for i in range(1, total_chunks + 1):
        loc = f"{base_url.rstrip('/')}/sitemap-{i}.xml"
        xml_lines.append("  <sitemap>")
        xml_lines.append(f"    <loc>{html.escape(loc)}</loc>")
        if latest_mod:
            xml_lines.append(f"    <lastmod>{html.escape(latest_mod)}</lastmod>")
        xml_lines.append("  </sitemap>")

    xml_lines.append("</sitemapindex>")
    return "\n".join(xml_lines)


async def build_sitemap_xml(base_url: str, page: Optional[int] = None) -> str:
    """
    Собирает sitemap.xml.
    Если page is None:
      - если объем ссылок <= sitemap_max_urls_per_file: возвращает стандартный <urlset>
      - если ссылок больше: возвращает <sitemapindex> со ссылками на sitemap-1.xml, sitemap-2.xml ...
    Если page is int (1-indexed):
      - возвращает страницу с соответствующим срезом ссылок.
    """
    cfg = get_seo_config()
    max_urls = cfg.sitemap_max_urls_per_file
    all_urls = await collect_all_sitemap_urls()

    if page is not None:
        # Запрошена конкретная пагинированная страница (1-indexed)
        if page < 1:
            page = 1
        start_idx = (page - 1) * max_urls
        end_idx = start_idx + max_urls
        chunk_urls = all_urls[start_idx:end_idx]
        return _render_urlset_xml(base_url, chunk_urls)

    # Запрошен корень /sitemap.xml
    if len(all_urls) <= max_urls:
        return _render_urlset_xml(base_url, all_urls)

    # Превышен лимит — генерируем <sitemapindex>
    total_chunks = math.ceil(len(all_urls) / max_urls)
    
    # Ищем самую свежую дату модификации для индекса
    latest_mod = None
    for u in all_urls:
        lm = _format_lastmod(u.get("lastmod"))
        if lm and (latest_mod is None or lm > latest_mod):
            latest_mod = lm

    _ensure_chunk_routes_registered(total_chunks)
    return _render_sitemap_index_xml(base_url, total_chunks, latest_mod=latest_mod)


def _ensure_chunk_routes_registered(total_chunks: int) -> None:
    """Регистрирует маршруты /sitemap-N.xml в HTTP_ROUTES ядра."""
    existing_paths = {r[0] for r in HTTP_ROUTES}
    for p in range(1, total_chunks + 1):
        chunk_path = f"/sitemap-{p}.xml"
        if chunk_path not in existing_paths:
            def _make_handler(page_num: int):
                async def _handler(scope: Any, proto: Any) -> None:
                    await sitemap_chunk_xml_handler(scope, proto, page_num)
                return _handler
            http_route(chunk_path, ["GET"])(_make_handler(p))


@http_route("/sitemap.xml", ["GET"])
async def sitemap_xml_handler(scope: Any, proto: Any) -> None:
    """
    HTTP-обработчик /sitemap.xml с поддержкой TTL-кэширования
    и автоматическим переходом на sitemapindex.
    """
    global _CACHED_SITEMAPS, _CACHE_TIMESTAMP

    cfg = get_seo_config()
    now = time.time()

    if "index" in _CACHED_SITEMAPS and (now - _CACHE_TIMESTAMP) < cfg.sitemap_ttl:
        xml_body = _CACHED_SITEMAPS["index"]
    else:
        host = extract_header(scope, "host")
        base_url = cfg.site_url
        if host and not base_url.startswith("http"):
            base_url = f"https://{host}"

        logger.info(f"[SITEMAP] Генерация sitemap.xml для {base_url}...")
        xml_body = await build_sitemap_xml(base_url, page=None)
        _CACHED_SITEMAPS["index"] = xml_body
        _CACHE_TIMESTAMP = now

    proto.response_str(
        status=200,
        headers=[
            ("content-type", "application/xml; charset=utf-8"),
            ("cache-control", f"public, max-age={cfg.sitemap_ttl}"),
        ],
        body=xml_body
    )


async def sitemap_chunk_xml_handler(scope: Any, proto: Any, page: int) -> None:
    """
    HTTP-обработчик дочерних страниц карты сайта /sitemap-N.xml с TTL-кэшированием.
    """
    global _CACHED_SITEMAPS, _CACHE_TIMESTAMP

    cfg = get_seo_config()
    now = time.time()

    if page in _CACHED_SITEMAPS and (now - _CACHE_TIMESTAMP) < cfg.sitemap_ttl:
        xml_body = _CACHED_SITEMAPS[page]
    else:
        host = extract_header(scope, "host")
        base_url = cfg.site_url
        if host and not base_url.startswith("http"):
            base_url = f"https://{host}"

        logger.info(f"[SITEMAP] Генерация sitemap-{page}.xml для {base_url}...")
        xml_body = await build_sitemap_xml(base_url, page=page)
        _CACHED_SITEMAPS[page] = xml_body
        _CACHE_TIMESTAMP = now

    proto.response_str(
        status=200,
        headers=[
            ("content-type", "application/xml; charset=utf-8"),
            ("cache-control", f"public, max-age={cfg.sitemap_ttl}"),
        ],
        body=xml_body
    )


async def handle_sitemap_http(scope: Any, proto: Any) -> bool:
    """
    Универсальный перехватчик запросов карты сайта (/sitemap.xml, /sitemap-N.xml).
    Возвращает True, если запрос был обработан картой сайта.
    """
    method = getattr(scope, "method", None)
    if method is None and isinstance(scope, dict):
        method = scope.get("method")
    if method not in ("GET", "HEAD"):
        return False

    path = getattr(scope, "path", None)
    if path is None and isinstance(scope, dict):
        path = scope.get("path")
    if not path:
        return False

    match = SITEMAP_PATH_RE.match(path)
    if not match:
        return False

    page_str = match.group(1)
    if page_str is None:
        await sitemap_xml_handler(scope, proto)
    else:
        await sitemap_chunk_xml_handler(scope, proto, int(page_str))
    return True


__all__ = [
    "SITEMAP_PROVIDERS",
    "register_sitemap_provider",
    "invalidate_sitemap_cache",
    "collect_all_sitemap_urls",
    "build_sitemap_xml",
    "sitemap_xml_handler",
    "sitemap_chunk_xml_handler",
    "handle_sitemap_http",
]

