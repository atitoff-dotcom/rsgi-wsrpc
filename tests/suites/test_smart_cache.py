# -*- coding: utf-8 -*-
"""
Тест-сьют: Плагин реактивного кэша (Smart Cache Suite).
Проверяет RPC-методы версионирования, рукопожатие оффлайн-синхронизации
и получение push-нотификаций cache.invalidate / cache.patch.
"""

import asyncio
from tests.framework import (
    PersonaManager,
    TestClient,
    assert_rpc_success,
    assert_notification,
)


async def test_cache_get_versions():
    """Проверяет получение версий тегов через cache.get_versions."""
    async with await PersonaManager.as_guest() as client:
        res = await client.call("cache.get_versions", {"tags": ["forum.topics", "non_existent_tag_xyz"]})
        assert_rpc_success(res, expected_keys=["versions"])
        versions = res["versions"]
        assert "forum.topics" in versions
        assert isinstance(versions["forum.topics"], int)
        assert versions["non_existent_tag_xyz"] == 1


async def test_cache_sync_check_stale_detection():
    """Проверяет выявление устаревших тегов при рукопожатии (cache.sync_check)."""
    async with await PersonaManager.as_guest() as client:
        # Сначала получаем актуальную версию
        v_res = await client.call("cache.get_versions", {"tags": ["forum.topics"]})
        current_v = v_res["versions"]["forum.topics"]

        # 1. Клиент заявляет устаревшую версию (current_v - 1)
        stale_check = await client.call("cache.sync_check", {
            "tags": {"forum.topics": max(0, current_v - 1)}
        })
        assert_rpc_success(stale_check, expected_keys=["stale_tags", "current_versions"])
        assert "forum.topics" in stale_check["stale_tags"], "Устаревший тег должен быть обнаружен в stale_tags"

        # 2. Клиент заявляет актуальную версию
        fresh_check = await client.call("cache.sync_check", {
            "tags": {"forum.topics": current_v}
        })
        assert "forum.topics" not in fresh_check["stale_tags"], "Актуальный тег не должен быть в stale_tags"


async def test_live_cache_invalidation_notification():
    """
    Проверяет перехват серверной push-нотификации cache.invalidate:
    Клиент-слушатель ожидает событие, а второй клиент вызывает инвалидацию тега.
    """
    async with await PersonaManager.as_guest() as listener:
        async with await PersonaManager.as_admin() as actor:
            test_tag = "test.suite.live_tag"

            # Создаем фоновую задачу ожидания нотификации
            wait_task = asyncio.create_task(listener.wait_for_notification("cache.invalidate", timeout=5.0))
            await asyncio.sleep(0.05)  # даем сокету встать на ожидание

            # Второй клиент запускает инвалидацию
            inv_res = await actor.call("cache.invalidate", {
                "tags": [test_tag],
                "reason": "test_mutation",
            })
            assert_rpc_success(inv_res, expected_keys=["invalidated_tags"])

            # Слушатель получает нотификацию
            notif = await wait_task
            assert_notification(notif, "cache.invalidate")
            params = notif["params"]
            assert test_tag in params["tags"]
            assert "versions" in params
            assert test_tag in params["versions"]
            assert params["versions"][test_tag] >= 2
