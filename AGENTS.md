# AI Agent Guide: Разработка на фреймворке `rsgi-wsrpc`

> **Инструкция для ИИ-ассистентов (Cursor, Antigravity, Claude, ChatGPT, Windsurf, Copilot)**  
> Этот документ содержит актуальные контракты, архитектурные правила и анти-паттерны для генерации кода на базе фреймворка `rsgi-wsrpc`.

---

## 1. Концепция и Архитектура

`rsgi-wsrpc` — высокопроизводительный реактивный Python-фреймворк:
- **Сетевой уровень:** Rust RSGI сервер **Granian** (не ASGI и не WSGI!).
- **Протокол:** Симметричный **JSON-RPC 2.0 (WSRPC)** поверх постоянного WebSocket-соединения + опциональный HTTP.
- **Сжатие данных:** Табличный формат **RFC 0002 (Tabular Data Compression)** — экономит 40–70% трафика в списках.
- **Безопасность:** По умолчанию гостям разрешены только методы `login.*`. Доступ к остальным требует авторизации или явного флага `public=True`.
- **Эталонный пример:** Живой интерактивный стенд со всеми плагинами находится в [examples/showcase](file:///home/alex/rsgi-wsrpc/examples/showcase).

---

## 2. Быстрый старт: Приложение (`server.py`)

```python
import os
from rsgi_wsrpc import RsgiWsrpcApp, rpc_method, tabular_response, RPCError, UserRole
from rsgi_wsrpc.plugins.broadcast import broadcast_notification

# 1. Инициализация приложения со всеми настройками (Code-First)
app = RsgiWsrpcApp(
    secret_key=os.getenv("SECRET_KEY", "dev-secret-key-change-in-production"),
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///app.db"),
    static_dir="./public",       # Раздача статики через нативный Rust Zero-Copy (proto.response_file)
    index_file="index.html",     # Автоматическая отдача на GET /
    login_rpc="login.",          # Гостям открыты только методы с префиксом login.
    cors=True
)

# 2. Публичный метод (доступен неавторизованным гостям)
@app.rpc("system.ping", public=True)
async def ping():
    return {"status": "pong"}

# 3. Метод с авто-распаковкой kwargs и табличным сжатием
@app.rpc("tasks.list")
@tabular_response(fields=["id", "title", "completed"])
async def list_tasks(limit: int = 100):
    return [
        {"id": 1, "title": "Купить хлеб", "completed": False},
        {"id": 2, "title": "Написать тесты", "completed": True},
    ]

# 4. Защищенный метод только для администраторов
@app.rpc("admin.cleanup", role=UserRole.ADMIN)
async def admin_cleanup():
    await broadcast_notification("system.alert", {"msg": "База очищена"})
    return {"status": "ok"}

# 5. Запуск сервера (workers=1 рекомендуется для in-memory backplane)
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, workers=1)
```

Запуск через CLI:
```bash
granian --rsgi server:app --host 127.0.0.1 --port 8080 --workers 1
```

---

## 3. Правила и контракты объявления RPC-методов

### 3.1. Декоратор `@rpc_method` / `@app.rpc`
```python
from rsgi_wsrpc.core.session import rpc_method, RPCError
from rsgi_wsrpc.core.constants import UserRole

@rpc_method("items.create", role=UserRole.USER, public=False)
async def create_item(session, title: str, count: int = 1):
    # session: текущая сессия сокета (AuthSession при авторизации)
    # Именованные аргументы автоматически извлекаются из JSON-RPC params
    if not title:
        raise RPCError(-32602, "Название не может быть пустым")
    return {"id": 42, "title": title, "count": count}
```

### 3.2. Сигнатуры хендлеров (поддерживаются все варианты):
1. `async def fn(session, params: dict)` — прямой доступ к объекту сессии и словарю параметров.
2. `async def fn(session, title: str, priority: int = 1)` — авто-маппинг kwargs + `session`.
3. `async def fn(title: str, priority: int = 1)` — только именованные параметры из `params`.
4. `async def fn()` — метод без аргументов.

### 3.3. Обработка ошибок (JSON-RPC 2.0 Error)
Для возврата ошибки клиенту используйте `raise RPCError(code, message)`:
- `raise RPCError("Текст ошибки")` → код `-32000` (Server Error).
- `raise RPCError(-32602, "Неверные параметры")` → стандартный код ошибки JSON-RPC.

---

## 4. Табличное сжатие (RFC 0002)

Всегда используйте `@tabular_response` для списков однотипных объектов:
```python
from rsgi_wsrpc.core.tabular import tabular_response

@rpc_method("users.get_all")
@tabular_response(fields=["id", "username", "email", "role"])
async def get_users():
    # Возвращает список словарей или ORM-моделей
    return await fetch_users_from_db()
```
*Эффект:* Превращает `[{"id":1, ...}, {"id":2, ...}]` в `{"$tabular": true, "fields": [...], "rows": [[1, ...], [2, ...]]}`. Клиентский TS/JS SDK распаковывает это прозрачно на лету через `unpackTabular()`.

---

## 5. Smart Cache и инвалидация тегов (RFC 0001)

Для реактивной инвалидации кэша на клиентах при мутациях используйте `@invalidates`:
```python
from rsgi_wsrpc.plugins.smart_cache import invalidates

@rpc_method("topics.delete")
@invalidates(tags=["forum.topics", "forum.category.{category_id}", "forum.topic.{topic_id}"])
async def delete_topic(topic_id: int, category_id: int):
    # Теги со строковыми шаблонами разрешаются автоматически из params/kwargs и result
    return {"status": "ok"}
```
Сервер монотонно увеличивает версию тегов в памяти/БД и рассылает сокетам событие `cache.invalidate`.

---

## 6. Multi-return Потоковый Стриминг (`stream: true`)

Для длительных задач отправляйте промежуточный прогресс без блокировки сокета:
```python
from rsgi_wsrpc.core.session import current_rpc_id_ctx

@app.rpc("analytics.generate")
async def generate_report(session):
    rpc_id = current_rpc_id_ctx.get()
    
    # Отправка промежуточных чанков прогресса
    await session.send_stream_chunk(rpc_id, {"progress": 30, "step": "Сканирование БД"})
    await session.send_stream_chunk(rpc_id, {"progress": 70, "step": "Сжатие"})
    
    # Финальный ответ завершает RPC-запрос
    return {"progress": 100, "report_url": "/reports/12.pdf"}
```

---

## 7. Полнодуплексный Reverse RPC (Сервер &rarr; Клиент)

WSRPC симметричен: сервер может сам отправить запрос клиенту и дождаться ответа:
```python
@app.rpc("client.inspect")
async def inspect_client(session):
    # Сервер отправляет JSON-RPC запрос в браузер
    client_response = await session.send_request("client.get_env", timeout=3.0)
    return {"browser_info": client_response}
```

---

## 8. Рассылки реального времени (Broadcast)

Неблокирующая O(1) рассылка уведомлений всем подключенным сокетам:
```python
from rsgi_wsrpc.plugins.broadcast import broadcast_notification

# Сериализация происходит 1 раз в память, после чего фрейм отправляется всем сокетам
await broadcast_notification("order.updated", {"order_id": 105, "status": "shipped"})
```

---

## 9. Загрузка файлов (Двухфазный коммит 2PC)

Загрузка больших файлов без буферизации в RAM через RSGI HTTP стриминг:
1. `POST /upload?folder_hash=...` — чанки пишутся сразу на диск с O(1) памяти.
2. Проверка прав: эндпоинт `/auth-check-upload` валидирует JWT в заголовке `Authorization: Bearer <JWT>`.
3. Фиксация: WSRPC метод `files.commit(folder_hash="...")` атомарно переносит файлы в постоянное хранилище.

---

## 10. Универсальный реактивный CRUD (`rsgi_wsrpc.plugins.crud`)

Авто-генерация API и встроенная панель управления на `/crud`:
1. Регистрация моделей:
   ```python
   from rsgi_wsrpc.plugins.crud import ModelRegistry
   ModelRegistry.register(Task)
   ```
2. Декларативное описание модели (`class Crud:`):
   ```python
   class Item(Base):
       __tablename__ = "items"
       id: Mapped[int] = mapped_column(Integer, primary_key=True)
       title: Mapped[str] = mapped_column(String(100), info={"label": "Название"})
       class Crud:
           verbose_name = "Элемент"
           verbose_name_plural = "Элементы"
           hidden = {"secret_col"}
           readonly = {"created_at"}
           protected = {"owner_id"}
   ```
3. Контракт методов WSRPC: `crud.schema`, `crud.list` ($tabular), `crud.get`, `crud.create`, `crud.update_cell`, `crud.bulk_update`, `crud.delete`.

---

## 11. SEO & Dynamic Rendering (`rsgi_wsrpc.plugins.seo`)

Автоматическое определение краулеров и отдача SSR HTML с мета-тегами:
```python
from rsgi_wsrpc.plugins.seo import bot_page, render_seo_page

@bot_page("/articles/{slug}")
async def article_seo(slug: str):
    article = await get_article(slug)
    return render_seo_page(
        title=article.title,
        description=article.summary,
        og_image=article.cover_url
    )
```

---

## 12. 🚫 КРИТИЧЕСКИЕ АНТИ-ПАТТЕРНЫ (Anti-Hallucination Guardrails)

1. ❌ **НЕ ИМПОРТИРУЙТЕ `fastapi`, `starlette` или ASGI-модули.**
   - Сервер работает на **Granian RSGI**, где `scope.proto` — `"http"` или `"websocket"`.
2. ❌ **НЕ ПИШИТЕ `await ws.send_json(...)` или `await ws.send_bytes(...)`.**
   - В WSRPC хендлеры просто делают `return dict_or_list`! Фреймворк сам упакует результат в JSON-RPC 2.0 response.
   - Если нужно отправить сообщение в сокет напрямую, используйте безопасный метод `await session.send_str(payload_str)`.
3. ❌ **НЕ ДЕЛАЙТЕ синхронный блокирующий I/O в async-функциях.**
   - Для тяжелых синхронных вызовов (хэширование, RSA, чтение файлов) используйте `await asyncio.to_thread(...)`.
4. ❌ **НЕ ЗАПУСКАЙТЕ `workers > 1` без распределенного бэкплейна.**
   - In-memory структуры (активные сокеты `ACTIVE_SESSIONS_SET`, кэш-версии) изолированы в процессах ОС. Для масштабирования используйте шину `BaseBackplane` (Redis/Postgres).
5. ❌ **НЕ ИСПОЛЬЗУЙТЕ устаревший `asyncio.iscoroutinefunction`.**
   - Используйте `inspect.iscoroutinefunction(func)` (совместимо с Python 3.11–3.14+).
6. ❌ **НЕ ЗАБЫВАЙТЕ про `public=True` для публичных методов.**
   - Если метод должен быть доступен неавторизованному гостю и не начинается с `login.`, всегда указывайте `@rpc_method("name", public=True)`.
7. ❌ **НЕ ЗАБЫВАЙТЕ `@functools.wraps(func)` в кастомных декораторах хендлеров.**
   - При создании декораторов всегда используйте `@wraps(func)`, чтобы механизм unwrapping и auto-mapping сигнатур корректно извлекал параметры.
