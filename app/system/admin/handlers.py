import asyncio
from typing import Optional, List, Dict, Any

from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.system.db import async_session
from core.session import rpc_method, RPCError, JsonRpcSession, ACTIVE_SESSIONS_SET, current_rpc_id_ctx
from app.session import Session
from core.logger import logger
# Импорты обновлены в рамках реструктуризации: перенос auth в system/auth
from app.system.auth.models import User, ActiveSession
from app.system.auth.handlers import session_bus, notify_session_change
from core.constants import UserRole
from core.router import http_route
import orjson

class AdminHandlers:
    """
    Класс, содержащий RPC-хендлеры для административных функций.
    """

    @staticmethod
    async def _get_sessions_data(current_session_db_id: Optional[int], username_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получает данные об активных сессиях из базы данных.
        """
        # Импорт обновлен в рамках реструктуризации: перенос auth в system/auth
        from app.system.auth.core import system_bypass_ctx
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(ActiveSession).options(selectinload(ActiveSession.user))
                if username_filter:
                    stmt = stmt.join(ActiveSession.user).where(User.login.ilike(f"%{username_filter}%"))
                
                result = await db.execute(stmt)
                sessions = result.scalars().all()
        finally:
            system_bypass_ctx.reset(bypass_token)
        
        result_data = []
        for s in sessions:
            result_data.append({
                "id": s.id,
                "username": s.user.login,
                "user_agent": s.user_agent,
                "ip_address": s.ip_address,
                "started_at": s.created_at.isoformat(),
                "is_current": s.id == current_session_db_id
            })
        return result_data

    @staticmethod
    @rpc_method("admin.watch_sessions")
    async def handle_watch_sessions(session: Session, args: Dict[str, Any]) -> None:
        """
        Запускает живой поток (stream) активных пользовательских сессий.

        Args:
            args (dict):
                - username (str, optional): Фильтр по имени пользователя.

        Returns:
            None: Метод работает в режиме стрима (отправляет порции данных через WebSocket).
        """
        payload: Dict[str, Any] = args if isinstance(args, dict) else {}
        username_filter: Optional[str] = str(payload.get("username", "")).strip()
        if not username_filter:
            username_filter = None
        
        rpc_id = current_rpc_id_ctx.get()

        user_id = session.uid if session else None
        db_id = session.session_db_id if session else None
        logger.info(f"[ADMIN] Начало стрима для пользователя {user_id} (ID запроса: {rpc_id})")

        data = await AdminHandlers._get_sessions_data(db_id, username_filter)
        await session.send_stream_chunk(rpc_id, data)
        
        try:
            while True:
                async with session_bus:
                    await session_bus.wait()
                
                if session._closed:
                    break
                    
                data = await AdminHandlers._get_sessions_data(db_id, username_filter)
                await session.send_stream_chunk(rpc_id, data)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            logger.info(f"[ADMIN] Стрим {rpc_id} для {user_id} завершен")

    @staticmethod
    @rpc_method("admin.terminate_session")
    async def handle_terminate(session: Session, args: Dict[str, Any]) -> bool:
        """
        Завершает принудительно активную пользовательскую сессию.

        Args:
            args (dict):
                - session_id (int): ID завершаемой сессии.

        Returns:
            bool: True при успешном завершении.
        """
        sid: Optional[int] = args.get("session_id")
        if not isinstance(sid, int):
            raise RPCError("Неверный формат session_id")

        async with async_session() as db:
            stmt = delete(ActiveSession).where(ActiveSession.id == sid)
            await db.execute(stmt)
            await db.commit()

        # Находим активную сессию в памяти и принудительно закрываем WebSocket соединение
        for s in ACTIVE_SESSIONS_SET:
            s_db_id = s.data.session_db_id if s.data else None
            if s_db_id == sid:
                logger.info(f"[ADMIN] Закрываем активное WebSocket-соединение для сессии #{sid}")
                asyncio.create_task(s.ws.close(code=4000, message=b"Terminated by admin"))
                break

        admin_id = session.uid if session else None
        logger.info(f"[ADMIN] Сессия #{sid} удалена админом {admin_id}")
        asyncio.create_task(notify_session_change())
        return True

    @staticmethod
    @rpc_method("admin.clear_external_data_cache")
    async def handle_clear_external_data_cache(session: Session, args: Dict[str, Any]) -> bool:
        """
        Очищает L1 RAM-кэш и удаляет все записи из L2 базы данных кэша внешних данных.

        Args:
            args (dict): Пустой словарь (аргументы не требуются).

        Returns:
            bool: True при успешной очистке.
        """
        from app.external_data.fetcher import clear_external_data_cache
        try:
            await clear_external_data_cache()
            return True
        except Exception as e:
            logger.error(f"[ADMIN] Ошибка при очистке кэша внешних данных: {e}")
            raise RPCError(f"Ошибка при очистке кэша: {str(e)}")

    @staticmethod
    @rpc_method("admin.get_api_docs", role=UserRole.ADMIN)
    async def handle_get_api_docs(session: Session, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Возвращает сгенерированную JSON-документацию к HTTP-RPC методам из БД.
        """
        # Импорт обновлен в рамках реструктуризации: перенос auth в system/auth
        from app.system.auth.models import SystemData
        async with async_session() as db:
            stmt = select(SystemData).where(SystemData.key == "http_rpc_api_docs")
            res = await db.execute(stmt)
            sys_data = res.scalar_one_or_none()
            if sys_data and sys_data.value:
                return sys_data.value
            return []

    @staticmethod
    @rpc_method("admin.test_api_endpoint", role=UserRole.ADMIN)
    async def handle_test_api_endpoint(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Вызывает указанный HTTP-RPC метод внутри процесса бэкенда для тестирования в песочнице.
        """
        from core.session import RPC_REGISTRY, RPCError
        method_name = args.get("method")
        params = args.get("params", {})

        if not isinstance(method_name, str):
            raise RPCError("Неверный формат имени метода")

        handler = RPC_REGISTRY.get(method_name)
        if not handler or not getattr(handler, "http", False):
            raise RPCError(f"Метод '{method_name}' не найден или недоступен для HTTP-RPC")

        try:
            result = await handler(session, params)
            return {"success": True, "result": result}
        except RPCError as e:
            return {"success": False, "error": e.message}
        except Exception as e:
            logger.error(f"[ADMIN] Ошибка при тестовом вызове метода '{method_name}': {e}", exc_info=True)
            return {"success": False, "error": f"Внутренняя ошибка сервера: {str(e)}"}

    @staticmethod
    @rpc_method("admin.list_roles", role=UserRole.ADMIN)
    async def handle_list_roles(session: Session, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Возвращает список всех ролей с их пермитами.
        """
        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Role
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
                result = await db.execute(stmt)
                roles = result.scalars().all()
                return [{
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "permissions": [{
                        "model_name": p.model_name,
                        "can_create": p.can_create,
                        "can_read": p.can_read,
                        "can_update": p.can_update,
                        "can_delete": p.can_delete,
                        "row_level_only": p.row_level_only
                    } for p in r.permissions]
                } for r in roles]
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.get_secure_models", role=UserRole.ADMIN)
    async def handle_get_secure_models(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Возвращает списки всех зарегистрированных моделей, которые наследуются от BasicSecureModel и RowSecureModel.
        """
        from app.system.auth.core import BasicSecureModel, RowSecureModel
        
        def get_subclasses(cls):
            subclasses = set()
            for sub in cls.__subclasses__():
                is_abstract = sub.__dict__.get("__abstract__", False)
                if not is_abstract:
                    subclasses.add(sub)
                subclasses.update(get_subclasses(sub))
            return subclasses

        row_classes = get_subclasses(RowSecureModel)
        all_basic_classes = get_subclasses(BasicSecureModel)
        
        basic_classes = all_basic_classes - row_classes

        labels = {
            "Order": "Заявки",
            "Bank": "Банки",
            "Passport": "Паспорта",
            "PassportCommission": "Тарифы",
            "User": "Пользователи",
            "Role": "Роли",
            "RolePermission": "Права ролей",
            "Team": "Команды",
        }

        def format_cls(cls):
            name = cls.__name__
            label = labels.get(name)
            if not label and cls.__doc__:
                doc = cls.__doc__.strip().split("\n")[0].strip().rstrip(".")
                if doc:
                    label = doc
            if not label:
                label = name
            return {
                "id": name,
                "label": f"{label} ({name})"
            }

        return {
            "basic_models": sorted([format_cls(c) for c in basic_classes], key=lambda x: x["id"]),
            "row_models": sorted([format_cls(c) for c in row_classes], key=lambda x: x["id"])
        }

    @staticmethod
    @rpc_method("admin.create_role", role=UserRole.ADMIN)
    async def handle_create_role(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает новую роль и привязанные к ней разрешения.
        """
        name = args.get("name")
        description = args.get("description", "")
        permissions = args.get("permissions", [])

        if not name or not isinstance(name, str) or not name.strip():
            raise RPCError("Имя роли обязательно")

        name = name.strip()
        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Role, RolePermission
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt_uniq = select(Role).where(Role.name == name)
                if (await db.execute(stmt_uniq)).scalar_one_or_none():
                    raise RPCError(f"Роль с именем '{name}' уже существует")

                role = Role(name=name, description=description)
                if session and session.uid:
                    role.creator_id = session.uid
                db.add(role)
                await db.flush()

                for p in permissions:
                    rp = RolePermission(
                        role_id=role.id,
                        model_name=p.get("model_name"),
                        can_create=bool(p.get("can_create")),
                        can_read=bool(p.get("can_read")),
                        can_update=bool(p.get("can_update")),
                        can_delete=bool(p.get("can_delete")),
                        row_level_only=bool(p.get("row_level_only", True))
                    )
                    if session and session.uid:
                        rp.creator_id = session.uid
                    db.add(rp)

                await db.commit()
                await db.refresh(role)

                stmt_full = select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
                role_new = (await db.execute(stmt_full)).scalar_one()

                return {
                    "id": role_new.id,
                    "name": role_new.name,
                    "description": role_new.description,
                    "permissions": [{
                        "model_name": p.model_name,
                        "can_create": p.can_create,
                        "can_read": p.can_read,
                        "can_update": p.can_update,
                        "can_delete": p.can_delete,
                        "row_level_only": p.row_level_only
                    } for p in role_new.permissions]
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.update_role", role=UserRole.ADMIN)
    async def handle_update_role(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновляет данные роли и её разрешения.
        """
        role_id = args.get("id")
        name = args.get("name")
        description = args.get("description", "")
        permissions = args.get("permissions", [])

        if not role_id or not isinstance(role_id, int):
            raise RPCError("Неверный ID роли")
        if not name or not isinstance(name, str) or not name.strip():
            raise RPCError("Имя роли обязательно")

        name = name.strip()
        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Role, RolePermission
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt_uniq = select(Role).where(Role.name == name, Role.id != role_id)
                if (await db.execute(stmt_uniq)).scalar_one_or_none():
                    raise RPCError(f"Роль с именем '{name}' уже существует")

                stmt = select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
                role = (await db.execute(stmt)).scalar_one_or_none()
                if not role:
                    raise RPCError("Роль не найдена")

                role.name = name
                role.description = description

                stmt_del = delete(RolePermission).where(RolePermission.role_id == role_id)
                await db.execute(stmt_del)

                for p in permissions:
                    rp = RolePermission(
                        role_id=role.id,
                        model_name=p.get("model_name"),
                        can_create=bool(p.get("can_create")),
                        can_read=bool(p.get("can_read")),
                        can_update=bool(p.get("can_update")),
                        can_delete=bool(p.get("can_delete")),
                        row_level_only=bool(p.get("row_level_only", True))
                    )
                    if session and session.uid:
                        rp.creator_id = session.uid
                    db.add(rp)

                await db.commit()
                await db.refresh(role)

                stmt_full = select(Role).options(selectinload(Role.permissions)).where(Role.id == role.id)
                role_new = (await db.execute(stmt_full)).scalar_one()

                return {
                    "id": role_new.id,
                    "name": role_new.name,
                    "description": role_new.description,
                    "permissions": [{
                        "model_name": p.model_name,
                        "can_create": p.can_create,
                        "can_read": p.can_read,
                        "can_update": p.can_update,
                        "can_delete": p.can_delete,
                        "row_level_only": p.row_level_only
                    } for p in role_new.permissions]
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.delete_role", role=UserRole.ADMIN)
    async def handle_delete_role(session: Session, args: Dict[str, Any]) -> bool:
        """
        Удаляет роль.
        """
        role_id = args.get("id")
        if not role_id or not isinstance(role_id, int):
            raise RPCError("Неверный ID роли")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Role
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(Role).where(Role.id == role_id)
                role = (await db.execute(stmt)).scalar_one_or_none()
                if not role:
                    raise RPCError("Роль не найдена")

                if role.name == "admin":
                    raise RPCError("Системную роль 'admin' нельзя удалить")

                await db.delete(role)
                await db.commit()
                return True
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.list_teams", role=UserRole.ADMIN)
    async def handle_list_teams(session: Session, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Возвращает список всех команд.
        """
        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Team
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(Team).order_by(Team.name)
                res = await db.execute(stmt)
                teams = res.scalars().all()
                return [{
                    "id": t.id,
                    "name": t.name,
                    "creator_id": t.creator_id,
                    "team_id": t.team_id,
                    "created_at": t.created_at.isoformat() if t.created_at else None
                } for t in teams]
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.create_team", role=UserRole.ADMIN)
    async def handle_create_team(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает новую команду.
        """
        name = args.get("name")
        if not name or not isinstance(name, str):
            raise RPCError("Имя команды обязательно")
        
        name = name.strip()
        if not name:
            raise RPCError("Имя команды не может быть пустым")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Team
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                # Проверим, существует ли уже команда с таким именем
                stmt = select(Team).where(Team.name == name)
                res = await db.execute(stmt)
                if res.scalar_one_or_none():
                    raise RPCError(f"Команда с именем '{name}' уже существует")

                team = Team(name=name)
                if session and session.uid:
                    team.creator_id = session.uid
                db.add(team)
                await db.commit()
                await db.refresh(team)
                return {
                    "id": team.id,
                    "name": team.name,
                    "creator_id": team.creator_id,
                    "team_id": team.team_id,
                    "created_at": team.created_at.isoformat() if team.created_at else None
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.update_team", role=UserRole.ADMIN)
    async def handle_update_team(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновляет имя команды.
        """
        team_id = args.get("id")
        name = args.get("name")
        if not team_id or not isinstance(team_id, int):
            raise RPCError("Неверный ID команды")
        if not name or not isinstance(name, str):
            raise RPCError("Имя команды обязательно")
        
        name = name.strip()
        if not name:
            raise RPCError("Имя команды не может быть пустым")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Team
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt_uniq = select(Team).where(Team.name == name, Team.id != team_id)
                res_uniq = await db.execute(stmt_uniq)
                if res_uniq.scalar_one_or_none():
                    raise RPCError(f"Команда с именем '{name}' уже существует")

                stmt = select(Team).where(Team.id == team_id)
                res = await db.execute(stmt)
                team = res.scalar_one_or_none()
                if not team:
                    raise RPCError("Команда не найдена")

                team.name = name
                await db.commit()
                await db.refresh(team)
                return {
                    "id": team.id,
                    "name": team.name,
                    "creator_id": team.creator_id,
                    "team_id": team.team_id,
                    "created_at": team.created_at.isoformat() if team.created_at else None
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.delete_team", role=UserRole.ADMIN)
    async def handle_delete_team(session: Session, args: Dict[str, Any]) -> bool:
        """
        Удаляет команду.
        """
        team_id = args.get("id")
        if not team_id or not isinstance(team_id, int):
            raise RPCError("Неверный ID команды")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import Team, User
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(Team).where(Team.id == team_id)
                res = await db.execute(stmt)
                team = res.scalar_one_or_none()
                if not team:
                    raise RPCError("Команда не найдена")

                stmt_users = select(User).where(User.primary_team_id == team_id)
                res_users = await db.execute(stmt_users)
                for u in res_users.scalars().all():
                    u.primary_team_id = None

                await db.delete(team)
                await db.commit()
                return True
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.list_users", role=UserRole.ADMIN)
    async def handle_list_users(session: Session, args: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Возвращает список всех пользователей.
        """
        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import User
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(User).options(
                    selectinload(User.roles),
                    selectinload(User.teams)
                ).order_by(User.id)
                res = await db.execute(stmt)
                users = res.scalars().all()
                return [{
                    "id": u.id,
                    "login": u.login,
                    "name": u.name,
                    "email": u.email,
                    "first_name": u.first_name,
                    "middle_name": u.middle_name,
                    "last_name": u.last_name,
                    "primary_team_id": u.primary_team_id,
                    "roles": [r.id for r in u.roles],
                    "teams": [t.id for t in u.teams]
                } for u in users]
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.create_user", role=UserRole.ADMIN)
    async def handle_create_user(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создает нового пользователя.
        """
        login = args.get("login")
        name = args.get("name")
        password = args.get("password")
        if not login or not isinstance(login, str):
            raise RPCError("Логин обязателен")
        if not name or not isinstance(name, str):
            raise RPCError("Отображаемое имя обязательно")
        if not password or not isinstance(password, str):
            raise RPCError("Пароль обязателен")

        login = login.strip()
        name = name.strip()
        password = password.strip()

        if not login:
            raise RPCError("Логин не может быть пустым")
        if not name:
            raise RPCError("Отображаемое имя не может быть пустым")
        if not password:
            raise RPCError("Пароль не может быть пустым")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import User, Role, Team
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(User).where(User.login == login)
                res = await db.execute(stmt)
                if res.scalar_one_or_none():
                    raise RPCError(f"Пользователь с логином '{login}' уже существует")

                user = User(
                    login=login,
                    name=name,
                    email=args.get("email"),
                    first_name=args.get("first_name"),
                    middle_name=args.get("middle_name"),
                    last_name=args.get("last_name"),
                    primary_team_id=args.get("primary_team_id")
                )
                user.password_hash = User._hash_password(password)
                if session and session.uid:
                    user.creator_id = session.uid

                role_ids = args.get("roles", [])
                if role_ids:
                    stmt_roles = select(Role).where(Role.id.in_(role_ids))
                    res_roles = await db.execute(stmt_roles)
                    user.roles = list(res_roles.scalars().all())

                team_ids = args.get("teams", [])
                if team_ids:
                    stmt_teams = select(Team).where(Team.id.in_(team_ids))
                    res_teams = await db.execute(stmt_teams)
                    user.teams = list(res_teams.scalars().all())

                db.add(user)
                await db.commit()
                await db.refresh(user)

                return {
                    "id": user.id,
                    "login": user.login,
                    "name": user.name,
                    "email": user.email,
                    "first_name": user.first_name,
                    "middle_name": user.middle_name,
                    "last_name": user.last_name,
                    "primary_team_id": user.primary_team_id,
                    "roles": [r.id for r in user.roles],
                    "teams": [t.id for t in user.teams]
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.update_user", role=UserRole.ADMIN)
    async def handle_update_user(session: Session, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Обновляет данные пользователя.
        """
        user_id = args.get("id")
        if not user_id or not isinstance(user_id, int):
            raise RPCError("Неверный ID пользователя")

        login = args.get("login")
        name = args.get("name")
        if not login or not isinstance(login, str):
            raise RPCError("Логин обязателен")
        if not name or not isinstance(name, str):
            raise RPCError("Отображаемое имя обязательно")

        login = login.strip()
        name = name.strip()
        if not login:
            raise RPCError("Логин не может быть пустым")
        if not name:
            raise RPCError("Отображаемое имя не может быть пустым")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import User, Role, Team
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt_uniq = select(User).where(User.login == login, User.id != user_id)
                res_uniq = await db.execute(stmt_uniq)
                if res_uniq.scalar_one_or_none():
                    raise RPCError(f"Логин '{login}' уже занят другим пользователем")

                stmt = select(User).options(
                    selectinload(User.roles),
                    selectinload(User.teams)
                ).where(User.id == user_id)
                res = await db.execute(stmt)
                user = res.scalar_one_or_none()
                if not user:
                    raise RPCError("Пользователь не найден")

                user.login = login
                user.name = name
                user.email = args.get("email")
                user.first_name = args.get("first_name")
                user.middle_name = args.get("middle_name")
                user.last_name = args.get("last_name")
                user.primary_team_id = args.get("primary_team_id")

                password = args.get("password")
                if password and isinstance(password, str):
                    password = password.strip()
                    if password:
                        user.password_hash = User._hash_password(password)

                role_ids = args.get("roles")
                if isinstance(role_ids, list):
                    if role_ids:
                        stmt_roles = select(Role).where(Role.id.in_(role_ids))
                        res_roles = await db.execute(stmt_roles)
                        user.roles = list(res_roles.scalars().all())
                    else:
                        user.roles = []

                team_ids = args.get("teams")
                if isinstance(team_ids, list):
                    if team_ids:
                        stmt_teams = select(Team).where(Team.id.in_(team_ids))
                        res_teams = await db.execute(stmt_teams)
                        user.teams = list(res_teams.scalars().all())
                    else:
                        user.teams = []

                await db.commit()
                await db.refresh(user)

                return {
                    "id": user.id,
                    "login": user.login,
                    "name": user.name,
                    "email": user.email,
                    "first_name": user.first_name,
                    "middle_name": user.middle_name,
                    "last_name": user.last_name,
                    "primary_team_id": user.primary_team_id,
                    "roles": [r.id for r in user.roles],
                    "teams": [t.id for t in user.teams]
                }
        finally:
            system_bypass_ctx.reset(bypass_token)

    @staticmethod
    @rpc_method("admin.delete_user", role=UserRole.ADMIN)
    async def handle_delete_user(session: Session, args: Dict[str, Any]) -> bool:
        """
        Удаляет пользователя.
        """
        user_id = args.get("id")
        if not user_id or not isinstance(user_id, int):
            raise RPCError("Неверный ID пользователя")

        if session and session.uid == user_id:
            raise RPCError("Нельзя удалить самого себя")

        from app.system.auth.core import system_bypass_ctx
        from app.system.auth.models import User
        bypass_token = system_bypass_ctx.set(True)
        try:
            async with async_session() as db:
                stmt = select(User).where(User.id == user_id)
                res = await db.execute(stmt)
                user = res.scalar_one_or_none()
                if not user:
                    raise RPCError("Пользователь не найден")

                await db.delete(user)
                await db.commit()
                return True
        finally:
            system_bypass_ctx.reset(bypass_token)


@http_route("/client_log", methods=["POST"])
async def handle_client_log(scope, proto):
    """
    HTTP POST эндпоинт для приема логов консоли фронтенда.
    """
    try:
        body = bytearray()
        async for chunk in proto:
            body.extend(chunk)
        
        if body:
            data = orjson.loads(body)
            level = data.get("level", "LOG")
            message = data.get("message", "")
            
            # Логируем с пометкой уровня
            if level == "ERROR":
                logger.error(f"[БРАУЗЕР] {message}")
            elif level == "WARN":
                logger.warning(f"[БРАУЗЕР] {message}")
            else:
                logger.info(f"[БРАУЗЕР] {message}")
                
        # Возвращаем 200 OK (метод синхронный в RSGI Granian, не требует await)
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*"),
                ("access-control-allow-headers", "content-type")
            ],
            body=orjson.dumps({"success": True}).decode("utf-8")
        )
    except Exception as e:
        logger.error(f"[ADMIN] Ошибка при обработке лога клиента: {e}")
        try:
            # В случае ошибки возвращаем 500
            proto.response_str(
                status=500,
                headers=[("content-type", "application/json")],
                body=orjson.dumps({"error": str(e)}).decode("utf-8")
            )
        except Exception:
            pass


@http_route("/settings.json", methods=["GET"])
async def handle_settings_json(scope, proto):
    """
    HTTP GET эндпоинт для предоставления настроек (интервал автореконнекта и статус логирования) фронтенду.
    Данные считываются из конфигурационного файла settings.yaml и его переопределений.
    """
    # Импортируем объект глобальных настроек приложения
    from app.config import settings
    try:
        # Получаем секцию настроек логгирования клиента
        client_logging = settings.get("client_logging")
        
        # Если секция настроек существует в конфигурационном файле
        if client_logging:
            # Считываем минимальный уровень логирования (по умолчанию "INFO")
            level = client_logging.get("level", "INFO")
            # Считываем интервал автореконнекта вебсокета (по умолчанию 3 секунды)
            reconnect_ws = client_logging.get("reconnect_ws", 3)
        else:
            # Значения по умолчанию, если секции нет в settings.yaml
            level = "INFO"
            reconnect_ws = 3
            
        # Формируем JSON-ответ для фронтенда
        response_data = {
            "client_logging_level": level,
            "reconnect_ws": reconnect_ws
        }
        
        # Отправляем успешный HTTP-ответ с JSON телом (метод синхронный, не требует await)
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=orjson.dumps(response_data).decode("utf-8")
        )
    except Exception as e:
        # Логируем ошибку, если не удалось прочитать настройки или отправить ответ
        logger.error(f"[ADMIN] Ошибка при обработке настроек для фронтенда: {e}", exc_info=True)
        try:
            # В случае ошибки возвращаем 500 статус с описанием
            proto.response_str(
                status=500,
                headers=[("content-type", "application/json")],
                body=orjson.dumps({"error": str(e)}).decode("utf-8")
            )
        except Exception:
            # Защита на случай повторного сбоя сокета ответа
            pass



