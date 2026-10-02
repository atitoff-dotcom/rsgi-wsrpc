# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.indexnow: Асинхронная отправка уведомлений в поисковики
(Яндекс, Bing) по протоколу IndexNow и верификация ключа.
"""

import asyncio
import urllib.request
import urllib.parse
from typing import Any, List, Optional
from urllib.parse import urlparse

import orjson

from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.core.router import http_route
from .config import get_seo_config

INDEXNOW_ENDPOINTS = [
    "https://api.indexnow.org/indexnow",
    "https://yandex.com/indexnow",
]


def _post_indexnow_sync(endpoint: str, payload_bytes: bytes, timeout: float = 10.0) -> int:
    """Синхронный POST-запрос с использованием urllib (без сторонних библиотек)."""
    req = urllib.request.Request(
        url=endpoint,
        data=payload_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status


async def _send_indexnow_background(
    urls: List[str],
    host: str,
    key: str,
    key_location: Optional[str] = None
) -> None:
    """Фоновая корутина для отправки уведомлений по всем эндпоинтам IndexNow."""
    if not urls:
        return

    payload = {
        "host": host,
        "key": key,
        "keyLocation": key_location or f"https://{host}/{key}.txt",
        "urlList": urls,
    }
    payload_bytes = orjson.dumps(payload)

    for endpoint in INDEXNOW_ENDPOINTS:
        try:
            status = await asyncio.to_thread(_post_indexnow_sync, endpoint, payload_bytes)
            logger.info(f"[INDEXNOW] Успешно отправлено {len(urls)} URL в {endpoint} (HTTP {status}).")
        except Exception as e:
            logger.warning(f"[INDEXNOW] Сбой при отправке в {endpoint}: {e}")


def notify_indexnow(
    urls: List[str],
    host: Optional[str] = None,
    key: Optional[str] = None
) -> asyncio.Task:
    """
    Отправляет URLs в поисковые системы по протоколу IndexNow в фоновом режиме.
    Не блокирует выполнение вызывающего кода.
    """
    cfg = get_seo_config()
    actual_key = key or cfg.indexnow_key
    if not actual_key:
        logger.warning("[INDEXNOW] Ключ IndexNow не указан. Отправка отменена.")
        # Возвращаем завершенную пустую задачу
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        future.set_result(None)
        return future

    if not host:
        parsed = urlparse(cfg.site_url)
        actual_host = parsed.netloc or cfg.site_url
    else:
        actual_host = host

    task = asyncio.create_task(_send_indexnow_background(urls, actual_host, actual_key))
    return task


def register_indexnow_key_route(key: str) -> None:
    """
    Регистрирует эндпоинт верификации текстового ключа IndexNow: GET /<key>.txt
    """
    route_path = f"/{key}.txt"

    async def key_txt_handler(scope: Any, proto: Any) -> None:
        proto.response_str(
            status=200,
            headers=[("content-type", "text/plain; charset=utf-8")],
            body=key
        )

    http_route(route_path, ["GET"])(key_txt_handler)
    logger.debug(f"[INDEXNOW] Зарегистрирован маршрут верификации ключа: {route_path}")


# Автоматическая регистрация маршрута верификации при наличии ключа в конфигурации
_initial_cfg = get_seo_config()
if _initial_cfg.indexnow_key:
    register_indexnow_key_route(_initial_cfg.indexnow_key)


__all__ = [
    "INDEXNOW_ENDPOINTS",
    "notify_indexnow",
    "register_indexnow_key_route",
]
