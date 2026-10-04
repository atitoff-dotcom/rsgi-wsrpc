# Рекомендации по rsgi-wsrpc: узкие места и аудит

Статус: **Все критические проблемы (P0) и ключевые архитектурные задачи (P1) верифицированы и исправлены.**
Подробный отчет о выполненных шагах зафиксирован в [AUDIT_PLAN.md](file:///home/alex/rsgi-wsrpc/AUDIT_PLAN.md).

Тесты: unit-тесты (58 тестов) полностью изолированы от e2e тестов через маркер `e2e` в `pyproject.toml` и проходят на 100% за < 1 секунды.

---

## 🔴 P0 — сломано / дыры в безопасности

| # | Проблема | Где | Статус |
|---|---|---|---|
| 1 | **Загрузка файлов тихо сохраняет пустые файлы.** `stream_request_to_disk` переписан на поддержку асинхронного итератора `proto` в RSGI. | [upload.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/files/upload.py) | ✅ Исправлено |
| 2 | **RPC `files.*` и сигнатуры `@rpc_method`.** Добавлен автоматический маппинг именованных параметров через `inspect.signature` и расширен `RPCError`. | [handlers.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/files/handlers.py), [session.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/session.py) | ✅ Исправлено |
| 3 | **`/auth-check-upload` валидация.** Добавлена проверка JWT через `decode_access_token`. | [upload.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/files/upload.py) | ✅ Исправлено |
| 4 | **Авторизация по умолчанию.** `login_rpc` установлен в `"login."` (гостям доступны только методы логина), добавлен флаг `@rpc_method(public=True)`. | [session.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/session.py), [config.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/lib/config.py) | ✅ Исправлено |
| 5 | **DoS через `login.get_key`.** Генерация RSA-2048 вынесена в тредпул с кэшем до 500 ключей и ротацией. | [handlers.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/auth/handlers.py) | ✅ Исправлено |
| 6 | **Пароли: слабые дефолты.** Итерации PBKDF2 повышены до 600 000 по умолчанию, сравнение через `hmac.compare_digest`. | [config.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/lib/config.py), [models.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/auth/models.py) | ✅ Исправлено |
| 7 | **Подмена `core` / `plugins` в чужих проектах.** `compat.py` теперь возвращает `None` для несуществующих подмодулей, устранены плоские импорты внутри библиотеки. | [compat.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/compat.py), [auth/core.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/auth/core.py) | ✅ Исправлено |
| 8 | **OAuth: безопасность связывания аккаунтов.** Добавлена проверка `oauth_auto_link_email` (по умолчанию `False`), предотвращающая захват аккаунтов. | [handlers.py](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/auth/handlers.py) | ✅ Исправлено |


---

## 🟠 P1 — архитектура и надёжность

### Нет собственно «приложения»
Фреймворк даёт декораторы и реестры, а RSGI-`app()` каждый пишет сам (см. [showcase/server.py:105-147](file:///home/alex/rsgi-wsrpc/examples/showcase/server.py#L105-L147)). HTTP-диспетчер — линейный перебор `HTTP_ROUTES` по точному пути: нет path-параметров, CORS, статики, `__rsgi_del__`, подключения `handle_bot_http` из SEO. Каждый пользователь будет копировать этот код.
**Рекомендация:** `RsgiWsrpcApp` / `create_app()` — единая точка входа (роутинг, WS, lifecycle, CORS, graceful shutdown).

### `core/session.py`
- Хак «Python 3.13 / Granian» (`awaitable.cancelled = lambda: False`) скопирован 6 раз (+ в broadcast и showcase). Нужен один `_send_str()`.
- `logger.info("Получено сообщение")` на каждое входящее сообщение.
- Нет лимита размера сообщения, числа одновременных хендлеров на сессию, таймаута хендлера.
- Если JSON не объект (`[]`, `1`) — `data.get` бросает `AttributeError` и валит сессию; `params` не проверяется на `dict`.
- `send_request` при таймауте не удаляет future из `_pending_requests` (утечка).
- Колбэки закрытия: `asyncio.create_task` без сохранения ссылки.
- Проверка роли смотрит только на `user_role` (первую), хотя ролей может быть несколько.
- `__del__` с логированием; `asyncio.iscoroutinefunction` deprecated в 3.14 (venv на 3.14).
- Глобальные `RPC_REGISTRY`, `HTTP_ROUTES`, `ACTIVE_SESSIONS_SET`, `settings` — два приложения/теста в одном процессе не живут.

### `plugins/auth/handlers.py` — 1061 строка
- Блок «найти/создать пользователя → refresh → ActiveSession → JWT → session_data → register_on_close» скопирован ~5 раз (login, refresh, vk, yandex, secure) — около 600 строк дубля.
- Скрытые зависимости от хост-приложения: `from app.config import settings`, `from app.session import Session` ([config.py:15](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/auth/config.py#L15), [db/session.py:22](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/db/session.py#L22)).
- `type("AppSession", (), {...})()` на каждый вход — нужен `dataclass AuthContext`.
- `UserRole(role_name) if hasattr(UserRole, role_name)` — всегда False (атрибуты в верхнем регистре) → мёртвый код.
- В `UserRole` доменные роли закрытого проекта: `BANK_WORKER`, `PRINCIPAL`, `AGENT`, `ANALYST`.
- JWT: срок жёстко 7 дней, `token_expire_hours` нигде не используется; `fpt` (отпечаток UA) кладётся в токен, но `decode_access_token` в пакете нигде не вызывается — JWT по сути декоративный.
- Refresh-токены хранятся в БД в открытом виде и не ротируются.
- `is_superadmin = role.id == 1 or role.name == "admin"` — привязка к значению PK.
- `SECRET_KEY = get_secret_key()` на уровне модуля устаревает после `configure()`; dev-ключ только логируется — в проде стоит падать.

### Многопроцессность
Всё состояние в памяти процесса: `ACTIVE_SESSIONS_SET`, `VersionRegistry`, `UploadCoordinator`, `ephemeral_keys`. При `workers>1`:
- `broadcast` / `send_to_user` / `cache.invalidate` дойдут только до клиентов своего воркера;
- версии Smart Cache разъедутся;
- RSA-ключ и 2PC-транзакция, созданные в одном воркере, не принимаются в другом.

Либо явно документировать «`workers=1`», либо backplane (Redis / PG `LISTEN/NOTIFY`).

### Smart Cache
- `_persist_versions` — fire-and-forget, порядок записей не гарантирован (в БД может осесть меньшая версия).
- Upsert через `sqlite_insert` для всех СУБД; на PostgreSQL ошибка переводит транзакцию в aborted, и fallback `db.get` тоже упадёт.
- `invalidates` без `functools.wraps`.

### Файлы
- Синхронный I/O в async-коде (`open().write`, `shutil.*`, `iterdir`) блокирует loop.
- `/tmp/app_uploads` по умолчанию не работает на Windows (в репо есть `run.bat`/`run.ps1`) → `tempfile.gettempdir()`.
- Дефолты разъехались: `files_path` = `./files` в конфиге и `./data/files` в `upload.py`.
- Транзакция загрузки не привязана к владельцу — достаточно знать `folder_hash`; нет проверки квоты/ожидаемого размера.
- Ошибка БД при standalone-загрузке проглатывается, клиент получает `success: true` с `file_id: null`.

### DB-плагин
Engine создаётся при импорте и один раз читает `DATABASE_URL`: `configure(database_url=...)` после первого импорта `plugins.db` ничего не меняет. Миграций нет (`create_all` вручную) — нужна интеграция с Alembic или документированный путь.

---

## 🟡 P2 — гигиена

- `rsgi_wsrpc/core/lib/` без `__init__.py` — добавить.
- Версия в двух местах (`pyproject.toml` и `__init__.py`).
- `pyjwt` / `cryptography` — обязательные зависимости, хотя нужны только `auth`/`files`; нет extras `dev` (pytest, pytest-asyncio, aiohttp).
- [core/changed.md](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/core/changed.md) — внутренний changelog с путями `app/...` лежит внутри пакета; в `tests/run.py` — «Agrita Backend Test Harness».
- `logger.py`: новый `logging.Formatter` на каждую запись; `setup_logging` пишет в `./logs` относительно cwd.
- `send_stream_chunk` глотает все ошибки.
- Документация в 4 копиях (`docs/`, `docs_ru/`, 2 README) — разойдётся без проверки в CI.
- Смесь unit (моки) и e2e (живой сервер) — именно это скрыло баги №1 и №2.

---

## ✅ Что стоит оставить

- **Ядро WSRPC** (симметричный JSON-RPC, `contextvars`, `__slots__`-сессия, orjson) — хорошая основа; нужен рефакторинг, не переписывание.
- **Tabular (RFC 0002)** — компактно и самодостаточно.
- **SEO-плагин** (detector, router, sitemap, IndexNow с файловой очередью) — продуман; замечание только про блокирующий `open()` в `enqueue_indexnow_urls`.
- **RLS на событиях SQLAlchemy** — интересная фича, но нужны тесты на не-SELECT и на bypass-контекст.

---

## Предлагаемый порядок работ

1. **Hotfix (P0 #1–#4):** `async for chunk in proto` в upload; сигнатуры `files.*` + тесты через реальный вызов `rpc_method`; проверка JWT в `/auth-check-upload` и `/upload`; secure-by-default для публичных методов.
2. **Auth hardening (#5, #6, #8):** `to_thread` для PBKDF2/RSA, TTL и лимит `ephemeral_keys` (или отказ от RSA), 600k итераций, `compare_digest`, проверка подтверждённого email.
3. **Compat-мост — opt-in** (`install_compat()` вручную), заменить `import plugins...` на канонические.
4. **`RsgiWsrpcApp`** + рефакторинг `session.py` (единый `_send`, лимиты, валидация).
5. **Auth refactor:** `AuthService`, OAuth-провайдеры, `AuthContext`, убрать зависимости от `app.*`.
6. **Тесты:** разделить `unit/` и `e2e/` (фикстура с реальным Granian), тест «реальная загрузка файла».
7. **Multi-worker:** backplane или документированное ограничение.
