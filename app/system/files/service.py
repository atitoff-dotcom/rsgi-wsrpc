# -*- coding: utf-8 -*-
"""
Сервис системного хранилища файлов (app/system/files/service.py).
Управляет регистрацией метаданных в БД, миграцией схемы и очисткой бандлов.
"""

import os
import shutil
from typing import Dict, Any, Optional, List
from sqlalchemy import text
from app.system.db import async_session
from core.logger import logger
from core.lifecycle import on_startup
from core.lib.config import settings


class FileStorageService:
    """
    Системный сервис для работы с файловыми метаданными и хранилищем.
    """

    @staticmethod
    @on_startup
    async def ensure_schema():
        """
        Гарантирует наличие всех необходимых колонок в таблице file_metadata.
        Безопасно выполняет ALTER TABLE, если колонки отсутствуют.
        """
        async with async_session() as session:
            async with session.begin():
                result = await session.execute(text("PRAGMA table_info(file_metadata)"))
                existing_cols = {row[1] for row in result.fetchall()}
                
                columns_to_add = [
                    ("folder_hash", "VARCHAR(64)"),
                    ("original_name", "TEXT"),
                    ("mime_type", "VARCHAR(128)"),
                    ("sha256", "VARCHAR(64)"),
                    ("is_public", "BOOLEAN DEFAULT 1"),
                ]
                
                for col_name, col_type in columns_to_add:
                    if col_name not in existing_cols:
                        logger.info(f"[FILES SCHEMA] Добавление отсутствующей колонки {col_name} ({col_type}) в file_metadata...")
                        await session.execute(text(f"ALTER TABLE file_metadata ADD COLUMN {col_name} {col_type}"))

    @staticmethod
    async def register_file(
        folder_hash: str,
        filename: str,
        original_name: str,
        size: int,
        owner_id: int = 1,
        mime_type: Optional[str] = None,
        sha256: Optional[str] = None,
        is_public: bool = True,
    ) -> int:
        """
        Регистрирует один файл в реестре file_metadata.
        """
        token_path = f"{folder_hash}/{filename}"
        async with async_session() as session:
            async with session.begin():
                stmt = text("""
                    INSERT INTO file_metadata (
                        folder_hash, filename, original_name, download_token,
                        size, mime_type, sha256, owner_id, is_public
                    ) VALUES (
                        :folder_hash, :filename, :original_name, :download_token,
                        :size, :mime_type, :sha256, :owner_id, :is_public
                    ) RETURNING id
                """)
                result = await session.execute(
                    stmt,
                    {
                        "folder_hash": folder_hash,
                        "filename": filename,
                        "original_name": original_name,
                        "download_token": token_path,
                        "size": size,
                        "mime_type": mime_type,
                        "sha256": sha256,
                        "owner_id": owner_id,
                        "is_public": 1 if is_public else 0,
                    },
                )
                file_id = result.scalar()
                logger.info(f"[FILES DB] ✅ Зарегистрирован файл #{file_id}: {token_path} ({size} bytes, owner={owner_id})")
                return file_id

    @staticmethod
    async def delete_bundle(folder_hash: str) -> Dict[str, Any]:
        """
        Атомарно удаляет весь бандл файлов с диска и его записи из file_metadata.
        """
        if not folder_hash:
            return {"deleted_files": 0, "disk_deleted": False}

        base_files_path = getattr(settings, "files_path", "files")
        folder_dir = os.path.join(base_files_path, folder_hash)
        
        disk_deleted = False
        if os.path.exists(folder_dir):
            try:
                shutil.rmtree(folder_dir, ignore_errors=True)
                disk_deleted = True
                logger.info(f"[FILES DELETE] 🗑️ Удалена папка с диска: {folder_dir}")
            except Exception as e:
                logger.error(f"[FILES DELETE] Ошибка удаления папки {folder_dir}: {e}", exc_info=True)

        deleted_meta_count = 0
        async with async_session() as session:
            async with session.begin():
                stmt = text("DELETE FROM file_metadata WHERE folder_hash = :f OR download_token LIKE :p")
                res = await session.execute(stmt, {"f": folder_hash, "p": f"{folder_hash}/%"})
                deleted_meta_count = res.rowcount
                logger.info(f"[FILES DELETE] 🗃️ Удалено записей из file_metadata: {deleted_meta_count} для бандла {folder_hash}")

        return {
            "deleted_files": deleted_meta_count,
            "disk_deleted": disk_deleted,
            "folder_hash": folder_hash,
        }
