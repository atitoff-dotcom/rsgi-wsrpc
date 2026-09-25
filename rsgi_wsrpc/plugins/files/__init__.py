# -*- coding: utf-8 -*-
"""
Официальный плагин хранения и двухфазной загрузки файлов (plugins/files).
Реализует RFC 0005: Two-Phase Commit (2PC) Upload Lifecycle & RSGI Streaming.
"""

from .models import StoredFile
from .upload import (
    UploadCoordinator,
    UploadTransaction,
    upload_coordinator,
    stream_request_to_disk,
    upload_handler,
    auth_check_upload_handler,
    get_storage_dir,
    get_upload_tmp_dir,
    sanitize_filename,
)
from .service import FileStorageService
# Импорт handlers регистрирует RPC-методы files.*
from . import handlers

__all__ = [
    "StoredFile",
    "FileStorageService",
    "UploadCoordinator",
    "UploadTransaction",
    "upload_coordinator",
    "stream_request_to_disk",
    "upload_handler",
    "auth_check_upload_handler",
    "get_storage_dir",
    "get_upload_tmp_dir",
    "sanitize_filename",
    "handlers",
]
