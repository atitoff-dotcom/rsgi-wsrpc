# -*- coding: utf-8 -*-
"""
RPC-хендлеры демонстрационного приложения Showcase.
Демонстрирует:
1. WSRPC методы (@rpc_method)
2. Табличное сжатие (RFC 0002, @tabular_response)
3. Потоковый мультиретурн (stream: true)
4. Разграничение доступа по ролям (role=UserRole.ADMIN)
5. Асинхронную работу с БД через SQLAlchemy 2.0 (plugins.db)
6. Мгновенную синхронизацию между всеми подключенными вкладками
"""

import asyncio
from typing import Dict, Any, List
import orjson
from sqlalchemy import select, delete

from core.session import rpc_method, JsonRpcSession, RPCError, ACTIVE_SESSIONS_SET, current_rpc_id_ctx
from core.tabular import tabular_response, pack_tabular
from core.constants import UserRole
from core.logger import logger

from plugins.db import async_session
from .models import Task


async def broadcast_tasks_updated():
    """Рассылает push-уведомление 'tasks.changed' всем активным WebSocket-клиентам."""
    if not ACTIVE_SESSIONS_SET:
        return
    payload = orjson.dumps({
        "jsonrpc": "2.0",
        "method": "tasks.changed",
        "params": {}
    }).decode("utf-8")

    for s in list(ACTIVE_SESSIONS_SET):
        try:
            if not getattr(s, "_closed", True) and getattr(s, "ws", None):
                awaitable = s.ws.send_str(payload)
                if not hasattr(awaitable, "cancelled"):
                    try:
                        awaitable.cancelled = lambda: False
                    except AttributeError:
                        pass
                await awaitable
        except Exception:
            pass


@rpc_method("tasks.list")
@tabular_response(fields=["id", "title", "completed", "priority", "created_at"])
async def list_tasks(session: JsonRpcSession, params: dict):
    """
    Возвращает список всех задач.
    Благодаря декоратору @tabular_response ответ сериализуется в формате RFC 0002 ($tabular: true),
    что экономит 50-70% сетевого трафика.
    """
    async with async_session() as db:
        result = await db.execute(select(Task).order_by(Task.id.desc()))
        tasks = result.scalars().all()
        return [t.to_dict() for t in tasks]


@rpc_method("tasks.add")
async def add_task(session: JsonRpcSession, params: dict):
    """Создает новую задачу и уведомляет всех подключенных клиентов."""
    title = (params.get("title") or "").strip()
    if not title:
        raise RPCError("Название задачи не может быть пустым")
    
    priority = params.get("priority", "normal")
    if priority not in ("low", "normal", "high"):
        priority = "normal"

    async with async_session() as db:
        task = Task(title=title, priority=priority, completed=False)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_data = task.to_dict()

    # Уведомляем остальные вкладки
    asyncio.create_task(broadcast_tasks_updated())
    return task_data


@rpc_method("tasks.toggle")
async def toggle_task(session: JsonRpcSession, params: dict):
    """Переключает статус выполнения задачи (completed)."""
    task_id = params.get("id")
    if not task_id:
        raise RPCError("Не указан ID задачи")

    async with async_session() as db:
        result = await db.execute(select(Task).where(Task.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            raise RPCError(f"Задача #{task_id} не найдена")

        task.completed = not task.completed
        await db.commit()
        await db.refresh(task)
        task_data = task.to_dict()

    asyncio.create_task(broadcast_tasks_updated())
    return task_data


@rpc_method("tasks.delete")
async def delete_task(session: JsonRpcSession, params: dict):
    """Удаляет задачу."""
    task_id = params.get("id")
    if not task_id:
        raise RPCError("Не указан ID задачи")

    async with async_session() as db:
        result = await db.execute(select(Task).where(Task.id == int(task_id)))
        task = result.scalar_one_or_none()
        if not task:
            raise RPCError(f"Задача #{task_id} не найдена")

        await db.delete(task)
        await db.commit()

    asyncio.create_task(broadcast_tasks_updated())
    return {"deleted": True, "id": task_id}


@rpc_method("stream.heavy_job")
async def heavy_job(session: JsonRpcSession, params: dict):
    """
    Демонстрация Multi-return потокового стриминга (stream: true).
    Сервер отправляет клиенту промежуточные чанки с прогрессом длинной задачи
    без блокировки других запросов в сокете!
    """
    rpc_id = current_rpc_id_ctx.get()
    steps = [
        (20, "Инициализация данных и прогрев кэша..."),
        (40, "Анализ записей базы данных..."),
        (60, "Сжатие детерминированных структур..."),
        (80, "Генерация отчета и подсчет контрольных сумм..."),
    ]

    for pct, message in steps:
        await asyncio.sleep(0.35)
        await session.send_stream_chunk(rpc_id, {
            "progress": pct,
            "message": message
        })

    await asyncio.sleep(0.35)
    # Финальный результат завершает RPC-запрос
    return {
        "progress": 100,
        "message": "Операция успешно завершена!",
        "summary": "Обработано 1,000 записей за 1.75 сек."
    }


@rpc_method("auth.set_role")
async def set_role(session: JsonRpcSession, params: dict):
    """
    Демонстрация смены роли текущей сессии для проверки системы прав.
    Допустимые роли: 'guest', 'user', 'admin'.
    """
    role_name = (params.get("role") or "guest").lower()
    if role_name == "admin":
        session.user_role = UserRole.ADMIN
    elif role_name == "user":
        session.user_role = UserRole.USER
    else:
        session.user_role = UserRole.GUEST

    return {
        "session_id": session.session_id,
        "role": session.user_role.value if hasattr(session.user_role, "value") else str(session.user_role)
    }


@rpc_method("admin.system_info", role=UserRole.ADMIN)
async def admin_system_info(session: JsonRpcSession, params: dict):
    """
    Защищенный метод ядра: доступен ТОЛЬКО при наличии роли admin.
    Если роли нет — ядро автоматически вернет RPCError с кодом ошибки.
    """
    import sys
    import platform
    return {
        "status": "authorized",
        "active_sessions_count": len(ACTIVE_SESSIONS_SET),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "granian_workers": 1,
    }
