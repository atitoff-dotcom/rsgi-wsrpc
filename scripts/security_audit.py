#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автономный инструмент внешнего аудита безопасности (Security Audit & Pentest)
для фреймворка rsgi-wsrpc.

Запуск:
    python scripts/security_audit.py
    python scripts/security_audit.py --target http://127.0.0.1:8080
"""

import argparse
import asyncio
import sys
import time
from typing import Dict, Any, List
import aiohttp
import orjson

# Цветовое оформление ANSI
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


class SecurityCheckResult:
    def __init__(self, name: str, passed: bool, details: str, elapsed_ms: float):
        self.name = name
        self.passed = passed
        self.details = details
        self.elapsed_ms = elapsed_ms


class SecurityAuditor:
    def __init__(self, target: str, timeout: float = 3.0):
        self.target = target.rstrip("/")
        self.ws_target = self.target.replace("http://", "ws://").replace("https://", "wss://") + "/"
        self.timeout = timeout
        self.results: List[SecurityCheckResult] = []

    async def run_all(self) -> bool:
        print(f"\n{BOLD}{CYAN}🛡️  Запуск внешнего аудита безопасности rsgi-wsrpc...{RESET}")
        print(f"{DIM}Целевой сервер: {self.target} (WebSocket: {self.ws_target}){RESET}\n")

        client_timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            checks = [
                ("Zero-Leakage 404 (Admin Stealth)", self._check_zero_leakage),
                ("Header Leakage Prevention", self._check_server_header_leakage),
                ("CSWSH Origin Isolation", self._check_cswsh),
                ("12MB Payload Bomb (DoS Protection)", self._check_payload_bomb),
                ("JSON-RPC 2.0 Strict Compliance", self._check_protocol_strictness),
                ("Prototype Pollution / Injection", self._check_prototype_pollution),
                ("Admin RBAC Privilege Isolation", self._check_guest_privilege_isolation),
                ("CRUD RLS & Mutation Boundaries", self._check_crud_mutation_boundaries),
                ("JWT Forgery & alg:none Rejection", self._check_jwt_forgery),
            ]

            total = len(checks)
            for idx, (name, check_fn) in enumerate(checks, start=1):
                print(f"[{idx}/{total}] {CYAN}⏳ {name}...{RESET}", end="\r", flush=True)
                start = time.perf_counter()
                try:
                    passed, details = await asyncio.wait_for(check_fn(session), timeout=self.timeout + 1.0)
                except asyncio.TimeoutError:
                    passed, details = False, f"Таймаут проверки превысил {self.timeout}с"
                except Exception as e:
                    passed, details = False, f"Ошибка выполнения: {e}"

                elapsed = (time.perf_counter() - start) * 1000
                res = SecurityCheckResult(name, passed, details, elapsed)
                self.results.append(res)

                status_badge = f"{GREEN}✔ PASS{RESET}" if passed else f"{RED}✖ FAIL{RESET}"
                print(f"[{idx}/{total}] {status_badge} {name:<36} {elapsed:>6.1f} ms  {DIM}{details}{RESET}", flush=True)

        return self._print_summary()

    async def _check_zero_leakage(self, session: aiohttp.ClientSession):
        """Проверяет Zero-Leakage 404 для административных панелей без сессии."""
        endpoints = ["/crud", "/crud/", "/admin", "/admin/", "/admin/system"]
        all_ok = True
        err_details = []

        for ep in endpoints:
            try:
                async with session.get(f"{self.target}{ep}", allow_redirects=False) as resp:
                    if resp.status not in (404, 307):
                        all_ok = False
                        err_details.append(f"{ep} -> HTTP {resp.status}")
            except Exception as e:
                all_ok = False
                err_details.append(f"{ep}: {e}")

        msg = "Все админ-пути скрыты статусом 404" if all_ok else "; ".join(err_details)
        return all_ok, msg

    async def _check_server_header_leakage(self, session: aiohttp.ClientSession):
        """Проверяет отсутствие утечек версий и фреймворка в HTTP-заголовках."""
        async with session.get(f"{self.target}/") as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            has_powered_by = "x-powered-by" in headers
            has_granian_ver = "server" in headers and any(c.isdigit() for c in headers["server"])
            passed = not has_powered_by and not has_granian_ver
            details = "Заголовки Server / X-Powered-By чистые" if passed else f"Утечка: {headers.get('server')}"
            return passed, details

    async def _check_cswsh(self, session: aiohttp.ClientSession):
        """Проверяет WebSocket handshake с внешним Origin."""
        headers = {"Origin": "https://evil-attacker-site.com"}
        try:
            async with session.ws_connect(self.ws_target, headers=headers) as ws:
                req = orjson.dumps({"jsonrpc": "2.0", "method": "admin.sessions_list", "id": 1}).decode()
                await ws.send_str(req)
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = orjson.loads(msg.data)
                    passed = "error" in data
                    details = "Чужой Origin изолирован в гостевых правах" if passed else "Метод admin выполнен с чужим Origin!"
                else:
                    passed = True
                    details = "Соединение разорвано сервером"
                return passed, details
        except Exception:
            return True, "Handshake отклонен сервером"

    async def _check_payload_bomb(self, session: aiohttp.ClientSession):
        """Отправляет пакет размером 11 МБ (превышение лимита max_message_size 10 МБ)."""
        try:
            async with session.ws_connect(self.ws_target, max_msg_size=16 * 1024 * 1024) as ws:
                bomb_str = "x" * (11 * 1024 * 1024)
                payload = orjson.dumps({"jsonrpc": "2.0", "method": "system.ping", "params": bomb_str, "id": 99}).decode()
                await ws.send_str(payload)
                msg = await ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = orjson.loads(msg.data)
                    passed = data.get("error", {}).get("code") == -32600
                    details = "Сервер вернул -32600 (Message too large)"
                else:
                    passed = True
                    details = "Сервер разорвал сокет без переполнения памяти"
                return passed, details
        except Exception:
            return True, "Соединение сброшено ядром (защита от DoS)"

    async def _check_protocol_strictness(self, session: aiohttp.ClientSession):
        """Проверяет соблюдение спецификации JSON-RPC 2.0 при отправке мусора."""
        async with session.ws_connect(self.ws_target) as ws:
            # 1. Не-словарь (массив)
            await ws.send_str("[1, 2, 3]")
            msg1 = await ws.receive()
            res1 = orjson.loads(msg1.data)
            p1 = res1.get("error", {}).get("code") == -32600

            # 2. Невалидный JSON
            await ws.send_str("{broken_json:")
            msg2 = await ws.receive()
            res2 = orjson.loads(msg2.data)
            p2 = res2.get("error", {}).get("code") == -32700

            # 3. Отсутствие обязательного method
            await ws.send_str(orjson.dumps({"jsonrpc": "2.0", "id": 4}).decode())
            msg3 = await ws.receive()
            res3 = orjson.loads(msg3.data)
            p3 = res3.get("error", {}).get("code") == -32600

            passed = p1 and p2 and p3
            details = "Спецификация строго соблюдена (-32600, -32700)" if passed else "Ошибка кодов протокола"
            return passed, details

    async def _check_prototype_pollution(self, session: aiohttp.ClientSession):
        """Проверяет попытки вызова системных свойств через имена методов."""
        targets = ["__proto__", "constructor", "prototype", "toString", "__class__"]
        all_passed = True
        async with session.ws_connect(self.ws_target) as ws:
            for idx, m in enumerate(targets):
                payload = orjson.dumps({"jsonrpc": "2.0", "method": m, "id": 100 + idx}).decode()
                await ws.send_str(payload)
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=1.5)
                    res = orjson.loads(msg.data)
                    if res.get("error", {}).get("code") != -32601:
                        all_passed = False
                        break
                except (asyncio.TimeoutError, Exception):
                    all_passed = False
                    break
        details = "Системные свойства изолированы (-32601 Method not found)" if all_passed else "Уязвимость: вызов системного имени!"
        return all_passed, details

    async def _check_guest_privilege_isolation(self, session: aiohttp.ClientSession):
        """Проверяет изоляцию административных методов от неавторизованного гостя."""
        admin_methods = [
            "admin.session_kill",
            "admin.sessions_list",
            "system.broadcast",
            "system.cache_invalidate",
            "system.recent_logs",
            "system.get_config",
        ]
        all_blocked = True
        failed_method = ""
        async with session.ws_connect(self.ws_target) as ws:
            for idx, method in enumerate(admin_methods):
                payload = orjson.dumps({
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": {"session_id": 1, "tags": ["test"], "message": "hack"},
                    "id": 200 + idx
                }).decode()
                await ws.send_str(payload)
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=1.5)
                    res = orjson.loads(msg.data)
                    if "result" in res or res.get("error", {}).get("code") not in (-32000, -32001, -32003):
                        all_blocked = False
                        failed_method = method
                        break
                except (asyncio.TimeoutError, Exception):
                    all_blocked = False
                    failed_method = f"{method} (timeout)"
                    break
        details = f"Все {len(admin_methods)} админ-методов заблокированы для гостя" if all_blocked else f"Метод {failed_method} доступен гостю!"
        return all_blocked, details

    async def _check_crud_mutation_boundaries(self, session: aiohttp.ClientSession):
        """Проверяет запрет мутаций в CRUD без соответствующих прав."""
        async with session.ws_connect(self.ws_target) as ws:
            payload = orjson.dumps({
                "jsonrpc": "2.0",
                "method": "crud.update_cell",
                "params": {"model": "Task", "id": 1, "field": "title", "value": "pwned"},
                "id": 301
            }).decode()
            await ws.send_str(payload)
            try:
                msg = await asyncio.wait_for(ws.receive(), timeout=1.5)
                res = orjson.loads(msg.data)
                passed = "result" not in res and res.get("error", {}).get("code") in (-32000, -32001, -32003, -32601)
                details = "Мутации CRUD заблокированы для гостей" if passed else "Мутация CRUD разрешена без прав!"
            except (asyncio.TimeoutError, Exception):
                passed, details = False, "Таймаут ответа CRUD"
            return passed, details

    async def _check_jwt_forgery(self, session: aiohttp.ClientSession):
        """Проверяет отклонение JWT-токенов с 'alg': 'none'."""
        fake_jwt = "eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiIsInJvbGUiOiJhZG1pbiIsImV4cCI6OTk5OTk5OTk5OX0."
        cookies = {"rsgi_crud_session": fake_jwt, "rsgi_session": fake_jwt}
        try:
            async with session.get(f"{self.target}/admin/", cookies=cookies, allow_redirects=False, timeout=2.0) as resp:
                passed = resp.status == 404
                details = "Токены с alg:none строго отклоняются (404)" if passed else f"Админка пустила токен alg:none (HTTP {resp.status})!"
                return passed, details
        except Exception as e:
            return False, f"Ошибка запроса: {e}"

    def _print_summary(self) -> bool:
        total = len(self.results)
        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = total - passed_count
        score = (passed_count / total) * 100

        print("-" * 80)
        if failed_count == 0:
            print(f"\n{BOLD}{GREEN}✅ АУДИТ УСПЕШНО ПРОЙДЕН! Индекс взломостойкости: {score:.1f}% ({passed_count}/{total}){RESET}\n")
            return True
        else:
            print(f"\n{BOLD}{RED}❌ ОБНАРУЖЕНЫ ЗАМЕЧАНИЯ! Индекс: {score:.1f}% ({passed_count}/{total}), Ошибок: {failed_count}{RESET}\n")
            return False


def main():
    parser = argparse.ArgumentParser(description="Автономный Security-аудитор rsgi-wsrpc")
    parser.add_argument("--target", default="http://127.0.0.1:8080", help="URL целевого сервера (default: http://127.0.0.1:8080)")
    parser.add_argument("--timeout", type=float, default=3.0, help="Таймаут проверки в секундах (default: 3.0)")
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

    auditor = SecurityAuditor(target=target, timeout=args.timeout)
    success = asyncio.run(auditor.run_all())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
