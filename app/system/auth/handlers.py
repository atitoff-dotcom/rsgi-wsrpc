from typing import Dict, Any, List
import asyncio

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from core.session import rpc_method, JsonRpcSession
from app.session import Session
from app.system.db import async_session
from core.logger import logger

# Импортируем модели User и ActiveSession из нового системного модуля
from app.system.auth.models import User, ActiveSession

# Уведомления об изменении сессий
session_bus = asyncio.Condition()

async def notify_session_change() -> None:
    """
    Уведомляет всех подписчиков об изменении состояния активных сессий.
    """
    async with session_bus:
        session_bus.notify_all()

async def handle_ws_disconnect(session_id: int) -> None:
    """
    Обрабатывает дисконнект WebSocket-соединения.
    Удаляет соответствующую активную сессию из базы данных.
    """
    async with async_session() as db:
        stmt = delete(ActiveSession).where(ActiveSession.id == session_id)
        result = await db.execute(stmt)
        await db.commit()
        deleted = result.rowcount > 0
    if deleted:
        logger.info(f"[Аутентификация] Активная сессия #{session_id} удалена из БД (дисконнект)")
        asyncio.create_task(notify_session_change())


async def cleanup_app_session(session: JsonRpcSession) -> None:
    """
    Колбэк для очистки ресурсов сессии приложения при дисконнекте.
    Удаляет активную сессию из базы данных.
    """
    if session.data and session.data.session_db_id:
        await handle_ws_disconnect(session.data.session_db_id)


class AuthHandlers:
    """
    Класс, содержащий RPC-хендлеры для авторизации и системных функций.
    """

    @staticmethod
    @rpc_method("auth.get_menu_items")
    async def handle_get_menu_items(session: Session, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Возвращает список доступных пунктов меню навигации в зависимости от роли пользователя.

        Args:
            args (dict): Пустой словарь (аргументы не требуются).

        Returns:
            List[dict]: Список доступных пунктов меню, каждый из которых содержит:
                - path (str): Путь/маршрут на фронтенде.
                - label (str): Отображаемое название пункта.
                - icon (str): Название иконки (например, "Lock", "Building2").
                - description (str): Краткое описание раздела меню.
        """
        # Пока возвращаем полный статический список, в реальном приложении фильтруется на основе session.user_role
        return [
            {
                "path": "/orders",
                "label": "Заявки",
                "icon": "ClipboardList",
                "description": "Управление заявками и скоринг"
            },
            {
                "path": "/dashboard",
                "label": "Главная",
                "icon": "LayoutDashboard",
                "description": "Общая аналитика и ключевые показатели эффективности"
            },
            {
                "path": "/passports_v2",
                "label": "Паспорта",
                "icon": "BookOpen",
                "description": "Паспорта банков и тарифы"
            },
            {
                "path": "/banks",
                "label": "Банки",
                "icon": "Building2",
                "description": "Реестр и управление подключенными банками"
            },
            {
                "path": "/bank_workspace",
                "label": "Кабинет Банка",
                "icon": "Building2",
                "description": "Обработка заявок и выдача гарантий банком"
            },
            {
                "path": "/sandbox",
                "label": "Песочница",
                "icon": "FlaskConical",
                "description": "Интерактивная среда для тестирования моделей скоринга"
            },
            {
                "path": "/external_data",
                "label": "Внешние данные",
                "icon": "Database",
                "description": "Справочник атомарных переменных скоринга и интеграционных маппингов"
            },
            {
                "path": "/admin",
                "label": "Админка",
                "icon": "Lock",
                "description": "Управление пользователями, ролями и системными настройками"
            }
        ]

    @staticmethod
    @rpc_method("auth.logout")
    async def handle_logout(session: Session, args: Dict[str, Any]) -> bool:
        """
        Выполняет выход пользователя из системы (удаление сессии WebSocket и RefreshToken).

        Args:
            args (dict): Пустой словарь (аргументы не требуются).

        Returns:
            bool: True при успешном выходе.
        """
        db_id = session.session_db_id
        username = session.user_name
        async with async_session() as db_session:
            stmt = select(ActiveSession).options(selectinload(ActiveSession.refresh_token)).where(ActiveSession.id == db_id)
            ws_session = (await db_session.execute(stmt)).scalar_one_or_none()
            if ws_session:
                if ws_session.refresh_token:
                    await db_session.delete(ws_session.refresh_token)
                await db_session.delete(ws_session)
                await db_session.commit()
        
        logger.info(f"[Аутентификация] Пользователь '{username}' вышел из системы. Сессия #{db_id} удалена.")
        
        await session.close()
        asyncio.create_task(notify_session_change())
        return True
