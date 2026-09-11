#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Универсальный модульный раннер тестов Agrita Backend Test Harness.
Запуск:
    python tests/run.py                  # Все тесты
    python tests/run.py smart_cache      # Только сьют smart_cache
    python tests/run.py forum auth       # Несколько сьютов
    python tests/run.py --target=local   # На локальном сервере
    python tests/run.py --target=stage   # На стейдже
"""

import sys
import os
import time
import inspect
import asyncio
import argparse
import traceback

# Гарантируем, что корень проекта в sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tests.framework.config import TARGETS, CURRENT_TARGET, TargetConfig
from tests.suites import test_auth, test_smart_cache, test_forum, test_files, test_load

SUITES = {
    "auth": test_auth,
    "smart_cache": test_smart_cache,
    "forum": test_forum,
    "files": test_files,
    "load": test_load,
}

# ANSI цвета для красивого терминального вывода
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def run_single_test(suite_name: str, test_name: str, test_fn) -> bool:
    """Выполняет один тест с замером времени и выводом результата."""
    start = time.perf_counter()
    try:
        if inspect.iscoroutinefunction(test_fn):
            await test_fn()
        else:
            test_fn()
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"  {GREEN}✔ PASS{RESET}  {suite_name}::{test_name}  {CYAN}({elapsed_ms:.1f} ms){RESET}", flush=True)
        return True
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        print(f"  {RED}✖ FAIL{RESET}  {suite_name}::{test_name}  {RED}({elapsed_ms:.1f} ms){RESET}", flush=True)
        print(f"    {YELLOW}Error: {e}{RESET}", flush=True)
        # Выводим подробный трейсбэк с отступом
        tb_lines = traceback.format_exc().splitlines()
        for line in tb_lines[-6:]:
            print(f"      {line}", flush=True)
        return False


async def main():
    parser = argparse.ArgumentParser(description="Agrita Backend Client Test Runner")
    parser.add_argument("suites", nargs="*", help=f"Названия сьютов для запуска: {list(SUITES.keys())} (по умолчанию: все)")
    parser.add_argument("--target", choices=list(TARGETS.keys()), default=CURRENT_TARGET, help="Целевой сервер (local / stage)")
    args = parser.parse_args()

    # Устанавливаем цель в конфиге
    os.environ["TEST_TARGET"] = args.target
    from tests.framework import config
    config.CURRENT_TARGET = args.target
    target = config.get_target(args.target)

    chosen_suites = args.suites if args.suites else list(SUITES.keys())

    print(f"\n{BOLD}{CYAN}=== Agrita Backend Test Harness ==={RESET}", flush=True)
    print(f"  Цель:      {BOLD}{target.name.upper()}{RESET} ({target.http_url} | {target.ws_url})", flush=True)
    print(f"  Сьюты:     {', '.join(chosen_suites)}\n", flush=True)

    total_passed = 0
    total_failed = 0
    start_all = time.perf_counter()

    for suite_name in chosen_suites:
        if suite_name not in SUITES:
            print(f"{RED}Неизвестный сьют '{suite_name}'. Доступны: {list(SUITES.keys())}{RESET}")
            continue

        suite_module = SUITES[suite_name]
        test_functions = [
            (name, fn)
            for name, fn in inspect.getmembers(suite_module, inspect.isfunction)
            if name.startswith("test_")
        ]

        print(f"{BOLD}▶ Сьют: {suite_name}{RESET} ({len(test_functions)} тестов)", flush=True)
        for test_name, test_fn in test_functions:
            success = await run_single_test(suite_name, test_name, test_fn)
            if success:
                total_passed += 1
            else:
                total_failed += 1
        print()

    total_time = time.perf_counter() - start_all
    total = total_passed + total_failed

    print(f"{BOLD}=== Итоги тестирования ==={RESET}", flush=True)
    status_color = GREEN if total_failed == 0 else RED
    print(f"Всего: {total}, {GREEN}Успешно: {total_passed}{RESET}, {RED}Провалено: {total_failed}{RESET} {CYAN}({total_time:.2f} s){RESET}\n")

    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
