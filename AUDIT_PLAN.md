# План проверки и исправлений rsgi-wsrpc

## Цель
Провести практическую верификацию каждого замечания из аудита `RECOMMENDATIONS.md`, отделить реальные баги от ложных срабатываний и последовательно исправить подтвержденные проблемы без нарушения обратной совместимости.

---

## Этап 1. Верификация критических утверждений (P0)

- [x] **1.1. Проверка стриминга файлов в Granian RSGI**
  - Подтверждено: Granian RSGI использует `proto` как асинхронный итератор (`async for chunk in proto`) и `await proto()`.
  - Исправлено в `rsgi_wsrpc/plugins/files/upload.py` с сохранением fallback.
- [x] **1.2. Проверка сигнатур хендлеров `files.*` и вызова RPCError**
  - Исправлен декоратор `@rpc_method` в `session.py`: добавлен авто-маппинг kwargs через `inspect.signature`.
  - Расширен `RPCError` для поддержки как `(message)`, так и `(code, message)` с передачей кода в JSON-RPC error response.
- [x] **1.3. Проверка безопасности `/auth-check-upload` и опции `login_rpc`**
  - В `/auth-check-upload` добавлена валидация JWT через `decode_access_token`.
  - Значение по умолчанию `login_rpc` изменено на `"login."` (гостям по умолчанию доступны только методы логина).
  - В `@rpc_method` добавлен флаг `public=True` для явного открытия не-логин методов неавторизованным гостям при необходимости.
- [x] **1.4. Проверка сайд-эффектов `compat.py`**
  - `_LegacyAliasFinder` в `compat.py` обновлен: возвращает `None`, если подмодуль не принадлежит `rsgi_wsrpc`, исключая перехват сторонних `core` и `plugins`.
  - Исправлен импорт `from . import security` в `plugins/auth/core.py`.
- [x] **Дополнительные P0 фиксы:**
  - Защита DoS в `login.get_key`: вынос генерации RSA-2048 в `asyncio.to_thread` и ограничение кэша до 500 ключей с ротацией.
  - Повышение итераций PBKDF2 до 600 000 по умолчанию, сравнение через `hmac.compare_digest`.
  - Устранены неявные импорты `app.config` и `app.session` в плагинах auth и db.


---

## Этап 2. Архитектурный анализ и рефакторинг (P1)

- [x] **2.1. Класс приложения (`RsgiWsrpcApp`)**
  - Создан `RsgiWsrpcApp` в `rsgi_wsrpc/app.py`: принимает все настройки в `__init__`, изолирует HTTP/WebSocket, CORS preflight, Zero-Copy раздачу статики через нативный `proto.response_file` Granian с защитой от traversal, и автоматический graceful lifecycle (`__rsgi_init__` / `__rsgi_del__`).
  - Showcase `examples/showcase/server.py` переведен на `RsgiWsrpcApp`, убрано ~60 строк ручного бойлерплейта.
- [x] **2.2. Зависимости от `app.*` внутри библиотеки**
  - Устранены неявные импорты `app.config` и `app.session` в плагинах auth и db.
  - Создан `AuthSession` dataclass в `plugins/auth/core.py`.
- [x] **2.3. Поведение в Multi-Worker (Granian workers > 1)**
  - Спроектирован интерфейс `BaseBackplane` и локальный `MemoryBackplane` в `rsgi_wsrpc/core/backplane.py`.
  - Добавлено автоматическое предупреждение при запуске с `workers > 1` на `MemoryBackplane`.
- [x] **2.4. Рефакторинг `plugins/auth/handlers.py` и проверка OAuth email/state**
  - Создана единая функция `_create_authenticated_session(...)`, устранены дублирования создания сессий и токенов в `login`, `login.secure`, `refresh`, `vk_auth` и `yandex_auth`.
  - Добавлена безопасная проверка настройки `oauth_auto_link_email` (по умолчанию `False`), исключающая захват аккаунта по совпадению неподтвержденного email.


---

## Этап 3. Реализация изменений (по результатам проверок)

- [x] **Фаза 1: Фиксы поломок (Bugfixes)**
  - Стриминг файлов через `proto` в RSGI.
  - Поддержка параметров в `@rpc_method` и исправление кодов `RPCError`.
  - Валидация JWT в `/auth-check-upload`.
  - Дефолтный `login_rpc="login."` для изоляции гостевого доступа.
  - Защита DoS в генерации RSA-ключей.
- [x] **Фаза 2: Чистка ядра и изоляция пакета**
  - Единый метод `session.send_str(...)` с обходом бага отмены Future.
  - Безопасный парсинг JSON с защитой от non-dict объектов и контролем лимита размера.
  - Ликвидация утечки памяти `_pending_requests` при таймаутах.
  - Избавление от импортов `app.*`, канонический класс `AuthSession`.
  - Класс `RsgiWsrpcApp` для лаконичного запуска приложения со всеми настройками и Zero-Copy статикой.
- [x] **Фаза 3: Тестирование и разделение unit/e2e**
  - Устранены предупреждения SQLAlchemy (SAWarning) и PytestCollectionWarning.
  - Разделены unit-тесты и e2e интеграционные тесты с помощью маркера `e2e` в `pyproject.toml`.
  - 100% unit-тестов (58 тестов) стабильно проходят за < 1 секунды без запущенного сервера.
