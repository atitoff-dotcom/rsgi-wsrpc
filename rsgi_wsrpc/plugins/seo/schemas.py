# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.schemas: Модели данных для генерации метатегов и HTML для ботов.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SeoPageData:
    """
    Структура данных для рендеринга страницы для поисковых ботов и OpenGraph превью.
    """
    title: str
    description: str = ""
    canonical_url: Optional[str] = None
    og_image: Optional[str] = None
    og_type: str = "website"              # "website", "article", "profile", etc.
    schema_type: str = "WebPage"          # "Article", "DiscussionForumPosting", "BreadcrumbList", etc.
    schema_data: Optional[Dict[str, Any]] = None
    body_html: str = ""                   # Основной семантический контент (h1, p, article)
    lang: str = "ru"
    published_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    author: Optional[str] = None
    breadcrumbs: Optional[List[Tuple[str, str]]] = None  # [("Главная", "/"), ("Статьи", "/articles")]
    robots: str = "index, follow"


__all__ = [
    "SeoPageData",
]
