# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.renderer: Быстрый сборщик валидного семантического HTML,
OpenGraph, Twitter Cards и Schema.org JSON-LD для поисковых ботов.
"""

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

import orjson

from .config import get_seo_config
from .schemas import SeoPageData


def _format_datetime(dt: Optional[datetime]) -> Optional[str]:
    """Форматирует дату/время в стандартный ISO-8601 формат."""
    if not dt:
        return None
    return dt.isoformat()


def render_seo_page(
    page: SeoPageData,
    current_path: str = "/",
    host: Optional[str] = None
) -> str:
    """
    Генерирует полный валидный HTML-документ для отдачи краулерам и ботам.
    """
    cfg = get_seo_config()

    # 1. URL и заголовки
    base_url = cfg.site_url
    if host and not base_url.startswith("https://") and not base_url.startswith("http://"):
        base_url = f"https://{host}"

    canonical = page.canonical_url or f"{base_url.rstrip('/')}/{current_path.lstrip('/')}"
    og_image = page.og_image or cfg.default_og_image
    if og_image and not (og_image.startswith("http://") or og_image.startswith("https://")):
        og_image = f"{base_url.rstrip('/')}/{og_image.lstrip('/')}"

    title_escaped = html.escape(page.title)
    desc_escaped = html.escape(page.description, quote=True)
    canonical_escaped = html.escape(canonical, quote=True)
    site_name_escaped = html.escape(cfg.site_name, quote=True)
    lang = page.lang or cfg.default_lang

    head_lines: List[str] = [
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        f'    <title>{title_escaped}</title>',
        f'    <meta name="description" content="{desc_escaped}">',
        f'    <meta name="robots" content="{html.escape(page.robots, quote=True)}">',
        f'    <link rel="canonical" href="{canonical_escaped}">',
    ]

    # 2. OpenGraph
    head_lines.extend([
        f'    <meta property="og:title" content="{title_escaped}">',
        f'    <meta property="og:description" content="{desc_escaped}">',
        f'    <meta property="og:type" content="{html.escape(page.og_type, quote=True)}">',
        f'    <meta property="og:url" content="{canonical_escaped}">',
        f'    <meta property="og:site_name" content="{site_name_escaped}">',
    ])
    if og_image:
        head_lines.append(f'    <meta property="og:image" content="{html.escape(og_image, quote=True)}">')

    pub_iso = _format_datetime(page.published_time)
    if pub_iso:
        head_lines.append(f'    <meta property="article:published_time" content="{pub_iso}">')

    mod_iso = _format_datetime(page.modified_time)
    if mod_iso:
        head_lines.append(f'    <meta property="article:modified_time" content="{mod_iso}">')

    if page.author:
        head_lines.append(f'    <meta property="article:author" content="{html.escape(page.author, quote=True)}">')

    # 3. Twitter Cards
    twitter_card = "summary_large_image" if og_image else "summary"
    head_lines.extend([
        f'    <meta name="twitter:card" content="{twitter_card}">',
        f'    <meta name="twitter:title" content="{title_escaped}">',
        f'    <meta name="twitter:description" content="{desc_escaped}">',
    ])
    if og_image:
        head_lines.append(f'    <meta name="twitter:image" content="{html.escape(og_image, quote=True)}">')

    # 4. Schema.org JSON-LD
    json_ld: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": page.schema_type,
        "name": page.title,
        "description": page.description,
        "url": canonical,
    }
    if page.schema_type == "Article":
        json_ld["headline"] = page.title

    if og_image:
        json_ld["image"] = og_image
    if pub_iso:
        json_ld["datePublished"] = pub_iso
    if mod_iso:
        json_ld["dateModified"] = mod_iso
    if page.author:
        json_ld["author"] = {"@type": "Person", "name": page.author}

    # Пользовательские данные Schema.org
    if page.schema_data:
        json_ld.update(page.schema_data)

    # Breadcrumbs в JSON-LD
    if page.breadcrumbs:
        breadcrumb_elements = []
        for i, (name, path) in enumerate(page.breadcrumbs, start=1):
            full_b_url = path if path.startswith("http") else f"{base_url.rstrip('/')}/{path.lstrip('/')}"
            breadcrumb_elements.append({
                "@type": "ListItem",
                "position": i,
                "name": name,
                "item": full_b_url,
            })
        json_ld["breadcrumb"] = {
            "@type": "BreadcrumbList",
            "itemListElement": breadcrumb_elements
        }

    json_ld_str = orjson.dumps(json_ld, option=orjson.OPT_INDENT_2).decode("utf-8")
    head_lines.append(f'    <script type="application/ld+json">\n{json_ld_str}\n    </script>')

    # 5. Сборка Body
    body_elements: List[str] = []

    # Хлебные крошки визуальные (для краулеров)
    if page.breadcrumbs:
        links = []
        for name, path in page.breadcrumbs:
            links.append(f'<a href="{html.escape(path, quote=True)}">{html.escape(name)}</a>')
        body_elements.append(
            '    <nav aria-label="breadcrumbs" class="seo-breadcrumbs">\n      '
            + " / ".join(links)
            + '\n    </nav>'
        )

    # Основной контент страницы
    if page.body_html:
        body_elements.append(f'    <main class="seo-content">\n{page.body_html}\n    </main>')
    else:
        body_elements.append(f'    <main class="seo-content">\n      <h1>{title_escaped}</h1>\n      <p>{desc_escaped}</p>\n    </main>')

    head_block = "\n".join(head_lines)
    body_block = "\n".join(body_elements)

    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="{html.escape(lang, quote=True)}">\n'
        f'  <head>\n{head_block}\n  </head>\n'
        f'  <body>\n{body_block}\n  </body>\n'
        f'</html>'
    )


def render_404_html(site_name: Optional[str] = None) -> str:
    """Генерирует чистый 404 HTML для краулеров."""
    name = site_name or get_seo_config().site_name
    return (
        f'<!DOCTYPE html>\n'
        f'<html lang="ru">\n'
        f'  <head>\n'
        f'    <meta charset="utf-8">\n'
        f'    <title>404 Not Found - {html.escape(name)}</title>\n'
        f'    <meta name="robots" content="noindex, nofollow">\n'
        f'  </head>\n'
        f'  <body>\n'
        f'    <h1>404 Not Found</h1>\n'
        f'    <p>Запрошенная страница не найдена.</p>\n'
        f'  </body>\n'
        f'</html>'
    )


__all__ = [
    "render_seo_page",
    "render_404_html",
]
