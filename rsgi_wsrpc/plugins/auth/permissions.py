# -*- coding: utf-8 -*-
"""
Проверка прав доступа (RBAC / Permissions) плагина авторизации.
"""

from rsgi_wsrpc.core.session import RPCError
from .core import current_user_ctx, system_bypass_ctx


def check_permissions(action: str, model_name: str, obj: object = None) -> None:
    """
    Проверяет права текущего пользователя на выполнение действия над моделью/объектом.
    Выбрасывает RPCError в случае отказа в доступе.

    :param action: 'create', 'read', 'update', 'delete'
    :param model_name: Имя модели, например, 'Diary'
    :param obj: (Опционально) Экземпляр объекта для проверки прав на уровне записи (row-level).
    """
    if system_bypass_ctx.get():
        return

    user_ctx = current_user_ctx.get()
    if not user_ctx:
        raise RPCError("Доступ запрещен: требуется аутентификация.")

    # Суперадминистратор имеет полный доступ ко всем ресурсам
    if getattr(user_ctx, "is_superadmin", False):
        return

    model_perms = getattr(user_ctx, "perms_dict", {}).get(model_name, {})

    # 1. Проверка права на само действие (can_create, can_update, etc.)
    if not model_perms.get(f"can_{action}", False):
        raise RPCError(f"Доступ запрещен: нет права '{action}' для '{model_name}'.")

    # 2. Проверка на уровне записи (если передан объект)
    if obj:
        is_global_perm = model_perms.get(f"{action}_global", False)
        if not is_global_perm:
            is_owner = hasattr(obj, "creator_id") and obj.creator_id == getattr(user_ctx, "user_id", None)
            team_ids = getattr(user_ctx, "team_ids", []) or []
            is_in_team = hasattr(obj, "team_id") and obj.team_id in team_ids

            if not (is_owner or is_in_team):
                raise RPCError(f"Доступ запрещен: нельзя выполнить '{action}' с чужим объектом '{model_name}'.")


def prefill_ownership(obj: object) -> None:
    """
    Заполняет поля creator_id и team_id для нового объекта из контекста пользователя.
    """
    if system_bypass_ctx.get():
        return

    user_ctx = current_user_ctx.get()
    if not user_ctx:
        return

    if hasattr(obj, "creator_id") and not obj.creator_id:
        obj.creator_id = getattr(user_ctx, "user_id", None)

    if hasattr(obj, "team_id") and not obj.team_id:
        team_ids = getattr(user_ctx, "team_ids", []) or []
        if team_ids:
            obj.team_id = team_ids[0]
