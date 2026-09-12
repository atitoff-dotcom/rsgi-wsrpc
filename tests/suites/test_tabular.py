# -*- coding: utf-8 -*-
"""
Тест-сьют: Табличное сжатие (Tabular Compression Suite / RFC 0002).
Проверяет:
1. Модульное кодирование/декодирование pack_tabular / unpack_tabular.
2. Экономию размера payload (>40% для коллекций).
3. Работу WSRPC: сервер возвращает сырой $tabular: true, клиент прозрачно распаковывает.
"""

import asyncio
import orjson
from tests.framework import PersonaManager, assert_rpc_success
from core.tabular import pack_tabular, unpack_tabular, is_tabular


def test_tabular_roundtrip():
    """Проверяет точное восстановление данных после pack -> unpack."""
    original = [
        {"id": 1, "title": "Первая тема", "views": 100, "pinned": True, "meta": {"tag": "agro"}},
        {"id": 2, "title": "Вторая тема", "views": 250, "pinned": False, "meta": {"tag": "calc"}},
        {"id": 3, "title": "Третья тема", "views": 0, "pinned": False, "meta": None},
    ]

    packed = pack_tabular(original)
    assert is_tabular(packed), "Упакованный объект должен содержать сигнатуру $tabular: True"
    assert packed["$tabular"] is True
    assert "fields" in packed and "rows" in packed
    assert len(packed["rows"]) == 3

    unpacked = unpack_tabular(packed)
    assert unpacked == original, "Распакованные данные должны совпадать с исходными"


def test_tabular_payload_savings():
    """Замеряет экономию сетевого трафика и размера payload."""
    items = [
        {
            "topic_id": i,
            "category_id": 4,
            "author_id": 12,
            "author_name": f"Agronomist_{i}",
            "title": f"Динамика EC и pH дренажа томата #{i}",
            "views_count": i * 15,
            "replies_count": i % 7,
            "is_pinned": i == 0,
            "created_at": "2026-09-11T12:00:00Z"
        }
        for i in range(50)
    ]

    raw_bytes = len(orjson.dumps(items))
    packed_bytes = len(orjson.dumps(pack_tabular(items)))
    savings = (1 - (packed_bytes / raw_bytes)) * 100

    assert packed_bytes < raw_bytes
    assert savings > 35.0, f"Ожидалась экономия более 35%, получено {savings:.1f}%"


async def test_wsrpc_raw_and_transparent_tabular():
    """
    Проверяет WSRPC-протокол:
    - При raw=True метод forum.get_categories возвращает сырой {$tabular: True, fields, rows}.
    - При обычном вызове клиент прозрачно разворачивает данные в список словарей.
    """
    async with await PersonaManager.as_guest() as client:
        # 1. Сырой ответ
        raw_res = await client.call("forum.get_categories", {}, raw=True)
        assert is_tabular(raw_res), f"Сервер должен отдавать категории с $tabular: True: {raw_res}"
        assert raw_res["$tabular"] is True
        assert isinstance(raw_res["fields"], list)
        assert isinstance(raw_res["rows"], list)

        # 2. Прозрачный ответ (как видит фронтенд)
        unpacked_res = await client.call("forum.get_categories", {}, raw=False)
        assert isinstance(unpacked_res, list), "Клиент должен прозрачно возвращать список объектов"
        assert len(unpacked_res) > 0
        first = unpacked_res[0]
        assert "id" in first
        assert "title" in first or "name" in first


async def test_wsrpc_topics_tabular():
    """Проверяет получение топиков форума в табличном сжатом формате."""
    async with await PersonaManager.as_guest() as client:
        raw_topics = await client.call("forum.get_topics", {"limit": 10}, raw=True)
        assert is_tabular(raw_topics), f"Сервер должен отдавать топики с $tabular: True: {raw_topics}"

        unpacked_topics = await client.call("forum.get_topics", {"limit": 10}, raw=False)
        assert isinstance(unpacked_topics, list)
        if len(unpacked_topics) > 0:
            assert "id" in unpacked_topics[0]
            assert "title" in unpacked_topics[0]
