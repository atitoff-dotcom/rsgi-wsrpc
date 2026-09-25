# -*- coding: utf-8 -*-
"""
Сервисный слой работы с постоянным файловым хранилищем (plugins/files/service.py).
Реализует операции с метаданными, квотами, токенами доступа и физическими файлами.
"""

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jwt
from sqlalchemy import delete, func, select

from rsgi_wsrpc.core.lib.config import get_config
from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.plugins.db import async_session
from .models import StoredFile
from .upload import get_storage_dir, upload_coordinator


class FileStorageService:
    """
    Высокоуровневый сервис управления файловым реестром и хранилищем.
    """

    @classmethod
    async def commit_upload(
        cls,
        folder_hash: str,
        owner_id: Optional[int] = None,
        is_public: bool = True,
        metadata_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> List[StoredFile]:
        """
        Фиксирует двухфазную транзакцию:
        1. Атомарно перемещает файлы из временной папки в постоянное хранилище (0 ms).
        2. Создает записи в таблице `file_metadata`.
        """
        tx = upload_coordinator.commit_transaction(folder_hash)
        if not tx:
            # Возможно, папка уже на диске
            logger.warning(f"[FileService] Транзакция {folder_hash} не найдена в памяти.")
            return []

        resolved_owner = owner_id if owner_id is not None else tx.owner_id
        saved_files: List[StoredFile] = []

        # Карта переопределений метаданных (например, пользовательские описания или оригинальные имена)
        overrides_map: Dict[str, Dict[str, Any]] = {}
        if metadata_overrides:
            for item in metadata_overrides:
                fname = item.get("filename")
                if fname:
                    overrides_map[fname] = item

        try:
            async with async_session() as session:
                for fname, info in tx.files.items():
                    override = overrides_map.get(fname, {})
                    record = StoredFile(
                        folder_hash=folder_hash,
                        filename=fname,
                        original_name=override.get("original_name") or info.get("original_name") or fname,
                        size=info.get("size", 0),
                        mime_type=override.get("mime_type") or info.get("mime_type") or "application/octet-stream",
                        sha256=info.get("sha256"),
                        owner_id=resolved_owner,
                        is_public=override.get("is_public", is_public),
                    )
                    session.add(record)
                    saved_files.append(record)

                await session.commit()
                for record in saved_files:
                    await session.refresh(record)

            logger.info(f"[FileService] Успешно закоммичено {len(saved_files)} файлов для папки {folder_hash}")
        except Exception as e:
            logger.error(f"[FileService] Ошибка сохранения метаданных для {folder_hash}: {e}", exc_info=True)

        return saved_files

    @classmethod
    async def get_file(cls, file_id: int) -> Optional[StoredFile]:
        """Возвращает метаданные файла по его ID."""
        async with async_session() as session:
            stmt = select(StoredFile).where(StoredFile.id == file_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()

    @classmethod
    async def get_by_folder(cls, folder_hash: str) -> List[StoredFile]:
        """Возвращает список всех файлов в бандле по хэшу папки."""
        async with async_session() as session:
            stmt = select(StoredFile).where(StoredFile.folder_hash == folder_hash)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    @classmethod
    async def list_user_files(
        cls,
        owner_id: int,
        page: int = 1,
        limit: int = 50
    ) -> Tuple[List[StoredFile], int]:
        """Постраничный список файлов конкретного пользователя."""
        page = max(1, page)
        limit = min(max(1, limit), 200)
        offset = (page - 1) * limit

        async with async_session() as session:
            count_stmt = select(func.count(StoredFile.id)).where(StoredFile.owner_id == owner_id)
            total = (await session.execute(count_stmt)).scalar() or 0

            stmt = (
                select(StoredFile)
                .where(StoredFile.owner_id == owner_id)
                .order_by(StoredFile.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            res = await session.execute(stmt)
            return list(res.scalars().all()), total

    @classmethod
    async def get_user_disk_usage(cls, owner_id: int) -> int:
        """Возвращает суммарный объем занятого дискового пространства пользователем (в байтах)."""
        async with async_session() as session:
            stmt = select(func.coalesce(func.sum(StoredFile.size), 0)).where(StoredFile.owner_id == owner_id)
            return (await session.execute(stmt)).scalar() or 0

    @classmethod
    async def delete_file(cls, file_id: int, user_id: Optional[int] = None) -> bool:
        """
        Удаляет файл из БД и физически стирает его с диска.
        Если передан user_id, проверяет права владельца.
        """
        async with async_session() as session:
            stmt = select(StoredFile).where(StoredFile.id == file_id)
            res = await session.execute(stmt)
            file_record = res.scalar_one_or_none()

            if not file_record:
                return False

            if user_id is not None and file_record.owner_id != user_id:
                raise PermissionError("Нет прав на удаление чужого файла")

            # 1. Физическое удаление с диска
            storage_path = get_storage_dir() / file_record.folder_hash / file_record.filename
            try:
                if storage_path.exists():
                    storage_path.unlink()
                # Если папка опустела — удаляем и её
                folder_dir = storage_path.parent
                if folder_dir.exists() and not any(folder_dir.iterdir()):
                    folder_dir.rmdir()
            except Exception as e:
                logger.warning(f"[FileService] Не удалось удалить физический файл {storage_path}: {e}")

            # 2. Удаление из базы данных
            await session.delete(file_record)
            await session.commit()
            return True

    @classmethod
    def generate_download_token(cls, file_id: int, secret_key: Optional[str] = None, expires_in: int = 3600) -> str:
        """
        Генерирует временный Capability-токен для защищенного скачивания приватного файла.
        """
        cfg = get_config()
        sec = secret_key or (getattr(cfg.security, "secret_key", None) if hasattr(cfg, "security") else None) or "file-secret-key"
        payload = {
            "sub": "file_download",
            "file_id": file_id,
            "exp": int(time.time()) + expires_in,
        }
        return jwt.encode(payload, sec, algorithm="HS256")

    @classmethod
    def verify_download_token(cls, token: str, secret_key: Optional[str] = None) -> Optional[int]:
        """
        Проверяет Capability-токен и возвращает ID файла.
        """
        cfg = get_config()
        sec = secret_key or (getattr(cfg.security, "secret_key", None) if hasattr(cfg, "security") else None) or "file-secret-key"
        try:
            payload = jwt.decode(token, sec, algorithms=["HS256"])
            if payload.get("sub") == "file_download":
                return payload.get("file_id")
        except Exception:
            pass
        return None
