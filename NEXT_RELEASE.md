# План задач к следующему обновлению (NEXT_RELEASE.md)

> **Внимание ИИ-ассистентов и разработчиков:**  
> Этот файл является обязательным бэклогом задач для следующего релиза.  
> **ПЕРЕД ЛЮБЫМ БАМПОМ ВЕРСИИ И ПУБЛИКАЦИЕЙ В PYPI ОБЯЗАТЕЛЬНО ПРОЧИТАТЬ ЭТОТ ФАЙЛ**, реализовать запланированные в нем задачи или учесть их. Новые задачи и идеи по рефакторингу/улучшениям сразу заносятся сюда.

---

## 📌 Запланировано к следующему релизу (Backlog)
<!-- Новые задачи на будущие релизы заносятся сюда -->

---

## ✅ Выполнено в текущем релизе / подготовке:
* [x] **v0.5.3: Единый системный стандарт эндпоинта WebSocket (`/ws`):**
  - **Канонический WebSocket эндпоинт (`/ws`):**
    - В [client/wsrpc.ts](file:///home/alex/rsgi-wsrpc/client/wsrpc.ts) унифицирована функция `getWsUrl()`: теперь соединение всегда направляется на `/ws` единообразно во всех окружениях (HTTP, HTTPS, Vite dev-сервер, Nginx reverse proxy).
    - Устранена рассинхронизация с Nginx: ранее при открытии админки по HTTP запрос уходил на `ws://host/` вместо `ws://host/ws`, что приводило к ошибке при наличии директивы `location /ws`.
    - Добавлен механизм явного переопределения URL сокета через `window.__WSRPC_URL__`.
    - Пересобраны автономная панель управления ([rsgi_wsrpc/plugins/crud/static](file:///home/alex/rsgi-wsrpc/rsgi_wsrpc/plugins/crud/static)) и интерактивная витрина ([examples/showcase/public](file:///home/alex/rsgi-wsrpc/examples/showcase/public)).
    - Скрипты нагрузочного тестирования и аудита безопасности ([scripts/benchmark.py](file:///home/alex/rsgi-wsrpc/scripts/benchmark.py), [scripts/security_audit.py](file:///home/alex/rsgi-wsrpc/scripts/security_audit.py)) и тестовый конфиг ([tests/framework/config.py](file:///home/alex/rsgi-wsrpc/tests/framework/config.py)) обновлены для использования пути `/ws`.

## ✅ Выполнено в предыдущих релизах
* [x] **v0.5.2:**
  - **Единый Mission Control Cockpit (`/admin`):**
    - Подраздел **`📊 Данные (CRUD)`**: управление зарегистрированными бизнес-моделями и матрицей прав доступа.
    - Подраздел **`⚙️ Система (System Cockpit)`**:
      - `admin.sessions_list` & `admin.session_kill`: мониторинг открытых дуплексных WebSocket-соединений и отключение клиентов (Kick).
      - `system.cache_stats` & `system.cache_invalidate`: инспекция монотонных версий тегов Smart Cache (RFC 0001) и ручная инвалидация.
      - `system.broadcast`: O(1) Zero-Copy рассылка системных уведомлений без блокировки сокетов.
      - `system.recent_logs`: кольцевой буфер оперативного журнала событий сервера в памяти с авто-обновлением (Live Log Streamer).
      - `system.get_config`: инспекция Runtime Config с маскированием секретных ключей.
  - **Теплая бежево-коричневая палитра оформления:**
    - **Светлая тема:** строго 80% от самого светлого в теплых бежевых тонах (`#dcd3c6` / `#e8e0d4` / `#2d221a`).
    - **Темная тема:** строго 20% от самого светлого в теплых коричневатых тонах (`#33241b` / `#3d2c22` / `#ece5dc`).
  - **Системная надежность ядра:**
    - Поддержка проверки `CloseMessage` по `__class__.__name__` для нативных RSGI-фреймов Granian и тестовых сокетов.
* [x] **v0.5.1:**

  - **Zero-Boilerplate DX (Developer Experience):**
    - `auto_auth_ws=True` (по умолчанию включено): автоматическая авторизация WebSocket-сессий по Cookie (`rsgi_crud_session`, `rsgi_session`, `rpc_jwt`, `token`) без необходимости писать ручной код в `@app.on_connect`.
    - Режим быстрой локальной разработки `dev_admin=True` в `RsgiWsrpcApp`: автоматическая регистрация `/dev-admin` с установкой Cookie и безопасный сидинг пользователя `admin`/`admin123`.
    - Бесшовная интеграция `plugins.crud` и `plugins.auth`: `get_crud_session` нативно валидирует JWT-токены фреймворка и защищен от циклической рекурсии.
    - Динамический ре-бинд базы данных (`AsyncEngineProxy` и `configure_db`): параметры `database_url` и `db_echo` в `RsgiWsrpcApp` и `configure()` прозрачно переконфигурируют движок и `async_session` независимо от порядка импортов в коде.
    - Алиас `send_stream_chunk` в `AuthSession` для соответствия контракту потокового стриминга.
    - Автоматическая регистрация моделей безопасности (`User`, `Role`, `RpcPermission`) в `ModelRegistry.register_auth_models()`.
* [x] **v0.5.0:**
  - **Новый GUI управления доступом и разрешениями (CRUD + RPC):** разделение прав на данные (CRUD-матрица для моделей) и процедурных прав (RPC), персональные разрешения поверх ролевых, модалка `PermissionsModal.svelte`.
  - **Навигация субъектов доступа (Гости, Пользователи, Роли):** поддержка `target_type = "guest"`, Zero-Noise скрытие кнопки при `allow_guests=False`.
  - **Стандартизация Docstring RPC-методов и интерактивная справка (Help Modal):** сохранение оригинальных docstrings в `@rpc_method`, auto-healing шаблонных записей в БД при discovery, компонент `RpcHelpModal.svelte` с кнопкой `ℹ️`.
  - **Очистка CRUD Admin от визуального и технического шума:** скрытие технических связующих моделей (`is_internal = True`), компактное форматирование времени, исправление инлайн-редактирования Many-to-Many ячеек.
  - **Showcase как единый источник правды (SSOT) и двуязычная документация:** манифест `showcase_docs.json`, скрипт `build_docs.py`, фронтенд Showcase на Svelte 5.
* [x] **v0.4.9:**
  - Поддержка связей Many-to-Many в CRUD Admin: отображение бейджей/тегов, множественный выбор чекбоксами в модалке создания и инлайн-редактирование ячеек.
  - Декларативные модели связей первого класса `UserRole`, `UserTeam`, `RoleRpcPermission` в реестре CRUD с сохранением обратной совместимости.
  - Новый RPC-метод `crud.lookup` для динамической подгрузки вариантов Foreign Key и Many-to-Many.
  - Информативные цветные логи `[WSRPC]` на клиенте и автоматическая поддержка подключения по локальному IP (LAN).
  - Кнопки быстрых действий (Action Buttons) и таски VS Code для запуска Showcase на `0.0.0.0:8080` и сборки UI CRUD.
* [x] **v0.4.8:**
  - Полноценная мультиязычность (RU / EN) в CRUD-панели на Svelte 5 с переключателем языка `🌐 RU / EN`.
  - Мультиязычность витрины `examples/showcase` (RU / EN).
  - Интеграция системных моделей безопасности `RpcPermission`, `Role`, `User` в панель CRUD (`ModelRegistry`).
  - Окончательное удаление рудимента `/crud/login` и HTML-формы входа; полный переход на SSO и Zero-Leakage 404.
* [x] **v0.4.7:** Экспорт `set_crud_session_validator` в публичный интерфейс `plugins/crud`.
* [x] **v0.4.6:** Безопасное извлечение `user_name` в системном логгере без `AttributeError`.
* [x] **v0.4.5:** Zero-Leakage (404 Not Found) для админки CRUD и бесшовный SSO-мост с приложением.
* [x] **v0.4.4:** Динамические роли в БД, Service Discovery RPC-методов, типизированный `RsgiWsrpcApp`.
