# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.config: Настройки подсистемы поисковой оптимизации и Dynamic Rendering.
"""

import os
from dataclasses import dataclass
from typing import Optional

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

    _CURRENT_SEO_CONFIG = SeoConfig(
        site_url=site_url,
        site_name=site_name,
        indexnow_key=indexnow_key,
        default_lang=default_lang,
        sitemap_ttl=sitemap_ttl,
        default_og_image=default_og_image,
    )
    return _CURRENT_SEO_CONFIG


def configure_seo(
    site_url: Optional[str] = None,
    site_name: Optional[str] = None,
    indexnow_key: Optional[str] = None,
    default_lang: Optional[str] = None,
    sitemap_ttl: Optional[int] = None,
    default_og_image: Optional[str] = None,
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

    return current


__all__ = [
    "SeoConfig",
    "get_seo_config",
    "configure_seo",
]
