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


