# Модульный каркас тестирования бэкенда (Client Test Harness)

В платформу **rsgi-wsrpc** встроен профессиональный, модульный асинхронный каркас тестирования (`tests/`), проверяющий поведение бэкенда **с точки зрения реального клиента** («черный ящик») по протоколам **WSRPC (WebSocket)** и **HTTP**.

Он решает главные проблемы ручного и разового скриптового тестирования:
* **Исключает повторные ошибки аутентификации**: готовые персоны (`Admin`, `User`, `Guest`) автоматически авторизуются через сокет без необходимости вручную хэшировать пароли и собирать токены.
* **Понимает специфику WSRPC**: умеет проверять потоковые ответы (`stream: true`), перехватывать входящие серверные push-события (`cache.invalidate`, `cache.patch`) и измерять реальные миллисекунды сетевой задержки.
* **Включает стресс- и нагрузочное тестирование**: замер RPS, распределения задержек (p50, p95, p99) и надежности мгновенной рассылки (Fan-out) на десятки и сотни параллельных клиентов.

---

## 🚀 Быстрый запуск

Запуск тестов выполняется единым консольным раннером:

```bash
# Активируйте виртуальное окружение
source .venv/bin/activate

# Запустить все тестовые сьюты против локального сервера (по умолчанию)
python tests/run.py

# Запустить конкретный сьют (например, реактивный кэш или форум)
python tests/run.py smart_cache
python tests/run.py forum auth

# Запустить нагрузочное и стресс-тестирование
python tests/run.py load

# Запустить тестирование против удаленного Stage-сервера
python tests/run.py --target=stage
```

### Пример вывода раннера:
```text
=== Agrita Backend Test Harness ===
  Цель:      LOCAL (http://127.0.0.1:8080 | ws://127.0.0.1:8080/)
  Сьюты:     auth, smart_cache, forum, files, load

▶ Сьют: auth (4 тестов)
  ✔ PASS  auth::test_guest_public_access  (2.3 ms)
  ✔ PASS  auth::test_login_and_whoami  (202.6 ms)
  ✔ PASS  auth::test_login_invalid_password  (4.6 ms)
  ✔ PASS  auth::test_token_refresh  (27.8 ms)

▶ Сьют: smart_cache (3 тестов)
  ✔ PASS  smart_cache::test_cache_get_versions  (2.8 ms)
  ✔ PASS  smart_cache::test_cache_sync_check_stale_detection  (3.1 ms)
  ✔ PASS  smart_cache::test_live_cache_invalidation_notification  (69.8 ms)

▶ Сьют: forum (3 тестов)
  ✔ PASS  forum::test_get_topics_guest  (4.9 ms)
  ✔ PASS  forum::test_topic_creation_and_cache_invalidation  (80.6 ms)
  ✔ PASS  forum::test_unauthorized_deletion_prevented  (44.2 ms)

▶ Сьют: files (1 тестов)
  ✔ PASS  files::test_two_phase_file_upload  (21.4 ms)

▶ Сьют: load (2 тестов)
  ⚡ [FAN-OUT STATS] Рассылка на 25 активных WebSocket-клиентов за 3.3ms
  ✔ PASS  load::test_concurrent_broadcast_fanout  (312.1 ms)
  📊 [LOAD STATS] 200 запросов за 0.06s | 3540.1 RPS
  ⏱️  Задержки: p50=4.1ms, p95=6.2ms, p99=6.6ms
  ✔ PASS  load::test_concurrent_rpc_throughput  (56.6 ms)

=== Итоги тестирования ===
Всего: 13, Успешно: 13, Провалено: 0 (0.84 s)
```

---

## 🏗 Архитектура тестового каркаса (`tests/`)

```
tests/
├── framework/              # Ядро и инфраструктура
│   ├── config.py           # Конфигурация хостов (local, stage, порты)
│   ├── client.py           # Асинхронный WSRPC + HTTP клиент (TestClient)
│   ├── personas.py         # Менеджер ролей (Admin, User, Guest) и сидинг БД
│   └── assertions.py       # Кастомные ассерты ответов, ошибок и пушей
├── suites/                 # Модульные наборы тестов
│   ├── test_auth.py        # Аутентификация, токены, RLS-профиль
│   ├── test_smart_cache.py # Версионирование тегов, рукопожатие, push-инвалидация
│   ├── test_forum.py       # Бизнес-логика, создание тем, права на удаление
│   ├── test_files.py       # Двухфазная загрузка файлов (/upload)
│   └── test_load.py        # Нагрузочное тестирование, RPS, задержки p50/p95/p99
└── run.py                  # CLI-раннер тестов с форматированием и таймингами
```

---

## 🔑 Управление персонами (`PersonaManager`)

Чтобы тесты не дублировали авторизационный бойлерплейт, используется класс `PersonaManager`:

```python
from tests.framework import PersonaManager

# 1. Гостевой клиент (без авторизации)
async with await PersonaManager.as_guest() as client:
    res = await client.call("system.echo", {"hello": "world"})

# 2. Обычный пользователь (автоматически логинится под 'test_user')
async with await PersonaManager.as_user() as client:
    res = await client.call("forum.create_topic", {...})

# 3. Администратор (права суперадмина)
async with await PersonaManager.as_admin() as admin:
    res = await admin.call("cache.invalidate", {"tags": ["forum.topics"]})
```

> [!TIP]
> При локальном запуске (`--target=local`) `PersonaManager` автоматически проверяет наличие тестового пользователя в базе данных SQLite/PostgreSQL. Если пользователя нет или у него сменился пароль, менеджер безопасно создает его с обходом RLS (`system_bypass_ctx`). Вам больше не нужно предварительно вручную заполнять базу данных!

---

## 📡 Возможности `TestClient`

Клиент `TestClient` инкапсулирует полное взаимодействие с WebSocket и HTTP сервисами платформы:

### 1. Одиночные вызовы (`call`)
```python
# Возвращает поле 'result' из JSON-RPC ответа или вызывает RPCClientError
res = await client.call("forum.get_topic", {"id": 42})
```

### 2. Ожидание серверных push-уведомлений (`wait_for_notification`)
Идеально для тестирования инвалидации кэша и живых обновлений:
```python
# Запускаем ожидание уведомления в фоне
wait_task = asyncio.create_task(client.wait_for_notification("cache.invalidate", timeout=5.0))

# Другой клиент совершает мутацию
await other_client.call("forum.create_topic", {...})

# Получаем и валидируем push-событие
notif = await wait_task
assert "forum.topics" in notif["params"]["tags"]
```

### 3. Потоковые мультиретурны (`stream`)
```python
# Итерируемся по промежуточным чанкам до завершения стрима
async for chunk in client.stream("reports.generate", {"year": 2026}):
    print(f"Получен промежуточный прогресс: {chunk}")
```

### 4. Потоковая загрузка файлов (`upload_file`)
```python
# Загружает байты на HTTP POST /upload без Base64 оверхеда
result = await client.upload_file(
    filename="avatar.png",
    content=b"RAW_IMAGE_BYTES",
    content_type="image/png"
)
print("Папка вложения:", result["folder_hash"])
```

---

## ⚡ Нагрузочное и стресс-тестирование (`test_load.py`)

Нагрузочные тесты выявляют скрытые архитектурные дефекты, которые невозможно заметить на одиночных юнит-тестах:

### 1. Что проверяет сьют `test_load`:
1. **RPS и распределение латентности** (`test_concurrent_rpc_throughput`):
   - Десятки одновременных клиентов бомбардируют сервер вызовами через активные WebSockets.
   - Замеряются метрики: **RPS** (запросов в секунду), медиана **p50**, хвостовые задержки **p95** и **p99**.
2. **Широковещательный стресс (Fan-out)** (`test_concurrent_broadcast_fanout`):
   - Подключается пул из десятков активных слушателей.
   - Автор отправляет импульс инвалидации `cache.invalidate`.
   - Проверяется, что 100% клиентов получили событие, сокеты не заблокировались, а время доставки броадкаста исчисляется миллисекундами (в среднем ~3 ms на 25 клиентов).

### 2. Типичные баги, вскрываемые нагрузочными тестами:
* **Блокировка базы данных (`database is locked` в SQLite)**: при одновременной записи нескольких сокетов. Решение: использование WAL-режима (`PRAGMA journal_mode=WAL`) и асинхронной очереди записи.
* **Зависание фоновых задач (`Task was destroyed but it is pending`)**: когда соединение клиента оборвалось в момент выполнения запроса.
* **Блокировка Event Loop**: тяжелые синхронные вычисления или файловый I/O в основном цикле asyncio приводят к резкому росту p99 с 4 ms до сотен миллисекунд.
* **Утечки памяти и сессий**: накопление брошенных WebSocket-соединений в памяти воркера при обрывах связи.

---

## 📝 Добавление собственного тестового сьюта

Создать тест для нового плагина или бизнес-модуля предельно просто:

1. Создайте файл `tests/suites/test_my_feature.py`:
```python
from tests.framework import PersonaManager, assert_rpc_success

async def test_my_action():
    async with await PersonaManager.as_user() as client:
        res = await client.call("my_feature.do_something", {"param": 1})
        assert_rpc_success(res, expected_keys=["status", "result_id"])
```

2. Зарегистрируйте сьют в словаре `SUITES` файла [tests/run.py](file:///home/alex/hydro_calc/tests/run.py):
```python
from tests.suites import test_my_feature

SUITES = {
    ...
    "my_feature": test_my_feature,
}
```

3. Запустите:
```bash
python tests/run.py my_feature
```
