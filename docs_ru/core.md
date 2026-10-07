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
4. [Табличное сжатие данных (RFC 0002): core/tabular.py](#4-табличное-сжатие-данных-rfc-0002-coretabularpy)
5. [Жизненный цикл сервера: core/lifecycle.py](#5-жизненный-цикл-сервера-corelifecyclepy)
6. [Безопасность и криптография: core/security.py](#6-безопасность-и-криптография-coresecuritypy)
7. [Конфигурация: core/lib/config.py](#7-конфигурация-corelibconfigpy)
8. [Клиент TypeScript/JavaScript: client/wsrpc.ts](#8-клиент-typescriptjavascript-clientwsrpcts)
9. [Единый класс приложения: RsgiWsrpcApp](#9-единый-класс-приложения-rsgiwsrpcapp)
10. [Масштабирование и Backplane](#10-масштабирование-и-backplane)

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
       │   - Streaming endpoints         │ │   - @rpc_method registry       │
       │   - Health checks (/health)     │ │   - ContextVars (user, session)│
       │   - Direct binary endpoints     │ │   - Rate Limiting (Token Bucket│
       └─────────────────────────────────┘ │   - Multi-return streaming     │
                                           │   - Symmetric Client Calls     │
                                           │   - register_on_close (2PC)    │
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

Каждый RPC-метод регистрируется с помощью декоратора `@rpc_method` (или `@app.rpc` при использовании `RsgiWsrpcApp`):

```python
from rsgi_wsrpc import rpc_method, JsonRpcSession, RPCError

# 1. Автоматическая распаковка именованных параметров (kwargs)
@rpc_method("calculator.add")
async def calculate_sum(a: int = 0, b: int = 0):
    return {"sum": a + b}

# 2. Доступ к объекту сессии + именованные аргументы
@rpc_method("tasks.create")
async def create_task(session: JsonRpcSession, title: str, priority: int = 1):
    return {"id": 42, "title": title, "priority": priority}

# 3. Классический доступ к полному словарю params
@rpc_method("raw.echo")
async def echo_raw(session: JsonRpcSession, params: dict):
    return params

# 4. Защищенный административный метод (права настраиваются в БД через CRUD)
@rpc_method("admin.restart_service")
async def restart_service(session: JsonRpcSession):
    # Если у пользователя нет прав администратора, ядро автоматически
    # вернет ошибку JSON-RPC клиенту: "Доступ к методу 'admin.restart_service' запрещен"
    return {"status": "restarting"}
```

#### Публичные методы (`public=True`)
По умолчанию из соображений безопасности гостевым (неавторизованным) соединениям разрешены **только** методы авторизации (префикс `login.`). 
Если метод должен быть доступен неавторизованным пользователям (например, проверка статуса, публичный каталог, калькулятор), обязательно укажите:
```python
@rpc_method("system.ping", public=True)
async def ping():
    return {"status": "pong"}
```

### Ролевая модель и контроль доступа (Single Source of Truth — БД)

Во фреймворке действует строгий архитектурный принцип: **в прикладном коде нет жестко закрепленных ролей и запретов**. Все роли, права доступа к RPC-методам и политики моделей настраиваются и хранятся **исключительно в базе данных** через панель управления CRUD.

Код методов пишется максимально чисто — без хардкода ролей в декораторах:

```python
@app.rpc("orders.dispatch")
async def dispatch_order(order_id: int):
    # Бизнес-логика выполнения заказа
    return {"status": "dispatched", "order_id": order_id}
```

#### Ключевые правила безопасности:

1. **Неавторизованный посетитель (Гость)**:
   * Не имеет учетной записи и роли (`None`).
   * Доступ разрешен только к методам, помеченным как публичные (`is_public = True` в таблице `auth_rpc_permission`), и методам аутентификации (`login.*`).
   * Проверка публичности выполняется за `O(1)` в RAM по in-memory кэшу ядра (`PUBLIC_RPC_METHODS`).

2. **Зарегистрированный пользователь**:
   * При первичной регистрации через `login.register` или OAuth пользователю автоматически присваивается базовая системная роль **`user`**.
   * Далее администратор через CRUD может изменить его роль или выдать дополнительные роли предметной области (`manager`, `editor`, `operator`, `buyer` и т.д.).

3. **Права доступа к RPC-методам (`auth_rpc_permission`)**:
   * При старте сервера Service Discovery автоматически сканирует все методы `@app.rpc` и синхронизирует их с таблицей `auth_rpc_permission`.
   * Администратор в интерфейсе CRUD привязывает методы к ролям:
     * Точное имя метода: `"orders.dispatch"`, `"reports.monthly"`.
     * Маска с префиксом (Wildcard): `"orders.*"`, `"catalog.*"`.
   * При входе пользователя список разрешенных методов кэшируется прямо в сессии сокета (`session.data.allowed_rpc_methods`), обеспечивая мгновенную проверку `O(1)` в памяти без повторных обращений к БД.

4. **Системные роли (Built-in Immutable Roles)**:
   * В системе существуют ровно две защищенные системные роли: **`admin`** и **`user`**.
   * Их невозможно удалить (`crud.delete`) или переименовать (`crud.update_cell`) через CRUD — ядро отклонит операцию с ошибкой.
   * Роль **`admin`** обладает привилегией **Superadmin Bypass** (безусловный доступ ко всем RPC-методам) и имеет исключительный доступ к управлению CRUD-панелью (`/crud`).

5. **Первый запуск системы (CLI Bootstrap)**:
   * Для создания первого администратора системы используется встроенная CLI-утилита:
   ```bash
   python -m rsgi_wsrpc createsuperuser --username admin --password secret
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

## 4. Табличное сжатие полезной нагрузки: `core/tabular.py` (RFC 0002)

Модуль `core/tabular.py` реализует детерминированную сериализацию списков данных в компактный табличный формат `$tabular: true`, устраняющий дублирование строковых названий ключей и экономящий 50–70% сетевого трафика.

```python
from core.tabular import pack_tabular, tabular_response

# 1. Автоматическая упаковка ответа декоратором
@rpc_method("tasks.list")
@tabular_response(fields=["id", "title", "completed", "priority"])
async def list_tasks(session, params):
    tasks = await fetch_tasks()
    return [t.to_dict() for t in tasks]

# 2. Прямая оптимизация сырых SQL-кортежей (без создания промежуточных dict)
@rpc_method("logs.get_recent")
async def get_recent_logs(session, params):
    async with db.execute("SELECT id, level, message FROM logs") as cursor:
        rows = await cursor.fetchall()  # Сырые кортежи
        return pack_tabular(rows, fields=["id", "level", "message"])
```

### Поддержка сокетных транзакций и отката (2PC Lifecycle Hooks)

Сетевое ядро `rsgi-wsrpc` полностью изолировано от файловой системы и не содержит жестко зашитых временных путей (`/tmp/...`). Для реализации двухфазных транзакций (2PC, загрузка файлов, распределенные операции) ядро предоставляет универсальный сокетный хук закрытия сессии `session.register_on_close`:

```python
# Привязка отката транзакции к жизненному циклу WebSocket-соединения:
session.register_on_close(lambda s: my_transaction.rollback())
```

Если клиент закрыл браузер или произошел обрыв сети до завершения операции, зарегистрированный колбэк автоматически выполняется ядром, предотвращая зависание временных ресурсов или сиротских файлов.

> Полное руководство по реализации двухфазной потоковой загрузки файлов см. в [docs_ru/files.md](files.md).

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

## 7. Конфигурация: `core/lib/config.py` (Code-First)

Фреймворк следует паттерну **Code-First и 12-Factor App** без обязательных внешних YAML-файлов. Настройки задаются напрямую в коде, подтягиваются из переменных окружения или используют безопасные dev-дефолты:

```python
import os
from core.lib.config import configure, settings

# 1. Программная конфигурация в коде
configure(
    secret_key=os.getenv("SECRET_KEY", "ваш-секретный-ключ-для-продакшена"),
    session_idle_timeout=900,
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/app.db"),
    files_path=os.getenv("FILES_PATH", "./files")
)

# 2. Доступ к параметрам в любом месте проекта
secret = settings.security.secret_key
db_url = settings.get("database_url")
```

---

## 8. Клиент TypeScript/JavaScript: `client/wsrpc.ts`

Официальный клиент `BinaryWSRPC` предоставляет полнофункциональную среду для работы с реактивным WSRPC-сервером в современных веб-приложениях (Svelte, React, Vue, Angular или чистый Vanilla JS/Node.js).

### Возможности клиента:
* **Единый постоянный сокет** для всех RPC-запросов и нотификаций.
* **Автоматическое переподключение** при обрыве сети с сохранением подписок.
* **Нативный мультиретурн (`callStream`)**: прогресс-бары, потоковая генерация данных и живые логи без создания дополнительных сокетов.
* **Прием нотификаций (Server Push)** и широковещательных рассылок (`rpc.on(...)`).
* **Симметричный RPC**: сервер может вызывать клиентские функции и ожидать результат (`rpc.registerMethod(...)`).
* **Системный шлюз сессий (`authInterceptor`)**: автоматическая синхронизация сессии. Исходящие бизнес-запросы автоматически ожидают подтверждения авторизации (`login.refresh`) при холодном старте (F5) или реконнекте, устраняя состояние гонки.
* **Реактивные сторы состояния**: реактивное отслеживание статуса сети (`wsConnected`, `wsStatus`).

---

### 1. Подключение и управление состоянием сети

```typescript
import { BinaryWSRPC, wsConnected, wsStatus } from './wsrpc';

// Создаем экземпляр клиента (или используем глобальный синглтон import { rpc } from './wsrpc')
export const rpc = new BinaryWSRPC('wss://api.example.com/ws');

// Настройка интервала авто-реконнекта (в секундах). По умолчанию 3 сек. (0 - отключить)
rpc.reconnectWs = 3;

// Триггеры событий соединения
rpc.onConnect = () => {
    console.log('[App] Соединение с сервером готово к работе');
};

rpc.onStatusChange = (isConnected: boolean) => {
    console.log('[App] Сетевой статус изменился:', isConnected ? 'ОНЛАЙН' : 'ОФФЛАЙН');
};

// Подключаемся
await rpc.connect();
```

#### Реактивное отображение плашки «Нет связи» в UI:
```typescript
// Svelte:
// {#if !$wsConnected}
//    <div class="offline-banner">Потеряно соединение с сервером. Восстановление связи...</div>
// {/if}

// React / Vue / Vanilla JS:
wsConnected.subscribe((connected) => {
    document.getElementById('status-indicator').textContent = connected ? 'Онлайн' : 'Переподключение...';
});
```

---

### 2. Обычный RPC-вызов (`call`)

Метод `rpc.call<T>(method, params, timeoutMs)` возвращает строгий `Promise<T>`:

```typescript
interface UserProfile {
    id: number;
    name: string;
    email: string;
    role: string;
}

try {
    // Вызов RPC с указанием типа ответа
    const profile = await rpc.call<UserProfile>('user.get_profile', { user_id: 42 });
    console.log(`Привет, ${profile.name}! Ваша роль: ${profile.role}`);
} catch (error) {
    // Если на бэкенде было выброшено raise RPCError("..."), 
    // ошибка будет перехвачена здесь с понятным сообщением
    console.error('Ошибка получения профиля:', error);
}
```

---

### 3. Мультиретурн: Стриминг прогресса (`callStream`)

Главная киллер-фича `rsgi-wsrpc`: клиент вызывает одну тяжелую операцию (экспорт базы, обучение модели, рендеринг видео, генерация PDF), сервер шлет серию промежуточных ответов с пометкой `stream: true`, а финальный результат разрешает основной промис!

#### Реализация на бэкенде (Python):
```python
# app/reports/handlers.py
@rpc_method("reports.generate")
async def generate_report(session, params):
    rpc_id = params.get("rpc_id")
    total_stages = 4
    
    stages = [
        "Анализ транзакций за период",
        "Расчет налоговых ставок и вычетов",
        "Формирование сводных графиков",
        "Сборка финального PDF-документа"
    ]
    
    for i, title in enumerate(stages, 1):
        await asyncio.sleep(1.0) # Выполнение этапа
        
        # Отправляем чанк прогресса клиенту в активный RPC-запрос
        await session.send_stream_chunk(rpc_id, {
            "stage": i,
            "total_stages": total_stages,
            "percent": int((i / total_stages) * 100),
            "message": title
        })
        
    # Финальный результат завершает RPC-вызов
    return {
        "status": "ready",
        "download_url": "/files/reports/report_q3_2026.pdf",
        "file_size": 2481020
    }
```

#### Обработка на фронтенде (TypeScript):
```typescript
interface ProgressChunk {
    stage: number;
    total_stages: number;
    percent: number;
    message: string;
}

interface ReportResult {
    status: string;
    download_url: string;
    file_size: number;
}

// Запускаем генерацию и подписываемся на прогресс
const finalReport = await rpc.callStream<ReportResult>(
    'reports.generate',
    { period: '2026-Q3', format: 'pdf' },
    (chunk: ProgressChunk) => {
        // Колбэк вызывается при каждом промежуточном чанке с сервера:
        console.log(`[${chunk.percent}%] Этап ${chunk.stage}/${chunk.total_stages}: ${chunk.message}`);
        
        // Обновляем шкалу прогресса в UI
        updateProgressBar(chunk.percent, chunk.message);
    }
);

// Сюда выполнение попадет только после успешного завершения всей операции
console.log('Отчет готов к скачиванию:', finalReport.download_url);
window.open(finalReport.download_url, '_blank');
```

---

### 4. Получение нотификаций и Server Push (`on`)

Сервер может в любой момент отправить событие клиенту без предварительного запроса (например, новое сообщение в чате, изменение статуса заявки, инвалидация кэша или системное оповещение).

#### Отправка с сервера (Python):
```python
# Оповещение конкретной сессии:
await session.send_request("notification.alert", {
    "level": "warning",
    "text": "Уважаемый пользователь, через 5 минут сервер уйдет на техобслуживание."
})

# Широковещательный broadcast на всех пользователей (app/system/broadcast.py):
from app.system.broadcast import broadcast_event

await broadcast_event("forum.new_topic", {
    "topic_id": 158,
    "title": "Релиз rsgi-wsrpc 1.0!",
    "author": "Alex"
})
```

#### Прием и подписка на клиенте (TypeScript):
```typescript
// 1. Подписка на системные оповещения
rpc.on('notification.alert', (data) => {
    uiNotification.show({
        type: data.level,
        message: data.text,
        duration: 10000
    });
});

// 2. Реактивное обновление ленты форума / чата
// Метод on() возвращает функцию для легкой отписки:
const unsubscribe = rpc.on('forum.new_topic', (topic) => {
    console.log('Новая тема на форуме:', topic.title);
    topicsStore.update(currentList => [topic, ...currentList]);
});

// В компоненте Svelte / React / Vue при размонтировании (cleanup):
// onDestroy(unsubscribe); // или useEffect(() => () => unsubscribe(), [])

// 3. Обработка завершения сессии по неактивности
rpc.on('session.expired', () => {
    uiDialog.alert('Ваша сессия завершена по неактивности. Пожалуйста, авторизуйтесь снова.');
    userStore.set(null);
    openLoginModal();
});
```

---

### 5. Симметричный RPC: Сервер запрашивает действие у клиента

В архитектуре WSRPC сервер и клиент равноправны. Сервер может вызвать зарегистрированный метод на стороне клиента и **дождаться возвращаемого клиентом значения**:

#### Регистрация метода подтверждения на фронтенде:
```typescript
// Регистрируем клиентский метод ui.confirm
rpc.registerMethod('ui.confirm', async (params: { title: string; message: string }) => {
    // Показываем пользователю модальное окно с кнопками "Подтвердить" / "Отмена"
    const isUserAgreed = await openConfirmationDialog({
        title: params.title,
        message: params.message
    });

    // Возвращаем результат серверу!
    return { confirmed: isUserAgreed };
});
```

#### Вызов с сервера (Python):
```python
@rpc_method("wallet.withdraw")
async def withdraw_money(session: JsonRpcSession, params: dict):
    amount = params.get("amount")
    account = params.get("account")
    
    # Сервер запрашивает интерактивное подтверждение у браузера пользователя
    try:
        response = await session.send_request(
            method="ui.confirm",
            params={
                "title": "Подтверждение перевода",
                "message": f"С вашего счета будет списано {amount} ₽ на счет {account}. Продолжить?"
            },
            timeout=30.0 # Ждем ответа пользователя до 30 секунд
        )
    except TimeoutError:
        raise RPCError("Время ожидания подтверждения истекло")

    if not response.get("result", {}).get("confirmed"):
        raise RPCError("Операция отменена пользователем")

    # Пользователь нажал "Подтвердить" — выполняем списание средств
    await execute_withdrawal(amount, account)
    return {"status": "success", "transferred": amount}
```

---

### 6. Системный шлюз авторизации сессий (`authInterceptor`)

WebSocket-соединения хранят состояние на сервере (stateful). При жесткой перезагрузке страницы (F5) или переподключении после обрыва сети новый физический сокет подключается к серверу как анонимный гость (`guest`) до тех пор, пока клиент не отправит вызов восстановления сессии (`login.refresh`).

Чтобы исключить состояние гонки, при котором компоненты UI запрашивают защищенные данные раньше, чем завершилась авторизация сокета, в клиент `BinaryWSRPC` встроен **Session Gatekeeper**:

```typescript
// Регистрация шлюза при старте приложения (например, в auth.ts):
rpc.authInterceptor = async () => {
    const token = localStorage.getItem('rpc_token');
    if (!token) return;
    await restoreSession();
};
```

#### Принцип работы:
1. **Автоматическая очередь запросов**: Если компоненты страницы вызывают защищенные методы (например, `admin.list_users` или `messages.get_conversations`), клиент автоматически удерживает все исходящие бизнес-запросы до тех пор, пока `authInterceptor` не подтвердит сессию.
2. **Защита от дедлоков**: Системные методы и методы авторизации (`login.*`, `auth.*`, `system.*`) пропускаются через шлюз напрямую без задержек.
3. **Бесшовный реконнект**: При обрыве связи и переподключении сокета первый же бизнес-запрос автоматически запустит переавторизацию новой сессии, предотвращая ошибки `401 / Forbidden` по всему интерфейсу.

---

## 9. Единый класс приложения: RsgiWsrpcApp

Начиная с версии `0.4.3`, создание и запуск приложений на `rsgi-wsrpc` унифицированы в классе `RsgiWsrpcApp`. Все настройки ядра и официальных плагинов передаются в **единой точке входа**:

```python
import os
from rsgi_wsrpc import RsgiWsrpcApp, VkOAuth, YandexOAuth, tabular_response, RPCError

app = RsgiWsrpcApp(
    # --- Сеть и HTTP ---
    static_dir="./public",             # Нативная Zero-Copy раздача статики (Rust RSGI)
    index_file="index.html",           # Автоматическая отдача на GET /
    cors=True,                         # Автоматический CORS preflight OPTIONS
    cors_origins="*",                  # Разрешенные origins
    max_message_size=10 * 1024 * 1024, # Лимит размера входящего WebSocket-сообщения (10 МБ)

    # --- База данных (plugins.db) ---
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///app.db"),
    db_echo=False,                     # SQL-логирование в консоль

    # --- Безопасность и сессии (plugins.auth) ---
    secret_key=os.getenv("SECRET_KEY", "dev-secret-key-change-in-production"),
    login_rpc="login.",                # Префикс методов, доступных гостям
    token_expire_hours=24 * 30,        # Срок жизни сессии (30 дней)
    auth_timeout=0,                    # Таймаут на вход (0 = гости не отключаются)
    guest_idle_timeout=900,            # Кик неактивных гостей через 15 минут
    user_idle_timeout=3600,            # Кик неактивных пользователей через 1 час

    # --- Внешняя авторизация (OAuth) ---
    oauth=[
        VkOAuth(client_id="12345", client_secret="секрет_vk"),
        YandexOAuth(client_id="67890", client_secret="секрет_ya"),
    ],

    # --- Файловое хранилище (plugins.files) ---
    files_path="./uploads",            # Каталог загрузок (2PC Commit)
    max_upload_size=50 * 1024 * 1024,  # Лимит на размер одного файла (50 МБ)

    # --- Масштабирование (backplane) ---
    backplane_url=None,                # "redis://127.0.0.1:6379/0" при workers > 1

    # --- SEO и SSR (plugins.seo) ---
    enable_seo=False,                  # Перехват поисковых ботов (Яндекс/Google)
    sitemap_host="https://my-app.com", # Базовый домен для /sitemap.xml
)

# Регистрация RPC-методов через декоратор приложения
@app.rpc("tasks.get_all")
@tabular_response(fields=["id", "title"])
async def get_tasks():
    return [{"id": 1, "title": "Задача 1"}]

# Запуск приложения
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, workers=1)
```

### Справочник параметров конструктора `RsgiWsrpcApp`:

| Параметр | Тип | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `static_dir` | `str \| None` | `None` | Путь к директории фронтенда. Раздается через Rust Zero-Copy (`proto.response_file`). |
| `index_file` | `str \| None` | `"index.html"` | Имя индексного файла, отдаваемого на корневой `GET /`. |
| `cors` | `bool` | `True` | Включение CORS-заголовков и автоматической обработки `OPTIONS` preflight. |
| `cors_origins` | `str \| list[str]`| `"*"` | Разрешенные домены (origins) для CORS. |
| `max_message_size` | `int` | `10 * 1024 * 1024` | Максимальный размер входящего WebSocket-фрейма (10 МБ). Защита от флуда. |
| `database_url` | `str` | `"sqlite+aiosqlite:///app.db"` | URL подключения SQLAlchemy (Postgres, SQLite, MySQL). |
| `db_echo` | `bool` | `False` | Логирование выполняемых SQL-запросов в терминал (удобно для отладки). |
| `secret_key` | `str` | `"dev-secret-key..."` | Секретный ключ для подписи токенов и HMAC. |
| `login_rpc` | `str` | `"login."` | Префикс методов, доступных гостям (наряду с методами с `is_public=True` в БД). |
| `token_expire_hours`| `int` | `720` (30 дней) | Срок действия сессионного токена. |
| `password_iterations`| `int` | `600_000` | Число итераций PBKDF2-SHA256 (стандарт безопасности OWASP). |
| `auth_timeout` | `int` | `0` | Время в секундах на авторизацию после подключения (`0` = отключено). |
| `guest_idle_timeout`| `int` | `900` (15 мин) | Таймаут неактивности для гостевых сокетов. |
| `user_idle_timeout` | `int` | `3600` (1 час) | Таймаут неактивности для авторизованных пользователей. |
| `oauth` | `list` | `[]` | Список типизированных провайдеров (`VkOAuth`, `YandexOAuth`). |
| `files_path` | `str` | `"./uploads"` | Папка постоянного хранения загруженных файлов. |
| `max_upload_size` | `int` | `50 * 1024 * 1024` | Максимальный объем загружаемого файла (50 МБ). |
| `backplane_url` | `str \| None` | `None` | URL шины распределенного состояния (`redis://...`) при `workers > 1`. |
| `enable_seo` | `bool` | `False` | Авто-определение поисковых ботов и отдача SSR HTML. |
| `sitemap_host` | `str \| None` | `None` | Домен для генерации карты сайта `/sitemap.xml`. |

### Ключевые преимущества `RsgiWsrpcApp`:
1. **Rust Zero-Copy раздача статики**: Для файлов в `static_dir` используется нативный вызов Granian RSGI `proto.response_file`, минуя чтение байтов в Python-память.
2. **Защита от Path Traversal**: Пути нормализуются с проверкой `resolve().startswith(static_dir)`. Попытки выйти за пределы каталога возвращают `403 Forbidden`.
3. **Хуки жизненного цикла**: Автоматически реализует методы RSGI протокола `__rsgi_init__` и `__rsgi_del__`, выполняя зарегистрированные функции `@on_startup` и `@on_shutdown`.

---

## 10. Масштабирование и Backplane

Для обеспечения горизонтального масштабирования в кластере или запуска нескольких воркеров Granian (`workers > 1`) используется шина сообщений:

```python
from rsgi_wsrpc.core.backplane import BaseBackplane, MemoryBackplane
```

* **`BaseBackplane`** — абстрактный контракт с методами `publish(channel, payload)`, `subscribe(channel, callback)`, `unsubscribe(channel)`.
* **`MemoryBackplane`** — легковесная in-memory шина по умолчанию (для `workers=1`).
* **Внимание при `workers > 1`**: Сессии WebSocket хранятся в памяти конкретного процесса операционной системы. При запуске нескольких воркеров без распределенного бэкплейна (Redis / Postgres) фреймворк выводит предупреждение в лог. Для продакшена с несколькими процессами подключайте Redis-бэкплейн.



