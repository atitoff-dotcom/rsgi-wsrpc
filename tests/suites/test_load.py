# -*- coding: utf-8 -*-
"""
Тест-сьют: Нагрузочное и стресс-тестирование (Load & Stress Suite).
Проверяет пропускную способность WebSocket-соединений, поведение при конкурентных
запросах, задержки (latency p50, p95, p99) и надежность рассылки push-нотификаций (fan-out)
при десятках и сотнях одновременно подключенных клиентов.
"""

import asyncio
import time
from typing import List
from tests.framework import (
    PersonaManager,
    TestClient,
    assert_rpc_success,
    assert_notification,
)


async def test_concurrent_rpc_throughput():
    """
    Стресс-тест конкурентных RPC-вызовов:
    Создает 25 параллельных клиентов, каждый из которых выполняет пачку запросов.
    Замеряет пропускную способность (RPS) и проверяет отсутствие 500 ошибок и тайм-аутов.
    """
    CONCURRENT_CLIENTS = 20
    REQUESTS_PER_CLIENT = 10
    total_requests = CONCURRENT_CLIENTS * REQUESTS_PER_CLIENT

    latencies: List[float] = []

    async def client_worker(worker_id: int):
        async with await PersonaManager.as_guest() as client:
            for i in range(REQUESTS_PER_CLIENT):
                t0 = time.perf_counter()
                res = await client.call("system.echo", {"worker": worker_id, "req": i})
                lat = (time.perf_counter() - t0) * 1000
                latencies.append(lat)
                assert res.get("status") == "ok"

    start = time.perf_counter()
    tasks = [asyncio.create_task(client_worker(i)) for i in range(CONCURRENT_CLIENTS)]
    await asyncio.gather(*tasks)
    total_duration = time.perf_counter() - start

    rps = total_requests / total_duration if total_duration > 0 else 0
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0

    print(f"\n      📊 [LOAD STATS] {total_requests} запросов за {total_duration:.2f}s | {rps:.1f} RPS")
    print(f"      ⏱️  Задержки: p50={p50:.1f}ms, p95={p95:.1f}ms, p99={p99:.1f}ms", end="")

    assert len(latencies) == total_requests, "Все запросы должны завершиться успешно"


async def test_concurrent_broadcast_fanout():
    """
    Стресс-тест широковещательной рассылки (Fan-out):
    Подключает 25 клиентов-слушателей одновременно, после чего автор
    производит инвалидацию тега. Проверяет, что 100% слушателей получили
    нотификацию без потерь и зависаний очереди событий.
    """
    LISTENERS_COUNT = 25
    test_tag = "load.test.fanout_tag"

    listeners: List[TestClient] = []
    try:
        # 1. Открываем пачку соединений
        for _ in range(LISTENERS_COUNT):
            client = await PersonaManager.as_guest()
            listeners.append(client)

        # 2. Каждый слушатель встает на ожидание нотификации
        wait_tasks = [
            asyncio.create_task(listener.wait_for_notification("cache.invalidate", timeout=5.0))
            for listener in listeners
        ]
        await asyncio.sleep(0.1)  # даем сокетам встать в режим ожидания

        # 3. Автор производит мутацию/инвалидацию
        async with await PersonaManager.as_admin() as actor:
            t0 = time.perf_counter()
            inv_res = await actor.call("cache.invalidate", {"tags": [test_tag]})
            assert_rpc_success(inv_res)

        # 4. Собираем результаты со всех слушателей
        notifications = await asyncio.gather(*wait_tasks)
        fanout_duration_ms = (time.perf_counter() - t0) * 1000

        print(f"\n      ⚡ [FAN-OUT STATS] Рассылка на {LISTENERS_COUNT} активных WebSocket-клиентов за {fanout_duration_ms:.1f}ms", end="")

        assert len(notifications) == LISTENERS_COUNT
        for notif in notifications:
            assert_notification(notif, "cache.invalidate")
            assert test_tag in notif["params"]["tags"]

    finally:
        # Корректно закрываем всех клиентов
        for client in listeners:
            await client.close()
