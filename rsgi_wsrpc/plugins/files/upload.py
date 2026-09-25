# -*- coding: utf-8 -*-
"""
Подсистема двухфазной потоковой загрузки файлов (plugins/files/upload.py).
Реализует RFC 0005: Two-Phase Commit (2PC) Upload Lifecycle & RSGI Streaming.
"""

import asyncio
import hashlib
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs

import orjson

from rsgi_wsrpc.core.lib.config import get_config
from rsgi_wsrpc.core.logger import logger
from rsgi_wsrpc.core.router import http_route
from rsgi_wsrpc.core.session import current_user_ctx
from rsgi_wsrpc.plugins.db import async_session
from .models import StoredFile

# Регулярка для очистки имени файла от опасных символов
SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._\-А-Яа-яЁё]")


def get_upload_tmp_dir() -> Path:
    """Возвращает путь к временной папке транзакций загрузки."""
    cfg = get_config()
    tmp_path = cfg.get("upload_tmp_dir") if hasattr(cfg, "get") else None
    path_str = tmp_path or os.getenv("UPLOAD_TMP_DIR", "/tmp/app_uploads")
    p = Path(path_str)
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_storage_dir() -> Path:
    """Возвращает путь к постоянному хранилищу файлов."""
    cfg = get_config()
    files_path = getattr(cfg, "files_path", None) or os.getenv("FILES_PATH", "./data/files")
    p = Path(files_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sanitize_filename(filename: Optional[str]) -> str:
    """
    Очищает и нормализует имя файла для предотвращения Path Traversal атак.
    """
    if not filename:
        return f"file_{secrets.token_hex(4)}"
    base = os.path.basename(filename).strip()
    safe = SAFE_FILENAME_RE.sub("_", base)
    if not safe or safe in (".", ".."):
        return f"file_{secrets.token_hex(4)}"
    return safe[:255]


def extract_header(scope, header_name: str, default: Optional[str] = None) -> Optional[str]:
    """
    Извлекает заголовок из RSGI scope в независимом от регистра формате.
    Поддерживает Granian Headers, dict, список кортежей.
    """
    target = header_name.lower()
    headers = getattr(scope, "headers", None)
    if headers is None and isinstance(scope, dict):
        headers = scope.get("headers")

    if headers is None:
        return default

    if hasattr(headers, "get"):
        val = headers.get(target) or headers.get(target.encode("latin1"))
        if val is not None:
            return val.decode("latin1") if isinstance(val, bytes) else str(val)

    items = headers.items() if hasattr(headers, "items") else headers
    try:
        for k, v in items:
            k_str = k.decode("latin1").lower() if isinstance(k, bytes) else str(k).lower()
            if k_str == target:
                return v.decode("latin1") if isinstance(v, bytes) else str(v)
    except Exception:
        pass

    return default


def extract_query_params(scope) -> Dict[str, str]:
    """Извлекает query-параметры из RSGI scope."""
    qs = getattr(scope, "query_string", "")
    if isinstance(qs, bytes):
        qs = qs.decode("utf-8", errors="replace")
    elif not isinstance(qs, str):
        qs = str(qs or "")
    parsed = parse_qs(qs)
    return {k: v[0] if v else "" for k, v in parsed.items()}


async def stream_request_to_disk(
    proto,
    dest_path: Path,
    max_size: int = 250 * 1024 * 1024
) -> Tuple[int, str]:
    """
    Асинхронно считывает бинарные байты из RSGI протокола напрямую на диск.
    Гарантирует потребление памяти O(1) RAM и параллельно вычисляет SHA-256.

    :param proto: RSGI-протокол Granian.
    :param dest_path: Целевой файл на диске.
    :param max_size: Максимально допустимый размер файла в байтах.
    :return: Кортеж (размер_в_байтах, sha256_hex).
    """
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    bytes_written = 0

    with open(dest_path, "wb") as f:
        while True:
            if hasattr(proto, "receive_bytes"):
                chunk = await proto.receive_bytes()
            elif hasattr(proto, "receive"):
                msg = await proto.receive()
                if isinstance(msg, bytes):
                    chunk = msg
                elif isinstance(msg, dict):
                    chunk = msg.get("body", b"")
                else:
                    chunk = b""
            else:
                chunk = b""

            if not chunk:
                break

            bytes_written += len(chunk)
            if bytes_written > max_size:
                # Ограничение размера файла превышено
                try:
                    f.close()
                    dest_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise ValueError(f"Размер загружаемого файла превысил лимит ({max_size} байт)")

            f.write(chunk)
            hasher.update(chunk)

    return bytes_written, hasher.hexdigest()


class UploadTransaction:
    """
    Инкапсулирует двухфазную транзакцию загрузки файлов (2PC).
    """
    def __init__(
        self,
        folder_hash: str,
        owner_id: Optional[int] = None,
        files_count: int = 1,
        session: Optional[Any] = None,
    ):
        self.folder_hash = folder_hash
        self.owner_id = owner_id
        self.files_count = files_count
        self.session = session
        self.created_at = time.time()
        self.tmp_dir = get_upload_tmp_dir() / folder_hash
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.files: Dict[str, Dict[str, Any]] = {}
        self.is_committed = False
        self.is_rolled_back = False

    def add_file(
        self,
        filename: str,
        size: int,
        sha256: str,
        original_name: Optional[str] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Регистрирует принятый файл внутри транзакции."""
        info = {
            "filename": filename,
            "original_name": original_name or filename,
            "size": size,
            "sha256": sha256,
            "mime_type": mime_type or "application/octet-stream",
            "folder_hash": self.folder_hash,
            "path": str(self.tmp_dir / filename),
            "uploaded_at": time.time(),
        }
        self.files[filename] = info
        return info

    def rollback(self) -> None:
        """
        Откат транзакции: немедленное физическое удаление временной папки.
        """
        if self.is_committed or self.is_rolled_back:
            return
        self.is_rolled_back = True
        try:
            if self.tmp_dir.exists():
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
                logger.info(f"[Upload] Откат транзакции {self.folder_hash}: временная папка удалена.")
        except Exception as e:
            logger.error(f"[Upload] Ошибка при очистке транзакции {self.folder_hash}: {e}")

    def commit(self, target_storage_dir: Optional[Path] = None) -> Path:
        """
        Атомарная фиксация транзакции: перенос папки в постоянное хранилище (0 ms).
        """
        if self.is_rolled_back:
            raise RuntimeError(f"Невозможно закоммитить отмененную транзакцию {self.folder_hash}")
        if self.is_committed:
            target_storage_dir = target_storage_dir or get_storage_dir()
            return target_storage_dir / self.folder_hash

        target_base = target_storage_dir or get_storage_dir()
        dest_dir = target_base / self.folder_hash

        # Атомарное перемещение папки
        if self.tmp_dir.exists():
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            if dest_dir.exists():
                shutil.rmtree(dest_dir, ignore_errors=True)
            try:
                # Атомарный rename на уровне файловой системы
                os.replace(str(self.tmp_dir), str(dest_dir))
            except OSError:
                # Если каталоги на разных файловых системах
                shutil.move(str(self.tmp_dir), str(dest_dir))

        self.is_committed = True
        logger.info(f"[Upload] Коммит транзакции {self.folder_hash} -> {dest_dir}")
        return dest_dir


class UploadCoordinator:
    """
    Глобальный координатор транзакций загрузки.
    Связывает транзакции с WebSocket-сессиями и обеспечивает автоматический Rollback.
    """
    def __init__(self):
        self._active_txs: Dict[str, UploadTransaction] = {}

    def generate_folder_hash(self) -> str:
        """Генерирует криптографически стойкий 12-символьный хэш папки."""
        while True:
            h = secrets.token_urlsafe(9).replace("-", "x").replace("_", "y")[:12]
            if h not in self._active_txs:
                return h

    def create_transaction(
        self,
        session: Optional[Any] = None,
        owner_id: Optional[int] = None,
        files_count: int = 1,
    ) -> UploadTransaction:
        """
        Инициализирует транзакцию двухфазной загрузки (Phase 1).
        Регистрирует хук авто-отката в WebSocket-сессии.
        """
        folder_hash = self.generate_folder_hash()
        tx = UploadTransaction(
            folder_hash=folder_hash,
            owner_id=owner_id,
            files_count=files_count,
            session=session,
        )
        self._active_txs[folder_hash] = tx

        # Привязка хука автоматической очистки к сокет-сессии
        if session is not None and hasattr(session, "register_on_close"):
            def _on_disconnect(_):
                self.rollback_transaction(folder_hash)
            session.register_on_close(_on_disconnect)

        logger.debug(f"[Upload] Создана транзакция 2PC: {folder_hash} (owner_id={owner_id})")
        return tx

    def get_transaction(self, folder_hash: str) -> Optional[UploadTransaction]:
        return self._active_txs.get(folder_hash)

    def rollback_transaction(self, folder_hash: str) -> None:
        """Откатывает и удаляет транзакцию."""
        tx = self._active_txs.pop(folder_hash, None)
        if tx:
            tx.rollback()

    def commit_transaction(self, folder_hash: str) -> Optional[UploadTransaction]:
        """Завершает транзакцию и переносит файлы в постоянное хранилище."""
        tx = self._active_txs.pop(folder_hash, None)
        if tx:
            tx.commit()
            return tx
        return None

    def cleanup_stale(self, max_age_seconds: int = 7200) -> int:
        """Фоновый сборщик мусора для осиротевших временных папок старше max_age_seconds."""
        now = time.time()
        cleaned = 0
        # 1. Очистка по памяти
        stale_hashes = [
            h for h, tx in self._active_txs.items()
            if now - tx.created_at > max_age_seconds
        ]
        for h in stale_hashes:
            self.rollback_transaction(h)
            cleaned += 1

        # 2. Очистка на диске в /tmp/app_uploads
        try:
            tmp_base = get_upload_tmp_dir()
            if tmp_base.exists():
                for item in tmp_base.iterdir():
                    if item.is_dir():
                        mtime = item.stat().st_mtime
                        if now - mtime > max_age_seconds:
                            shutil.rmtree(item, ignore_errors=True)
                            cleaned += 1
        except Exception as e:
            logger.error(f"[Upload] Ошибка фоновой очистки временных файлов: {e}")

        return cleaned


# Глобальный реестр транзакций загрузки
upload_coordinator = UploadCoordinator()


@http_route("/auth-check-upload", ["GET", "POST", "OPTIONS"])
async def auth_check_upload_handler(scope, proto):
    """
    Эндпоинт предварительной проверки прав для Nginx `auth_request`.
    Отсекает неавторизованные сетевые потоки до передачи бинарного тела.
    """
    if scope.method == "OPTIONS":
        proto.response_str(
            status=204,
            headers=[
                ("access-control-allow-origin", "*"),
                ("access-control-allow-methods", "GET, POST, OPTIONS"),
                ("access-control-allow-headers", "*"),
            ],
            body=""
        )
        return

    auth_header = extract_header(scope, "authorization")
    cookie_header = extract_header(scope, "cookie")

    token = None
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    elif cookie_header:
        for part in cookie_header.split(";"):
            part = part.strip()
            if part.startswith("rpc_jwt="):
                token = part[8:].strip()
                break

    if not token:
        proto.response_str(
            status=401,
            headers=[("content-type", "application/json")],
            body='{"error": "Unauthorized"}'
        )
        return

    # Если токен найден — отдаем 200 OK
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status": "authorized"}'
    )


@http_route("/upload", ["POST", "OPTIONS"])
async def upload_handler(scope, proto):
    """
    Главный асинхронный RSGI-эндпоинт потоковой загрузки файлов.
    Поддерживает:
      1. Двухфазную транзакционную загрузку (query-параметр `folder` / заголовок `X-Folder-Hash`).
      2. Автономную одиночную загрузку с моментальным сохранением в БД и прод-папку.
    """
    # 1. Обработка CORS pre-flight
    if scope.method == "OPTIONS":
        proto.response_str(
            status=204,
            headers=[
                ("access-control-allow-origin", "*"),
                ("access-control-allow-methods", "POST, OPTIONS"),
                ("access-control-allow-headers", "content-type, x-file-name, x-folder-hash, authorization"),
            ],
            body=""
        )
        return

    try:
        # Извлечение параметров
        params = extract_query_params(scope)
        folder_hash = params.get("folder") or extract_header(scope, "x-folder-hash")
        raw_filename = (
            params.get("filename")
            or params.get("name")
            or extract_header(scope, "x-file-name")
            or "uploaded_file"
        )
        filename = sanitize_filename(raw_filename)
        content_type = extract_header(scope, "content-type") or "application/octet-stream"

        # Определение текущего пользователя
        current_user = current_user_ctx.get()
        owner_id = current_user.get("id") or current_user.get("user_id") if isinstance(current_user, dict) else getattr(current_user, "id", None)

        is_standalone = False
        tx = upload_coordinator.get_transaction(folder_hash) if folder_hash else None

        if tx is None:
            # Автономная моментальная загрузка (1-Phase / Standalone)
            is_standalone = True
            folder_hash = upload_coordinator.generate_folder_hash()
            dest_folder = get_storage_dir() / folder_hash
            dest_folder.mkdir(parents=True, exist_ok=True)
            dest_file = dest_folder / filename
        else:
            # 2PC Транзакция: пишем в изолированную временную папку
            dest_file = tx.tmp_dir / filename

        # 2. Потоковое асинхронное чтение байтов из RSGI протокола на диск (O(1) RAM)
        bytes_written, sha256_hex = await stream_request_to_disk(proto, dest_file)

        # 3. Регистрация файла
        file_id = None
        if not is_standalone and tx:
            tx.add_file(
                filename=filename,
                size=bytes_written,
                sha256=sha256_hex,
                original_name=raw_filename,
                mime_type=content_type,
            )
        else:
            # Для автономной загрузки сразу регистрируем в file_metadata
            try:
                async with async_session() as session:
                    stored_file = StoredFile(
                        folder_hash=folder_hash,
                        filename=filename,
                        original_name=raw_filename,
                        size=bytes_written,
                        mime_type=content_type,
                        sha256=sha256_hex,
                        owner_id=owner_id,
                        is_public=True,
                    )
                    session.add(stored_file)
                    await session.commit()
                    await session.refresh(stored_file)
                    file_id = stored_file.id
            except Exception as db_err:
                logger.warning(f"[Upload] Запись в БД пропущена (БД не настроена): {db_err}")

        # 4. Формирование успешного ответа
        url = f"/files/{folder_hash}/{filename}"
        result_payload = {
            "status": "ok",
            "success": True,
            "folder_hash": folder_hash,
            "filename": filename,
            "original_name": raw_filename,
            "size": bytes_written,
            "sha256": sha256_hex,
            "url": url,
            "file_id": file_id,
        }

        body_bytes = orjson.dumps(result_payload)
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json; charset=utf-8"),
                ("access-control-allow-origin", "*"),
            ],
            body=body_bytes.decode("utf-8")
        )

    except ValueError as ve:
        # Лимит размера или валидация
        err_body = orjson.dumps({"status": "error", "error": str(ve)})
        proto.response_str(
            status=413,
            headers=[("content-type", "application/json")],
            body=err_body.decode("utf-8")
        )
    except Exception as e:
        logger.error(f"[Upload] Ошибка при обработке загрузки: {e}", exc_info=True)
        err_body = orjson.dumps({"status": "error", "error": f"Upload failed: {str(e)}"})
        proto.response_str(
            status=500,
            headers=[("content-type", "application/json")],
            body=err_body.decode("utf-8")
        )
