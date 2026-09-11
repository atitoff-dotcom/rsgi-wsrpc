from core.session import RPCError
# Импортируем контекст пользователя и флаг системного обхода прав
from app.system.auth.core import current_user_ctx, system_bypass_ctx

def check_permissions(action: str, model_name: str, obj: object = None):
    """
    Проверяет права текущего пользователя на выполнение действия над моделью/объектом.
    Выбрасывает RPCError в случае отказа в доступе.

    :param action: 'create', 'read', 'update', 'delete'
    :param model_name: Имя модели, например, 'Bank'
    :param obj: (Опционально) Экземпляр объекта для проверки прав на уровне записи (row-level).
    """
    if system_bypass_ctx.get():
        return

    user_ctx = current_user_ctx.get()
    if not user_ctx:
        raise RPCError("Доступ запрещен: требуется аутентификация.")

    model_perms = user_ctx.perms_dict.get(model_name, {})
    
    # 1. Проверка права на само действие (can_create, can_update, etc.)
    if not model_perms.get(f"can_{action}", False):
        raise RPCError(f"Доступ запрещен: нет права '{action}' для '{model_name}'.")

    # 2. Проверка на уровне записи (если передан объект)
    if obj:
        is_global_perm = model_perms.get(f"{action}_global", False)
        if not is_global_perm:
            # Проверяем, что пользователь является создателем или входит в команду объекта
            is_owner = hasattr(obj, 'creator_id') and obj.creator_id == user_ctx.user_id
            is_in_team = hasattr(obj, 'team_id') and obj.team_id in user_ctx.team_ids
            
            if not (is_owner or is_in_team):
                raise RPCError(f"Доступ запрещен: нельзя выполнить '{action}' с чужим объектом '{model_name}'.")

def prefill_ownership(obj: object):
    """
    Заполняет поля creator_id и team_id для нового объекта из контекста пользователя.
    """
    if system_bypass_ctx.get():
        return

    user_ctx = current_user_ctx.get()
    if not user_ctx:
        return # Should have been caught by check_permissions, but as a safeguard

    if hasattr(obj, 'creator_id') and not obj.creator_id:
        obj.creator_id = user_ctx.user_id
    
    if hasattr(obj, 'team_id') and not obj.team_id and user_ctx.team_ids:
        obj.team_id = user_ctx.team_ids[0] # Default to primary team
