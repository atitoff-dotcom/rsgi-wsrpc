# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.router: Диспетчер бот-маршрутов с типизированными параметрами URL.
"""

import inspect
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from rsgi_wsrpc.core.http import extract_header, extract_query_params
from rsgi_wsrpc.core.logger import logger
from .detector import is_bot
from .renderer import render_404_html, render_seo_page
from .schemas import SeoPageData

# Поддерживаемые конвертеры типов для параметров маршрутов
TYPE_CONVERTERS: Dict[str, Tuple[str, Callable[[str], Any]]] = {
    "int": (r"\d+", int),
    "str": (r"[^/]+", str),
    "float": (r"\d+(?:\.\d+)?", float),
    "uuid": (r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", UUID),
}

# Регулярка для поиска плейсхолдеров вида {name} или {name:type}
PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::([a-zA-Z_]+))?\}")


class BotRoute:
    """Маршрут для генерации SEO-страниц ботам."""

    def __init__(self, raw_path: str, handler: Callable):
        self.raw_path = raw_path
        self.handler = handler
        self.is_async = inspect.iscoroutinefunction(handler)
        self.param_types: Dict[str, Callable[[str], Any]] = {}

        # Преобразуем шаблон пути в регулярное выражение
        regex_pattern = "^"
        last_idx = 0

        for match in PARAM_RE.finditer(raw_path):
            start, end = match.span()
            regex_pattern += re.escape(raw_path[last_idx:start])
            param_name = match.group(1)
            type_name = match.group(2) or "str"

            converter_info = TYPE_CONVERTERS.get(type_name)
            if not converter_info:
                # Если тип неизвестен, считаем произвольной строкой до слэша
                param_regex, converter_fn = (r"[^/]+", str)
            else:
                param_regex, converter_fn = converter_info

            regex_pattern += f"(?P<{param_name}>{param_regex})"
            self.param_types[param_name] = converter_fn
            last_idx = end

        regex_pattern += re.escape(raw_path[last_idx:]) + "$"
        self.compiled_regex = re.compile(regex_pattern)

    def match(self, path: str) -> Optional[Dict[str, Any]]:
        """
        Проверяет совпадение пути и извлекает типизированные параметры.
        Возвращает None, если путь не совпал.
        """
        m = self.compiled_regex.match(path)
        if not m:
            return None

        raw_dict = m.groupdict()
        typed_dict: Dict[str, Any] = {}
        for k, v in raw_dict.items():
            converter = self.param_types.get(k, str)
            try:
                typed_dict[k] = converter(v)
            except (ValueError, TypeError):
                return None
        return typed_dict


# Глобальный реестр маршрутов ботов
BOT_ROUTES: List[BotRoute] = []


def bot_page(path: str) -> Callable:
    """
    Декоратор для регистрации SEO-страницы бота.
    Пример:
        @bot_page("/forum/{topic_id:int}")
        async def get_topic_seo(topic_id: int) -> Optional[SeoPageData]:
            ...
    """
    def decorator(func: Callable) -> Callable:
        route = BotRoute(path, func)
        BOT_ROUTES.append(route)
        logger.debug(f"[SEO] Зарегистрирован бот-маршрут: {path} -> {func.__name__}")
        return func
    return decorator


async def handle_bot_http(scope: Any, proto: Any) -> bool:
    """
    RSGI-перехватчик входящих HTTP-запросов для Dynamic Rendering.
    Если клиент является ботом и запрошен маршрут, возвращает True (обработано).
    Если не бот или маршрут не зарегистрирован, возвращает False (пропустить дальше).
    """
    # 1. Проверяем метод (боты индексируют только GET и HEAD)
    method = getattr(scope, "method", None)
    if method is None and isinstance(scope, dict):
        method = scope.get("method")
    if method not in ("GET", "HEAD"):
        return False

    # 2. Проверяем, является ли клиент поисковым ботом
    # (также поддерживаем отладочный параметр ?bot=1 для удобного тестирования из обычного браузера)
    query_params = extract_query_params(scope)
    is_debug_bot = query_params.get("bot") in ("1", "true")
    if not (is_debug_bot or is_bot(scope)):
        return False

    path = getattr(scope, "path", None)
    if path is None and isinstance(scope, dict):
        path = scope.get("path")
    if not path:
        return False

    # 3. Ищем совпадающий бот-маршрут
    for route in BOT_ROUTES:
        params = route.match(path)
        if params is None:
            continue

        # Маршрут совпал! Вызываем хендлер
        ua = extract_header(scope, "user-agent", default="unknown")
        logger.info(f"[SEO] Бот '{ua}' запросил '{path}'. Рендеринг через {route.handler.__name__}...")

        try:
            if route.is_async:
                page_data = await route.handler(**params)
            else:
                page_data = route.handler(**params)
        except Exception as e:
            logger.error(f"[SEO] Ошибка в хендлере бот-страницы {route.raw_path}: {e}", exc_info=True)
            proto.response_str(
                status=500,
                headers=[("content-type", "text/plain; charset=utf-8")],
                body="500 Internal Server Error"
            )
            return True

        # Если хендлер вернул None — отдаем 404
        if page_data is None:
            logger.info(f"[SEO] Объект не найден ({path}). Отдаем 404.")
            proto.response_str(
                status=404,
                headers=[("content-type", "text/html; charset=utf-8")],
                body=render_404_html()
            )
            return True

        if not isinstance(page_data, SeoPageData):
            logger.warning(f"[SEO] Хендлер {route.handler.__name__} вернул {type(page_data)} вместо SeoPageData.")
            return False

        # Рендерим семантический HTML
        host = extract_header(scope, "host")
        html_content = render_seo_page(page_data, current_path=path, host=host)

        proto.response_str(
            status=200,
            headers=[
                ("content-type", "text/html; charset=utf-8"),
                ("x-rendered-for", "bot"),
            ],
            body=html_content
        )
        return True

    # Ни один бот-маршрут не совпал — передаем дальше (например, в SPA fallback)
    return False


__all__ = [
    "BotRoute",
    "BOT_ROUTES",
    "bot_page",
    "handle_bot_http",
]
