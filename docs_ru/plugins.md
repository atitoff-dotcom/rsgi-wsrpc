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
- `engine`: Асинхронный движок SQLAlchemy, настраиваемый через `app_settings.yaml` (PostgreSQL / SQLite).
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
  - Настраиваемый срок жизни сессии в `app_settings.yaml` (по умолчанию 30 дней).
  - Каждое успешное обновление токена (`login.refresh`) автоматически сдвигает срок действия токена вперед на `session_lifetime_days`.
  - Автоматическая очистка просроченных токенов при авторизации.
  - Контроль лимита одновременных устройств пользователя (`max_active_sessions`, по умолчанию 10).
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

### Конфигурация (`app_settings.yaml`)
```yaml
auth:
  session_lifetime_days: 30
  max_active_sessions: 10

oauth:
  vk:
    enabled: true
    client_id: "..."
    client_secret: "..."
  yandex:
    enabled: true
    client_id: "..."
    client_secret: "..."
```

---

## 3. Паттерн фасадов приложений

Прикладные проекты (Agrita, CRM, Showcase) организуют доступ к плагинам через доменные фасады или используют их напрямую:
```python
# Вариант 1: Прямое использование плагинов фреймворка
from plugins.db import Base, async_session
from plugins.auth.models import User

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

## 4. Живой пример использования

Рабочий пример использования плагинов `plugins.db` и ролевой модели `plugins.auth` доступен в демонстрационном приложении:
- `examples/showcase/server.py`
- `examples/showcase/models.py`
- `examples/showcase/handlers.py`

