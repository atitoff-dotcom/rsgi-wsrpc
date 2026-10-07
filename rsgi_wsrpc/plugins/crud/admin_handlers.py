# -*- coding: utf-8 -*-
"""
RPC-обработчики системного пульта управления (Mission Control Cockpit /admin/system).
Предоставляют инспекцию и управление активными сессиями, Smart Cache, рассылками,
системными логами и конфигурацией фреймворка.
"""

import time
from typing import Any, Dict, List, Optional

from rsgi_wsrpc.core.session import (
    rpc_method,
    RPCError,
    ACTIVE_SESSIONS_SET,
    current_transport_ctx,
)
from rsgi_wsrpc.core.logger import get_recent_logs, _extract_username_safe, logger
from rsgi_wsrpc.core.lib.config import settings
from rsgi_wsrpc.plugins.broadcast import broadcast_notification
from rsgi_wsrpc.plugins.smart_cache.engine import version_registry, invalidate_tags


def _ensure_admin(session) -> None:
    """Проверяет права администратора для вызова системных методов."""
    if not session or not getattr(session, "data", None):
        raise RPCError(-32000, "Доступ запрещен: требуется авторизация администратора")
    data = session.data
    role = None
    if isinstance(data, dict):
        role = data.get("role")
    else:
        role = getattr(data, "role", None)
    if str(role).lower() not in ("admin", "superadmin", "administrator"):
        raise RPCError(-32003, "Доступ запрещен: требуются права администратора (role: admin)")


@rpc_method("admin.sessions_list")
async def list_active_sessions(session) -> List[Dict[str, Any]]:
    """Мониторинг активных WebSocket-подключений и сессий пользователей.

    Возвращает список подключенных клиентов с IP-адресами, именами пользователей,
    ролями и временем бездействия.
    """
    _ensure_admin(session)
    now = time.time()
    current_id = getattr(session, "session_id", None)
    sessions = []
    for s in list(ACTIVE_SESSIONS_SET):
        s_id = getattr(s, "session_id", None)
        ip = getattr(s, "ip", "0.0.0.0")
        username = _extract_username_safe(s)
        role = "guest"
        if getattr(s, "data", None):
            if isinstance(s.data, dict):
                role = s.data.get("role", "user")
            else:
                role = getattr(s.data, "role", "user")
        last_act = getattr(s, "last_activity", now)
        idle_sec = max(0, int(now - last_act))
        sessions.append({
            "session_id": s_id,
            "ip": ip,
            "username": username,
            "role": str(role),
            "idle_seconds": idle_sec,
            "rate_limit_enabled": getattr(s, "rate_limit_enabled", True),
            "is_current": s_id == current_id,
        })
    # Сортируем: текущая сессия первой, затем по ID
    sessions.sort(key=lambda x: (not x["is_current"], x["session_id"]))
    return sessions


@rpc_method("admin.session_kill")
async def kill_session(session, session_id: int) -> Dict[str, Any]:
    """Принудительное завершение активной WebSocket-сессии (Kick/Disconnect).

    Разрывает WebSocket-соединение указанного клиента и очищает его контекст.
    Нельзя принудительно разорвать свою собственную текущую сессию.

    :param session_id: Идентификатор активной сессии.
    """
    _ensure_admin(session)
    if session_id == getattr(session, "session_id", None):
        raise RPCError(-32602, "Нельзя принудительно отключить свою собственную сессию")

    target = None
    for s in list(ACTIVE_SESSIONS_SET):
        if getattr(s, "session_id", None) == session_id:
            target = s
            break

    if not target:
        raise RPCError(-32602, f"Сессия {session_id} не найдена или уже завершена")

    username = _extract_username_safe(target)
    await target.close()
    logger.info(f"[Admin] Сессия {session_id} ({username}) принудительно отключена администратором")
    return {"status": "ok", "session_id": session_id, "username": username}


@rpc_method("system.cache_stats")
async def get_cache_stats(session) -> List[Dict[str, Any]]:
    """Инспекция версий тегов Smart Cache (RFC 0001).

    Возвращает актуальный список тегов кэша в оперативной памяти и БД
    с их текущими монотонными версиями.
    """
    _ensure_admin(session)
    versions_map = version_registry.get_all_versions()
    stats = [{"tag": tag, "version": ver} for tag, ver in sorted(versions_map.items())]
    return stats


@rpc_method("system.cache_invalidate")
async def invalidate_cache_tags(session, tags: List[str]) -> Dict[str, Any]:
    """Принудительная реактивная инвалидация тегов кэша.

    Инкрементирует монотонные версии тегов и отправляет клиентам
    WSRPC-нотификацию cache.invalidate в реальном времени.

    :param tags: Список тегов для инвалидации (например, ['items', 'users']).
    """
    _ensure_admin(session)
    if not tags or not isinstance(tags, list):
        raise RPCError(-32602, "Параметр 'tags' должен быть непустым списком строк")
    clean_tags = [str(t).strip() for t in tags if str(t).strip()]
    if not clean_tags:
        raise RPCError(-32602, "Список тегов пуст")

    new_versions = await invalidate_tags(clean_tags, reason="admin_manual_invalidate")
    return {"status": "ok", "invalidated_tags": new_versions}


@rpc_method("system.broadcast")
async def send_system_broadcast(
    session,
    message: str,
    level: str = "info",
    title: Optional[str] = None
) -> Dict[str, Any]:
    """Отправка системного всплывающего оповещения всем подключенным клиентам.

    Мгновенно рассылает JSON-RPC нотификацию system.alert по открытым сокетам.

    :param message: Текст сообщения.
    :param level: Уровень важности ('info', 'warning', 'error', 'success').
    :param title: Заголовок уведомления (опционально).
    """
    _ensure_admin(session)
    if not message or not message.strip():
        raise RPCError(-32602, "Текст сообщения не может быть пустым")

    admin_name = _extract_username_safe(session)
    payload = {
        "title": title or "Системное оповещение",
        "message": message.strip(),
        "level": level if level in ("info", "warning", "error", "success") else "info",
        "sender": admin_name,
        "timestamp": time.time(),
    }
    delivered = await broadcast_notification("system.alert", payload)
    logger.info(f"[Admin] Системная рассылка '{payload['title']}' отправлена {delivered} клиентам")
    return {"status": "ok", "delivered_count": delivered}


@rpc_method("system.recent_logs")
async def stream_recent_logs(session, limit: int = 100) -> List[Dict[str, Any]]:
    """Просмотр системного журнала событий сервера из оперативной памяти.

    Возвращает последние записи логов сервера с временными метками, уровнями
    логирования и контекстом сессий.

    :param limit: Количество последних записей (максимум 200).
    """
    _ensure_admin(session)
    safe_limit = min(max(1, limit), 200)
    return get_recent_logs(safe_limit)


@rpc_method("system.get_config")
async def get_system_config(session) -> Dict[str, Any]:
    """Просмотр системной конфигурации и параметров ядра платформы.

    Возвращает текущие настройки безопасности, таймаутов и путей.
    Секретные ключи экранируются в целях безопасности.
    """
    _ensure_admin(session)
    conf = settings.to_dict()
    # Маскируем чувствительные данные
    if "security" in conf and isinstance(conf["security"], dict):
        sec = conf["security"].copy()
        if "secret_key" in sec and sec["secret_key"]:
            sec["secret_key"] = sec["secret_key"][:4] + "••••••••" + sec["secret_key"][-4:]
        conf["security"] = sec
    return conf
