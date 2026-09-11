import asyncio
from typing import Callable, List
from core.logger import logger

# Реестр колбэков запуска приложения
STARTUP_CALLBACKS: List[Callable] = []

def on_startup(func: Callable) -> Callable:
    """
    Декоратор для регистрации функций инициализации на старте приложения.
    """
    STARTUP_CALLBACKS.append(func)
    return func

async def run_startup_callbacks() -> None:
    """
    Запускает все зарегистрированные функции инициализации (поддерживает sync/async).
    """
    logger.info(f"[Lifecycle] Запуск {len(STARTUP_CALLBACKS)} startup-колбэков: {[c.__name__ for c in STARTUP_CALLBACKS]}")
    for callback in STARTUP_CALLBACKS:
        logger.info(f"[Lifecycle] Выполнение {callback.__name__}...")
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                callback()
        except Exception as e:
            logger.error(f"[Lifecycle] Ошибка выполнения startup-колбэка {callback.__name__}: {e}", exc_info=True)
    logger.info("[Lifecycle] Все startup-колбэки выполнены.")
