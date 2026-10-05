# Подсистема универсального реактивного CRUD (Core Reactive CRUD & Admin Architecture)

## 1. Введение и концепция

Плагин **`rsgi_wsrpc.plugins.crud`** — официальная батарейка фреймворка `rsgi-wsrpc`, реализующая реактивный, типобезопасный и расширяемый слой администрирования данных на базе SQLAlchemy 2.0 (async).

В отличие от традиционных монолитных админок (Django Admin, Flask-Admin), плагин спроектирован по принципам современных распределенных систем:

1. **Симметричный транспорт WSRPC (JSON-RPC 2.0):**  
   Все операции (выборка, создание, редактирование ячеек, удаление) выполняются по постоянному WebSocket-соединению с ультранизкими задержками (<1 мс).
2. **RFC 0002 Tabular Data Compression:**  
   Списки записей передаются в компактном матричном формате (`fields` + `rows`), что сокращает объем передаваемого JSON на **40–70%** без потери читаемости.
3. **Capability-Based Access Control (Zero Hardcoded Roles):**  
   В ядре плагина отсутствуют жестко закодированные имена ролей (`admin`, `editor`, `lead`, `viewer`). Доступ управляется проверкой атомарных прав (`{model}:read`, `{model}:create`, `{model}:update`, `{model}:delete`, `{model}:transfer`, `*`) и SQL-предикатами.
4. **Абстракция окружения (`IdentityProvider`):**  
   Плагин полностью изолирован от структуры таблиц пользователей, команд и организационной иерархии конкретного проекта. Вся информация о контексте сессии поступает через стандартизированный протокол.
5. **Единый предикат безопасности (`AccessPolicy.scope`):**  
   Ограничения RLS накладываются непосредственно на уровне SQL-запросов (`WHERE id = :id AND <scope>`), исключая race conditions и уязвимости обхода прав.
6. **Реактивный кэш (`cache.patch`):**  
   При любых мутациях сокеты получают неблокирующее уведомление о факте изменения данных без раскрытия значений колонок неавторизованным клиентам.
7. **Встроенный автономный UI (Svelte 5 Runes):**  
   Готовая к работе одностраничная панель управления на современной дизайн-системе (светлая и темно-серая темы), раздаваемая через нативный RSGI Zero-Copy (`proto.response_file`).

---

## 2. Архитектура и поток данных

```
┌────────────────────────────────────────────────────────────────────────┐
│                        КЛИЕНТСКИЙ УРОВЕНЬ                              │
│   • Standalone SPA (/crud, /admin) на Svelte 5 Runes                   │
│   • Кастомный интерфейс проекта (GenericDataGrid.svelte)               │
│   • WSRPC Client: вызовы crud.* + прослушивание cache.patch            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ WebSocket / JSON-RPC 2.0
┌──────────────────────────────────▼─────────────────────────────────────┐
│                 ТРАНСПОРТНЫЙ УРОВЕНЬ (WSRPC Handlers)                  │
│   crud.schema       crud.list ($tabular)     crud.get                  │
│   crud.create       crud.update_cell         crud.bulk_update          │
│   crud.delete       GET /crud/* (Static Zero-Copy RSGI)                │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                       ЯДРО БЕЗОПАСНОСТИ И RLS                          │
│   1. IdentityProvider: session -> AccessContext (user_id, perms, teams)│
│   2. AccessPolicy.scope: генерация SQL WHERE (owner_id, team_id, ...)  │
│   3. AccessPolicy.allowed_fields: фильтрация колонок (read-only/prot.) │
│   4. Type Coercion & Security Guard: валидация типов + срез секретов   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                     БАЗА ДАННЫХ (SQLAlchemy 2.0 Async)                 │
│   DeclarativeBase Models + class Crud: (Meta, Widgets, Hidden)         │
│   PostgreSQL / SQLite / MySQL через единый async_sessionmaker          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Быстрый старт: подключение в проект

### Шаг 1. Импорт и авто-обнаружение моделей
В точке входа бэкенда (`server.py` или `main.py`) зарегистрируйте модели в реестре CRUD:

```python
from rsgi_wsrpc import RsgiWsrpcApp
from rsgi_wsrpc.plugins.db import Base
# 1. Импорт плагина автоматически регистрирует WSRPC-методы crud.* и роуты /crud
import rsgi_wsrpc.plugins.crud as crud

# 2. Сканирование моделей приложения
crud.ModelRegistry.auto_discover(Base)

app = RsgiWsrpcApp(
    database_url="postgresql+asyncpg://user:pass@localhost:5432/app_db",
    cors=True
)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
```

После старта сервера:
- RPC-методы `crud.*` готовы к обработке вызовов по WebSocket.
- Автономный интерфейс доступен в браузере по адресу `http://127.0.0.1:8080/crud/` (или `/admin/`).

---

## 4. Декларативное описание моделей (`class Crud:`)

Настройки отображения и политик задаются прямо внутри SQLAlchemy-модели через вложенный класс `Crud` и атрибут `column.info`.

### Пример описания модели:
```python
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Integer, String, Boolean, DateTime, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from rsgi_wsrpc.plugins.db import Base

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Виджеты настраиваются через info={"label": "...", "widget": "..."}
    title: Mapped[str] = mapped_column(
        String(255), 
        nullable=False,
        info={"label": "Название заказа"}
    )
    
    amount: Mapped[float] = mapped_column(
        Numeric(12, 2), 
        default=0.0,
        info={"label": "Сумма, ₽", "widget": "money"}
    )
    
    is_completed: Mapped[bool] = mapped_column(
        Boolean, 
        default=False,
        info={"label": "Завершен"}
    )

    # Поля владения и аудита
    creator_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_id: Mapped[int] = mapped_column(Integer, index=True)
    team_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Внешние ключи автоматически резолвятся в метаданных схемы
    contract_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stored_files.id", ondelete="SET NULL"),
        nullable=True,
        info={"label": "Договор", "widget": "file"}
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # --- Декларативная конфигурация CRUD ---
    class Crud:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        
        # Поля, исключаемые из выдачи фронтенду (не видны в схеме и списке)
        hidden = {"internal_notes"}
        
        # Поля только для чтения (запрещены к изменению через update_cell)
        readonly = {"created_at", "updated_at", "creator_id"}
        
        # Защищенные поля: требуют специального права `{model}:transfer` для смены
        protected = {"owner_id", "team_id"}
```

### Безусловная защита конфиденциальных данных:
Поля, имена которых соответствуют шаблонам:
`*password*`, `*_hash`, `*secret*`, `*token*`, `*private_key*`
**автоматически и принудительно помечаются `hidden=True`**. Они никогда не отдаются в `crud.schema`, исключаются из выборок `crud.list` и блокируются в `crud.get`.

---

## 5. Интеграция с авторизацией проекта (`IdentityProvider`)

Плагин поставляется со стандартным `DefaultIdentityProvider`, который извлекает пользователя из `current_user_ctx` сессии WSRPC.

Если в проекте используется собственная ролевая модель, корпоративное замещение сотрудников или команды, реализуйте интерфейс `IdentityProvider`:

```python
from typing import Optional, Set, Any
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from rsgi_wsrpc.plugins.crud import IdentityProvider, set_identity_provider

class AppIdentityProvider:
    """Адаптер авторизации проекта для CRUD-плагина."""

    def user_id(self, session: Any) -> Optional[int]:
        """Извлекает ID авторизованного пользователя из сессии сокета."""
        return getattr(session, "uid", None)

    def user_name(self, session: Any) -> str:
        """Отображаемое имя (для логов аудита cache.patch)."""
        return getattr(session, "user_name", "Сотрудник")

    def is_superuser(self, user_id: Optional[int]) -> bool:
        """Суперпользователь имеет неограниченный доступ ко всем данным."""
        return check_is_admin(user_id)

    def has_permission(self, user_id: Optional[int], perm: str) -> bool:
        """
        Проверка атомарного права доступа (capability).
        perm может быть: 'Order:read', 'Order:update', 'Order:transfer', '*'
        """
        return permissions_registry.has_access(user_id, perm)

    async def effective_user_ids(self, user_id: int, model_name: str, db: AsyncSession) -> Set[int]:
        """
        Возвращает множество ID пользователей, чьи записи текущий пользователь
        имеет право просматривать и обрабатывать (сам пользователь + активные замещения).
        """
        substitutions = await fetch_active_delegations(user_id, model_name, db)
        return {user_id}.union(substitutions)

    async def user_team_ids(self, user_id: int, db: AsyncSession) -> Set[int]:
        """Множество ID команд/отделов, в которые входит пользователь."""
        return await fetch_user_teams(user_id, db)

    async def primary_team_id(self, user_id: int, db: AsyncSession) -> Optional[int]:
        """Основная команда (подставляется по умолчанию при создании записей)."""
        return await fetch_primary_team(user_id, db)

# Регистрация провайдера на старте приложения
set_identity_provider(AppIdentityProvider())
```

---

## 6. Спецификация WSRPC API (`crud.*`)

Все вызовы осуществляются по протоколу JSON-RPC 2.0 через WebSocket.

### 6.1. `crud.schema` — Метаданные моделей
Возвращает схему всех доступных текущему пользователю моделей либо одной конкретной модели с вычисленными флагами прав (`can_read`, `can_create`, `can_update`, `can_delete`, `row_level_only`).

*Запрос:*
```json
{"jsonrpc": "2.0", "id": 1, "method": "crud.schema", "params": {"model": "Order"}}
```

*Ответ:*
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "model": {
      "key": "Order",
      "verbose_name": "Заказ",
      "verbose_name_plural": "Заказы",
      "is_row_secure": true,
      "is_archivable": false,
      "permissions": {
        "can_read": true,
        "can_create": true,
        "can_update": true,
        "can_delete": false,
        "row_level_only": true
      },
      "fields": [
        {"name": "id", "type": "integer", "label": "ID", "primary_key": true, "editable": false},
        {"name": "title", "type": "string", "label": "Название заказа", "editable": true},
        {"name": "amount", "type": "decimal", "label": "Сумма, ₽", "widget": "money", "editable": true},
        {"name": "owner_id", "type": "integer", "label": "Ответственный", "protected": true, "editable": false}
      ]
    }
  }
}
```

---

### 6.2. `crud.list` — Выборка данных ($tabular)
Выполняет серверную пагинацию, сортировку, поиск с экранированием спецсимволов и точную фильтрацию. Результат упакован по стандарту RFC 0002.

*Запрос:*
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "crud.list",
  "params": {
    "model": "Order",
    "page": 1,
    "page_size": 25,
    "sort_field": "id",
    "sort_dir": "desc",
    "search": "Поставка",
    "filters": {"is_completed": false},
    "show_archived": false
  }
}
```

*Ответ ($tabular format):*
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "total": 142,
    "page": 1,
    "page_size": 25,
    "$tabular": true,
    "fields": ["id", "title", "amount", "is_completed", "owner_id"],
    "rows": [
      [105, "Поставка оборудования", "1250000.00", false, 12],
      [104, "Поставка комплектующих", "48200.50", false, 7]
    ]
  }
}
```

---

### 6.3. `crud.get` — Детальная карточка записи
Возвращает полную запись по первичному ключу с обязательной валидацией RLS-предиката.

*Запрос:*
```json
{"jsonrpc": "2.0", "id": 3, "method": "crud.get", "params": {"model": "Order", "id": 105}}
```

*Ответ:*
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "record": {
      "id": 105,
      "title": "Поставка оборудования",
      "amount": "1250000.00",
      "is_completed": false,
      "owner_id": 12,
      "created_at": "2026-10-05T10:15:00+00:00"
    }
  }
}
```

---

### 6.4. `crud.update_cell` — Быстрое точечное редактирование
Атомарно обновляет единственное поле записи. Поддерживает строгую типизацию (`coerce_value`). При попытке записать строку в целое число возвращается стандартная ошибка `-32602`.

*Запрос:*
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "crud.update_cell",
  "params": {
    "model": "Order",
    "id": 105,
    "field": "amount",
    "value": "1300000"
  }
}
```

*Ответ:*
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {"success": true, "field": "amount", "value": 1300000.0}
}
```

---

### 6.5. `crud.create` — Создание записи
Создает объект с авто-проставлением полей аудита (`creator_id = текущий пользователь`, `owner_id`, `created_at`). Поддерживает создание от имени замещаемого сотрудника (`acting_for_user_id`).

*Запрос:*
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "method": "crud.create",
  "params": {
    "model": "Order",
    "data": {
      "title": "Новый контракт",
      "amount": 250000
    },
    "acting_for_user_id": 7
  }
}
```

*Ответ:*
```json
{
  "jsonrpc": "2.0",
  "id": 5,
  "result": {"success": true, "id": 106}
}
```

---

### 6.6. `crud.bulk_update` — Пакетные действия
Массовая модификация или архивация набора строк в рамках одной транзакции (ограничение до 500 записей за вызов).

*Запрос:*
```json
{
  "jsonrpc": "2.0",
  "id": 6,
  "method": "crud.bulk_update",
  "params": {
    "model": "Order",
    "ids": [101, 102, 103],
    "patch": {"is_completed": true}
  }
}
```

---

### 6.7. `crud.delete` — Удаление записи
Удаляет запись с проверкой прав (суперпользователь либо владелец записи при наличии права `{model}:delete`).

*Запрос:*
```json
{"jsonrpc": "2.0", "id": 7, "method": "crud.delete", "params": {"model": "Order", "id": 106}}
```

---

## 7. Реактивные уведомления (`cache.patch`)

При любых успешных мутациях (`create`, `update_cell`, `bulk_update`, `delete`) сервер отправляет в активные сокеты событие `cache.patch`:

```json
{
  "jsonrpc": "2.0",
  "method": "cache.patch",
  "params": {
    "model": "Order",
    "id": 105,
    "kind": "updated",
    "by_user": "Иванов И.И."
  }
}
```

**Безопасность:** В уведомлении передаются только метаданные события. Значения колонок не раскрываются, предотвращая утечку закрытой информации между клиентами с разными уровнями доступа. Заинтересованный клиент дочитывает запись через RLS-защищенный вызов `crud.get`.

---

## 8. Автономная веб-панель управления (Standalone UI)

Плагин включает встроенный SPA-интерфейс, скомпилированный в `rsgi_wsrpc/plugins/crud/static/`.

### Возможности интерфейса:
- **Zero Configuration:** работает сразу при подключении плагина, автоматически строя форму и таблицу по схеме `crud.schema`.
- **Инлайн-редактирование:** мгновенное сохранение ячеек по Enter / клику.
- **Поддержка $tabular:** клиент на лету распаковывает сжатые матричные данные.
- **Двухрежимная тема:** автоматическое определение системной темы, быстрое переключение «☀️ Светлая / 🌙 Темно-серая (#18191d)» с запоминанием в `localStorage`.
- **Реактивность:** обновление данных в реальном времени при получении `cache.patch`.
- **Zero-Copy RSGI раздача:** файлы отдаются ядром Granian на Rust через `proto.response_file` с валидацией Content-Type, кешированием `immutable` и защитой от Path Traversal.

---

## 9. Чек-лист интеграции в существующий проект (на примере PL3_2)

1. **Установка пакета:** убедитесь, что `rsgi-wsrpc` обновлен до версии с плагином CRUD (`pip install -e /path/to/rsgi-wsrpc`).
2. **Регистрация провайдера:** создайте класс-адаптер `Pl3IdentityProvider`, реализующий протокол `IdentityProvider`, и вызовите `set_identity_provider(Pl3IdentityProvider())`.
3. **Авто-обнаружение моделей:** вызовите `ModelRegistry.auto_discover(Base)`.
4. **Обратная совместимость (при необходимости):** если клиентский код проекта использует старые имена методов `admin.*`, добавьте в проект алиасы, делегирующие выполнение в `handle_crud_*`.
5. **Валидация тестами:** запустите тестовый сьют `pytest test/admin/` и проверку сборки фронтенда `npm run check && npm run build`.
