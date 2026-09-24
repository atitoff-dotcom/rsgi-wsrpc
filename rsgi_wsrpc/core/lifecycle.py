import asyncio
from typing import Callable, List
from .logger import logger

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


# Реестр колбэков завершения работы приложения
SHUTDOWN_CALLBACKS: List[Callable] = []


def on_shutdown(func: Callable) -> Callable:
    """
    Декоратор для регистрации функций завершения работы приложения (on_shutdown).
    """
    SHUTDOWN_CALLBACKS.append(func)
    return func


async def run_shutdown_callbacks() -> None:
    """
    Запускает все зарегистрированные функции завершения приложения (sync/async).
    """
    logger.info(f"[Lifecycle] Запуск {len(SHUTDOWN_CALLBACKS)} shutdown-колбэков: {[c.__name__ for c in SHUTDOWN_CALLBACKS]}")
    for callback in SHUTDOWN_CALLBACKS:
        logger.info(f"[Lifecycle] Выполнение {callback.__name__}...")
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                callback()
        except Exception as e:
            logger.error(f"[Lifecycle] Ошибка выполнения shutdown-колбэка {callback.__name__}: {e}", exc_info=True)
    logger.info("[Lifecycle] Все shutdown-колбэки выполнены.")

