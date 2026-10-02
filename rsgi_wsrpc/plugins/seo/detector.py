# -*- coding: utf-8 -*-
"""
rsgi_wsrpc.plugins.seo.detector: Высокопроизводительное распознавание поисковых,
социальных и ИИ-роботов по User-Agent.
"""

import re
from typing import Any, Optional, Union

from rsgi_wsrpc.core.http import extract_header

# Скомпилированный регистронезависимый паттерн для детекции ботов
# 1. Поисковые системы: Google, Yandex, Bing, Baidu, DuckDuckGo, Yahoo, Mail.ru, Ecosia
# 2. Соцсети и мессенджеры: Telegram, VK, Twitter, Facebook, WhatsApp, Discord, Slack, LinkedIn, Pinterest, Skype, Viber
# 3. ИИ-краулеры: OpenAI, ChatGPT, Perplexity, Claude, Applebot-Extended, CommonCrawl
BOT_USER_AGENT_PATTERN = re.compile(
    r"("
    # Поисковики
    r"googlebot|yandex(?:bot|images|video|media|blogs|favicons)?|bingbot|baiduspider|"
    r"duckduckbot|yahoo!\s+slurp|mail\.ru_bot|ecosia|"
    # Мессенджеры и социальные сети
    r"telegrambot|vkshare|twitterbot|facebookexternalhit|whatsapp|discordbot|"
    r"slackbot|linkedinbot|pinterest(?:bot)?|skypeuripreview|viber|"
    # ИИ-краулеры и сборщики данных
    r"oai-searchbot|chatgpt-user|gptbot|perplexitybot|claudebot|applebot-extended|ccbot"
    r")",
    re.IGNORECASE
)


def is_bot(scope_or_ua: Optional[Union[str, Any]]) -> bool:
    """
    Определяет, является ли клиент поисковым краулером, ботом соцсети или ИИ-ботом.
    Принимает либо строку User-Agent, либо RSGI scope (или словарь запроса).
    """
    if scope_or_ua is None:
        return False

    if isinstance(scope_or_ua, str):
        ua = scope_or_ua.strip()
    else:
        # Извлекаем заголовок из RSGI scope
        ua = extract_header(scope_or_ua, "user-agent", default="")

    if not ua:
        return False

    return bool(BOT_USER_AGENT_PATTERN.search(ua))


__all__ = [
    "BOT_USER_AGENT_PATTERN",
    "is_bot",
]
