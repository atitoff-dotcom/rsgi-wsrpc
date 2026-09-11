# -*- coding: utf-8 -*-

import os
import secrets
import re
import urllib.parse
import traceback
import mimetypes
import orjson
import shutil
from sqlalchemy import text

from app.system.db import async_session
from app.system.files.service import FileStorageService
from core.security import decode_access_token
from core.lib.config import settings
from core.router import http_route
from core.logger import logger
from core.upload import upload_coordinator, stream_request_to_disk


def get_header(scope, name: str) -> str | None:
    """
    Безопасно извлекает заголовок из scope.headers.
    В RSGI/Granian scope.headers является объектом типа Headers/dict-like,
    который поддерживает метод .get() и возвращает bytes.
    """
    try:
        val = scope.headers.get(name.lower()) or scope.headers.get(name)
        if val is None:
            return None
        if isinstance(val, bytes):
            return val.decode("utf-8")
        return str(val)
    except Exception:
        return None


@http_route("/auth-check-upload", methods=["GET", "POST"])
async def handle_check_upload(scope, proto):
    """
    Проверяет JWT-токен из заголовков запроса.
    Используется Nginx auth_request для контроля доступа перед загрузкой тела файла.
    """
    try:
        token = None
        
        # 1. Проверяем заголовок Authorization
        auth_val = get_header(scope, "authorization")
        if auth_val and auth_val.startswith("Bearer "):
            token = auth_val.split(" ")[1]
            
        # 2. Проверяем Cookie rpc_jwt
        if not token:
            cookie_val = get_header(scope, "cookie")
            if cookie_val:
                match = re.search(r'rpc_jwt=([^;]+)', cookie_val)
                if match:
                    token = match[1]

        if not token:
            proto.response_str(
                status=401,
                headers=[("content-type", "text/plain")],
                body="Unauthorized: Missing token"
            )
            return

        try:
            decode_access_token(token)
            proto.response_str(
                status=200,
                headers=[("content-type", "text/plain")],
                body="OK"
            )
        except Exception as e:
            proto.response_str(
                status=403,
                headers=[("content-type", "text/plain")],
                body=f"Forbidden: Invalid token ({str(e)})"
            )
    except Exception as e:
        traceback.print_exc()
        try:
            proto.response_str(status=500, body=str(e))
        except Exception:
            pass


@http_route("/upload-register", methods=["POST"])
async def handle_file_upload_register(scope, proto):
    """
    Обработчик HTTP POST /upload-register.
    Получает путь к временному файлу Nginx из заголовка X-File-Path,
    перемещает его в бандл-директорию (транзакционную или боевую) и регистрирует в БД.
    """
    try:
        temp_filepath = None
        filename = "uploaded_file"
        token = None

        x_file_path = get_header(scope, "x-file-path")
        if x_file_path:
            temp_filepath = urllib.parse.unquote(x_file_path)

        x_file_name = get_header(scope, "x-file-name")
        if x_file_name:
            filename = urllib.parse.unquote(x_file_name)

        auth_val = get_header(scope, "authorization")
        if auth_val and auth_val.startswith("Bearer "):
            token = auth_val.split(" ")[1]

        if not token:
            cookie_val = get_header(scope, "cookie")
            if cookie_val:
                match = re.search(r'rpc_jwt=([^;]+)', cookie_val)
                if match:
                    token = match[1]

        if not temp_filepath:
            proto.response_str(
                status=400,
                headers=[("content-type", "application/json")],
                body=orjson.dumps({"error": "Missing X-File-Path header"}).decode("utf-8")
            )
            return

        if not os.path.exists(temp_filepath):
            proto.response_str(
                status=400,
                headers=[("content-type", "application/json")],
                body=orjson.dumps({"error": f"Nginx temp file not found at {temp_filepath}"}).decode("utf-8")
            )
            return

        user_id = 1
        if token:
            try:
                payload = decode_access_token(token)
                user_id = int(payload.get("sub", 1))
            except Exception:
                user_id = 1

        size = os.path.getsize(temp_filepath)

        base_files_path = getattr(settings, "files_path", "files")
        if not os.path.exists(base_files_path):
            os.makedirs(base_files_path, exist_ok=True)

        # 1. Извлекаем или генерируем хэш папки
        folder_hash = get_header(scope, "x-folder-hash")
        if not folder_hash and hasattr(scope, "query_string"):
            qs_raw = scope.query_string
            if isinstance(qs_raw, bytes):
                qs_raw = qs_raw.decode("utf-8")
            qs = urllib.parse.parse_qs(str(qs_raw or ""))
            folder_hash = qs.get("folder", [None])[0]

        if not folder_hash:
            folder_hash = secrets.token_urlsafe(9)
        folder_hash = re.sub(r'[^a-zA-Z0-9_-]', '', str(folder_hash))[:32]

        ext = os.path.splitext(filename)[1].lower()
        if not ext or len(ext) > 10:
            ext = ".webp"

        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        # Проверяем, есть ли открытая транзакция в Core UploadCoordinator
        tx = upload_coordinator.get_transaction(folder_hash)
        target_dir = tx.temp_dir if tx else os.path.join(base_files_path, folder_hash)
        os.makedirs(target_dir, exist_ok=True)

        existing_files = [f for f in os.listdir(target_dir) if not f.startswith(".")]
        new_filename = f"{len(existing_files) + 1}{ext}"
        final_filepath = os.path.join(target_dir, new_filename)
        token_path = f"{folder_hash}/{new_filename}"

        # Перемещаем временный файл Nginx в целевую папку
        shutil.move(temp_filepath, final_filepath)

        # Регистрируем в БД через FileStorageService
        file_id = await FileStorageService.register_file(
            folder_hash=folder_hash,
            filename=new_filename,
            original_name=filename,
            size=size,
            owner_id=user_id,
            mime_type=mime_type,
            is_public=True,
        )

        if tx:
            tx.add_file(
                filename=new_filename,
                original_name=filename,
                size=size,
                mime_type=mime_type,
            )

        resp_data = orjson.dumps({
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "folder_hash": folder_hash,
            "token_path": token_path,
            "url": f"/files/{token_path}",
            "download_filename": filename,
        })
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
    except Exception as e:
        logger.error(f"[UPLOAD-REGISTER] Ошибка регистрации файла: {e}", exc_info=True)
        err_data = orjson.dumps({"error": str(e)})
        try:
            proto.response_str(
                status=500,
                headers=[("content-type", "application/json")],
                body=err_data.decode("utf-8")
            )
        except Exception:
            pass


@http_route("/upload", methods=["POST"])
async def handle_file_upload(scope, proto):
    """
    Потоковый обработчик HTTP POST /upload на базе core/upload.py.
    Считывает данные напрямую из RSGI proto в файл на диске с O(1) RAM.
    Поддерживает как транзакционный 2PC режим, так и прямое сохранение.
    """
    try:
        filename = "uploaded_file"
        token = None

        x_file_name = get_header(scope, "x-file-name")
        if x_file_name:
            filename = urllib.parse.unquote(x_file_name)

        auth_val = get_header(scope, "authorization")
        if auth_val and auth_val.startswith("Bearer "):
            token = auth_val.split(" ")[1]

        if not token:
            cookie_val = get_header(scope, "cookie")
            if cookie_val:
                match = re.search(r'rpc_jwt=([^;]+)', cookie_val)
                if match:
                    token = match[1]

        user_id = 1
        if token:
            try:
                payload = decode_access_token(token)
                user_id = int(payload.get("sub", 1))
            except Exception:
                user_id = 1

        base_files_path = getattr(settings, "files_path", "files")
        if not os.path.exists(base_files_path):
            os.makedirs(base_files_path, exist_ok=True)

        # 1. Извлекаем или генерируем хэш папки
        folder_hash = get_header(scope, "x-folder-hash")
        if not folder_hash and hasattr(scope, "query_string"):
            qs_raw = scope.query_string
            if isinstance(qs_raw, bytes):
                qs_raw = qs_raw.decode("utf-8")
            qs = urllib.parse.parse_qs(str(qs_raw or ""))
            folder_hash = qs.get("folder", [None])[0]

        if not folder_hash:
            folder_hash = secrets.token_urlsafe(9)
        folder_hash = re.sub(r'[^a-zA-Z0-9_-]', '', str(folder_hash))[:32]

        ext = os.path.splitext(filename)[1].lower()
        if not ext or len(ext) > 10:
            ext = ".webp"

        mime_type, _ = mimetypes.guess_type(filename)
        mime_type = mime_type or "application/octet-stream"

        # Проверяем, есть ли транзакция в Core UploadCoordinator
        tx = upload_coordinator.get_transaction(folder_hash)
        target_dir = tx.temp_dir if tx else os.path.join(base_files_path, folder_hash)
        os.makedirs(target_dir, exist_ok=True)

        existing_files = [f for f in os.listdir(target_dir) if not f.startswith(".")]
        new_filename = f"{len(existing_files) + 1}{ext}"
        final_filepath = os.path.join(target_dir, new_filename)
        token_path = f"{folder_hash}/{new_filename}"

        # Потоковая запись чанков прямо на диск (O(1) RAM) с расчетом SHA-256
        size, sha256_hex = await stream_request_to_disk(proto, final_filepath)

        # Регистрируем в БД через FileStorageService
        file_id = await FileStorageService.register_file(
            folder_hash=folder_hash,
            filename=new_filename,
            original_name=filename,
            size=size,
            owner_id=user_id,
            mime_type=mime_type,
            sha256=sha256_hex,
            is_public=True,
        )

        if tx:
            tx.add_file(
                filename=new_filename,
                original_name=filename,
                size=size,
                mime_type=mime_type,
                sha256=sha256_hex,
            )

        resp_data = orjson.dumps({
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "folder_hash": folder_hash,
            "token_path": token_path,
            "url": f"/files/{token_path}",
            "download_filename": filename,
            "sha256": sha256_hex,
        })
        proto.response_str(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("access-control-allow-origin", "*")
            ],
            body=resp_data.decode("utf-8")
        )
    except Exception as e:
        logger.error(f"[UPLOAD STREAM] Ошибка потоковой загрузки файла: {e}", exc_info=True)
        err_data = orjson.dumps({"error": str(e)})
        try:
            proto.response_str(
                status=500,
                headers=[("content-type", "application/json")],
                body=err_data.decode("utf-8")
            )
        except Exception:
            pass
