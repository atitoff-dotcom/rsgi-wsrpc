# -*- coding: utf-8 -*-
"""
WSRPC JSON-RPC обработчики файловой подсистемы (plugins/files/handlers.py).
Реализует спецификацию методов files.* согласно RFC 0005.
"""

from typing import Any, Dict, List, Optional

from rsgi_wsrpc.core.session import (
    RPCError,
    current_session_ctx,
    current_transport_ctx,
    current_user_ctx,
    rpc_method,
)
from rsgi_wsrpc.core.tabular import tabular_response
from .models import StoredFile
from .service import FileStorageService
from .upload import upload_coordinator


def _get_current_user_id() -> Optional[int]:
    """Извлекает ID текущего авторизованного пользователя из контекста."""
    user = current_user_ctx.get()
    if not user:
        return None
    if isinstance(user, dict):
        return user.get("id") or user.get("user_id")
    return getattr(user, "id", None)


@rpc_method("files.init_upload")
async def files_init_upload(
    files_count: int = 1,
    total_expected_size: int = 0,
) -> Dict[str, Any]:
    """
    Фаза 1 двухфазного коммита: инициализация транзакции загрузки.
    Аллоцирует защищенную временную папку /tmp/app_uploads/<folder_hash>/
    и регистрирует хук очистки при обрыве соединения.
    """
    session = current_transport_ctx.get() or current_session_ctx.get()
    owner_id = _get_current_user_id()

    tx = upload_coordinator.create_transaction(
        session=session,
        owner_id=owner_id,
        files_count=max(1, files_count),
    )

    return {
        "status": "ready",
        "folder_hash": tx.folder_hash,
        "upload_url": f"/upload?folder={tx.folder_hash}",
        "files_count": tx.files_count,
    }


@rpc_method("files.commit")
async def files_commit(
    folder_hash: str,
    metadata: Optional[List[Dict[str, Any]]] = None,
    is_public: bool = True,
) -> Dict[str, Any]:
    """
    Фаза 2 двухфазного коммита: атомарная фиксация файлов.
    Переносит временную папку в боевое хранилище (0 ms) и индексирует в БД.
    """
    if not folder_hash:
        raise RPCError(-32602, "Параметр 'folder_hash' обязателен")

    owner_id = _get_current_user_id()
    saved_files = await FileStorageService.commit_upload(
        folder_hash=folder_hash,
        owner_id=owner_id,
        is_public=is_public,
        metadata_overrides=metadata,
    )

    return {
        "status": "committed",
        "folder_hash": folder_hash,
        "files_count": len(saved_files),
        "files": [f.to_dict() for f in saved_files],
    }


@rpc_method("files.rollback")
async def files_rollback(folder_hash: str) -> Dict[str, Any]:
    """
    Явный откат транзакции загрузки со стороны клиента.
    Мгновенно стирает временную директорию.
    """
    if not folder_hash:
        raise RPCError(-32602, "Параметр 'folder_hash' обязателен")

    upload_coordinator.rollback_transaction(folder_hash)
    return {
        "status": "aborted",
        "folder_hash": folder_hash,
    }


@rpc_method("files.list_my_files")
@tabular_response(fields=["id", "folder_hash", "filename", "original_name", "size", "mime_type", "url", "created_at"])
async def files_list_my_files(page: int = 1, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Возвращает список файлов текущего пользователя с табличным сжатием (RFC 0002).
    """
    owner_id = _get_current_user_id()
    if not owner_id:
        raise RPCError(-32001, "Требуется авторизация для просмотра файлов")

    files, _ = await FileStorageService.list_user_files(owner_id=owner_id, page=page, limit=limit)
    return [f.to_dict() for f in files]


@rpc_method("files.delete")
async def files_delete(file_id: int) -> Dict[str, Any]:
    """
    Удаляет файл пользователя из хранилища и реестра БД.
    """
    owner_id = _get_current_user_id()
    if not owner_id:
        raise RPCError(-32001, "Требуется авторизация")

    try:
        deleted = await FileStorageService.delete_file(file_id=file_id, user_id=owner_id)
        if not deleted:
            raise RPCError(-32004, f"Файл с ID {file_id} не найден")
        return {"status": "ok", "deleted": True, "file_id": file_id}
    except PermissionError:
        raise RPCError(-32003, "Отказано в доступе: вы не являетесь владельцем файла")


@rpc_method("files.get_quota")
async def files_get_quota() -> Dict[str, Any]:
    """
    Возвращает статистику занятого дискового пространства текущего пользователя.
    """
    owner_id = _get_current_user_id()
    if not owner_id:
        raise RPCError(-32001, "Требуется авторизация")

    used_bytes = await FileStorageService.get_user_disk_usage(owner_id)
    return {
        "owner_id": owner_id,
        "used_bytes": used_bytes,
        "used_mb": round(used_bytes / (1024 * 1024), 2),
    }
