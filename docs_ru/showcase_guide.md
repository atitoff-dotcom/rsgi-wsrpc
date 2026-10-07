# Архитектурное руководство и витрина возможностей rsgi-wsrpc

> **Примечание:** Данный документ автоматически сгенерирован из единого источника правды интерактивной витрины (`examples/showcase/content/showcase_docs.json`). Все приведенные примеры и RPC-контракты полностью рабочие.

---

## Оглавление

- [1. Архитектура Rust RSGI и протокол JSON-RPC 2.0](#overview)
- [2. Табличное сжатие данных списков (RFC 0002)](#tabular)
- [3. Smart Cache и инвалидация тегов (RFC 0001)](#cache)
- [4. Универсальный реактивный CRUD и Админ-панель](#crud)
- [5. Multi-return Потоковый Стриминг (stream: true)](#stream)
- [6. Симметричный Reverse RPC (Сервер → Браузер)](#reverse-rpc)
- [7. Realtime Broadcast (Рассылки в реальном времени)](#broadcast)
- [8. Загрузка файлов: Двухфазный коммит (2PC)](#files)
- [9. Роли, права и безопасность (RLS)](#rbac)
- [10. SEO и рендеринг для поисковых ботов](#seo)

---

<a id="overview"></a>
## ⚡ 1. Архитектура Rust RSGI и протокол JSON-RPC 2.0

> **Спецификация:** `Granian RSGI • Zero-Overhead`

Высокопроизводительный нативный сервер Granian RSGI без накладных расходов WSGI/ASGI. Одно постоянное WebSocket-соединение для всех запросов.

**Архитектурная суть:**
В отличие от традиционного REST, требующего постоянных TCP-рукопожатий, TLS-согласований и парсинга заголовков HTTP на каждый чих, браузер держит одно постоянное соединение. Любой RPC-вызов обрабатывается за 0.2–1 мс.

### Бэкенд (Python)
```python
@app.rpc("system.ping", public=True)
async def ping():
    return {"status": "pong", "server_time": time.time()}
```

### Клиент (TypeScript / JavaScript)
```typescript
import { rpc } from '@wsrpc/wsrpc';

const response = await rpc.call('system.ping');
console.log(response); // { status: 'pong', server_time: ... }
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
--> {"jsonrpc": "2.0", "id": 1, "method": "system.ping", "params": {}}
<-- {"jsonrpc": "2.0", "id": 1, "result": {"status": "pong", "server_time": 1775546000.12}}
```

---

<a id="tabular"></a>
## 📊 2. Табличное сжатие данных списков (RFC 0002)

> **Спецификация:** `RFC 0002 • 40–70% Compression`

Устраняет дублирование JSON-ключей в массивах однотипных объектов. Имена колонок передаются один раз, а строки — компактной 2D-матрицей.

**Архитектурная суть:**
Декоратор @tabular_response экономит от 40% до 70% сетевого трафика. Клиентский SDK прозрачно распаковывает матрицу в обычный массив объектов через unpackTabular().

### Бэкенд (Python)
```python
@app.rpc("tasks.list", public=True)
@tabular_response(fields=["id", "title", "completed", "priority"])
async def list_tasks():
    # Возвращает стандартный список словарей или ORM моделей
    return await fetch_tasks_from_db()
```

### Клиент (TypeScript / JavaScript)
```typescript
const res = await rpc.call('tasks.list');
// Клиент распаковывает матрицу в привычные объекты:
const items = unpackTabular(res.result);
// [{ id: 1, title: 'Задача 1', completed: true, ... }]
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
--> {"jsonrpc": "2.0", "id": 2, "method": "tasks.list"}
<-- {"jsonrpc": "2.0", "id": 2, "result": {"$tabular": true, "fields": ["id", "title", "completed"], "rows": [[1, "Task 1", true], [2, "Task 2", false]]}}
```

---

<a id="cache"></a>
## 🔄 3. Smart Cache и инвалидация тегов (RFC 0001)

> **Спецификация:** `RFC 0001 • Invalidation Bus`

Монотонные версии тегов сущностей в памяти и БД. Сервер проактивно уведомляет клиентов о необходимости сброса кэша при мутациях.

**Архитектурная суть:**
При вызове метода с декоратором @invalidates сервер инкрементирует версию затронутых тегов и рассылает сокетам событие cache.invalidate. Клиенты мгновенно обновляют устаревшие срезы данных.

### Бэкенд (Python)
```python
@app.rpc("tasks.complete")
@invalidates(tags=["tasks.list", "task.{task_id}"])
async def complete_task(task_id: int):
    await mark_completed(task_id)
    return {"status": "ok", "task_id": task_id}
```

### Клиент (TypeScript / JavaScript)
```typescript
rpc.on('cache.invalidate', (data) => {
  console.log('Инвалидированы теги:', data.tags);
  // Очистка локального стора и рефетч
});
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
<-- {"jsonrpc": "2.0", "method": "cache.invalidate", "params": {"tags": ["tasks.list", "task.42"], "version": 105}}
```

---

<a id="crud"></a>
## 🗄️ 4. Универсальный реактивный CRUD и Админ-панель

> **Спецификация:** `Svelte 5 • Capability Access`

Автоматическая генерация API и встроенная панель управления на Svelte 5. Поддержка связей Many-to-Many, ForeignKey и фильтрации.

**Архитектурная суть:**
Достаточно зарегистрировать модель SQLAlchemy через ModelRegistry.register(MyModel), и методы crud.schema, crud.list ($tabular), crud.get, crud.create, crud.update_cell и crud.delete становятся доступны мгновенно.

### Бэкенд (Python)
```python
from rsgi_wsrpc.plugins.crud import ModelRegistry

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))

ModelRegistry.register(Task)
```

### Клиент (TypeScript / JavaScript)
```typescript
const schema = await rpc.call('crud.schema', { model: 'Task' });
const list = await rpc.call('crud.list', { model: 'Task', page: 1, page_size: 50 });
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
--> {"jsonrpc": "2.0", "id": 4, "method": "crud.update_cell", "params": {"model": "Task", "id": 1, "field": "completed", "value": true}}
<-- {"jsonrpc": "2.0", "id": 4, "result": {"success": true, "id": 1}}
```

---

<a id="stream"></a>
## 🌊 5. Multi-return Потоковый Стриминг (stream: true)

> **Спецификация:** `Multi-Return • Non-Blocking`

Отправка промежуточных результатов и прогресса длительных операций без блокировки сокета и без дробления на polling-запросы.

**Архитектурная суть:**
Метод session.send_stream_chunk(rpc_id, chunk) отправляет клиенту промежуточные события, помечаемые флагом stream: true. Финальный return завершает общий RPC-запрос.

### Бэкенд (Python)
```python
@app.rpc("analytics.generate")
async def generate_analytics(session):
    rpc_id = current_rpc_id_ctx.get()
    for i in range(1, 4):
        await asyncio.sleep(0.5)
        await session.send_stream_chunk(rpc_id, {"step": i, "progress": i * 25})
    return {"progress": 100, "report_url": "/reports/summary.pdf"}
```

### Клиент (TypeScript / JavaScript)
```typescript
await rpc.call('analytics.generate', {}, {
  onChunk: (chunk) => console.log('Прогресс:', chunk.progress)
});
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
<-- {"jsonrpc": "2.0", "id": 5, "stream": true, "result": {"step": 1, "progress": 25}}
<-- {"jsonrpc": "2.0", "id": 5, "result": {"progress": 100, "report_url": "/reports/summary.pdf"}}
```

---

<a id="reverse-rpc"></a>
## 🪞 6. Симметричный Reverse RPC (Сервер → Браузер)

> **Спецификация:** `Full Duplex • Browser RPC`

WSRPC полностью симметричен: бэкенд может сам отправить JSON-RPC запрос в браузер и асинхронно дождаться ответа.

**Архитектурная суть:**
Сервер вызывает метод браузера через session.send_request('client.inspect', timeout=3.0). Браузер выполняет вычисление и возвращает ответ серверу.

### Бэкенд (Python)
```python
@app.rpc("admin.inspect_client")
async def inspect_client(session):
    browser_env = await session.send_request("client.get_env", timeout=5.0)
    return {"inspected": browser_env}
```

### Клиент (TypeScript / JavaScript)
```typescript
rpc.register('client.get_env', () => {
  return { userAgent: navigator.userAgent, screen: `${screen.width}x${screen.height}` };
});
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
<-- {"jsonrpc": "2.0", "id": "srv-1", "method": "client.get_env", "params": {}}
--> {"jsonrpc": "2.0", "id": "srv-1", "result": {"userAgent": "Mozilla..."}}
```

---

<a id="broadcast"></a>
## 📢 7. Realtime Broadcast (Рассылки в реальном времени)

> **Спецификация:** `O(1) Broadcast • Zero-Copy`

Мгновенная O(1) рассылка уведомлений всем подключенным сокетам. Сериализация в JSON выполняется ровно 1 раз в памяти.

**Архитектурная суть:**
Функция broadcast_notification() сериализует сообщение один раз через orjson, после чего Rust-движок Granian рассылает байты всем сокетам без лишней нагрузки на Python-интерпретатор.

### Бэкенд (Python)
```python
from rsgi_wsrpc.plugins.broadcast import broadcast_notification

@app.rpc("alerts.publish")
async def publish_alert(message: str):
    await broadcast_notification("system.alert", {"message": message, "time": time.time()})
    return {"status": "broadcast_sent"}
```

### Клиент (TypeScript / JavaScript)
```typescript
rpc.on('system.alert', (data) => {
  console.warn('Получено системное оповещение:', data.message);
});
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
<-- {"jsonrpc": "2.0", "method": "system.alert", "params": {"message": "Server maintenance in 5 min", "time": 1775546200}}
```

---

<a id="files"></a>
## 📁 8. Загрузка файлов: Двухфазный коммит (2PC)

> **Спецификация:** `Granian RSGI • Streaming 2PC`

Потоковая загрузка больших файлов без буферизации в оперативной памяти и атомарная фиксация через WSRPC.

**Архитектурная суть:**
1-я фаза: Чанки пишутся напрямую на диск в транзакционную папку POST /upload с O(1) памяти. 2-я фаза: WSRPC-метод files.commit атомарно переносит файлы в постоянное хранилище.

### Бэкенд (Python)
```python
# Фаза 1: HTTP-стриминг чанков на диск
# POST /upload?folder_hash=abc123

# Фаза 2: WSRPC атомарный коммит
@app.rpc("files.commit")
async def commit_files(folder_hash: str):
    saved_files = await finalize_folder_upload(folder_hash)
    return {"status": "committed", "files": saved_files}
```

### Клиент (TypeScript / JavaScript)
```typescript
// 1. Загрузка через FormData стримом
await fetch(`/upload?folder_hash=${hash}`, { method: 'POST', body: formData });
// 2. Атомарная фиксация через WebSocket
const res = await rpc.call('files.commit', { folder_hash: hash });
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
--> POST /upload?folder_hash=abc123 (Binary Stream)
<-- HTTP/1.1 200 OK {"uploaded": 3}
--> {"jsonrpc": "2.0", "id": 8, "method": "files.commit", "params": {"folder_hash": "abc123"}}
```

---

<a id="rbac"></a>
## 🔐 9. Роли, права и безопасность (RLS)

> **Спецификация:** `RLS Engine • SQLAlchemy 2.0`

Гибридный контроль доступа: динамические роли в БД, разделение прав на CRUD и RPC, Row-Level Security по командам и владельцам.

**Архитектурная суть:**
По умолчанию гостям открыт только login.* (Default Deny). Модели RowSecureModel содержат team_id и creator_id, гарантируя, что пользователи видят только данные своей команды.

### Бэкенд (Python)
```python
class Task(RowSecureModel):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(100))
    # id, creator_id, team_id, created_at встроены в RowSecureModel!

# В handlers.py:
@rpc_method("tasks.create")
async def create_task(session, title: str):
    check_permissions("create", "Task")
    # Права проверяются на уровне ORM
```

### Клиент (TypeScript / JavaScript)
```typescript
const me = await rpc.call('auth.me');
console.log(me.role, me.permissions);
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
--> {"jsonrpc": "2.0", "id": 9, "method": "tasks.list", "params": {"only_mine": true}}
<-- {"jsonrpc": "2.0", "id": 9, "result": {"$tabular": true, "rows": [...]}}
```

---

<a id="seo"></a>
## 🤖 10. SEO и рендеринг для поисковых ботов

> **Спецификация:** `Bot Detector • SSR Crawler`

Автоматическое распознавание краулеров поисковых систем и отдача статического SSR HTML с мета-тегами OpenGraph и JSON-LD.

**Архитектурная суть:**
Поисковые краулеры (Googlebot, Яндекс, Telegram, Discord) мгновенно получают чистый HTML с разметкой, а живые пользователи получают реактивный SPA без перезагрузок страниц.

### Бэкенд (Python)
```python
from rsgi_wsrpc.plugins.seo import bot_page, render_seo_page

@bot_page("/tasks/{task_id}")
async def task_seo(task_id: int):
    task = await get_task_by_id(task_id)
    return render_seo_page(
        title=task.title,
        description="Просмотр задачи на rsgi-wsrpc",
        og_image="/static/og.png"
    )
```

### Клиент (TypeScript / JavaScript)
```typescript
// Браузер работает как обычный SPA:
window.history.pushState({}, '', '/tasks/42');
```

### Сетевой протокол (JSON-RPC 2.0 Wire Frame)
```json
GET /tasks/42 User-Agent: Googlebot/2.1
HTTP/1.1 200 OK Content-Type: text/html
<html><head><title>Task 42</title><meta property="og:title" content="Task 42"></head>...
```

---
