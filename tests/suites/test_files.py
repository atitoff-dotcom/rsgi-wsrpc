# -*- coding: utf-8 -*-
"""
Тест-сьют: Двухфазная загрузка файлов (Files Suite).
Проверяет потоковую загрузку файлов на HTTP /upload и раздачу.
"""

from tests.framework import (
    PersonaManager,
    TestClient,
    assert_rpc_success,
)


async def test_two_phase_file_upload():
    """Проверяет загрузку файла на сервер через потоковый /upload."""
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
