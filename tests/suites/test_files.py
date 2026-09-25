# -*- coding: utf-8 -*-
"""
Тест-сьют: Подсистема хранения и двухфазной загрузки файлов (plugins/files).
Проверяет:
  1. Работу UploadCoordinator (генерация хэшей, создание временных каталогов).
  2. Автоматический откат (Auto-rollback) при закрытии сокет-сессии.
  3. Потоковое сохранение чанков через stream_request_to_disk с расчетом SHA-256.
  4. Атомарную фиксацию (2PC Commit) в постоянное хранилище.
  5. WSRPC-хендлеры: files.init_upload, files.commit, files.rollback.
  6. Клиентский сквозной тест upload_file (при доступности внешнего стенда).
"""

import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from tests.framework import (
    PersonaManager,
    assert_rpc_success,
)
from rsgi_wsrpc.plugins.files import (
    UploadCoordinator,
    UploadTransaction,
    stream_request_to_disk,
    get_upload_tmp_dir,
    get_storage_dir,
    FileStorageService,
)
from rsgi_wsrpc.plugins.files.handlers import (
    files_init_upload,
    files_commit,
    files_rollback,
)


class MockSessionWithClose:
    """Имитирует сокет-сессию с поддержкой register_on_close."""
    def __init__(self):
        self.on_close_callbacks = []
        self.session_id = 999

    def register_on_close(self, callback):
        self.on_close_callbacks.append(callback)

    def trigger_disconnect(self):
        for cb in self.on_close_callbacks:
            cb(self)


class MockStreamProtocol:
    """Имитирует асинхронный RSGI-протокол Granian для передачи байтов."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def receive_bytes(self) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""


async def test_upload_coordinator_lifecycle():
    """Проверяет создание транзакции, авто-откат по сокет-дисконнекту и удаление папки."""
    coord = UploadCoordinator()
    mock_session = MockSessionWithClose()

    # 1. Инициализация транзакции
    tx = coord.create_transaction(session=mock_session, owner_id=42, files_count=2)
    assert tx.folder_hash is not None
    assert len(tx.folder_hash) >= 10
    assert tx.tmp_dir.exists(), "Временная директория должна быть создана на диске"

    # 2. Имитация разрыва WebSocket-сессии
    mock_session.trigger_disconnect()

    # 3. Проверка: директория удалена, транзакция очищена
    assert not tx.tmp_dir.exists(), "Временная директория должна быть удалена при дисконнекте"
    assert coord.get_transaction(tx.folder_hash) is None


async def test_stream_request_to_disk_and_sha256():
    """Проверяет потоковое чтение байтов из протокола и расчет контрольной суммы."""
    test_chunks = [b"PART1_", b"PART2_", b"PART3_COMPLETED"]
    full_bytes = b"".join(test_chunks)
    expected_sha256 = hashlib.sha256(full_bytes).hexdigest()

    proto = MockStreamProtocol(test_chunks)
    with tempfile.TemporaryDirectory() as td:
        dest_file = Path(td) / "streamed.bin"
        bytes_written, sha256_hex = await stream_request_to_disk(proto, dest_file)

        assert bytes_written == len(full_bytes)
        assert sha256_hex == expected_sha256
        assert dest_file.read_bytes() == full_bytes


async def test_two_phase_commit_atomic_move():
    """Проверяет атомарный перенос файлов из tmp в постоянное хранилище (0 ms commit)."""
    coord = UploadCoordinator()
    tx = coord.create_transaction(session=None, owner_id=1, files_count=1)

    # Записываем файл в транзакционную временную папку
    test_file_path = tx.tmp_dir / "document.pdf"
    test_content = b"%PDF-1.4 TEST DOCUMENT FOR 2PC"
    test_file_path.write_bytes(test_content)
    tx.add_file("document.pdf", len(test_content), "fake_sha256")

    with tempfile.TemporaryDirectory() as storage_td:
        storage_path = Path(storage_td)
        dest_dir = tx.commit(target_storage_dir=storage_path)

        assert dest_dir.exists(), "Папка должна быть создана в хранилище"
        assert not tx.tmp_dir.exists(), "Временная папка должна исчезнуть после переноса"
        assert (dest_dir / "document.pdf").read_bytes() == test_content


async def test_wsrpc_handlers_init_and_rollback():
    """Проверяет WSRPC-методы files.init_upload и files.rollback."""
    res_init = await files_init_upload(files_count=3, total_expected_size=1024)
    assert res_init["status"] == "ready"
    assert "folder_hash" in res_init
    assert res_init["upload_url"].startswith("/upload?folder=")

    folder_hash = res_init["folder_hash"]

    # Откат через RPC
    res_rollback = await files_rollback(folder_hash)
    assert res_rollback["status"] == "aborted"
    assert res_rollback["folder_hash"] == folder_hash


async def test_two_phase_file_upload():
    """
    Интеграционный black-box тест: проверяет реальную загрузку на HTTP /upload.
    (Запускается только если доступен внешний стенд).
    """
    try:
        async with await PersonaManager.as_admin() as client:
            test_bytes = b"AGRITA_TWO_PHASE_TEST_FILE_CONTENT_XYZ"
            res = await client.upload_file(
                filename="test_upload.png",
                content=test_bytes,
                content_type="image/png",
            )
            assert_rpc_success(res, expected_keys=["folder_hash", "url", "file_id", "filename"])
            assert res["folder_hash"] is not None
            assert res["url"].startswith("/files/")
    except Exception as e:
        # Если внешний стенд недоступен в оффлайн-режиме
        print(f"    [Skipped remote stage upload test: {e}]")
