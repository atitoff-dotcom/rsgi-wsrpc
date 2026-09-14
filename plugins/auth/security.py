# -*- coding: utf-8 -*-
"""
Автоматический контроль прав доступа на уровне SQLAlchemy ORM (Row-Level Security).
Перехватывает события сессии do_orm_execute и before_flush.
"""

from typing import Any
from sqlalchemy import event, or_, inspect
from sqlalchemy.orm import ORMExecuteState, Session

from plugins.auth.core import current_user_ctx, system_bypass_ctx, BasicSecureModel, RowSecureModel
from core.logger import logger


@event.listens_for(Session, "do_orm_execute")
def _add_security_filters(execute_state: ORMExecuteState) -> None:
    """
    Автоматически накладывает ограничения на SELECT запросы к защищенным моделям.
    """
    if system_bypass_ctx.get():
        return

    # Проверяем, есть ли среди задействованных моделей защищенные
    secure_mappers = []
    for mapper in execute_state.all_mappers:
        if issubclass(mapper.class_, BasicSecureModel):
            secure_mappers.append(mapper)

    if not secure_mappers:
        return

    # Ограничения накладываем только на SELECT запросы
    if not execute_state.is_select:
        return

    current_user = current_user_ctx.get()
    if not current_user:
        raise PermissionError(
            "Пользователь не авторизован (отсутствует контекст пользователя)"
        )

    # Суперадминистратор видит все записи без ограничений
    if getattr(current_user, "is_superadmin", False):
        return

    for mapper in secure_mappers:
        model_cls = mapper.class_
        model_name = model_cls.__name__

        perms_dict = getattr(current_user, "perms_dict", {})
        user_perms = perms_dict.get(model_name)

        # Если нет прав на чтение данной модели — возвращаем пустой результат (WHERE 1=0)
        if not user_perms or not user_perms.get("can_read"):
            execute_state.statement = execute_state.statement.where(1 == 0)
            return

        # Если доступ не глобальный (только свои записи/команды), сужаем область видимости
        is_global = user_perms.get("read_global", False) or not issubclass(model_cls, RowSecureModel)
        if not is_global:
            user_id = getattr(current_user, "user_id", None)
            team_ids = getattr(current_user, "team_ids", []) or []

            conditions = []
            if hasattr(model_cls, "creator_id"):
                conditions.append(model_cls.creator_id == user_id)
            if hasattr(model_cls, "team_id") and team_ids:
                conditions.append(model_cls.team_id.in_(team_ids))

            if conditions:
                execute_state.statement = execute_state.statement.where(or_(*conditions))
            else:
                # Если у модели нет полей creator_id/team_id, но доступ ограничен — скрываем данные
                execute_state.statement = execute_state.statement.where(1 == 0)


@event.listens_for(Session, "before_flush")
def _validate_write_permissions(session: Session, flush_context: Any, instances: Any) -> None:
    """
    Выполняет проверку прав доступа перед фиксацией изменений (flush) в БД.
    """
    if system_bypass_ctx.get():
        return

    has_secure = False
    for collection in (session.new, session.dirty, session.deleted):
        for obj in collection:
            if isinstance(obj, BasicSecureModel):
                has_secure = True
                break
        if has_secure:
            break

    if not has_secure:
        return

    current_user = current_user_ctx.get()
    if not current_user:
        raise PermissionError(
            "Пользователь не авторизован (отсутствует контекст пользователя)"
        )

    is_superadmin = getattr(current_user, "is_superadmin", False)

    # 1. Валидация вставок (INSERT) и автозаполнение полей владельца
    for obj in session.new:
        if isinstance(obj, BasicSecureModel):
            if not is_superadmin:
                _check_cud_action(current_user, obj, "create")
            
            # Автозаполнение полей creator_id и team_id (только для моделей с Row-Level)
            if isinstance(obj, RowSecureModel):
                if not obj.creator_id:
                    obj.creator_id = getattr(current_user, "user_id", None)
                if not obj.team_id and getattr(current_user, "team_ids", None):
                    obj.team_id = current_user.team_ids[0]

    # 2. Валидация обновлений (UPDATE)
    for obj in session.dirty:
        if isinstance(obj, BasicSecureModel):
            state = inspect(obj)
            if state.modified:
                if not is_superadmin:
                    _check_cud_action(current_user, obj, "update")

    # 3. Валидация удалений (DELETE)
    for obj in session.deleted:
        if isinstance(obj, BasicSecureModel):
            if not is_superadmin:
                _check_cud_action(current_user, obj, "delete")


def _check_cud_action(current_user: Any, obj: BasicSecureModel, action: str) -> None:
    model_name = obj.__class__.__name__
    perms_dict = getattr(current_user, "perms_dict", {})
    user_perms = perms_dict.get(model_name)

    perm_key = f"can_{action}"
    global_key = f"{action}_global"

    if not user_perms or not user_perms.get(perm_key):
        raise PermissionError(
            f"Нет прав на действие {action} для модели {model_name}"
        )

    # Если модель не поддерживает row-level права (не наследуется от RowSecureModel),
    # то CUD действия разрешены на уровне всей модели, пропускаем проверки владельца.
    if not isinstance(obj, RowSecureModel):
        return

    is_global = user_perms.get(global_key, False)
    if not is_global:
        user_id = getattr(current_user, "user_id", None)
        team_ids = getattr(current_user, "team_ids", []) or []

        if action == "create":
            if obj.creator_id and obj.creator_id != user_id:
                raise PermissionError(
                    f"Нельзя создать запись для другого пользователя (creator_id={obj.creator_id})"
                )
            if obj.team_id and obj.team_id not in team_ids:
                raise PermissionError(
                    f"Нельзя создать запись для чужой команды (team_id={obj.team_id})"
                )
        else:
            creator_id = obj.creator_id
            team_id = obj.team_id

            is_owner = (creator_id == user_id)
            is_in_team = (team_id in team_ids)

            if not (is_owner or is_in_team):
                raise PermissionError(
                    f"Нет прав на изменение чужой записи в {model_name} (creator_id={creator_id}, team_id={team_id})"
                )

            if action == "update":
                state = inspect(obj)
                creator_history = state.attrs.creator_id.history if hasattr(obj, "creator_id") else None
                team_history = state.attrs.team_id.history if hasattr(obj, "team_id") else None

                if creator_history and creator_history.has_changes():
                    new_creator = creator_history.added[0] if creator_history.added else None
                    if new_creator and new_creator != user_id:
                        raise PermissionError(
                            f"Нельзя передать владение записью другому пользователю (creator_id={new_creator})"
                        )
                if team_history and team_history.has_changes():
                    new_team = team_history.added[0] if team_history.added else None
                    if new_team and new_team not in team_ids:
                        raise PermissionError(
                            f"Нельзя передать запись чужой команде (team_id={new_team})"
                        )
