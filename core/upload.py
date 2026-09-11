# -*- coding: utf-8 -*-
"""
Подсистема загрузки файлов ядра Agrita (Core Upload & Two-Phase Commit).
Обеспечивает координацию транзакций загрузки, потоковую запись на диск (RSGI O(1) RAM),
вычисление SHA-256 на лету и автоматический откат (Rollback) при дисконнекте сессий WSRPC.
"""

import os
import shutil
import hashlib
import secrets
import asyncio
import time
from typing import Dict, Any, Optional, List, Tuple
from core.logger import logger

TEMP_UPLOADS_ROOT = os.environ.get("UPLOADS_TEMP_DIR", "/tmp/agrita_uploads")


class UploadTransaction:
    """
    Транзакция загрузки файлов (Two-Phase Commit).
    Хранит состояние загрузки бандла, контролирует временную директорию
    и гарантирует откат (удаление временных файлов) при сбое.
    """

    def __init__(
        self,
        folder_hash: str,
        temp_dir: str,
        expected_files_count: int = 0,
        owner_id: int = 1,
        session=None,
    ):
        self.folder_hash: str = folder_hash
        self.temp_dir: str = temp_dir
        self.expected_files_count: int = expected_files_count
        self.owner_id: int = owner_id
        self.session = session
        self.received_files: List[Dict[str, Any]] = []
        self.is_committed: bool = False
        self.is_rolled_back: bool = False
        self.created_at: float = time.time()
        self._completion_event: asyncio.Event = asyncio.Event()

    def add_file(
        self,
        filename: str,
        original_name: str,
        size: int,
        mime_type: str = "application/octet-stream",
        sha256: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Регистрирует принятый файл в рамках транзакции.
        """
        file_info = {
            "filename": filename,
            "original_name": original_name,
            "size": size,
            "mime_type": mime_type,
            "sha256": sha256,
            "relative_path": f"{self.folder_hash}/{filename}",
            "temp_path": os.path.join(self.temp_dir, filename),
            "added_at": time.time(),
        }
        self.received_files.append(file_info)
        logger.info(
            f"[UPLOAD TX] [{self.folder_hash}] Принят файл: {filename} "
            f"({size} bytes, sha256={sha256[:8] if sha256 else 'none'}...). "
            f"Всего файлов: {len(self.received_files)}/{self.expected_files_count or '?'}"
        )

        if self.expected_files_count and len(self.received_files) >= self.expected_files_count:
            self._completion_event.set()

        return file_info

    async def wait_completed(self, timeout: float = 60.0) -> bool:
        """
        Ожидает завершения загрузки всех заявленных файлов.
        """
        if not self.expected_files_count or len(self.received_files) >= self.expected_files_count:
            return True
        try:
            await asyncio.wait_for(self._completion_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                f"[UPLOAD TX] [{self.folder_hash}] Таймаут ожидания загрузки файлов ({timeout}с). "
                f"Получено: {len(self.received_files)}/{self.expected_files_count}"
            )
            return False

    def commit(self, target_base_dir: str) -> str:
        """
        Фаза фиксации (Commit): атомарно перемещает временную директорию
        в постоянное хранилище (например, files/<folder_hash>).
        """
        if self.is_rolled_back:
            raise RuntimeError(f"Невозможно закоммитить транзакцию {self.folder_hash}: она уже откатана")
        if self.is_committed:
            logger.warning(f"[UPLOAD TX] [{self.folder_hash}] Транзакция уже закоммичена")
            return os.path.join(target_base_dir, self.folder_hash)

        os.makedirs(target_base_dir, exist_ok=True)
        final_target_dir = os.path.join(target_base_dir, self.folder_hash)

        if os.path.exists(final_target_dir):
            # Если целевая папка уже существует, перемещаем файлы внутрь
            for item in os.listdir(self.temp_dir):
                s = os.path.join(self.temp_dir, item)
                d = os.path.join(final_target_dir, item)
                if os.path.exists(d):
                    if os.path.isdir(d):
                        shutil.rmtree(d, ignore_errors=True)
                    else:
                        os.remove(d)
                shutil.move(s, d)
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        else:
            # Атомарное перемещение папки целиком в Linux (0 миллисекунд)
            shutil.move(self.temp_dir, final_target_dir)

        self.is_committed = True
        logger.info(
            f"[UPLOAD TX] [{self.folder_hash}] ✅ Коммит успешен! "
            f"Перемещено {len(self.received_files)} файлов в {final_target_dir}"
        )
        upload_coordinator.remove_transaction(self.folder_hash)
        return final_target_dir

    def rollback(self, reason: str = "manual") -> None:
        """
        Фаза отката (Rollback): мгновенно удаляет временную директорию
        со всеми недогруженными файлами.
        """
        if self.is_committed:
            logger.warning(f"[UPLOAD TX] [{self.folder_hash}] Попытка отката уже закоммиченной транзакции (игнорируется)")
            return
        if self.is_rolled_back:
            return

        self.is_rolled_back = True
        logger.warning(f"[UPLOAD TX] [{self.folder_hash}] ⚠️ Откат транзакции (причина: {reason}). Очистка {self.temp_dir}...")

        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                logger.info(f"[UPLOAD TX] [{self.folder_hash}] 🗑️ Временная папка успешно удалена: {self.temp_dir}")
        except Exception as e:
            logger.error(f"[UPLOAD TX] [{self.folder_hash}] Ошибка удаления временной папки: {e}", exc_info=True)
        finally:
            upload_coordinator.remove_transaction(self.folder_hash)


class UploadCoordinator:
    """
    Синглтон-координатор транзакций загрузки.
    Отслеживает открытые загрузки и привязывает их к сессиям WSRPC.
    """

    def __init__(self):
        self._transactions: Dict[str, UploadTransaction] = {}
        os.makedirs(TEMP_UPLOADS_ROOT, exist_ok=True)

    def create_transaction(
        self,
        session=None,
        expected_files_count: int = 0,
        owner_id: int = 1,
        folder_hash: Optional[str] = None,
    ) -> UploadTransaction:
        """
        Создает новую транзакцию загрузки. При передаче session автоматически
        вешает хук на дисконнект для гарантированной очистки временных файлов.
        """
        if not folder_hash:
            folder_hash = secrets.token_urlsafe(9)
        # Очистка хэша от спецсимволов
        folder_hash = "".join(c for c in folder_hash if c.isalnum() or c in ("-", "_"))[:32]

        temp_dir = os.path.join(TEMP_UPLOADS_ROOT, folder_hash)
        os.makedirs(temp_dir, exist_ok=True)

        tx = UploadTransaction(
            folder_hash=folder_hash,
            temp_dir=temp_dir,
            expected_files_count=expected_files_count,
            owner_id=owner_id,
            session=session,
        )

        self._transactions[folder_hash] = tx
        logger.info(
            f"[UPLOAD COORDINATOR] Создана транзакция: hash={folder_hash}, "
            f"owner={owner_id}, expected_files={expected_files_count}, temp_dir={temp_dir}"
        )

        # Если есть сессия WSRPC — регистрируем авто-откат при дисконнекте
        if session and hasattr(session, "register_on_close"):
            def on_session_close(_s):
                if not tx.is_committed and not tx.is_rolled_back:
                    logger.info(f"[UPLOAD COORDINATOR] 🔌 WS Дисконнект сессии! Авто-откат транзакции {folder_hash}")
                    tx.rollback(reason="ws_disconnect")

            session.register_on_close(on_session_close)

        return tx

    def get_transaction(self, folder_hash: str) -> Optional[UploadTransaction]:
        return self._transactions.get(folder_hash)

    def remove_transaction(self, folder_hash: str) -> Optional[UploadTransaction]:
        return self._transactions.pop(folder_hash, None)

    def cleanup_stale_transactions(self, max_age_seconds: float = 3600) -> int:
        """
        Очистка зависших транзакций старше max_age_seconds (по умолчанию 1 час).
        """
        now = time.time()
        stale_hashes = [
            h for h, tx in self._transactions.items()
            if (now - tx.created_at) > max_age_seconds and not tx.is_committed
        ]
        count = 0
        for h in stale_hashes:
            tx = self._transactions.get(h)
            if tx:
                tx.rollback(reason="stale_timeout")
                count += 1
        return count


# Глобальный синглтон координатора
upload_coordinator = UploadCoordinator()


async def stream_request_to_disk(
    proto,
    target_filepath: str,
    max_size: int = 100 * 1024 * 1024,
) -> Tuple[int, str]:
    """
    Потоково считывает байты из RSGI proto прямо в файл на диске.
    Обеспечивает O(1) RAM и считает SHA-256 на лету.
    """
    total_size = 0
    hasher = hashlib.sha256()

    os.makedirs(os.path.dirname(target_filepath), exist_ok=True)

    with open(target_filepath, "wb") as f:
        async for chunk in proto:
            chunk_len = len(chunk)
            total_size += chunk_len
            if total_size > max_size:
                raise ValueError(f"Превышен максимальный допустимый размер файла ({max_size} байт)")
            hasher.update(chunk)
            f.write(chunk)

    sha256_hex = hasher.hexdigest()
    logger.debug(f"[STREAM UPLOAD] Сохранено {total_size} байт в {target_filepath}, sha256={sha256_hex[:8]}...")
    return total_size, sha256_hex
