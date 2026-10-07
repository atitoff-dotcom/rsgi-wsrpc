# -*- coding: utf-8 -*-
"""
Типизированные классы конфигурации OAuth2-провайдеров для rsgi-wsrpc.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class VkOAuth:
    """Конфигурация авторизации через VK ID (OAuth 2.0)."""
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None
    enabled: bool = True


@dataclass
class YandexOAuth:
    """Конфигурация авторизации через Яндекс ID (OAuth 2.0)."""
    client_id: str
    client_secret: str
    redirect_uri: Optional[str] = None
    enabled: bool = True
