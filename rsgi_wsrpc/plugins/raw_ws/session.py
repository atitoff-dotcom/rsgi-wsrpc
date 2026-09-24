# -*- coding: utf-8 -*-
"""
Класс сырой WebSocket-сессии (RawWebSocketSession) для бинарных и произвольных протоколов.
Минимизирован по памяти (__slots__) для поддержки десятков тысяч одновременных подключений.
"""

import time
import inspect
import asyncio
from typing import Callable, List, Union, Optional
from rsgi_wsrpc.core.logger import logger


class RawWebSocketSession:
    """
    Легковесная обертка над Granian WebSocket-протоколом.
    Обеспечивает явную работу с session_id, сырыми байтами и жизненным циклом.
    """
    __slots__ = ("ws", "session_id", "scope", "_closed", "last_active", "_on_close_callbacks")

    def __init__(self, ws, session_id: int, scope: dict):
        self.ws = ws
        self.session_id = session_id
        self.scope = scope
        self._closed = False
        self.last_active = time.monotonic()
        self._on_close_callbacks: List[Callable] = []

    @property
    def is_closed(self) -> bool:
        return self._closed

    def on_close(self, callback: Callable) -> None:
        """
        Регистрация функции обратного вызова при обрыве/закрытии сессии.
        Колбэк может быть как синхронным, так и асинхронным (принимает session или session_id).
        """
        self._on_close_callbacks.append(callback)

    async def send_bytes(self, data: bytes) -> bool:
        """Отправка бинарного фрейма клиенту."""
        if self._closed or not self.ws:
            return False
        try:
            awaitable = self.ws.send_bytes(data)
            if hasattr(awaitable, "__await__"):
                await awaitable
            return True
        except Exception as e:
            logger.debug(f"[RawWS] Ошибка отправки байт в сессию {self.session_id}: {e}")
            return False

    async def send_str(self, data: str) -> bool:
        """Отправка текстового фрейма клиенту."""
        if self._closed or not self.ws:
            return False
        try:
            awaitable = self.ws.send_str(data)
            if hasattr(awaitable, "__await__"):
                await awaitable
            return True
        except Exception as e:
            logger.debug(f"[RawWS] Ошибка отправки строки в сессию {self.session_id}: {e}")
            return False

    async def close(self, code: int = 1000) -> None:
        """Явное закрытие соединения сервером."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.ws:
                close_awaitable = self.ws.close(code)
                if hasattr(close_awaitable, "__await__"):
                    await close_awaitable
        except Exception as e:
            logger.debug(f"[RawWS] Исключение при закрытии сессии {self.session_id}: {e}")

    async def run(self, message_handler: Callable) -> None:
        """
        Основной цикл чтения фреймов из сокета и диспетчеризации в message_handler.
        """
        logger.info(f"[RawWS] Старт сессии {self.session_id} на пути {self.scope.get('path', '')}")

        # Предварительно определяем сигнатуру обработчика
        sig = inspect.signature(message_handler)
        params_count = len(sig.parameters)
        is_async = inspect.iscoroutinefunction(message_handler)

        try:
            while not self._closed:
                msg = await self.ws.receive()
                
                # Проверка на закрытие соединения
                if not msg or "CloseMessage" in type(msg).__name__:
                    logger.info(f"[RawWS] Дисконнект со стороны клиента: сессия {self.session_id}")
                    break

                self.last_active = time.monotonic()
                data = getattr(msg, "data", msg)

                # Вызов пользовательского обработчика с явной передачей session_id
                try:
                    if params_count >= 3:
                        res = message_handler(self.session_id, data, self)
                    else:
                        res = message_handler(self.session_id, data)

                    if is_async or hasattr(res, "__await__"):
                        await res
                except Exception as handler_err:
                    logger.error(
                        f"[RawWS] Ошибка в обработчике сессии {self.session_id}: {handler_err}",
                        exc_info=True
                    )

        except asyncio.CancelledError:
            logger.info(f"[RawWS] Задача сессии {self.session_id} отменена")
        except Exception as e:
            logger.error(f"[RawWS] Сбой сокетного цикла сессии {self.session_id}: {e}", exc_info=True)
        finally:
            self._closed = True
            # Гарантированное оповещение слушателей об обрыве
            for cb in self._on_close_callbacks:
                try:
                    cb_sig = inspect.signature(cb)
                    cb_args = (self,) if len(cb_sig.parameters) >= 1 else ()
                    res = cb(*cb_args)
                    if inspect.iscoroutinefunction(cb) or hasattr(res, "__await__"):
                        await res
                except Exception as cb_err:
                    logger.error(
                        f"[RawWS] Ошибка в on_close колбэке сессии {self.session_id}: {cb_err}",
                        exc_info=True
                    )
            logger.info(f"[RawWS] Сессия {self.session_id} полностью завершена и очищена")
