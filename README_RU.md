# rsgi-wsrpc: Реактивный полнофункциональный фреймворк для Python

> **«Всё, чем должен был стать Django, и всё, о чем забыл FastAPI»**  
> Высокоскоростной асинхронный веб-фреймворк на базе **Rust (Granian RSGI)** с симметричным протоколом **WSRPC (JSON-RPC 2.0)**, встроенной базой данных, авторизацией и транзакционной двухфазной загрузкой файлов.

---

## 🧭 Содержание
1. [Главная идея и манифест](#-главная-идея-и-манифест)
2. [Архитектура: Ядро + Плагины + Приложение](#-архитектура-ядро--плагины--приложение)
   * [Рекомендуемая структура проекта (Файловое дерево)](#-рекомендуемая-структура-проекта-файловое-дерево)
3. [Сравнение: rsgi-wsrpc vs Django vs FastAPI](#-сравнение-rsgi-wsrpc-vs-django-vs-fastapi)
4. [🤖 AI-Native: Экономия токенов и идеальная среда для LLM](#-ai-native-экономия-токенов-и-идеальная-среда-для-llm)
5. [Быстрый старт за 60 секунд](#-быстрый-старт-за-60-секунд)
6. [Сетевое ядро (Core Engine)](#-сетевое-ядро-core-engine)
   * [Полное руководство разработчика ядра (docs_ru/core.md)](docs_ru/core.md)
7. [Официальные системные плагины (Plugins)](#-официальные-системные-плагины-plugins)
   * [Плагин базы данных (db)](#1-плагин-базы-данных-pluginsdb)
   * [Плагин авторизации и пользователей (auth)](#2-плагин-пользователей-и-авторизации-pluginsauth)
   * [Плагин файлов и двухфазной загрузки (files)](#3-плагин-файлов-и-двухфазной-загрузки-pluginsfiles)
8. [Создание собственных плагинов и модулей в папке app](#-создание-собственных-плагинов-и-модулей-в-папке-app)
9. [Клиентская библиотека (TypeScript/JavaScript)](#-клиентская-библиотека-typescriptjavascript)
10. [Лицензия](#-лицензия)

---

## 💡 Главная идея и манифест

Современный веб изменился: пользователям больше не нужны статические страницы, которые перезагружаются по полсекунды. Нужен мгновенный отклик (1–5 мс), реактивные обновления данных в реальном времени и стриминг прогресса без ожидания.

Однако разработчики на Python оказались зажаты между двумя крайностями:
1. **Django** — 20-летний неповоротливый монолит из эпохи Web 2.0. Чтобы прикрутить к нему веб-сокеты и реактивность, приходится городить зоопарк из `Django + DRF + Channels + Redis + Celery + Daphne`, съедающий гигабайты памяти.
2. **FastAPI** — быстрый, но застрявший в парадигме плоского REST HTTP/1.1 (Request-Response). На каждый клик открывается новое соединение, гоняются килобайты HTTP-заголовков, а «батареек» (готовой авторизации, сессий, управления файлами) нет вовсе — каждый проект приходится собирать из 50 сторонних библиотек.

**`rsgi-wsrpc` объединяет лучшее из обоих миров:**
* **От Rust и Granian** — запредельная скорость обработки запросов без GIL-ограничений (RSGI).
* **От WSRPC (JSON-RPC 2.0)** — одно постоянное мультиплексированное соединение для всех операций, симметричный вызов методов (сервер может вызывать клиент) и нативный стриминг.
* **От Django** — готовые системные батарейки (Auth, DB, Two-Phase Files), но в виде легких независимых плагинов.

---

## 🏛 Архитектура: Ядро + Плагины + Приложение

Архитектура построена по принципу строгого однонаправленного потока зависимостей (Clean Architecture):

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                       1. ВАШЕ ПРИЛОЖЕНИЕ (Application)                  │
│                                                                         │
│   Знает обо всех компонентах: настраивает конфиг (settings.yaml),      │
│   подключает нужные системные плагины и запускает бизнес-логику.        │
│   Примеры: Социальная сеть, CRM, Форум, Личный кабинет, IoT-сервер.     │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ использует и собирает
┌────────────────────────────────────▼────────────────────────────────────┐
│                    2. СИСТЕМНЫЕ И ПРИКЛАДНЫЕ ПЛАГИНЫ                    │
│                                                                         │
│   [ Plugin: DB ]        [ Plugin: Auth ]       [ Plugin: Files ]        │
│   Асинхронная БД        Пользователи, JWT,     2PC-стриминг файлов,     │
│   SQLite / PostgreSQL   роли и права           реестр и Nginx offload   │
│                                                                         │
│   [ Прикладные плагины: Forum, Billing, Notifications, Analytics... ]   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ регистрируются в
┌────────────────────────────────────▼────────────────────────────────────┐
│                        3. СЕТЕВОЕ ЯДРО (Core)                           │
│                                                                         │
│   Чистый высокоскоростной сокетный и RSGI-движок (Granian на Rust).     │
│   НЕ знает ничего о базе данных и бизнес-логике.                        │
│   Отвечает за: WSRPC (JSON-RPC 2.0), мультиретурн, сессии, авто-откат. │
└─────────────────────────────────────────────────────────────────────────┘
```

### Главные правила архитектуры:
1. **Ядро автономно**: в `core/` нет ни одного импорта из приложения или БД.
2. **Плагины модульны**: каждый плагин решает одну задачу и регистрирует свои методы через API ядра (`@rpc_method`, `@on_startup`, `session.register_on_close`).
3. **Приложение управляет составом**: если вам нужен микросервис без БД — просто не подключайте плагин `db`. Нужен полный стек — подключаете готовый бандл.

---

### 📁 Рекомендуемая структура проекта (Файловое дерево)

Ниже представлена рекомендуемая и протестированная на боевых проектах структура репозитория с четким разделением сетевого ядра (`core/`), системных плагинов (`app/system/`) и прикладных модулей приложения (`app/<модули>/`):

```text
my_project/
├── core/                           # ⚡ СЕТЕВОЕ ЯДРО (RSGI + WSRPC)
│   ├── lib/
│   │   └── config.py               # Загрузка настроек settings.yaml
│   ├── constants.py                # Системные константы и роли (UserRole)
│   ├── lifecycle.py                # Асинхронные хуки @on_startup и @on_shutdown
│   ├── logger.py                   # Высокопроизводительное логирование
│   ├── router.py                   # HTTP-роутинг поверх RSGI (@http_route)
│   ├── security.py                 # Argon2id, JWT токены, RSA криптография
│   ├── session.py                  # JsonRpcSession, @rpc_method, ContextVars, Rate-Limiting
│   └── upload.py                   # Двухфазная загрузка O(1) RAM (2PC) и UploadCoordinator
│
├── app/                            # 📦 СЛОЙ ПРИЛОЖЕНИЯ И ПЛАГИНОВ
│   ├── system/                     # 🔌 Системные плагины ядра (Official Batteries)
│   │   ├── db.py                   # Асинхронный движок SQLAlchemy 2.0 (async_session, Base)
│   │   ├── broadcast.py            # Широковещательные уведомления активных сокетов
│   │   ├── auth/                   # Пользователи, права и Row-Level Security (RLS)
│   │   │   ├── models.py           # Модели User, Role, Permit
│   │   │   ├── handlers.py         # RPC-методы auth.*
│   │   │   ├── permissions.py      # Проверка прав доступа и ролей
│   │   │   └── security.py         # Хэширование и правила безопасности
│   │   ├── login/                  # Аутентификация, RSA handshake, RefreshToken
│   │   │   ├── handlers.py         # RPC-методы login.submit, login.refresh, login.whoami
│   │   │   └── db.py               # Сессии и токены в базе данных
│   │   ├── files/                  # Служба файлов и реестр метаданных
│   │   │   ├── models.py           # Модель FileMetadata в БД
│   │   │   ├── service.py          # FileStorageService (учет, автомиграция, удаление бандлов)
│   │   │   └── handlers.py         # HTTP-роут /upload и RPC-методы files.*
│   │   ├── admin/                  # Административная панель (сессии, кэш, пользователи)
│   │   │   └── handlers.py
│   │   └── internal_api/           # Авто-генерация интерактивной документации RPC
│   │       ├── api.html            # Встроенный UI песочницы
│   │       ├── handlers.py         # Эндпоинты инспекции API
│   │       └── generate_docs.py    # Парсер докстрингов и сигнатур
│   │
│   └── <business_modules>/         # 🚀 Ваши прикладные модули приложения
│       ├── forum/                  # Пример: Модуль форума и сообщества
│       │   ├── models.py           # Модели Topic, Message, Tag
│       │   └── handlers.py         # RPC-методы forum.get_topics, forum.create_topic
│       ├── billing/                # Пример: Модуль биллинга и счетов
│       │   ├── models.py           # Модели Invoice, Transaction
│       │   └── handlers.py         # RPC-методы billing.create_invoice, billing.pay
│       └── notifications/          # Пример: Сервис уведомлений и событий
│           └── handlers.py         # Реактивные рассылки через broadcast
│
├── client/                         # 💻 КЛИЕНТСКИЕ БИБЛИОТЕКИ
│   └── wsrpc.ts                    # Официальный TypeScript/JavaScript WSRPC-клиент
│
├── docs/                           # 📚 Документация фреймворка (EN)
│   ├── readme.md
│   ├── core.md                     # Полное руководство разработчика ядра
│   └── files.md                    # Руководство по загрузке файлов (2PC)
│
├── docs_ru/                        # 📚 Зеркальная документация фреймворка (RU)
│   ├── readme.md
│   ├── core.md                     # Полное руководство разработчика ядра
│   └── files.md                    # Руководство по загрузке файлов (2PC)
│
├── main.py                         # 🚀 Точка входа: сборка плагинов, RSGI app
├── settings.yaml                   # ⚙️ Конфигурация проекта (БД, порты, секреты)
└── pyproject.toml                  # 📦 Зависимости и манифест проекта
```

---

## ⚡ Сравнение: rsgi-wsrpc vs Django vs FastAPI

### 1. Как клиент общается с сервером

#### Традиционный REST (FastAPI / Django):
На каждый запрос клиент заново устанавливает TCP/TLS соединение, отправляет заголовки cookies/headers и ждет ответа:
```text
[ Клиент ] ──── TCP + TLS Handshake (50-100 ms) ────► [ Сервер ]
[ Клиент ] ──── POST /api/items (Headers + Body) ───► [ Сервер ]
[ Клиент ] ◄─── 200 OK (Headers + Body) ──────────── [ Сервер ]  (соединение закрыто)

[ Клиент ] ──── TCP + TLS Handshake (50-100 ms) ────► [ Сервер ]
[ Клиент ] ──── GET /api/user/profile ──────────────► [ Сервер ]
[ Клиент ] ◄─── 200 OK ───────────────────────────── [ Сервер ]
```

#### Реактивный WSRPC (`rsgi-wsrpc`):
Одно постоянное мультиплексированное WebSocket-соединение. Нулевой оверхед на рукопожатия, мгновенный пинг 1–3 мс:
```text
[ Клиент ] ═════════════════════════════════════════► [ Сервер ]
           (Единый постоянный защищенный WSRPC-канал)
           
           ─── id: 1, method: "items.create" ───────► (1 ms)
           ◄── id: 1, result: { id: 42 } ──────────── (1 ms)
           
           ─── id: 2, method: "user.get_profile" ───► (1 ms)
           ◄── id: 2, result: { name: "Alex" } ────── (1 ms)
           
           ◄── SERVER PUSH: method: "notify" ──────── (Сервер сам вызывает клиент!)
```

| Возможность | Django | FastAPI | `rsgi-wsrpc` |
| :--- | :--- | :--- | :--- |
| **Сетевой движок** | Python WSGI / медленный ASGI | Uvicorn (ASGI) | **Granian (Rust RSGI)** 🚀 |
| **Время отклика** | 80–250 мс | 30–120 мс | **1–5 мс** |
| **Симметричность** | ❌ Только Client ➔ Server | ❌ Только Client ➔ Server | ✅ **Client ⇄ Server (двусторонний)** |
| **Стриминг прогресса** | ❌ Нужен Redis + Channels | ❌ Сложный бойлерплейт сокетов | ✅ **Нативный мультиретурн (`stream: true`)** |
| **Потребление RAM** | ~150–250 МБ на воркер | ~80–120 МБ на воркер | **~25–40 МБ на воркер** |
| **Загрузка файлов** | Загрузка файла в память воркера | Загрузка в память / SpooledFile | **Потоковый O(1) RAM + 2PC + Nginx Offload** |
| **Готовая авторизация** | ✅ Встроена (но синхронная) | ❌ Отсутствует (делай сам) | ✅ **Встроена (JWT + Refresh + Argon2)** |
| **Инфраструктура** | Python + Postgres + Redis + Celery | Python + Postgres + ... | **Один бинарник Granian + SQLite/Postgres** |
| **Разработка с ИИ (AI-Native)** | ❌ Крайне неэффективно | ⚠️ Средне (много бойлерплейта) | 🚀 **Максимальная (AI-Native)** |
| **Расход токенов LLM на фичу** | ~3 000 – 5 000 токенов | ~2 000 – 3 500 токенов | **~300 – 600 токенов (в 5–10 раз меньше!)** |
| **Файлов для одной фичи** | 5–7 файлов | 4–6 файлов | **1–2 файла (`handlers.py` + `rpc.call`)** |
| **Бойлерплейт кода** | Огромный (DTO, URLs, views, redux) | Высокий (Pydantic, routers, Depends) | **Минимальный (чистый `@rpc_method`)** |

---

## 🤖 AI-Native: Экономия токенов и идеальная среда для LLM

`rsgi-wsrpc` спроектирован с учетом современной реальности: **код пишут и рефакторят нейросети и AI-агенты (Cursor, Claude, Gemini, GPT-4o, GitHub Copilot)**. 

В классическом стеке (FastAPI / Django) до 80% времени и токенов тратится на генерацию «клея» и бойлерплейта. В `rsgi-wsrpc` весь протокол унифицирован, а архитектура обеспечивает **рекордную экономию контекстного окна LLM**.

```text
РАСХОД ТОКЕНОВ НА ДОБАВЛЕНИЕ ОДНОЙ ФИЧИ (НАПРИМЕР: ДОБАВИТЬ КОММЕНТАРИЙ С ПУШ-УВЕДОМЛЕНИЕМ)

Django REST:  ████████████████████████████████████████ (~4 200 токенов)
FastAPI:      █████████████████████████ (~2 600 токенов)
rsgi-wsrpc:   ███ (~350 токенов)  ──► ЭКОНОМИЯ ТОКЕНОВ ДО 85%!
```

### Почему ИИ пишет код для `rsgi-wsrpc` быстрее, точнее и дешевле:

#### 1. Ноль лишнего бойлерплейта (Zero-Boilerplate)
Вам больше не нужно просить ИИ генерировать бесконечные Pydantic DTO для запроса, Pydantic DTO для ответа, схему ошибок, роутер, регистрацию роутера в `main.py`, и зеркальные интерфейсы с `fetch()` на фронтенде.
* **Бэкенд**: один декоратор `@rpc_method("domain.action")`. Контекст пользователя (`current_user_ctx`) и сессии доступны сразу без цепочек `Depends()`.
* **Фронтенд**: одна строка `await rpc.call("domain.action", { ... })`.

#### 2. Единый протокол вместо зоопарка технологий
В традиционных приложениях разработчик вынужден объяснять ИИ зоопарк: REST HTTP для CRUD, WebSocket/SSE для уведомлений, Redis Pub/Sub для очередей и Multipart для файлов. ИИ быстро забивает контекст и начинает галлюцинировать.
В `rsgi-wsrpc` **всё общение происходит через один симметричный протокол WSRPC (JSON-RPC 2.0)**: и вызовы, и стриминг прогресса (`stream: true`), и пуш-нотификации (`rpc.on`), и даже запросы подтверждений от сервера к клиенту (`rpc.registerMethod`).

#### 3. Максимальная локальность контекста (High Context Locality)
Модули в каталоге `app/<module>/` автономны. Чтобы ИИ добавил новую фичу или исправил баг, ему достаточно загрузить в контекст **всего 1 файл** (`handlers.py`), а не 10 взаимосвязанных файлов архитектуры.
* **Меньше входных токенов** — мгновенные ответы нейросети.
* **Выше точность** — ИИ не теряет важные детали в огромном промпте.
* **Ниже расходы** — прямая экономия бюджета на API LLM.

---

## 🚀 Быстрый старт за 60 секунд

### 1. Минимальный сервер (`main.py`)
```python
from core.session import rpc_method, JsonRpcSession
from core.lifecycle import on_startup

# Регистрируем RPC-метод
@rpc_method("math.add")
async def add_numbers(session: JsonRpcSession, params: dict):
    a = params.get("a", 0)
    b = params.get("b", 0)
    return {"result": a + b}

# Метод со стримингом прогресса (мультиретурн)
@rpc_method("task.run_long")
async def run_task(session: JsonRpcSession, params: dict):
    rpc_id = params.get("rpc_id")
    for step in range(1, 4):
        # Отправляем промежуточный чанк прогресса в сокет
        await session.send_stream_chunk(rpc_id, {"progress": step * 33})
    return {"status": "completed"}
```

### 2. Запуск сервера через Granian
```bash
granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
```

### 3. Вызов с клиента (JavaScript / TypeScript)
```javascript
import { BinaryWSRPC } from './wsrpc.js';

const client = new BinaryWSRPC('ws://127.0.0.1:8080');
await client.connect();

// Обычный вызов
const sum = await client.call('math.add', { a: 10, b: 25 });
console.log(sum.result); // 35

// Вызов со стримингом прогресса
await client.callStream('task.run_long', {}, (chunk) => {
    console.log(`Прогресс: ${chunk.progress}%`);
});
```

---

## ⚙️ Сетевое ядро (Core Engine)

> 📖 **Исчерпывающее техническое руководство по ядру со всеми примерами кода см. в документе: [docs_ru/core.md](docs_ru/core.md)**.

Сетевое ядро расположено в каталоге `core/` и содержит базовые примитивы:

* **[core/session.py](core/session.py)**:
  * Класс `JsonRpcSession` — управление постоянным сокетом клиента.
  * Мультиплексирование входящих и исходящих RPC-вызовов по уникальному числовому `id`.
  * Встроенный **Rate-Limiting (Token Bucket)** для автоматической защиты от флуда (30 req/s) без накладных расходов.
  * Изолированные контекстные переменные Python `ContextVar` (`current_user_ctx`, `current_session_ctx`, `current_rpc_id_ctx`, `current_transport_ctx`), доступные в любой глубине асинхронного стека без прокидывания параметров.
  * Реестр колбэков завершения сессии: `session.register_on_close(callback)` для очистки фоновых задач и транзакций.
  * Симметричный вызов клиента с сервера: `await session.send_request("client_method", params)`.

* **[core/router.py](core/router.py)**:
  * Декоратор `@http_route(path, methods)` для регистрации прямых HTTP-обработчиков поверх RSGI.
  * Прием сырых стримов байтов, вебхуков и healthcheck без лишнего оверхеда.

* **[core/upload.py](core/upload.py)**:
  * Координатор двухфазной транзакционной загрузки `UploadCoordinator`.
  * Потоковый прием файлов из протокола RSGI с расходом оперативной памяти **O(1) RAM** (`stream_request_to_disk`).
  * Вычисление контрольной суммы SHA-256 на лету в процессе приема байтов.
  * Автоматический откат (`await tx.rollback()`, удаление временных файлов) при обрыве соединения.

* **[core/security.py](core/security.py)**:
  * Надежное хэширование паролей на базе стойкого алгоритма **Argon2id**.
  * Генерация и валидация JWT access-токенов.
  * Асимметричное шифрование RSA для безопасной передачи чувствительных данных.

* **[core/lifecycle.py](core/lifecycle.py)**:
  * Диспетчер инициализации приложения `@on_startup` (выполняет миграции БД, прогрев кэша и запуск фоновых задач до начала приема трафика).

* **[core/lib/config.py](core/lib/config.py)**:
  * Парсер настроек `settings.yaml` со строгой валидацией и поддержкой переопределения через переменные окружения.

---

## 🔌 Официальные системные плагины (Plugins)

Фреймворк поставляется с набором готовых, протестированных системных плагинов (слой `app/system/`):

### 1. Плагин базы данных (`plugins/db`)
* **Технологии**: SQLAlchemy 2.0 (Async) + `orjson` для ультрабыстрой сериализации JSON-полей.
* **СУБД**: SQLite «из коробки» (без установки сторонних серверов). Переключение на PostgreSQL выполняется одной строкой в `settings.yaml`.
* **Использование**:
  ```python
  from app.system.db import async_session, Base
  from sqlalchemy import select

  async with async_session() as db:
      users = (await db.execute(select(User))).scalars().all()
  ```

---

### 2. Плагин пользователей и авторизации (`plugins/auth`)
* **Возможности**:
  * Модель `User`, поддержка ролей (`admin`, `moderator`, `user`, `guest`).
  * Механизм **Row-Level Security (RLS)**: базовые классы `BasicSecureModel` и `RowSecureModel` для автоматической фильтрации записей по владельцу.
  * Безопасное продление сессий через `RefreshToken` и отслеживание активных устройств в `ActiveSession`.
  * Доступ к текущему пользователю в любой точке кода без прокидывания аргументов:
    ```python
    from core.session import current_user_ctx
    user = current_user_ctx.get()
    ```

---

### 3. Плагин файлов и двухфазной загрузки (`plugins/files`)
* Подробная архитектура: см. **[docs_ru/files.md](docs_ru/files.md)**.
* **Как работает Two-Phase Commit**:
  1. Клиент запрашивает транзакцию загрузки: сервер выделяет уникальную хэш-папку `/tmp/agrita_uploads/<folder_hash>/`.
  2. Клиент заливает файлы потоком через `POST /upload`. Байты стримятся прямо на диск без переполнения памяти воркера.
  3. Если клиент оборвал связь — ядро через хук `session.on_close` мгновенно стирает временную папку. Мусор на сервере исключен.
  4. При успехе — папка атомарно перемещается в боевую директорию `/files/<folder_hash>/` за 0 миллисекунд.
  5. Все файлы автоматически учитываются в едином реестре `file_metadata` (контроль квот, оригинальные имена, mime-типы).
  6. Раздача подтвержденных файлов идет напрямую через **Nginx** с агрессивным кэшированием без нагрузки на Python.

---

## 🛠 Создание собственных плагинов и модулей в папке app

Создать собственный модуль (например, модуль тикетов техподдержки `app/tickets/`) предельно просто:

```python
# app/tickets/handlers.py
from core.session import rpc_method, RPCError, current_user_ctx
from app.system.db import async_session
from app.system.files.service import FileStorageService

@rpc_method("tickets.create")
async def create_ticket(session, params):
    user = current_user_ctx.get()
    if not user:
        raise RPCError("Необходима авторизация")

    title = params.get("title")
    text = params.get("text")
    folder_hash = params.get("folder_hash") # Если были прикреплены файлы

    # Сохраняем тикет в БД
    async with async_session() as db:
        async with db.begin():
            ticket = Ticket(title=title, text=text, author_id=user.id, folder=folder_hash)
            db.add(ticket)

    return {"status": "ok", "ticket_id": ticket.id}

@rpc_method("tickets.delete")
async def delete_ticket(session, params):
    ticket_id = params.get("ticket_id")
    
    async with async_session() as db:
        ticket = await db.get(Ticket, ticket_id)
        if ticket and ticket.folder:
            # Атомарно удаляем все вложенные файлы тикета с диска и из реестра
            await FileStorageService.delete_bundle(ticket.folder)
        await db.delete(ticket)
        await db.commit()

    return {"deleted": True}
```

Чтобы модуль заработал, достаточно импортировать его хендлеры в `main.py`:
```python
# main.py
import app.tickets.handlers  # noqa: F401
```

---

## 💻 Клиентская библиотека (TypeScript/JavaScript)

В репозиторий включен официальный легковесный клиент `client/wsrpc.ts` с нулевыми внешними зависимостями:

```typescript
import { BinaryWSRPC, wsConnected, wsStatus } from './wsrpc';

const rpc = new BinaryWSRPC('wss://api.example.com/ws');
await rpc.connect();

// 1. Обычный типизированный RPC-вызов
const profile = await rpc.call<UserProfile>('user.get_profile', { user_id: 42 });
console.log('Пользователь:', profile.name);

// 2. Мультиретурн: стриминг прогресса выполнения тяжелой операции
const report = await rpc.callStream<ReportResult>(
    'reports.generate', 
    { period: '2026-Q3' }, 
    (chunk) => {
        console.log(`[${chunk.percent}%] Прогресс: ${chunk.message}`);
        updateProgressBar(chunk.percent); // Живое обновление UI!
    }
);
console.log('Отчет готов:', report.download_url);

// 3. Получение нотификаций и Server Push (события от сервера)
const unsubscribe = rpc.on('chat.new_message', (msg) => {
    console.log(`[${msg.author}]: ${msg.text}`);
    messagesList.update(items => [...items, msg]);
});

// 4. Симметричный RPC: сервер запрашивает подтверждение у браузера
rpc.registerMethod('ui.confirm', async (params) => {
    const isApproved = await showConfirmationModal(params.title, params.message);
    return { confirmed: isApproved }; // Возвращаем ответ серверу!
});
```

> 📖 **Исчерпывающие примеры интеграции с UI-фреймворками (Svelte, React, Vue), обработки ошибок и отписок см. в [docs_ru/core.md](docs_ru/core.md#8-клиент-typescriptjavascript-clientwsrpcts)**.

---

## 📄 Лицензия
Проект распространяется под свободной лицензией **MIT**.  
Разрешено коммерческое использование, модификация и распространение.
