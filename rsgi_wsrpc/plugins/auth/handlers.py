# -*- coding: utf-8 -*-
"""
RPC-хендлеры авторизации и аутентификации (plugins/auth/handlers.py).
Реализует безопасный вход (RSA / PBKDF2), скользящие сессии (Sliding Expiration),
OAuth2 провайдеры (VK, Yandex) и управление активными сессиями.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
import asyncio
import secrets
import uuid
import urllib.request
import urllib.parse
import urllib.error
import json

from sqlalchemy import select, delete, or_
from sqlalchemy.orm import selectinload

from rsgi_wsrpc.core.session import rpc_method, RPCError, JsonRpcSession
from rsgi_wsrpc.core.constants import UserRole
from rsgi_wsrpc.core.security import generate_rsa_keypair, decrypt_rsa, create_access_token, verify_password
from rsgi_wsrpc.core.logger import logger

from rsgi_wsrpc.plugins.db import async_session
from .models import User, Role, RefreshToken, ActiveSession, OAuthAccount
from .core import system_bypass_ctx, current_user_ctx
from .config import get_session_lifetime_days, get_max_active_sessions

# Уведомления об изменении сессий
session_bus = asyncio.Condition()

async def notify_session_change() -> None:
    """Уведомляет подписчиков об изменении активных сессий."""
    async with session_bus:
        session_bus.notify_all()

async def handle_ws_disconnect(session_id: int) -> None:
    """Удаляет активную сокетную сессию из БД при дисконнекте."""
    async with async_session() as db:
        stmt = delete(ActiveSession).where(ActiveSession.id == session_id)
        result = await db.execute(stmt)
        await db.commit()
        deleted = result.rowcount > 0
    if deleted:
        logger.info(f"[AUTH] Активная сессия #{session_id} удалена из БД (дисконнект)")
        asyncio.create_task(notify_session_change())

async def cleanup_app_session(session: JsonRpcSession) -> None:
    """Колбэк при закрытии сокета для освобождения сессии."""
    if hasattr(session, "data") and session.data and getattr(session.data, "session_db_id", None):
        await handle_ws_disconnect(session.data.session_db_id)


# Глобальное хранилище для эфемерных приватных ключей RSA
ephemeral_keys: Dict[str, Dict[str, Any]] = {}

def cleanup_expired_keys() -> None:
    now = datetime.now(timezone.utc)
    expired = [kid for kid, key_data in ephemeral_keys.items() if key_data["expires_at"] < now]
    for kid in expired:
        ephemeral_keys.pop(kid, None)

def generate_token() -> str:
    return secrets.token_hex(32)


async def issue_refresh_token(db_session, user_id: int) -> RefreshToken:
    """
    Создает новый RefreshToken со скользящим сроком жизни,
    удаляет истекшие токены и сдерживает лимит одновременных устройств пользователя.
    """
    lifetime_days = get_session_lifetime_days()
    max_sessions = get_max_active_sessions()
    now = datetime.now(timezone.utc)

    # 1. Удаляем только реально истекшие токены пользователя
    stmt_del_expired = delete(RefreshToken).where(
        RefreshToken.user_id == user_id,
        RefreshToken.expires_at <= now
    )
    await db_session.execute(stmt_del_expired)

    # 2. Если количество активных токенов превышает лимит, удаляем самые старые
    stmt_active = (
        select(RefreshToken)
        .where(RefreshToken.user_id == user_id)
        .order_by(RefreshToken.id.asc())
    )
    active_tokens = (await db_session.execute(stmt_active)).scalars().all()
    if len(active_tokens) >= max_sessions:
        to_delete_count = len(active_tokens) - max_sessions + 1
        for old_rt in active_tokens[:to_delete_count]:
            logger.info(f"[AUTH] Удален устаревший RefreshToken #{old_rt.id} пользователя ID={user_id} (превышен лимит {max_sessions})")
            await db_session.delete(old_rt)

    # 3. Создаем новый токен
    rt_str: str = generate_token()
    rt_obj = RefreshToken(
        user_id=user_id,
        token=rt_str,
        expires_at=now + timedelta(days=lifetime_days)
    )
    db_session.add(rt_obj)
    await db_session.flush()
    logger.info(f"[AUTH] Выдан RefreshToken #{rt_obj.id} для пользователя ID={user_id} со сроком {lifetime_days} дн. (до {rt_obj.expires_at.isoformat()}).")
    return rt_obj


def _sync_http_request_json(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15
) -> Dict[str, Any]:
    req_headers = {"User-Agent": "rsgi-wsrpc-auth/1.0"}
    if headers:
        req_headers.update(headers)
    encoded_data = None
    if data is not None:
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")
        if "Content-Type" not in req_headers:
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except Exception as e:
        return {"error": str(e)}


async def async_http_request_json(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 15
) -> Dict[str, Any]:
    """Асинхронный HTTP запрос через thread pool."""
    return await asyncio.to_thread(_sync_http_request_json, url, method, data, headers, timeout)



@rpc_method("login.get_key")
async def handle_get_key(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Генерирует эфемерную пару ключей RSA для безопасной передачи пароля."""
    cleanup_expired_keys()
    private_key_pem, public_key_pem = generate_rsa_keypair()
    key_id = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    ephemeral_keys[key_id] = {
        "private_key_pem": private_key_pem,
        "expires_at": expires_at
    }
    return {
        "key_id": key_id,
        "public_key": public_key_pem,
        "expires_at": expires_at.isoformat()
    }


@rpc_method("login.submit")
async def handle_login(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Вход пользователя по открытому логину и паролю."""
    username: Optional[str] = args.get("username")
    password: Optional[str] = args.get("password")
    user_agent: str = args.get("user_agent", "unknown")

    if not username or not password:
        logger.warning("[AUTH] Попытка входа с незаполненными учетными данными.")
        raise RPCError("Требуются имя пользователя и пароль")

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            stmt = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(or_(User.login == username, User.email == username))
            
            user = (await db_session.execute(stmt)).scalar_one_or_none()
            if not user or not user.verify_password(password):
                logger.warning(f"[AUTH] Неудачная попытка входа для пользователя '{username}'.")
                raise RPCError("Неверный логин или пароль")

            rt_obj = await issue_refresh_token(db_session, user.id)

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

            jwt_token, _, _ = create_access_token(
                user_id=user.id,
                username=user.login,
                roles=role_names,
                user_agent=user_agent
            )

            # Настраиваем контекст сессии
            from rsgi_wsrpc.core.session import current_transport_ctx
            transport = current_transport_ctx.get()
            current_user_ctx.set(user_context)

            # Регистрируем данные сессии
            session_data = type("AppSession", (), {
                "uid": user.id,
                "user": user,
                "user_name": user.login,
                "user_role": UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                "user_roles": role_names,
                "session_db_id": ws_session.id,
                "user_ctx": user_context,
            })()

            if transport:
                transport.data = session_data
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = session_data
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(token)

    logger.info(f"[AUTH] Пользователь '{user.login}' успешно вошел в систему. ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())

    return {
        "token": rt_obj.token,
        "jwt_token": jwt_token,
        "user_id": user.id,
        "username": user.login,
        "name": user.name or user.login,
        "email": user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict if hasattr(user_context, "perms_dict") else (user_context or {}),
        "is_superadmin": getattr(user, "is_superadmin", False)
    }


@rpc_method("login.secure")
async def handle_login_secure(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Безопасный вход пользователя с шифрованием пароля через RSA."""
    username: Optional[str] = args.get("username")
    encrypted_password: Optional[str] = args.get("encrypted_password")
    key_id: Optional[str] = args.get("key_id")
    user_agent: str = args.get("user_agent", "unknown")

    if not username or not encrypted_password or not key_id:
        logger.warning("[AUTH] Попытка безопасного входа с неполными параметрами.")
        raise RPCError("Требуются логин, зашифрованный пароль и идентификатор ключа")

    cleanup_expired_keys()
    key_data = ephemeral_keys.pop(key_id, None)
    if not key_data or key_data["expires_at"] < datetime.now(timezone.utc):
        logger.warning(f"[AUTH] Недействительный или истекший ключ RSA: key_id={key_id}")
        raise RPCError("Ключ шифрования устарел или не найден. Запросите новый ключ.")

    try:
        decrypted_password = decrypt_rsa(key_data["private_key_pem"], encrypted_password)
    except Exception as e:
        logger.error(f"[AUTH] Ошибка расшифровки пароля RSA: {e}", exc_info=True)
        raise RPCError("Ошибка расшифровки пароля")

    # Делегируем стандартному логину с расшифрованным паролем
    return await handle_login(session, {
        "username": username,
        "password": decrypted_password,
        "user_agent": user_agent
    })


@rpc_method("login.refresh")
async def handle_refresh_token(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Выполняет вход пользователя/продление сессии по ранее выданному токену (RefreshToken).
    Обеспечивает скользящее продление срока действия токена (Sliding Expiration).
    """
    token_str: Optional[str] = args.get("token")
    user_agent: str = args.get("user_agent", "unknown")

    if not token_str:
        raise RPCError("Токен не предоставлен")

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            stmt = select(RefreshToken).options(
                selectinload(RefreshToken.user).selectinload(User.roles).selectinload(Role.permissions),
                selectinload(RefreshToken.user).selectinload(User.teams)
            ).where(
                RefreshToken.token == token_str,
                RefreshToken.expires_at > datetime.now(timezone.utc)
            )
            rt_obj = (await db_session.execute(stmt)).scalar_one_or_none()

            if not rt_obj:
                logger.warning("[AUTH] Попытка обновления сессии с недействительным или просроченным токеном.")
                raise RPCError("Сессия истекла или токен недействителен")
            
            # СКОЛЬЗЯЩЕЕ ПРОДЛЕНИЕ: сдвигаем срок действия RefreshToken вперед
            lifetime_days = get_session_lifetime_days()
            now_utc = datetime.now(timezone.utc)
            rt_obj.expires_at = now_utc + timedelta(days=lifetime_days)
            logger.info(f"[AUTH] Скользящее продление RefreshToken #{rt_obj.id} для '{rt_obj.user.login}' на {lifetime_days} дн. (до {rt_obj.expires_at.isoformat()}).")

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

            from rsgi_wsrpc.core.session import current_transport_ctx
            transport = current_transport_ctx.get()
            current_user_ctx.set(user_context)

            session_data = type("AppSession", (), {
                "uid": rt_obj.user.id,
                "user": rt_obj.user,
                "user_name": rt_obj.user.login,
                "user_role": UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                "user_roles": role_names,
                "session_db_id": ws_session.id,
                "user_ctx": user_context,
            })()

            if transport:
                transport.data = session_data
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = session_data
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(token)

    logger.info(f"[AUTH] Сессия пользователя '{rt_obj.user.login}' успешно продлена через RefreshToken. ActiveSession #{ws_session.id}.")
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
        "permissions": user_context.perms_dict if hasattr(user_context, "perms_dict") else (user_context or {}),
        "is_superadmin": getattr(rt_obj.user, "is_superadmin", False)
    }


@rpc_method("login.whoami")
async def handle_whoami(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Возвращает данные о текущем авторизованном пользователе сокета."""
    user_context = current_user_ctx.get()
    if not user_context:
        return {"authenticated": False, "role": "guest", "roles": ["guest"], "permissions": {}}

    user_id = getattr(user_context, "user_id", None)
    if not user_id:
        return {"authenticated": False, "role": "guest", "roles": ["guest"], "permissions": {}}

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            stmt = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(User.id == user_id)
            user = (await db_session.execute(stmt)).scalar_one_or_none()
            if not user:
                return {"authenticated": False, "role": "guest", "roles": ["guest"], "permissions": {}}

            role_names = [r.name for r in user.roles] if user.roles else ["guest"]
            role_name = role_names[0] if role_names else "guest"

            return {
                "authenticated": True,
                "user_id": user.id,
                "username": user.login,
                "name": user.name or user.login,
                "email": user.email,
                "role": role_name,
                "roles": role_names,
                "permissions": user._get_permissions_dict(),
                "is_superadmin": getattr(user, "is_superadmin", False)
            }
    finally:
        system_bypass_ctx.reset(token)


@rpc_method("auth.logout")
async def handle_logout(session: JsonRpcSession, args: Dict[str, Any]) -> bool:
    """Выход пользователя: удаление сессии WebSocket и привязанного RefreshToken."""
    session_data = getattr(session, "data", None)
    db_id = getattr(session_data, "session_db_id", None)
    username = getattr(session_data, "user_name", "unknown")

    if db_id:
        async with async_session() as db_session:
            stmt = select(ActiveSession).options(selectinload(ActiveSession.refresh_token)).where(ActiveSession.id == db_id)
            ws_session = (await db_session.execute(stmt)).scalar_one_or_none()
            if ws_session:
                if ws_session.refresh_token:
                    await db_session.delete(ws_session.refresh_token)
                await db_session.delete(ws_session)
                await db_session.commit()

        logger.info(f"[AUTH] Пользователь '{username}' вышел из системы. Сессия #{db_id} удалена.")

    await session.close()
    asyncio.create_task(notify_session_change())
    return True


@rpc_method("login.get_oauth_providers")
async def handle_get_oauth_providers(session: JsonRpcSession, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Возвращает список доступных OAuth2 провайдеров из настроек."""
    providers = []
    oauth_conf = {}
    try:
        from app.config import settings
        oauth_conf = getattr(settings, "oauth", {}) or {}
    except Exception:
        pass

    vk_conf = getattr(oauth_conf, "vk", {}) if hasattr(oauth_conf, "vk") else oauth_conf.get("vk", {})
    if vk_conf and getattr(vk_conf, "enabled", False) if hasattr(vk_conf, "enabled") else vk_conf.get("enabled", False):
        client_id = getattr(vk_conf, "client_id", "") if hasattr(vk_conf, "client_id") else vk_conf.get("client_id", "")
        providers.append({
            "name": "vk",
            "title": "ВКонтакте (VK ID)",
            "client_id": client_id
        })

    ya_conf = getattr(oauth_conf, "yandex", {}) if hasattr(oauth_conf, "yandex") else oauth_conf.get("yandex", {})
    if ya_conf and getattr(ya_conf, "enabled", False) if hasattr(ya_conf, "enabled") else ya_conf.get("enabled", False):
        client_id = getattr(ya_conf, "client_id", "") if hasattr(ya_conf, "client_id") else ya_conf.get("client_id", "")
        providers.append({
            "name": "yandex",
            "title": "Яндекс ID",
            "client_id": client_id
        })

    return providers


@rpc_method("login.register")
async def handle_register(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Регистрация нового пользователя."""
    username: Optional[str] = args.get("username")
    email: Optional[str] = args.get("email")
    password: Optional[str] = args.get("password")
    name: Optional[str] = args.get("name") or username

    if not username or not password:
        raise RPCError("Имя пользователя и пароль обязательны")
    if len(password) < 6:
        raise RPCError("Пароль должен быть не менее 6 символов")

    token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            stmt = select(User).where(User.login == username)
            existing = (await db_session.execute(stmt)).scalar_one_or_none()
            if existing:
                raise RPCError("Пользователь с таким именем уже существует")

            if email:
                stmt_email = select(User).where(User.email == email)
                existing_email = (await db_session.execute(stmt_email)).scalar_one_or_none()
                if existing_email:
                    raise RPCError("Пользователь с таким email уже существует")

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

            logger.info(f"[AUTH] Зарегистрирован новый пользователь '{username}' (id={new_user.id}).")
            return {
                "success": True,
                "user_id": new_user.id,
                "username": new_user.login,
                "message": "Пользователь успешно зарегистрирован"
            }
    finally:
        system_bypass_ctx.reset(token)


@rpc_method("login.oauth_vk")
async def handle_oauth_vk(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Авторизация и регистрация через VK ID (OAuth 2.0)."""
    code: Optional[str] = args.get("code")
    redirect_uri: Optional[str] = args.get("redirect_uri")
    device_id: Optional[str] = args.get("device_id")
    code_verifier: Optional[str] = args.get("code_verifier")
    state: Optional[str] = args.get("state")
    user_agent: str = args.get("user_agent", "unknown")

    if not code:
        logger.warning("[AUTH VK] Запрос oauth_vk без кода авторизации.")
        raise RPCError("Отсутствует код авторизации VK")

    oauth_cfg = {}
    try:
        from app.config import settings
        oauth_cfg = getattr(settings, "oauth", {}) or {}
    except Exception:
        pass
    vk_cfg = oauth_cfg.get("vk", {}) if isinstance(oauth_cfg, dict) else getattr(oauth_cfg, "vk", {})
    if not vk_cfg:
        logger.error("[AUTH VK] Провайдер VK не сконфигурирован на сервере.")
        raise RPCError("Авторизация через VK временно не настроена")

    client_id = vk_cfg.get("client_id") if isinstance(vk_cfg, dict) else getattr(vk_cfg, "client_id", None)
    client_secret = vk_cfg.get("client_secret") if isinstance(vk_cfg, dict) else getattr(vk_cfg, "client_secret", None)

    if not client_id:
        logger.error("[AUTH VK] Не задан client_id для VK.")
        raise RPCError("Ошибка конфигурации OAuth VK на сервере")

    logger.info(f"[AUTH VK] Обмен кода авторизации на токен доступа. redirect_uri={redirect_uri}, has_pkce={bool(code_verifier)}")

    access_token = None
    vk_user_id = None
    vk_email = None
    first_name = ""
    last_name = ""
    photo_url = None
    screen_name = None

    token_url_vkid = "https://id.vk.com/oauth2/auth"
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": str(client_id),
        "code": code,
        "redirect_uri": redirect_uri or "",
    }
    if code_verifier:
        token_payload["code_verifier"] = code_verifier
    if device_id:
        token_payload["device_id"] = device_id
    if state:
        token_payload["state"] = state
    if client_secret:
        token_payload["client_secret"] = str(client_secret)

    try:
        token_data = await async_http_request_json(token_url_vkid, method="POST", data=token_payload)
        logger.info(f"[AUTH VK] Ответ id.vk.com/oauth2/auth: {token_data.get('error', 'ok')}")
        if "access_token" in token_data:
            access_token = token_data.get("access_token")
            vk_user_id = token_data.get("user_id")
            vk_email = token_data.get("email")
    except Exception as e:
        logger.warning(f"[AUTH VK] Ошибка запроса к id.vk.com/oauth2/auth: {e}")

    if not access_token:
        legacy_params = {
            "client_id": str(client_id),
            "client_secret": str(client_secret) if client_secret else "",
            "redirect_uri": redirect_uri or "",
            "code": code
        }
        legacy_url = f"https://oauth.vk.com/access_token?{urllib.parse.urlencode(legacy_params)}"
        try:
            legacy_data = await async_http_request_json(legacy_url, method="GET")
            logger.info(f"[AUTH VK] Ответ oauth.vk.com/access_token: {legacy_data.get('error', 'ok')}")
            if "access_token" in legacy_data:
                access_token = legacy_data.get("access_token")
                vk_user_id = legacy_data.get("user_id")
                vk_email = legacy_data.get("email")
            elif "error" in legacy_data:
                err_desc = legacy_data.get("error_description", legacy_data.get("error"))
                logger.error(f"[AUTH VK] Ошибка ответа legacy VK: {err_desc}")
        except Exception as e:
            logger.warning(f"[AUTH VK] Ошибка запроса к legacy oauth.vk.com: {e}")

    if not access_token or not vk_user_id:
        logger.error("[AUTH VK] Не удалось получить access_token или user_id от VK.")
        raise RPCError("Не удалось авторизоваться через VK ID (проверьте код авторизации)")

    logger.info(f"[AUTH VK] Токен получен успешно: user_id={vk_user_id}, email={vk_email}")

    try:
        udata = await async_http_request_json(
            "https://id.vk.com/oauth2/user_info",
            method="POST",
            data={"client_id": str(client_id), "access_token": access_token}
        )
        if "user" in udata and isinstance(udata["user"], dict):
            u = udata["user"]
            first_name = u.get("first_name", "")
            last_name = u.get("last_name", "")
            photo_url = u.get("avatar")
            if not vk_email and u.get("email"):
                vk_email = u.get("email")
    except Exception as e:
        logger.warning(f"[AUTH VK] Запрос user_info не удался: {e}")

    if not first_name:
        user_params = {
            "user_ids": str(vk_user_id),
            "fields": "photo_200,first_name,last_name,screen_name",
            "access_token": access_token,
            "v": "5.199"
        }
        user_get_url = f"https://api.vk.com/method/users.get?{urllib.parse.urlencode(user_params)}"
        try:
            profile_data = await async_http_request_json(user_get_url, method="GET")
            if "response" in profile_data and len(profile_data["response"]) > 0:
                uinfo = profile_data["response"][0]
                first_name = uinfo.get("first_name", "")
                last_name = uinfo.get("last_name", "")
                photo_url = photo_url or uinfo.get("photo_200")
                screen_name = uinfo.get("screen_name")
        except Exception as e:
            logger.warning(f"[AUTH VK] Не удалось загрузить расширенный профиль VK users.get: {e}")

    bypass_token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            oauth_stmt = select(OAuthAccount).options(
                selectinload(OAuthAccount.user).selectinload(User.roles).selectinload(Role.permissions),
                selectinload(OAuthAccount.user).selectinload(User.teams)
            ).where(
                OAuthAccount.provider == "vk",
                OAuthAccount.provider_user_id == str(vk_user_id)
            )
            oauth_acc = (await db_session.execute(oauth_stmt)).scalar_one_or_none()

            if oauth_acc and oauth_acc.user:
                user = oauth_acc.user
                logger.info(f"[AUTH VK] Найден существующий пользователь '{user.login}' (id={user.id}) по OAuth VK.")
            else:
                user = None
                if vk_email:
                    email_stmt = select(User).options(
                        selectinload(User.roles).selectinload(Role.permissions),
                        selectinload(User.teams)
                    ).where(User.email == vk_email)
                    user = (await db_session.execute(email_stmt)).scalar_one_or_none()
                    if user:
                        logger.info(f"[AUTH VK] Найден пользователь с email '{vk_email}' (id={user.id}), связываем с VK #{vk_user_id}.")

                if not user:
                    full_name = f"{first_name} {last_name}".strip()
                    base_login = screen_name if screen_name else f"vk_{vk_user_id}"
                    clean_login = base_login

                    check_stmt = select(User).where(User.login == clean_login)
                    if (await db_session.execute(check_stmt)).scalar_one_or_none():
                        clean_login = f"vk_{vk_user_id}"

                    role_stmt = select(Role).where(Role.name == "user")
                    user_role = (await db_session.execute(role_stmt)).scalar_one_or_none()

                    user = User(
                        name=full_name or clean_login,
                        first_name=first_name or None,
                        last_name=last_name or None,
                        login=clean_login,
                        email=vk_email,
                        password_hash=None
                    )
                    if user_role:
                        user.roles.append(user_role)

                    db_session.add(user)
                    await db_session.flush()
                    logger.info(f"[AUTH VK] Зарегистрирован новый пользователь '{user.login}' (id={user.id}) через VK.")

                if not oauth_acc:
                    oauth_acc = OAuthAccount(
                        user_id=user.id,
                        provider="vk",
                        provider_user_id=str(vk_user_id),
                        email=vk_email,
                        extra_data={
                            "first_name": first_name,
                            "last_name": last_name,
                            "photo_200": photo_url,
                            "screen_name": screen_name
                        }
                    )
                    db_session.add(oauth_acc)
                else:
                    oauth_acc.user_id = user.id
                    oauth_acc.email = vk_email

            rt_obj = await issue_refresh_token(db_session, user.id)

            ws_session = ActiveSession(
                user_id=user.id,
                ip_address=getattr(session, "ip", "0.0.0.0") or "0.0.0.0",
                user_agent=user_agent,
                refresh_token_id=rt_obj.id
            )
            db_session.add(ws_session)
            await db_session.commit()
            await db_session.refresh(ws_session)

            stmt_user = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(User.id == user.id)
            user = (await db_session.execute(stmt_user)).scalar_one()

            user_context = user.get_permissions()
            user_roles = user.roles
            role_name = user_roles[0].name if user_roles else "user"
            role_names = [r.name for r in user_roles] if user_roles else ["user"]

            jwt_token, _, _ = create_access_token(
                user_id=user.id,
                username=user.login,
                roles=role_names,
                user_agent=user_agent
            )

            from rsgi_wsrpc.core.session import current_transport_ctx
            transport = current_transport_ctx.get()
            current_user_ctx.set(user_context)

            try:
                from app.session import Session as AppSession
                session_data = AppSession(
                    uid=user.id,
                    user=user,
                    user_name=user.login,
                    user_role=UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                    user_roles=role_names,
                    session_db_id=ws_session.id,
                    user_ctx=user_context,
                    send_request_cb=transport.send_request if transport else session.send_request,
                    send_stream_cb=transport.send_stream_chunk if transport else session.send_stream_chunk,
                    close_cb=transport.close if transport else session.close
                )
            except Exception:
                session_data = type("AppSession", (), {
                    "uid": user.id,
                    "user": user,
                    "user_name": user.login,
                    "user_role": UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                    "user_roles": role_names,
                    "session_db_id": ws_session.id,
                    "user_ctx": user_context,
                })()

            if transport:
                transport.data = session_data
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = session_data
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(bypass_token)

    logger.info(f"[AUTH VK] Пользователь '{user.login}' (id={user.id}) успешно авторизован через VK ID. ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())
    return {
        "token": rt_obj.token,
        "jwt_token": jwt_token,
        "user_id": user.id,
        "username": user.login,
        "name": user.name or user.login,
        "email": user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict if hasattr(user_context, "perms_dict") else (user_context or {}),
        "is_superadmin": getattr(user, "is_superadmin", False),
        "photo_url": photo_url
    }


@rpc_method("login.oauth_yandex")
async def handle_oauth_yandex(session: JsonRpcSession, args: Dict[str, Any]) -> Dict[str, Any]:
    """Авторизация и регистрация через Яндекс ID (OAuth 2.0)."""
    code: Optional[str] = args.get("code")
    redirect_uri: Optional[str] = args.get("redirect_uri")
    user_agent: str = args.get("user_agent", "unknown")

    if not code:
        logger.warning("[AUTH YANDEX] Запрос oauth_yandex без кода авторизации.")
        raise RPCError("Отсутствует код авторизации Яндекс")

    oauth_cfg = {}
    try:
        from app.config import settings
        oauth_cfg = getattr(settings, "oauth", {}) or {}
    except Exception:
        pass
    ya_cfg = oauth_cfg.get("yandex", {}) if isinstance(oauth_cfg, dict) else getattr(oauth_cfg, "yandex", {})
    if not ya_cfg:
        logger.error("[AUTH YANDEX] Провайдер Яндекс не сконфигурирован на сервере.")
        raise RPCError("Авторизация через Яндекс ID временно не настроена")

    client_id = ya_cfg.get("client_id") if isinstance(ya_cfg, dict) else getattr(ya_cfg, "client_id", None)
    client_secret = ya_cfg.get("client_secret") if isinstance(ya_cfg, dict) else getattr(ya_cfg, "client_secret", None)

    if not client_id or not client_secret:
        logger.error("[AUTH YANDEX] Не заданы client_id или client_secret для Яндекс ID.")
        raise RPCError("Ошибка конфигурации OAuth Яндекс на сервере")

    logger.info(f"[AUTH YANDEX] Обмен кода авторизации на токен доступа. redirect_uri={redirect_uri}")

    access_token = None
    token_url = "https://oauth.yandex.ru/token"
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": str(client_id),
        "client_secret": str(client_secret),
    }
    if redirect_uri:
        token_payload["redirect_uri"] = redirect_uri

    try:
        token_data = await async_http_request_json(token_url, method="POST", data=token_payload)
        logger.info(f"[AUTH YANDEX] Ответ oauth.yandex.ru/token: {token_data.get('error', 'ok')}")
        if "access_token" in token_data:
            access_token = token_data.get("access_token")
        elif "error" in token_data:
            err_desc = token_data.get("error_description", token_data.get("error"))
            logger.error(f"[AUTH YANDEX] Ошибка обмена токена Яндекс: {err_desc}")
    except Exception as e:
        logger.error(f"[AUTH YANDEX] Ошибка запроса к oauth.yandex.ru/token: {e}")

    if not access_token:
        logger.error("[AUTH YANDEX] Не удалось получить access_token от Яндекс.")
        raise RPCError("Не удалось авторизоваться через Яндекс ID (код устарел или неверен)")

    profile_url = "https://login.yandex.ru/info?format=json"
    headers = {"Authorization": f"OAuth {access_token}"}
    try:
        udata = await async_http_request_json(profile_url, method="GET", headers=headers)
        logger.info(f"[AUTH YANDEX] Ответ login.yandex.ru/info: user_id={udata.get('id')}")
    except Exception as e:
        logger.error(f"[AUTH YANDEX] Ошибка запроса данных профиля к login.yandex.ru/info: {e}")
        raise RPCError("Не удалось получить данные профиля от Яндекс ID")

    ya_user_id = udata.get("id")
    if not ya_user_id:
        logger.error(f"[AUTH YANDEX] В ответе Яндекс отсутствует id пользователя: {udata}")
        raise RPCError("Не удалось определить ID пользователя в Яндекс")

    ya_email = udata.get("default_email")
    if not ya_email and udata.get("emails"):
        ya_email = udata["emails"][0]

    first_name = udata.get("first_name", "")
    last_name = udata.get("last_name", "")
    display_name = udata.get("display_name") or udata.get("real_name") or ""
    full_name = display_name if display_name else f"{first_name} {last_name}".strip()

    avatar_id = udata.get("default_avatar_id")
    is_avatar_empty = udata.get("is_avatar_empty", False)
    photo_url = None
    if avatar_id and not is_avatar_empty:
        photo_url = f"https://avatars.yandex.net/get-yapic/{avatar_id}/islands-200"

    ya_login = udata.get("login")

    bypass_token = system_bypass_ctx.set(True)
    try:
        async with async_session() as db_session:
            oauth_stmt = select(OAuthAccount).options(
                selectinload(OAuthAccount.user).selectinload(User.roles).selectinload(Role.permissions),
                selectinload(OAuthAccount.user).selectinload(User.teams)
            ).where(
                OAuthAccount.provider == "yandex",
                OAuthAccount.provider_user_id == str(ya_user_id)
            )
            oauth_acc = (await db_session.execute(oauth_stmt)).scalar_one_or_none()

            if oauth_acc and oauth_acc.user:
                user = oauth_acc.user
                logger.info(f"[AUTH YANDEX] Найден существующий пользователь '{user.login}' (id={user.id}) по OAuth Yandex.")
            else:
                user = None
                if ya_email:
                    email_stmt = select(User).options(
                        selectinload(User.roles).selectinload(Role.permissions),
                        selectinload(User.teams)
                    ).where(User.email == ya_email)
                    user = (await db_session.execute(email_stmt)).scalar_one_or_none()
                    if user:
                        logger.info(f"[AUTH YANDEX] Найден пользователь с email '{ya_email}' (id={user.id}), связываем с Yandex #{ya_user_id}.")

                if not user:
                    clean_login = ya_login if ya_login else f"ya_{ya_user_id}"
                    check_stmt = select(User).where(User.login == clean_login)
                    if (await db_session.execute(check_stmt)).scalar_one_or_none():
                        clean_login = f"ya_{ya_user_id}"

                    role_stmt = select(Role).where(Role.name == "user")
                    user_role = (await db_session.execute(role_stmt)).scalar_one_or_none()

                    user = User(
                        name=full_name or clean_login,
                        first_name=first_name or None,
                        last_name=last_name or None,
                        login=clean_login,
                        email=ya_email,
                        password_hash=None
                    )
                    if user_role:
                        user.roles.append(user_role)

                    db_session.add(user)
                    await db_session.flush()
                    logger.info(f"[AUTH YANDEX] Зарегистрирован новый пользователь '{user.login}' (id={user.id}) через Яндекс ID.")

                if not oauth_acc:
                    oauth_acc = OAuthAccount(
                        user_id=user.id,
                        provider="yandex",
                        provider_user_id=str(ya_user_id),
                        email=ya_email,
                        extra_data={
                            "login": ya_login,
                            "display_name": display_name,
                            "first_name": first_name,
                            "last_name": last_name,
                            "avatar_id": avatar_id,
                            "photo_url": photo_url
                        }
                    )
                    db_session.add(oauth_acc)
                else:
                    oauth_acc.user_id = user.id
                    oauth_acc.email = ya_email

            rt_obj = await issue_refresh_token(db_session, user.id)

            ws_session = ActiveSession(
                user_id=user.id,
                ip_address=getattr(session, "ip", "0.0.0.0") or "0.0.0.0",
                user_agent=user_agent,
                refresh_token_id=rt_obj.id
            )
            db_session.add(ws_session)
            await db_session.commit()
            await db_session.refresh(ws_session)

            stmt_user = select(User).options(
                selectinload(User.roles).selectinload(Role.permissions),
                selectinload(User.teams)
            ).where(User.id == user.id)
            user = (await db_session.execute(stmt_user)).scalar_one()

            user_context = user.get_permissions()
            user_roles = user.roles
            role_name = user_roles[0].name if user_roles else "user"
            role_names = [r.name for r in user_roles] if user_roles else ["user"]

            jwt_token, _, _ = create_access_token(
                user_id=user.id,
                username=user.login,
                roles=role_names,
                user_agent=user_agent
            )

            from rsgi_wsrpc.core.session import current_transport_ctx
            transport = current_transport_ctx.get()
            current_user_ctx.set(user_context)

            try:
                from app.session import Session as AppSession
                session_data = AppSession(
                    uid=user.id,
                    user=user,
                    user_name=user.login,
                    user_role=UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                    user_roles=role_names,
                    session_db_id=ws_session.id,
                    user_ctx=user_context,
                    send_request_cb=transport.send_request if transport else session.send_request,
                    send_stream_cb=transport.send_stream_chunk if transport else session.send_stream_chunk,
                    close_cb=transport.close if transport else session.close
                )
            except Exception:
                session_data = type("AppSession", (), {
                    "uid": user.id,
                    "user": user,
                    "user_name": user.login,
                    "user_role": UserRole(role_name) if hasattr(UserRole, role_name) else role_name,
                    "user_roles": role_names,
                    "session_db_id": ws_session.id,
                    "user_ctx": user_context,
                })()

            if transport:
                transport.data = session_data
                transport.register_on_close(cleanup_app_session)
            elif hasattr(session, "register_on_close"):
                session.data = session_data
                session.register_on_close(cleanup_app_session)
    finally:
        system_bypass_ctx.reset(bypass_token)

    logger.info(f"[AUTH YANDEX] Пользователь '{user.login}' (id={user.id}) успешно авторизован через Яндекс ID. ActiveSession #{ws_session.id}.")
    asyncio.create_task(notify_session_change())
    return {
        "token": rt_obj.token,
        "jwt_token": jwt_token,
        "user_id": user.id,
        "username": user.login,
        "name": user.name or user.login,
        "email": user.email,
        "role": role_name,
        "roles": role_names,
        "permissions": user_context.perms_dict if hasattr(user_context, "perms_dict") else (user_context or {}),
        "is_superadmin": getattr(user, "is_superadmin", False),
        "photo_url": photo_url
    }

