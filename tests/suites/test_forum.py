# -*- coding: utf-8 -*-
"""
Тест-сьют: Форум (Forum Suite).
Проверяет жизненный цикл топиков, права доступа и push-инвалидацию кэша при создании/удалении.
"""

import asyncio
from tests.framework import (
    PersonaManager,
    TestClient,
    assert_rpc_success,
    assert_rpc_error,
    assert_notification,
)


async def test_get_topics_guest():
    """Проверяет получение списка топиков гостевым клиентом."""
    async with await PersonaManager.as_guest() as client:
        res = await client.call("forum.get_topics", {})
        assert isinstance(res, (list, dict)), "Список тем должен возвращаться в виде списка или словаря"


async def test_topic_creation_and_cache_invalidation():
    """
    Проверяет:
    1. Создание новой темы авторизованным пользователем.
    2. Автоматическое получение push-нотификации cache.invalidate с тегом 'forum.topics'.
    3. Очистку созданной темы.
    """
    async with await PersonaManager.as_guest() as listener:
        async with await PersonaManager.as_admin() as author:
            # Слушатель ждет события инвалидации кэша форума
            wait_task = asyncio.create_task(listener.wait_for_notification("cache.invalidate", timeout=5.0))
            await asyncio.sleep(0.05)

            # Автор создает топик
            topic_res = await author.call("forum.create_topic", {
                "title": "Автотест каркаса тестирования",
                "category_id": 1,
                "content": "Содержимое тестового топика, созданного автоматическим раннером.",
            })
            assert_rpc_success(topic_res, expected_keys=["id", "status"])
            topic_id = topic_res["id"]

            try:
                # Проверяем, что слушатель получил уведомление об инвалидации тем
                notif = await wait_task
                assert_notification(notif, "cache.invalidate")
                tags = notif["params"]["tags"]
                assert "forum.topics" in tags, f"Тег 'forum.topics' должен быть в списке инвалидированных: {tags}"

            finally:
                # Удаляем тестовый топик
                del_res = await author.call("forum.delete_topic", {"id": topic_id})
                assert_rpc_success(del_res)


async def test_unauthorized_deletion_prevented():
    """
    Проверяет Row-Level Security / проверку прав:
    Обычный пользователь не может удалить чужой топик.
    """
    async with await PersonaManager.as_admin() as admin:
        # Админ создает тему
        t = await admin.call("forum.create_topic", {
            "title": "Админский топик для проверки прав",
            "category_id": 1,
            "content": "Только админ или автор может удалить.",
        })
        topic_id = t["id"]

        try:
            # Обычный пользователь пытается удалить
            async with await PersonaManager.as_user("regular_user_probe", "Pass123456!") as regular_user:
                await assert_rpc_error(
                    regular_user.call("forum.delete_topic", {"id": topic_id}),
                    expected_message="Нет прав на удаление",
                )
        finally:
            # Админ подчищает топик
            await admin.call("forum.delete_topic", {"id": topic_id})
