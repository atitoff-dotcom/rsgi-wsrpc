# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.detector: Высокопроизводительное распознавание поисковых,
социальных и ИИ-роботов по User-Agent (двухслойный гибридный анализ).
"""

import re
from typing import Any, Optional, Union

from rsgi_wsrpc.core.http import extract_header
from .config import get_seo_config

# Фаза 1: Скомпилированный регистронезависимый паттерн для явных ботов
# 1. Поисковые системы: Google, Yandex, Bing, Baidu, DuckDuckGo, Yahoo, Mail.ru, Ecosia, Seznam, Sogou
# 2. Соцсети и мессенджеры: Telegram, VK, Twitter, Facebook, WhatsApp, Discord, Slack, LinkedIn, Pinterest, Skype, Viber
# 3. ИИ-краулеры и LLM-индексаторы: OpenAI/ChatGPT, Perplexity, Claude/Anthropic, Applebot, ByteSpider, CommonCrawl, Cohere, Diffbot, Amazonbot
BOT_USER_AGENT_PATTERN = re.compile(
    r"("
    # Поисковики
    r"googlebot|yandex(?:bot|images|video|media|blogs|favicons)?|bingbot|baiduspider|"
    r"duckduckbot|yahoo!\s+slurp|mail\.ru_bot|ecosia|seznambot|sogou|"
    # Мессенджеры и социальные сети
    r"telegrambot|vkshare|twitterbot|facebookexternalhit|whatsapp|discordbot|"
    r"slackbot|linkedinbot|pinterest(?:bot)?|skypeuripreview|viber|"
    # ИИ-краулеры и сборщики данных
    r"oai-searchbot|chatgpt-user|gptbot|perplexitybot|claudebot|anthropic-ai|"
    r"applebot-extended|applebot|bytespider|ccbot|cohere-ai|diffbot|amazonbot"
    r")",
    re.IGNORECASE
)

# Фаза 1.5: Известные консольные утилиты и скриптовые библиотеки (не браузеры)
CLI_SCRAPERS_PATTERN = re.compile(
    r"^(?:curl|wget|python|aiohttp|httpx|requests|urllib|go-http-client|node-fetch|axios|postman|scrapy|java|httpie)",
    re.IGNORECASE
)

# Фаза 2: Валидные браузерные движки и идентификаторы реальных браузеров
BROWSER_ENGINE_PATTERN = re.compile(
    r"(?:AppleWebKit|WebKit|Gecko|Trident|Blink|Chrome|Safari|Firefox|Opera|Edge|Edg)",
    re.IGNORECASE
)


def is_bot(scope_or_ua: Optional[Union[str, Any]]) -> bool:
    """
    Определяет, является ли клиент поисковым краулером, ботом соцсети,
    ИИ-ботом или текстовым клиентом (двухслойный гибридный анализ).
    Принимает либо строку User-Agent, либо RSGI scope (или словарь запроса).
    """
    if scope_or_ua is None:
        return False

    if isinstance(scope_or_ua, str):
        ua = scope_or_ua.strip()
    else:
        ua = extract_header(scope_or_ua, "user-agent", default="").strip()

    if not ua:
        return False

    cfg = get_seo_config()

    # 0. Пользовательский детектор разработчика (если задан)
    if cfg.custom_detector is not None:
        verdict = cfg.custom_detector(scope_or_ua)
        if verdict is not None:
            return bool(verdict)

    # 0.1. Пользовательские дополнительные паттерны
    if cfg.extra_bot_patterns:
        for pattern in cfg.extra_bot_patterns:
            if re.search(pattern, ua, re.IGNORECASE):
                return True

    # 1. Фаза 1: Проверка по явному черному списку ботов/краулеров
    if BOT_USER_AGENT_PATTERN.search(ua):
        return True

    # 2. Фаза 1.5: CLI-утилиты и HTTP библиотеки
    if CLI_SCRAPERS_PATTERN.search(ua):
        return True

    # 3. Фаза 2: Инвертированный вайтлист браузерных движков
    # Если в User-Agent нет признаков браузерных движков — считаем клиента краулером
    if not BROWSER_ENGINE_PATTERN.search(ua):
        return True

    # 4. Клиент содержит браузерный стек и не имеет маркеров бота -> обычный пользователь или In-App WebView
    return False


# Алиас для обратной совместимости
is_search_bot = is_bot

__all__ = [
    "BOT_USER_AGENT_PATTERN",
    "CLI_SCRAPERS_PATTERN",
    "BROWSER_ENGINE_PATTERN",
    "is_bot",
    "is_search_bot",
]

