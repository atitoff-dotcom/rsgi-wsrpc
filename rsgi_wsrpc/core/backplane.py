# -*- coding: utf-8 -*-
"""
Шина событий (Backplane) для синхронизации в распределенном окружении (multi-worker / multi-node).
Предоставляет базовый интерфейс BaseBackplane и реализацию по умолчанию MemoryBackplane.
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Callable, Dict, Set, Any
from .logger import logger


class BaseBackplane(ABC):
    """
    Абстрактный интерфейс шины событий для рассылок (broadcast) и инвалидации кэша.
    """

    @abstractmethod
    async def publish(self, channel: str, message: Any) -> None:
        """Публикует сообщение в именованный канал."""
        pass

    @abstractmethod
    async def subscribe(self, channel: str, callback: Callable[[Any], Any]) -> None:
        """Подписывается на сообщения из указанного канала."""
        pass

    @abstractmethod
    async def unsubscribe(self, channel: str, callback: Callable[[Any], Any]) -> None:
        """Отменяет подписку."""
        pass


class MemoryBackplane(BaseBackplane):
    """
    In-memory шина событий (по умолчанию для режима с 1 воркером).
    """

    def __init__(self):
        self._subscribers: Dict[str, Set[Callable]] = {}

    async def publish(self, channel: str, message: Any) -> None:
        callbacks = list(self._subscribers.get(channel, set()))
        for cb in callbacks:
            try:
                res = cb(message)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.error(f"[MemoryBackplane] Ошибка в подписчике канала '{channel}': {e}", exc_info=True)

    async def subscribe(self, channel: str, callback: Callable[[Any], Any]) -> None:
        if channel not in self._subscribers:
            self._subscribers[channel] = set()
        self._subscribers[channel].add(callback)

    async def unsubscribe(self, channel: str, callback: Callable[[Any], Any]) -> None:
        if channel in self._subscribers:
            self._subscribers[channel].discard(callback)
            if not self._subscribers[channel]:
                del self._subscribers[channel]


# Глобальный синглтон шины по умолчанию
_CURRENT_BACKPLANE: BaseBackplane = MemoryBackplane()


def get_backplane() -> BaseBackplane:
    """Возвращает текущую активную шину событий."""
    return _CURRENT_BACKPLANE


def set_backplane(backplane: BaseBackplane) -> None:
    """Устанавливает глобальную шину событий (например, RedisBackplane)."""
    global _CURRENT_BACKPLANE
    _CURRENT_BACKPLANE = backplane
