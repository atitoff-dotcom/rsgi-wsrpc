from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import asyncio
import secrets
import uuid

from sqlalchemy import select, delete, or_
from sqlalchemy.orm import selectinload

from core.session import rpc_method, RPCError, JsonRpcSession
from core.constants import UserRole
from app.system.db import async_session
from core.security import generate_rsa_keypair, decrypt_rsa, create_access_token, verify_password
from core.logger import logger

# Импортируем необходимые модели из модуля аутентификации/авторизации (app.system.auth)
from app.system.auth.models import User, RefreshToken, ActiveSession
from app.system.auth.handlers import notify_session_change

# Глобальное хранилище для эфемерных приватных ключей RSA (для безопасного логина).
# Формат: {key_id: {"private_key_pem": str, "expires_at": datetime}}
ephemeral_keys: Dict[str, Dict[str, Any]] = {}

def cleanup_expired_keys() -> None:
    """
    Удаляет просроченные эфемерные ключи RSA из памяти.
    """
    now = datetime.now(timezone.utc)
    expired = [kid for kid, key_data in ephemeral_keys.items() if key_data["expires_at"] < now]
    for kid in expired:
        ephemeral_keys.pop(kid, None)

def generate_token() -> str:
    """
    Генерирует случайную токен-строку для RefreshToken.
    """
    return secrets.token_urlsafe(32)


@rpc_method("login.get_key")
async def handle_get_login_key(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Генерирует одноразовый публичный RSA-ключ для шифрования пароля на клиенте.

    Args:
        args (dict): Пустой словарь (аргументы не требуются).

    Returns:
        dict: Данные ключа:
            - public_key (str): Публичный ключ RSA в PEM-формате.
            - key_id (str): Уникальный UUID идентификатор ключа.
    """
    cleanup_expired_keys()
    
    private_pem, public_pem = generate_rsa_keypair()
    key_id = str(uuid.uuid4())
    
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=30)
    ephemeral_keys[key_id] = {
        "private_key_pem": private_pem,
        "expires_at": expires_at
    }
    
    logger.info(f"[Логинизация] Сгенерирован эфемерный ключ RSA #{key_id}. Действителен до {expires_at}.")
    return {"public_key": public_pem, "key_id": key_id}


@rpc_method("login.secure")
async def handle_login_secure(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет безопасный вход в систему с паролем, зашифрованным на клиенте публичным ключом RSA.

    Args:
        args (dict):
            - username (str): Логин пользователя.
            - encrypted_password (str): Пароль, зашифрованный с помощью публичного ключа RSA.
            - key_id (str): UUID идентификатор эфемерного публичного ключа RSA.
            - user_agent (str, optional): Строка User-Agent клиента (по умолчанию "unknown").

    Returns:
        dict: Данные успешной авторизации:
            - token (str): Токен обновления (RefreshToken).
            - jwt_token (str): JWT токен доступа для HTTP-RPC запросов.
            - role (str): Название первой роли пользователя.
    """
    cleanup_expired_keys()
    
    username: Optional[str] = args.get("username")
    encrypted_password: Optional[str] = args.get("encrypted_password")
    key_id: Optional[str] = args.get("key_id")
    user_agent: str = args.get("user_agent", "unknown")
    
    if not username or not encrypted_password or not key_id:
        logger.warning("[Логинизация] Попытка безопасного входа с неполными учетными данными.")
        raise RPCError("Неполные учетные данные")
        
    key_data = ephemeral_keys.get(key_id)
    if not key_data:
        logger.warning(f"[Логинизация] Попытка входа по несуществующему или истекшему ключу #{key_id}.")
        raise RPCError("Сессия авторизации истекла или недействительна")
        
    ephemeral_keys.pop(key_id, None)
    
    if key_data["expires_at"] < datetime.now(timezone.utc):
        logger.warning(f"[Логинизация] Ключ #{key_id} просрочен.")
        raise RPCError("Сессия авторизации истекла")
        
    try:
        # Расшифровываем пароль с помощью соответствующего приватного ключа
        password = decrypt_rsa(key_data["private_key_pem"], encrypted_password)
    except Exception as e:
        logger.error(f"[Логинизация] Ошибка дешифрования пароля для '{username}': {e}", exc_info=True)
        raise RPCError("Ошибка дешифрования данных")
        
    from app.system.auth.core import system_bypass_ctx
    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            # Поскольку selectinload требует правильного импорта класса Role, импортируем его локально
            from app.system.auth.models import Role
            stmt = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(or_(User.login == username, User.email == username))
            
            user = (await db_session.execute(stmt)).scalar_one_or_none()
            if not user or not user.verify_password(password):
                logger.warning(f"[Логинизация] Неудачная попытка входа для пользователя '{username}'.")
                raise RPCError("Неверный логин или пароль")

            rt_str: str = generate_token()
            
            # Удаляем старые токены обновления пользователя
            stmt_del = delete(RefreshToken).where(RefreshToken.user_id == user.id)
            await db_session.execute(stmt_del)
            
            # Создаем новый токен обновления
            rt_obj = RefreshToken(
                user_id=user.id, token=rt_str, 
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
            db_session.add(rt_obj)
            await db_session.flush()

            # Создаем запись об активной сессии WebSocket
            ws_session = ActiveSession(
                user_id=user.id, 
                ip_address=getattr(session, "ip", "0.0.0.0") or "0.0.0.0", 
                user_agent=user_agent, 
                refresh_token_id=rt_obj.id
            )
            db_session.add(ws_session)
            await db_session.commit()
            await db_session.refresh(ws_session)

            user_context = user.get_permissions()
            user_roles = user.roles
            role_name = user_roles[0].name if user_roles else "guest"
            role_names = [r.name for r in user_roles] if user_roles else ["guest"]

            # Выдаем короткоживущий JWT-токен для авторизации HTTP/RPC
            jwt_token, _, _ = create_access_token(
                user_id=user.id,
                username=user.login,
                roles=role_names,
                user_agent=user_agent
            )

            # Заполняем поля сессии для прохождения последующих проверок прав
            from app.system.auth.core import current_user_ctx
            from app.session import Session as AppSession
            from app.system.auth.handlers import cleanup_app_session
            from core.session import current_transport_ctx
            transport = current_transport_ctx.get()

            current_user_ctx.set(user_context)
            app_session = AppSession(
                uid=user.id,
                user=user,
                user_name=user.login,
                user_role=UserRole(role_name),
                user_roles=role_names,
                session_db_id=ws_session.id,
                user_ctx=user_context,
                send_request_cb=transport.send_request if transport else session.send_request,
                send_stream_cb=transport.send_stream_chunk if transport else session.send_stream_chunk,
                close_cb=transport.close if transport else session.close
            )
            if transport:
                transport.data = app_session
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = app_session
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(token)

    logger.info(f"[Логинизация] Пользователь '{username}' успешно авторизован через Secure Login. ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())
    return {
        "token": rt_str,
        "jwt_token": jwt_token,
        "user_id": user.id,
        "username": user.login,
        "name": user.name or user.login,
        "email": user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict,
        "is_superadmin": user_context.is_superadmin
    }


@rpc_method("login.submit")
async def handle_login(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Обычный вход пользователя по логину и открытому паролю (например, для локальной разработки).

    Args:
        args (dict):
            - username (str): Логин пользователя.
            - password (str): Пароль в открытом виде.
            - user_agent (str, optional): Строка User-Agent клиента (по умолчанию "unknown").

    Returns:
        dict: Данные успешной авторизации:
            - token (str): Токен обновления (RefreshToken).
            - jwt_token (str): JWT токен доступа для HTTP-RPC запросов.
            - role (str): Название первой роли пользователя.
            - roles (list): Список названий всех ролей пользователя.
    """
    username: Optional[str] = args.get("username")
    password: Optional[str] = args.get("password")
    user_agent: str = args.get("user_agent", "unknown")

    if not username or not password:
        logger.warning("[Логинизация] Попытка входа с незаполненными учетными данными.")
        raise RPCError("Требуются имя пользователя и пароль")

    from app.system.auth.core import system_bypass_ctx
    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            from app.system.auth.models import Role
            stmt = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(or_(User.login == username, User.email == username))
            
            user = (await db_session.execute(stmt)).scalar_one_or_none()
            if not user or not user.verify_password(password):
                logger.warning(f"[Логинизация] Неудачная попытка входа для '{username}' (неверный пароль).")
                raise RPCError("Неверный логин или пароль")

            rt_str: str = generate_token()
            
            stmt_del = delete(RefreshToken).where(RefreshToken.user_id == user.id)
            await db_session.execute(stmt_del)
            
            rt_obj = RefreshToken(
                user_id=user.id, token=rt_str, 
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
            db_session.add(rt_obj)
            await db_session.flush()

            ws_session = ActiveSession(
                user_id=user.id, 
                ip_address=getattr(session, "ip", "0.0.0.0") or "0.0.0.0", 
                user_agent=user_agent, 
                refresh_token_id=rt_obj.id
            )
            db_session.add(ws_session)
            await db_session.commit()
            await db_session.refresh(ws_session)

            user_context = user.get_permissions()
            user_roles = user.roles
            role_name = user_roles[0].name if user_roles else UserRole.GUEST
            role_names = [role.name for role in user_roles] if user_roles else [UserRole.GUEST]

            jwt_token, _, _ = create_access_token(
                user_id=user.id,
                username=user.login,
                roles=role_names,
                user_agent=user_agent
            )

            from app.system.auth.core import current_user_ctx
            from app.session import Session as AppSession
            from app.system.auth.handlers import cleanup_app_session
            from core.session import current_transport_ctx
            transport = current_transport_ctx.get()

            current_user_ctx.set(user_context)
            app_session = AppSession(
                uid=user.id,
                user=user,
                user_name=user.login,
                user_role=UserRole(role_name),
                user_roles=role_names,
                session_db_id=ws_session.id,
                user_ctx=user_context,
                send_request_cb=transport.send_request if transport else session.send_request,
                send_stream_cb=transport.send_stream_chunk if transport else session.send_stream_chunk,
                close_cb=transport.close if transport else session.close
            )
            if transport:
                transport.data = app_session
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = app_session
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(token)

    logger.info(f"[Логинизация] Пользователь '{username}' успешно авторизован. Создана ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())
    return {
        "token": rt_str,
        "jwt_token": jwt_token,
        "user_id": user.id,
        "username": user.login,
        "name": user.name or user.login,
        "email": user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict,
        "is_superadmin": user_context.is_superadmin
    }


@rpc_method("login.refresh")
async def handle_refresh_token(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет вход пользователя/продление сессии по ранее выданному токену обновления (RefreshToken).

    Args:
        args (dict):
            - token (str): Токен обновления (RefreshToken).
            - user_agent (str, optional): Строка User-Agent клиента (по умолчанию "unknown").

    Returns:
        dict: Продленные данные авторизации:
            - token (str): Токен обновления (тот же).
            - jwt_token (str): Новый JWT токен доступа.
            - role (str): Название первой роли пользователя.
            - roles (list): Список названий всех ролей пользователя.
    """
    token_str: Optional[str] = args.get("token")
    user_agent: str = args.get("user_agent", "unknown")

    if not token_str:
        raise RPCError("Токен не предоставлен")

    from app.system.auth.core import system_bypass_ctx
    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            from app.system.auth.models import Role
            stmt = select(RefreshToken).options(
                selectinload(RefreshToken.user).selectinload(User.roles).selectinload(Role.permissions),
                selectinload(RefreshToken.user).selectinload(User.teams)
            ).where(
                RefreshToken.token == token_str,
                RefreshToken.expires_at > datetime.now(timezone.utc)
            )
            rt_obj = (await db_session.execute(stmt)).scalar_one_or_none()

            if not rt_obj:
                logger.warning("[Логинизация] Попытка обновления сессии с недействительным или просроченным токеном.")
                raise RPCError("Сессия истекла или токен недействителен")
            
            ws_session = ActiveSession(
                user_id=rt_obj.user.id, 
                ip_address=getattr(session, "ip", "0.0.0.0") or "0.0.0.0", 
                user_agent=user_agent, 
                refresh_token_id=rt_obj.id
            )
            db_session.add(ws_session)
            await db_session.commit()
            await db_session.refresh(ws_session)

            user_context = rt_obj.user.get_permissions()
            user_roles = rt_obj.user.roles
            role_name = user_roles[0].name if user_roles else "guest"
            role_names = [role.name for role in user_roles]

            jwt_token, _, _ = create_access_token(
                user_id=rt_obj.user.id,
                username=rt_obj.user.login,
                roles=role_names,
                user_agent=user_agent
            )

            from app.system.auth.core import current_user_ctx
            from app.session import Session as AppSession
            from app.system.auth.handlers import cleanup_app_session
            from core.session import current_transport_ctx
            transport = current_transport_ctx.get()

            current_user_ctx.set(user_context)
            app_session = AppSession(
                uid=rt_obj.user.id,
                user=rt_obj.user,
                user_name=rt_obj.user.login,
                user_role=UserRole(role_name),
                user_roles=role_names,
                session_db_id=ws_session.id,
                user_ctx=user_context,
                send_request_cb=transport.send_request if transport else session.send_request,
                send_stream_cb=transport.send_stream_chunk if transport else session.send_stream_chunk,
                close_cb=transport.close if transport else session.close
            )
            if transport:
                transport.data = app_session
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = app_session
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(token)

    logger.info(f"[Логинизация] Сессия пользователя '{rt_obj.user.login}' успешно продлена через RefreshToken. ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())
    return {
        "token": token_str,
        "jwt_token": jwt_token,
        "user_id": rt_obj.user.id,
        "username": rt_obj.user.login,
        "name": rt_obj.user.name or rt_obj.user.login,
        "email": rt_obj.user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict,
        "is_superadmin": user_context.is_superadmin
    }


@rpc_method("login.whoami")
async def handle_whoami(session, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Возвращает информацию о текущем авторизованном пользователе в рамках данной WebSocket-сессии.

    Args:
        args (dict): Пустой словарь (аргументы не требуются).

    Returns:
        dict: Информация о пользователе:
            - authenticated (bool): Флаг авторизации.
            - user_id (int or None): ID пользователя или None.
            - role (str): Роль пользователя (например, "admin", "user", "guest").
    """
    from app.session import Session as AppSession
    if isinstance(session, AppSession):
        async with async_session() as db_session:
            from app.system.auth.models import Role
            stmt = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(User.id == session.uid)
            user = (await db_session.execute(stmt)).scalar_one_or_none()
            if user:
                user_context = user.get_permissions()
                user_roles = user.roles
                role_name = user_roles[0].name if user_roles else "guest"
                return {
                    "authenticated": True,
                    "user_id": session.uid,
                    "username": user.login,
                    "name": user.name or user.login,
                    "email": user.email,
                    "role": role_name,
                    "roles": [r.name for r in user_roles],
                    "permissions": user_context.perms_dict,
                    "is_superadmin": user_context.is_superadmin
                }
    return {"authenticated": False, "user_id": None, "username": None, "name": None, "email": None, "role": "guest", "roles": ["guest"], "permissions": {}, "is_superadmin": False}


@rpc_method("login.register")
async def handle_register(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Регистрация нового пользователя в системе Agrita.
    """
    username: Optional[str] = args.get("username")
    email: Optional[str] = args.get("email")
    password: Optional[str] = args.get("password")
    name: Optional[str] = args.get("name") or username

    if not username or not password:
        raise RPCError("Имя пользователя и пароль обязательны")
    if len(password) < 6:
        raise RPCError("Пароль должен быть не менее 6 символов")

    from app.system.auth.core import system_bypass_ctx
    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            from app.system.auth.models import Role
            # Проверяем уникальность логина
            stmt = select(User).where(User.login == username)
            existing = (await db_session.execute(stmt)).scalar_one_or_none()
            if existing:
                raise RPCError("Пользователь с таким именем уже существует")

            if email:
                stmt_email = select(User).where(User.email == email)
                existing_email = (await db_session.execute(stmt_email)).scalar_one_or_none()
                if existing_email:
                    raise RPCError("Пользователь с таким email уже существует")

            # Получаем роль user
            role_stmt = select(Role).where(Role.name == "user")
            user_role = (await db_session.execute(role_stmt)).scalar_one_or_none()

            pwd_hash = User._hash_password(password)
            new_user = User(
                name=name,
                login=username,
                email=email,
                password_hash=pwd_hash
            )
            if user_role:
                new_user.roles.append(user_role)

            db_session.add(new_user)
            await db_session.commit()
            await db_session.refresh(new_user)

            logger.info(f"[Регистрация] Зарегистрирован новый пользователь '{username}' (id={new_user.id}).")
            return {
                "success": True,
                "user_id": new_user.id,
                "username": new_user.login,
                "message": "Пользователь успешно зарегистрирован"
            }
    finally:
        system_bypass_ctx.reset(token)

