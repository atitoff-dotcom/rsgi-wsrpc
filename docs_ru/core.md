# ⚙️ Сетевое ядро (Core Engine): Руководство разработчика

Сетевое ядро `rsgi-wsrpc` расположено в каталоге `core/`. Оно представляет собой высокопроизводительный асинхронный сокетный рантайм, работающий поверх протокола **Rust Granian RSGI**.

Ядро спроектировано по принципам Clean Architecture:
* **Нулевые внешние зависимости от бизнес-логики**: ядро ничего не знает о базе данных, моделях данных или пользователях конкретного проекта.
* **Строгая изоляция**: все взаимодействие с прикладным уровнем происходит через абстракции (декораторы `@rpc_method`, `@on_startup`, контекстные переменные `ContextVar` и колбэки закрытия сессии).

---

## 🧭 Содержание руководства
1. [Архитектура и компоненты ядра](#1-архитектура-и-компоненты-ядра)
2. [Сессии и RPC: core/session.py](#2-сессии-и-rpc-coresessionpy)
   * [Регистрация методов (@rpc_method)](#регистрация-методов-rpc_method)
   * [Контекстные переменные (ContextVars)](#контекстные-переменные-contextvars)
   * [Обработка ошибок (RPCError)](#обработка-ошибок-rpcerror)
   * [Мультиретурн и стриминг прогресса](#мультиретурн-и-стриминг-прогресса)
   * [Симметричный RPC (сервер вызывает клиент)](#симметричный-rpc-сервер-вызывает-клиент)
   * [Хуки закрытия сессии (session.register_on_close)](#хуки-закрытия-сессии-sessionregister_on_close)
   * [Встроенная защита (Rate Limiting и таймауты)](#встроенная-защита-rate-limiting-и-таймауты)
3. [Роутинг и протокол RSGI: core/router.py](#3-роутинг-и-протокол-rsgi-corerouterpy)
4. [Двухфазная загрузка файлов: core/upload.py](#4-двухфазная-загрузка-файлов-coreuploadpy)
5. [Жизненный цикл сервера: core/lifecycle.py](#5-жизненный-цикл-сервера-corelifecyclepy)
6. [Безопасность и криптография: core/security.py](#6-безопасность-и-криптография-coresecuritypy)
7. [Конфигурация: core/lib/config.py](#7-конфигурация-corelibconfigpy)
8. [Клиент TypeScript/JavaScript: client/wsrpc.ts](#8-клиент-typescriptjavascript-clientwsrpcts)

---

## 1. Архитектура и компоненты ядра

```text
                     ┌──────────────────────────────────────┐
                     │          Granian RSGI Server         │
                     │          (Rust Event Loop)           │
                     └──────────────────┬───────────────────┘
                                        │ scope, proto
                     ┌──────────────────▼───────────────────┐
                     │           main:app (RSGI Entry)      │
                     └──────────┬───────────────────┬───────┘
            scope.proto == "http"                   scope.proto == "websocket"
                                │                   │
       ┌────────────────────────▼────────┐ ┌────────▼───────────────────────┐
       │         core/router.py          │ │          core/session.py       │
       │   @http_route(path, methods)    │ │   JsonRpcSession, WSRPC Engine │
       │   - Streaming upload (/upload)  │ │   - @rpc_method registry       │
       │   - Health checks (/health)     │ │   - ContextVars (user, session)│
       │   - Direct binary endpoints     │ │   - Rate Limiting (Token Bucket│
       └─────────────────────────────────┘ │   - Multi-return streaming     │
                                           │   - Symmetric Client Calls     │
                                           └────────────────┬───────────────┘
                                                            │
                                  ┌─────────────────────────┴───────────────┐
                                  │                                         │
                   ┌──────────────▼──────────────┐           ┌──────────────▼──────────────┐
                   │       core/upload.py        │           │      core/lifecycle.py      │
                   │   UploadCoordinator & 2PC   │           │   @on_startup, __rsgi_init__│
                   │   - O(1) RAM Streamer       │           │   - Async Schema Migrations │
                   │   - Auto-rollback on close  │           │   - Cache Warming           │
                   └─────────────────────────────┘           └─────────────────────────────┘
```

---

## 2. Сессии и RPC: `core/session.py`

Модуль `core/session.py` — сердце фреймворка. Он преобразует сырое WebSocket-соединение в постоянную, защищенную сессию WSRPC (JSON-RPC 2.0).

### Регистрация методов (`@rpc_method`)

Каждый RPC-метод регистрируется с помощью декоратора `@rpc_method`:

```python
from core.session import rpc_method, JsonRpcSession, RPCError

# Базовый метод
@rpc_method("calculator.add")
async def calculate_sum(session: JsonRpcSession, params: dict):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"sum": a + b}

# Метод с ограничением доступа по роли
from core.constants import UserRole

@rpc_method("admin.restart_service", role=UserRole.ADMIN)
async def restart_service(session: JsonRpcSession, params: dict):
    # Если у сессии нет прав администратора, ядро автоматически
    # вернет ошибку JSON-RPC клиенту: "Доступ запрещен: требуется роль admin"
    return {"status": "restarting"}
```

### Контекстные переменные (`ContextVars`)

Во время исполнения хендлера ядро автоматически проставляет асинхронные контекстные переменные. Вам **не нужно** передавать объект сессии или пользователя через десятки внутренних функций:

```python
from core.session import (
    current_user_ctx,
    current_session_ctx,
    current_rpc_id_ctx,
    current_transport_ctx
)

async def internal_audit_log(action: str):
    # Доступ к текущему пользователю из любой глубины кода!
    user = current_user_ctx.get()
    user_id = user.id if user else "anonymous"
    rpc_id = current_rpc_id_ctx.get()
    print(f"[AUDIT] User {user_id} performed {action} in RPC call #{rpc_id}")
```

### Обработка ошибок (`RPCError`)

Вместо падений с 500 ошибками используйте `RPCError`. Сообщение будет корректно упаковано в стандартный ответ JSON-RPC 2.0 (`error: {code: -32000, message: "..."}`):

```python
@rpc_method("order.cancel")
async def cancel_order(session: JsonRpcSession, params: dict):
    order_id = params.get("order_id")
    if not order_id:
        raise RPCError("Параметр order_id является обязательным")

    order = await get_order(order_id)
    if not order:
        raise RPCError("Заказ с указанным ID не найден")

    if order.is_shipped:
        raise RPCError("Нельзя отменить уже отправленный заказ")

    await order.cancel()
    return {"success": True}
```

### Мультиретурн и стриминг прогресса

В отличие от стандартного REST или плоского JSON-RPC, `rsgi-wsrpc` поддерживает нативный мультиретурн: на один запрос клиента сервер может отправить серию промежуточных чанков, завершив финальным `result`:

```python
@rpc_method("reports.generate")
async def generate_large_report(session: JsonRpcSession, params: dict):
    rpc_id = params.get("rpc_id")
    total_steps = 5

    for step in range(1, total_steps + 1):
        await asyncio.sleep(0.5) # Имитация долгого расчета
        
        # Отправляем чанк прогресса клиенту
        await session.send_stream_chunk(rpc_id, {
            "step": step,
            "total": total_steps,
            "percent": int((step / total_steps) * 100),
            "status": f"Обработка блока {step}..."
        })

    # Финальный результат завершает RPC-запрос
    return {"report_url": "/files/reports/report_2026.pdf", "status": "done"}
```

### Симметричный RPC (сервер вызывает клиент)

Поскольку сокет WSRPC симметричен, сервер может в любой момент инициировать RPC-запрос на сторону браузера и дождаться ответа от пользователя:

```python
@rpc_method("security.transfer_funds")
async def transfer_funds(session: JsonRpcSession, params: dict):
    amount = params.get("amount")
    
    # Сервер запрашивает подтверждение у фронтенда (например, диалог 2FA)
    client_response = await session.send_request(
        method="ui.request_confirmation",
        params={
            "title": "Подтверждение перевода",
            "message": f"Вы действительно хотите перевести {amount} ₽?",
            "timeout_sec": 30
        },
        timeout=30.0
    )
    
    if not client_response.get("result", {}).get("confirmed"):
        raise RPCError("Операция отклонена пользователем")
        
    return {"status": "funds_transferred"}
```

### Хуки закрытия сессии (`session.register_on_close`)

Чтобы избежать утечек памяти и зависших фоновых задач при обрыве связи (закрытие вкладки браузера, сбой сети):

```python
@rpc_method("live.subscribe")
async def subscribe_to_telemetry(session: JsonRpcSession, params: dict):
    device_id = params.get("device_id")
    
    async def cleanup(closed_session):
        print(f"Сессия закрыта, отписываемся от телеметрии устройства {device_id}")
        await telemetry_hub.unsubscribe(device_id, closed_session)
        
    session.register_on_close(cleanup)
    await telemetry_hub.subscribe(device_id, session)
    return {"subscribed": True}
```

### Встроенная защита (Rate Limiting и таймауты)

Каждая `JsonRpcSession` содержит аппаратную защиту:
1. **Rate Limiter (Token Bucket)**: автоматически сбрасывает счетчик каждую секунду без создания тяжелых тасок (`loop.call_later`). Если сокет присылает более 30 запросов в секунду — соединение разрывается с кодом `-32005 Too many requests`.
2. **Auth Timeout**: если подключившийся клиент не прошел авторизацию за 60 секунд — сессия принудительно гасится.
3. **Idle Timeout**: если от авторизованного клиента нет активности дольше заданного в настройках времени (по умолчанию 900 с) — сессия корректно завершается с предварительным уведомлением `session.expired`.

---

## 3. Роутинг и протокол RSGI: `core/router.py`

Модуль `core/router.py` регистрирует прямые HTTP-эндпоинты поверх RSGI. Это необходимо для высокоскоростного стриминга файлов, вебхуков внешних систем и healthcheck-проверок.

```python
from core.router import http_route

@http_route("/health", methods=["GET"])
async def health_check(scope, proto):
    proto.response_str(
        status=200,
        headers=[("content-type", "application/json")],
        body='{"status":"healthy","engine":"rsgi-wsrpc"}'
    )

@http_route("/webhook/payment", methods=["POST"])
async def payment_webhook(scope, proto):
    # Чтение сырого тела запроса из RSGI протокола
    body_bytes = bytearray()
    while True:
        chunk = await proto.receive()
        if not chunk:
            break
        body_bytes.extend(chunk)
        
    # Обработка вебхука...
    proto.response_str(status=200, headers=[], body="OK")
```

---

## 4. Двухфазная загрузка файлов: `core/upload.py`

Модуль `core/upload.py` реализует транзакционный протокол двухфазного коммита (2PC) для безопасного приема файлов:

```python
from core.upload import UploadCoordinator, stream_request_to_disk

# 1. Открытие транзакции в WSRPC-методе
@rpc_method("files.begin_upload")
async def begin_upload(session, params):
    total_files = params.get("file_count", 1)
    tx = await UploadCoordinator.create_transaction(
        session=session,
        expected_files=total_files
    )
    return {"folder_hash": tx.folder_hash}

# 2. Потоковый прием байтов в HTTP-роуте (O(1) RAM)
@http_route("/upload", methods=["POST"])
async def handle_upload(scope, proto):
    folder_hash = get_header(scope, "x-folder-hash")
    file_name = get_header(scope, "x-file-name")
    
    tx = UploadCoordinator.get_transaction(folder_hash)
    if not tx:
        proto.response_str(status=404, headers=[], body="Transaction not found")
        return
        
    # Потоковая запись прямо на диск с подсчетом SHA-256
    file_path = tx.temp_dir / file_name
    size, sha256_hex = await stream_request_to_disk(proto, file_path)
    
    tx.register_file(file_name, size, sha256_hex)
    proto.response_str(status=200, headers=[], body='{"status":"uploaded"}')

# 3. Фиксация транзакции (Commit)
@rpc_method("files.commit_upload")
async def commit_upload(session, params):
    folder_hash = params.get("folder_hash")
    tx = UploadCoordinator.get_transaction(folder_hash)
    
    # Атомарное перемещение из временной папки в постоянную
    final_dir = await tx.commit(target_base_dir="/files")
    return {"status": "committed", "path": str(final_dir)}
```

> **Важно**: Если клиент закрыл вкладку посреди загрузки — `UploadCoordinator` мгновенно выполнит `await tx.rollback()`, физически удалив недогруженные файлы с диска.

---

## 5. Жизненный цикл сервера: `core/lifecycle.py`

Позволяет регистрировать асинхронные задачи, которые гарантированно завершатся **до** того, как воркер Granian начнет принимать клиентские соединения:

```python
from core.lifecycle import on_startup

@on_startup
async def init_cache_and_db():
    print("[Startup] Проверка схемы базы данных...")
    await migrate_schema()
    
    print("[Startup] Прогрев L1 кэша...")
    await warm_up_memory_cache()
```

В `main.py` хуки вызываются через нативный хук воркера Granian:
```python
def __rsgi_init__(loop):
    loop.run_until_complete(run_startup_callbacks())

app.__rsgi_init__ = __rsgi_init__
```

---

## 6. Безопасность и криптография: `core/security.py`

В ядро встроены безопасные стандарты аутентификации и шифрования:

```python
from core.security import hash_password, verify_password, create_jwt_token, decode_jwt_token

# Хэширование Argon2id
hashed = hash_password("super_secret_password")
is_valid = verify_password("super_secret_password", hashed) # True

# JWT токены
token = create_jwt_token(payload={"sub": 105, "role": "admin"}, expires_in_seconds=3600)
data = decode_jwt_token(token)
```

---

## 7. Конфигурация: `core/lib/config.py`

Конфигурация проекта считывается из `settings.yaml` и доступна через глобальный объект `settings`:

```python
from core.lib.config import settings

# Доступ к полям
db_url = settings.db.get("url")
upload_dir = settings.storage.get("upload_dir", "/files")
```

---

## 8. Клиент TypeScript/JavaScript: `client/wsrpc.ts`

Официальный клиент `BinaryWSRPC` для браузера и Node.js:

```typescript
import { BinaryWSRPC } from './wsrpc';

const wsrpc = new BinaryWSRPC('wss://api.example.com/ws');
await wsrpc.connect();

// 1. Обычный вызов метода
const result = await wsrpc.call('calculator.add', { a: 10, b: 20 });
console.log('Сумма:', result.sum);

// 2. Вызов со стримингом промежуточных результатов
await wsrpc.callStream('reports.generate', {}, (chunk) => {
    console.log(`Прогресс: ${chunk.percent}% — ${chunk.status}`);
});

// 3. Регистрация метода на клиенте для вызова сервером
wsrpc.registerMethod('ui.request_confirmation', async (params) => {
    const ok = window.confirm(params.message);
    return { confirmed: ok };
});
```
