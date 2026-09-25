# Официальные плагины («Батарейки в комплекте»)

Фреймворк `rsgi-wsrpc` следует трехуровневой архитектуре:
1. **Ядро (`core/`)**: Компактный, высокопроизводительный асинхронный движок протокола RSGI/WSRPC, сессионный роутер, криптографические примитивы и управление жизненным циклом соединений.
2. **Плагины (`plugins/`)**: Официальные модульные расширения («батарейки»), подключаемые к интерфейсам ядра: сессии базы данных, аутентификация/авторизация корпоративного уровня, RLS, кэширование.
3. **Приложения (`App/`)**: Специфическая бизнес-логика (например, Agrita), использующая ядро и выбранные плагины.

---

## 1. Плагин базы данных (`plugins.db`)

Предоставляет асинхронное управление сессиями SQLAlchemy 2.0, пул подключений, реестр метаданных и утилиты пагинации.

### Ключевые компоненты
- `Base`: Центральный декларативный базовый класс (`DeclarativeBase`), обеспечивающий единый `metadata` между всеми плагинами и таблицами приложения (внешние ключи FK работают бесшовно).
- `engine`: Асинхронный движок SQLAlchemy, настраиваемый в коде через `configure(database_url=...)` или переменную окружения `DATABASE_URL` (PostgreSQL / SQLite / MySQL).
- `async_session`: Фабрика асинхронных сессий (`async_sessionmaker[AsyncSession]`) с поддержкой контекстного менеджера (`async with async_session() as db:`).
- `apply_pagination(stmt, page, limit)`: Стандартная утилита пагинации запросов.

### Пример использования
```python
from plugins.db import Base, async_session
from sqlalchemy import select

async def get_records():
    async with async_session() as db:
        result = await db.execute(select(MyModel))
        return result.scalars().all()
```

---

## 2. Плагин аутентификации и авторизации (`plugins.auth`)

Полнофункциональная система аутентификации и разграничения прав доступа с поддержкой Row-Level Security (RLS), сквозного RSA-шифрования, OAuth2 и скользящих сессий.

### Возможности
- **Скользящие сессии (Sliding Expiration)**:
  - Настраиваемый срок жизни сессии через `configure(...)` или переменную окружения (по умолчанию 30 дней).
  - Каждое успешное обновление токена (`login.refresh`) автоматически сдвигает срок действия токена вперед на `session_lifetime_days`.
  - Автоматическая очистка просроченных токенов при авторизации.
  - Контроль лимита одновременных устройств пользователя (`max_active_sessions`, по умолчанию 10).
- **Динамические роли и права в БД (`auth_role`, `auth_role_permission`)**:
  - Роли не захардкожены: таблица `auth_role` позволяет создавать любые роли предметной области (`moderator`, `operator`, `manager`, `inspector`).
  - Связь Many-to-Many: у одного пользователя может быть несколько активных ролей.
  - Матрица прав: таблица `auth_role_permission` задает атомарные флаги доступа к моделям (`can_create`, `can_read`, `can_update`, `can_delete`, `create_global`, `read_global`).
  - При авторизации роли пользователя автоматически привязываются к сокет-сессии, обеспечивая проверку на уровне `@rpc_method(role=...)`.
- **Безопасность на уровне строк (Row-Level Security / RLS)**:
  - Миксины `BasicSecureModel` и `RowSecureModel`.
  - Слушатели событий сессии SQLAlchemy автоматически фильтруют выборки согласно контексту `current_user_ctx`.
  - `system_bypass_ctx`: Контекстный менеджер для выполнения системных и фоновых задач без ограничений RLS.
- **RPC-хендлеры**:
  - `login.get_key`: Генерация эфемерного публичного ключа RSA для шифрования пароля на клиенте.
  - `login.secure`: Дешифрование пароля приватным ключом и авторизация.
  - `login.submit`: Прямая аутентификация по логину/паролю (PBKDF2-SHA256).
  - `login.refresh`: Выпуск новых access токенов и скользящее продление RefreshToken.
  - `login.whoami`: Получение данных текущего пользователя сокета, его ролей и разрешений.
  - `login.register`: Регистрация нового пользователя с валидацией.
  - `login.get_oauth_providers`: Получение списка включенных провайдеров OAuth2 из настроек.
  - `login.oauth_vk`: Вход и регистрация через VK ID (OAuth 2.0 PKCE).
  - `login.oauth_yandex`: Вход и регистрация через Яндекс ID (OAuth 2.0).
  - `auth.logout`: Завершение сессии WebSocket и удаление связанного RefreshToken.
  - `auth.get_sessions`: Просмотр списка активных сессий пользователя (IP, User-Agent, дата входа).
  - `auth.terminate_session`: Дистанционное завершение конкретной сессии.
  - `auth.active_sessions_stream`: Реактивный поток изменений сессий в реальном времени.

### Конфигурация (Code-First)
```python
from core.lib.config import configure

configure(
    database_url="postgresql+asyncpg://user:pass@127.0.0.1:5432/mydb",
    auth={
        "session_lifetime_days": 30,
        "max_active_sessions": 10,
    },
    oauth={
        "vk": {"enabled": True, "client_id": "...", "client_secret": "..."},
        "yandex": {"enabled": True, "client_id": "...", "client_secret": "..."}
    }
)
```

---

---

## 4. Плагин сырых и бинарных WebSocket-сессий (`plugins.raw_ws`)

Предоставляет поддержку специализированных низкоуровневых и бинарных двунаправленных WebSocket-протоколов (например, телеметрия контроллеров, Protobuf, потоковые аудио/видео каналы) по выделенным URL путям в обход стандартного WSRPC JSON-RPC.

### Возможности
- **Изоляция и Zero-Overhead**: Выделенный URL перехватывается до WSRPC, не создавая накладных расходов на JSON-сериализацию.
- **64-битные уникальные ID сессий (Snowflake-style)**: Гарантированное отсутствие коллизий между несколькими воркерами Granian (`--workers N`) и после перезапусков.
- **Явная передача `session_id` в обработчик приёма**: Сигнатура `(session_id, data, session)` обеспечивает немедленный доступ к идентификатору сессии без поиска в контексте.
- **Двунаправленный обмен**: Методы `send_bytes(data: bytes)` и `send_str(data: str)`.
- **Гарантированное отслеживание дисконнекта**: Хуки `@handler.on_connect`, `@handler.on_disconnect` и `session.on_close(...)`.
- **Реестр сессий и рассылка**: `send_to_session(session_id, data)` и `broadcast_raw(data, path=None)`.

### Пример использования
```python
from plugins.raw_ws import raw_ws_route, RawWebSocketSession
from core.logger import logger

@raw_ws_route("/ws/telemetry")
async def on_telemetry(session_id: int, data: bytes, session: RawWebSocketSession):
    # Явный session_id и сырые байты от клиента
    logger.info(f"[Telemetry] Пакет от сессии {session_id}, байт: {len(data)}")
    # Двунаправленный ответ клиенту
    await session.send_bytes(b"ACK")

@on_telemetry.on_connect
async def on_connect(session: RawWebSocketSession):
    logger.info(f"[Telemetry] Устройство подключено: {session.session_id}")

@on_telemetry.on_disconnect
async def on_disconnect(session: RawWebSocketSession):
    logger.warning(f"[Telemetry] Обрыв связи: {session.session_id}")
```

### Подключение в точку входа сервера (`main.py`)
```python
from plugins.raw_ws import dispatch_raw_ws

async def app(scope, proto):
    if scope.proto == "websocket":
        # Плагин перехватывает зарегистрированные роуты (/ws/telemetry и т.д.)
        if await dispatch_raw_ws(scope, proto):
            return

        # Для остальных путей работает стандартный WSRPC
        ws = await proto.accept()
        session = JsonRpcSession(ws, next(GLOBAL_SESSION_COUNTER))
        await session.start()
```

---

## 5. Паттерн фасадов приложений

Прикладные проекты (Agrita, CRM, Showcase) организуют доступ к плагинам через доменные фасады или используют их напрямую:
```python
# Вариант 1: Прямое использование плагинов фреймворка
from plugins.db import Base, async_session
from plugins.auth.models import User
from plugins.raw_ws import raw_ws_route

# Вариант 2: Фасадный реэкспорт внутри приложения (app/system/)
# app/system/db.py
from plugins.db import *

# app/system/auth/models.py
from plugins.auth.models import *

# app/system/auth/handlers.py
from plugins.auth.handlers import *
```
Это позволяет гибко комбинировать ядро, плагины и приложение без дублирования кода.

---

## 6. Живой пример использования

Рабочий пример использования плагинов `plugins.db` и ролевой модели `plugins.auth` доступен в демонстрационном приложении:
- `examples/showcase/server.py`
- `examples/showcase/models.py`
- `examples/showcase/handlers.py`

---

## 7. Официальный реестр плагинов и спецификаций RFC

В следующей таблице зафиксированы официальные плагины-батарейки фреймворка и их стандартизированные RFC-спецификации:

| Имя плагина | Статус | Спецификация RFC | Описание |
| :--- | :--- | :--- | :--- |
| **`plugins.db`** | ✅ Стабилен | Ядро платформы | Асинхронный пул подключений SQLAlchemy 2.0 и декларативный Base |
| **`plugins.auth`** | ✅ Стабилен | Ядро платформы | RBAC, RLS (`RowSecureModel`), OAuth2, скользящие сессии |
| **`plugins.raw_ws`** | ✅ Стабилен | Ядро платформы | Сырые и бинарные двунаправленные WebSocket-сессии с 64-битными ID |
| **`plugins.smart_cache`**| ⚡ В разработке | [RFC 0001](rfc/0001-smart-cache.md) | Реактивный кэш с обратной связью и 0 мс задержкой интерфейса |
| **`plugins.admin`** | 📝 На рассмотрении | [RFC 0003](rfc/0003-reactive-admin-plugin.md) | Реактивная панель администрирования и корпоративный CRUD-движок |
| **`plugins.files`** | ✅ Стабилен | [RFC 0005](rfc/0005-file-storage-and-upload-subsystem.md) | Двухфазный коммит загрузок (2PC) и kernel-level отдача статики |
| **`plugins.broadcast`** | 📝 На рассмотрении | [RFC 0006](rfc/0006-websocket-broadcast-and-event-bus.md) | Высокопроизводительная Zero-Copy рассылка событий и таргетинг |
| **`plugins.gateway`** | 📝 На рассмотрении | [RFC 0007](rfc/0007-http-api-gateway-and-documentation.md) | HTTP API Gateway для WSRPC и авто-генерация документации Swagger |
| **`plugins.discussions`**| 📝 На рассмотрении | [RFC 0008](rfc/0008-threaded-discussions-and-forum.md) | Иерархический форум, вложенные треды и эмодзи-реакции |
| **`plugins.messages`** | 📝 На рассмотрении | [RFC 0009](rfc/0009-direct-messaging-and-chat.md) | Личные сообщения 1-на-1, чат и полиморфные вложения |
| **`plugins.articles`** | 📝 На рассмотрении | [RFC 0010](rfc/0010-knowledge-base-and-articles-cms.md) | База знаний Markdown, FAQ и система управления статьями |

