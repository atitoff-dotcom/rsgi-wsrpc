# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.indexnow: Асинхронная отправка уведомлений в поисковики
(Яндекс, Bing) по протоколу IndexNow, файловый буфер-пакетировщик и верификация ключа.
"""

import asyncio
import os
import time
import urllib.request
import urllib.parse
from typing import Any, List, Optional, Set
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
            if status in (200, 202):
                logger.info(f"[INDEXNOW] Успешно отправлено {len(urls)} URL в {endpoint} (HTTP {status}).")
            elif status == 429:
                logger.warning(f"[INDEXNOW] Лимит частоты запросов превышен (HTTP 429) на {endpoint}.")
            else:
                logger.warning(f"[INDEXNOW] Эндпоинт {endpoint} вернул статус HTTP {status}.")
        except Exception as e:
            logger.warning(f"[INDEXNOW] Сбой при отправке в {endpoint}: {e}")


def enqueue_indexnow_urls(urls: List[str], queue_file: Optional[str] = None) -> int:
    """
    Добавляет URL в файловую очередь IndexNow.
    Атомарно на уровне ОС в режиме append, безопасно для нескольких воркеров.
    """
    cfg = get_seo_config()
    target_file = queue_file or cfg.indexnow_queue_file
    if not target_file or not urls:
        return 0

    dir_name = os.path.dirname(target_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    count = 0
    with open(target_file, "a", encoding="utf-8") as f:
        for u in urls:
            u_clean = u.strip()
            if u_clean:
                f.write(u_clean + "\n")
                count += 1
    return count


async def flush_indexnow_queue(
    queue_file: Optional[str] = None,
    host: Optional[str] = None,
    key: Optional[str] = None,
) -> int:
    """
    Атомарно забирает накопленную файловую очередь, дедуплицирует ссылки
    и отправляет пачками по 10 000 URL в IndexNow (Яндекс / Bing).
    Безопасно для конкурентных воркеров благодаря атомарному os.replace.
    """
    cfg = get_seo_config()
    actual_key = key or cfg.indexnow_key
    if not actual_key:
        logger.warning("[INDEXNOW] Ключ IndexNow не указан. Сброс очереди отменен.")
        return 0

    target_file = queue_file or cfg.indexnow_queue_file
    if not target_file or not os.path.exists(target_file) or os.path.getsize(target_file) == 0:
        return 0

    # Атомарно забираем файл для обработки конкретным процессом
    tmp_file = f"{target_file}.processing.{os.getpid()}.{time.time_ns()}"
    try:
        os.replace(target_file, tmp_file)
    except (FileNotFoundError, OSError):
        # Другой воркер уже забрал файл на обработку
        return 0

    # Считываем и дедуплицируем URLs
    unique_urls: Set[str] = set()
    try:
        with open(tmp_file, "r", encoding="utf-8") as f:
            for line in f:
                item = line.strip()
                if item:
                    unique_urls.add(item)
    except Exception as e:
        logger.error(f"[INDEXNOW] Ошибка чтения временного файла очереди {tmp_file}: {e}")
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        return 0

    if not unique_urls:
        if os.path.exists(tmp_file):
            os.remove(tmp_file)
        return 0

    if not host:
        parsed = urlparse(cfg.site_url)
        actual_host = parsed.netloc or cfg.site_url
    else:
        actual_host = host

    url_list = list(unique_urls)
    total_sent = 0
    logger.info(f"[INDEXNOW] Сброс {len(url_list)} уникальных URL из очереди на {actual_host}...")

    # Спецификация IndexNow: максимум 10 000 URL в одном запросе
    MAX_BATCH = 10_000
    try:
        for i in range(0, len(url_list), MAX_BATCH):
            batch = url_list[i : i + MAX_BATCH]
            await _send_indexnow_background(batch, actual_host, actual_key)
            total_sent += len(batch)
    finally:
        if os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

    return total_sent


def notify_indexnow(
    urls: List[str],
    host: Optional[str] = None,
    key: Optional[str] = None
) -> Any:
    """
    Регистрирует URLs для отправки в поисковые системы по протоколу IndexNow.
    Если включена файловая очередь (по умолчанию), быстро сохраняет ссылки на диск
    для периодической пакетной отправки.
    Если файловая очередь отключена (None), производит немедленную отправку в фоне.
    """
    cfg = get_seo_config()
    actual_key = key or cfg.indexnow_key
    if not actual_key:
        logger.warning("[INDEXNOW] Ключ IndexNow не указан. Отправка отменена.")
        try:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.set_result(0)
            return fut
        except RuntimeError:
            return None

    if not urls:
        try:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.set_result(0)
            return fut
        except RuntimeError:
            return None

    # Если включен файловый буфер — сохраняем ссылки на диск
    if cfg.indexnow_queue_file is not None:
        enqueue_indexnow_urls(urls, cfg.indexnow_queue_file)
        
        # Проверяем, не превышен ли лимит очереди для досрочного сброса
        try:
            if os.path.exists(cfg.indexnow_queue_file):
                # Если файл уже достаточно большой, запускаем фоновый сброс
                if os.path.getsize(cfg.indexnow_queue_file) > cfg.indexnow_max_queue_size * 50:
                    try:
                        loop = asyncio.get_running_loop()
                        return loop.create_task(flush_indexnow_queue(host=host, key=actual_key))
                    except RuntimeError:
                        pass
        except Exception:
            pass

        try:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            fut.set_result(len(urls))
            return fut
        except RuntimeError:
            return len(urls)

    # Режим немедленной фоновой отправки (когда файловая очередь отключена)
    if not host:
        parsed = urlparse(cfg.site_url)
        actual_host = parsed.netloc or cfg.site_url
    else:
        actual_host = host

    try:
        loop = asyncio.get_running_loop()
        return loop.create_task(_send_indexnow_background(urls, actual_host, actual_key))
    except RuntimeError:
        return None


async def start_indexnow_file_flusher() -> None:
    """
    Фоновый периодический процесс для периодического сброса очереди IndexNow
    каждые `indexnow_flush_interval` секунд (по умолчанию 30 минут / 1800 с).
    """
    cfg = get_seo_config()
    if not cfg.indexnow_key:
        return

    logger.debug(
        f"[INDEXNOW] Запущен периодический сбросщик очереди (интервал: {cfg.indexnow_flush_interval}с, файл: {cfg.indexnow_queue_file})"
    )

    while True:
        try:
            await asyncio.sleep(cfg.indexnow_flush_interval)
            await flush_indexnow_queue()
        except asyncio.CancelledError:
            logger.debug("[INDEXNOW] Фоновый сбросщик очереди остановлен.")
            break
        except Exception as e:
            logger.error(f"[INDEXNOW] Ошибка в периодическом цикле сброса очереди: {e}", exc_info=True)


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
    "enqueue_indexnow_urls",
    "flush_indexnow_queue",
    "notify_indexnow",
    "start_indexnow_file_flusher",
    "register_indexnow_key_route",
]

