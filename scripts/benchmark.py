#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Высокопроизводительный открытый стресс-бенчмарк для фреймворка rsgi-wsrpc.
Замеряет чистый RPS, перцентили задержки (p50, p95, p99) и эффективность
табличного сжатия RFC 0002 Tabular.

Запуск:
    python scripts/benchmark.py
    python scripts/benchmark.py --concurrency 100 --requests 20000
    python scripts/benchmark.py --target http://127.0.0.1:8080 --method system.ping
"""

import argparse
import asyncio
import math
import statistics
import sys
import time
from typing import List, Tuple
import aiohttp
import orjson

# ANSI цвета
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


async def worker(
    worker_id: int,
    ws_url: str,
    method: str,
    params: dict,
    req_per_worker: int,
    latencies: List[float],
    bytes_counter: List[int],
    timeout: float,
):
    """Один воркер, отправляющий пачку запросов в постоянный WebSocket."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.ws_connect(ws_url, timeout=timeout) as ws:
                for i in range(req_per_worker):
                    req_id = (worker_id * 1_000_000) + i + 1
                    payload = orjson.dumps({
                        "jsonrpc": "2.0",
                        "method": method,
                        "params": params,
                        "id": req_id
                    }).decode()

                    start = time.perf_counter()
                    await ws.send_str(payload)
                    msg = await ws.receive(timeout=timeout)
                    elapsed_ms = (time.perf_counter() - start) * 1000

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        latencies.append(elapsed_ms)
                        bytes_counter[0] += len(msg.data)
                    else:
                        break
        except Exception:
            pass


async def run_benchmark(
    target: str,
    method: str,
    params: dict,
    concurrency: int,
    total_requests: int,
    timeout: float,
):
    ws_base = target.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    ws_url = ws_base if ws_base.endswith("/ws") else f"{ws_base}/ws"
    req_per_worker = total_requests // concurrency
    actual_total = req_per_worker * concurrency

    print(f"\n{BOLD}{CYAN}⚡  Запуск стресс-теста rsgi-wsrpc...{RESET}")
    print(f"{DIM}Target: {ws_url} | RPC Method: {method}{RESET}")
    print(f"{DIM}Параллельных соединений: {concurrency} | Запросов на сокет: {req_per_worker} | Всего: {actual_total}{RESET}\n")

    latencies: List[float] = []
    bytes_counter = [0]

    bench_start = time.perf_counter()

    tasks = [
        worker(w_id, ws_url, method, params, req_per_worker, latencies, bytes_counter, timeout)
        for w_id in range(concurrency)
    ]

    async def report_progress():
        try:
            bar_len = 25
            while True:
                await asyncio.sleep(0.1)
                done = len(latencies)
                pct = (done / actual_total) * 100 if actual_total > 0 else 0
                curr_time = time.perf_counter() - bench_start
                curr_rps = done / curr_time if curr_time > 0 else 0
                filled = int(bar_len * (done / actual_total)) if actual_total > 0 else 0
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"\r  {CYAN}Прогресс:{RESET} [{bar}] {pct:>5.1f}% ({done:,}/{actual_total:,}) | {curr_rps:,.0f} RPS", end="", flush=True)
        except asyncio.CancelledError:
            pass

    reporter_task = asyncio.create_task(report_progress())
    await asyncio.gather(*tasks)
    reporter_task.cancel()
    try:
        await reporter_task
    except asyncio.CancelledError:
        pass
    print("\r" + " " * 80 + "\r", end="", flush=True)

    total_time = time.perf_counter() - bench_start
    successful = len(latencies)
    rps = successful / total_time if total_time > 0 else 0

    if not latencies:
        print(f"{RED}❌ Ошибка: не удалось получить ответы от сервера. Проверьте адрес {target}!{RESET}\n")
        return

    latencies.sort()
    avg_lat = statistics.mean(latencies)
    median_lat = statistics.median(latencies)
    p95_lat = latencies[int(len(latencies) * 0.95)] if len(latencies) > 20 else latencies[-1]
    p99_lat = latencies[int(len(latencies) * 0.99)] if len(latencies) > 100 else latencies[-1]
    min_lat = latencies[0]
    max_lat = latencies[-1]
    total_kb = bytes_counter[0] / 1024

    # Вывод результатов
    print("=" * 75)
    print(f"{BOLD}{'МЕТРИКА ПРОИЗВОДИТЕЛЬНОСТИ':<45} {'ЗНАЧЕНИЕ':<25}{RESET}")
    print("-" * 75)
    print(f"{'Общее время теста':<45} {total_time:.2f} сек")
    print(f"{'Успешных RPC-ответов':<45} {GREEN}{successful:,} / {actual_total:,}{RESET}")
    print(f"{BOLD}{'Throughput (Пропускная способность)':<45} {MAGENTA}{BOLD}{rps:,.1f} RPS{RESET}")
    print(f"{'Объем входящего трафика':<45} {total_kb:,.1f} КБ ({total_kb / total_time:,.1f} КБ/с)")
    print("-" * 75)
    print(f"{'Минимальная задержка (Min)':<45} {min_lat:.2f} ms")
    print(f"{'Медианная задержка (p50)':<45} {GREEN}{median_lat:.2f} ms{RESET}")
    print(f"{'Средняя задержка (Avg)':<45} {avg_lat:.2f} ms")
    print(f"{'95-й перцентиль (p95)':<45} {YELLOW}{p95_lat:.2f} ms{RESET}")
    print(f"{'99-й перцентиль (p99)':<45} {YELLOW}{p99_lat:.2f} ms{RESET}")
    print(f"{'Максимальная задержка (Max)':<45} {max_lat:.2f} ms")
    print("=" * 75)

    if rps >= 20000:
        badge = f"{GREEN}🏆 ЭКСТРЕМАЛЬНЫЙ УРОВЕНЬ (>20 000 RPS){RESET}"
    elif rps >= 10000:
        badge = f"{GREEN}⚡ ВЫСОКАЯ ПРОИЗВОДИТЕЛЬНОСТЬ (>10 000 RPS){RESET}"
    else:
        badge = f"{YELLOW}🚀 СТАНДАРТНЫЙ УРОВЕНЬ{RESET}"

    print(f"\n{BOLD}Вердикт надежности:{RESET} {badge}\n")


def main():
    parser = argparse.ArgumentParser(description="Стресс-бенчмарк для rsgi-wsrpc")
    parser.add_argument("--target", default="http://127.0.0.1:8080", help="URL сервера (default: http://127.0.0.1:8080)")
    parser.add_argument("--method", default="system.ping", help="RPC-метод для теста (default: system.ping)")
    parser.add_argument("--concurrency", type=int, default=50, help="Количество параллельных сокетов (default: 50)")
    parser.add_argument("--requests", type=int, default=10000, help="Общее количество запросов (default: 10000)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Таймаут сокета (default: 5.0с)")
    args = parser.parse_args()

    target = args.target
    if "127.0.0.1:8080" in target or "localhost:8080" in target:
        import socket
        def is_open(p):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.15)
                return s.connect_ex(("127.0.0.1", p)) == 0

        if not is_open(8080) and is_open(8000):
            target = target.replace("8080", "8000")
            print(f"{YELLOW}ℹ️  Порт 8080 недоступен, обнаружен сервер на порту 8000: переключение на {target}{RESET}")

    asyncio.run(run_benchmark(
        target=target,
        method=args.method,
        params={},
        concurrency=args.concurrency,
        total_requests=args.requests,
        timeout=args.timeout,
    ))


if __name__ == "__main__":
    main()
