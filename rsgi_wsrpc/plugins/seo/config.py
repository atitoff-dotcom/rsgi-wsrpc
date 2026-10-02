# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.config: Настройки подсистемы поисковой оптимизации и Dynamic Rendering.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Union

from rsgi_wsrpc.core.lib.config import get_config


@dataclass
class SeoConfig:
    """Конфигурация плагина SEO."""
    site_url: str = "http://localhost:8080"
    site_name: str = "RSGI WSRPC"
    indexnow_key: Optional[str] = None
    default_lang: str = "ru"
    sitemap_ttl: int = 3600  # 1 час кэша по умолчанию
    default_og_image: Optional[str] = None
    extra_bot_patterns: List[str] = field(default_factory=list)
    custom_detector: Optional[Callable[[Union[str, Any]], Optional[bool]]] = None
    indexnow_queue_file: Optional[str] = "data/indexnow_queue.txt"
    indexnow_flush_interval: int = 1800  # 30 минут
    indexnow_max_queue_size: int = 1000
    sitemap_max_urls_per_file: int = 50_000


_CURRENT_SEO_CONFIG: Optional[SeoConfig] = None


def get_seo_config() -> SeoConfig:
    """
    Возвращает актуальную конфигурацию SEO, считывая настройки приложения
    или переменные окружения.
    """
    global _CURRENT_SEO_CONFIG
    if _CURRENT_SEO_CONFIG is not None:
        return _CURRENT_SEO_CONFIG

    app_cfg = get_config()
    cfg_dict = app_cfg.to_dict() if hasattr(app_cfg, "to_dict") else {}
    seo_raw = cfg_dict.get("seo", {}) if isinstance(cfg_dict, dict) else {}

    site_url = (
        seo_raw.get("site_url")
        or os.getenv("SITE_URL")
        or "http://localhost:8080"
    ).rstrip("/")

    site_name = (
        seo_raw.get("site_name")
        or os.getenv("SITE_NAME")
        or "RSGI WSRPC"
    )

    indexnow_key = (
        seo_raw.get("indexnow_key")
        or os.getenv("INDEXNOW_KEY")
        or None
    )

    default_lang = (
        seo_raw.get("default_lang")
        or os.getenv("DEFAULT_LANG")
        or "ru"
    )

    sitemap_ttl = int(
        seo_raw.get("sitemap_ttl")
        or os.getenv("SITEMAP_TTL")
        or 3600
    )

    default_og_image = (
        seo_raw.get("default_og_image")
        or os.getenv("DEFAULT_OG_IMAGE")
        or None
    )

    extra_bot_patterns = seo_raw.get("extra_bot_patterns") or []
    if isinstance(extra_bot_patterns, str):
        extra_bot_patterns = [p.strip() for p in extra_bot_patterns.split(",") if p.strip()]

    queue_file_env = os.getenv("INDEXNOW_QUEUE_FILE")
    indexnow_queue_file = (
        seo_raw.get("indexnow_queue_file")
        if "indexnow_queue_file" in seo_raw
        else (queue_file_env if queue_file_env is not None else "data/indexnow_queue.txt")
    )
    if indexnow_queue_file in ("", "none", "false", "None"):
        indexnow_queue_file = None

    indexnow_flush_interval = int(
        seo_raw.get("indexnow_flush_interval")
        or os.getenv("INDEXNOW_FLUSH_INTERVAL")
        or 1800
    )

    indexnow_max_queue_size = int(
        seo_raw.get("indexnow_max_queue_size")
        or os.getenv("INDEXNOW_MAX_QUEUE_SIZE")
        or 1000
    )

    sitemap_max_urls_per_file = int(
        seo_raw.get("sitemap_max_urls_per_file")
        or os.getenv("SITEMAP_MAX_URLS_PER_FILE")
        or 50_000
    )

    _CURRENT_SEO_CONFIG = SeoConfig(
        site_url=site_url,
        site_name=site_name,
        indexnow_key=indexnow_key,
        default_lang=default_lang,
        sitemap_ttl=sitemap_ttl,
        default_og_image=default_og_image,
        extra_bot_patterns=list(extra_bot_patterns),
        custom_detector=seo_raw.get("custom_detector"),
        indexnow_queue_file=indexnow_queue_file,
        indexnow_flush_interval=indexnow_flush_interval,
        indexnow_max_queue_size=indexnow_max_queue_size,
        sitemap_max_urls_per_file=sitemap_max_urls_per_file,
    )
    return _CURRENT_SEO_CONFIG


def configure_seo(
    site_url: Optional[str] = None,
    site_name: Optional[str] = None,
    indexnow_key: Optional[str] = None,
    default_lang: Optional[str] = None,
    sitemap_ttl: Optional[int] = None,
    default_og_image: Optional[str] = None,
    extra_bot_patterns: Optional[List[str]] = None,
    custom_detector: Optional[Callable[[Union[str, Any]], Optional[bool]]] = None,
    indexnow_queue_file: Optional[str] = ...,  # type: ignore[assignment]
    indexnow_flush_interval: Optional[int] = None,
    indexnow_max_queue_size: Optional[int] = None,
    sitemap_max_urls_per_file: Optional[int] = None,
) -> SeoConfig:
    """Программная настройка плагина SEO."""
    current = get_seo_config()
    if site_url is not None:
        current.site_url = site_url.rstrip("/")
    if site_name is not None:
        current.site_name = site_name
    if indexnow_key is not None:
        current.indexnow_key = indexnow_key
    if default_lang is not None:
        current.default_lang = default_lang
    if sitemap_ttl is not None:
        current.sitemap_ttl = sitemap_ttl
    if default_og_image is not None:
        current.default_og_image = default_og_image
    if extra_bot_patterns is not None:
        current.extra_bot_patterns = list(extra_bot_patterns)
    if custom_detector is not None:
        current.custom_detector = custom_detector
    if indexnow_queue_file is not ...:
        current.indexnow_queue_file = indexnow_queue_file
    if indexnow_flush_interval is not None:
        current.indexnow_flush_interval = indexnow_flush_interval
    if indexnow_max_queue_size is not None:
        current.indexnow_max_queue_size = indexnow_max_queue_size
    if sitemap_max_urls_per_file is not None:
        current.sitemap_max_urls_per_file = sitemap_max_urls_per_file

    return current


__all__ = [
    "SeoConfig",
    "get_seo_config",
    "configure_seo",
]
