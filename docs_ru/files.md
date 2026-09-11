# Подсистема загрузки и хранения файлов (Core File & Upload Architecture)

## 1. Введение и концепция

В реактивном фреймворке **Agrita** работа с файлами построена на гибридной модели:
1. **WSRPC (JSON-RPC 2.0)** выступает координатором транзакций, прав доступа, реактивного прогресса и метаданных.
2. **HTTP POST (RSGI)** используется как потоковая магистраль для передачи сырых бинарных данных.
3. **Nginx** осуществляет высокопроизводительную раздачу подтвержденных файлов без участия Python-воркеров.

> **Главный архитектурный принцип:**  
> Никакого Base64 в WebSocket! Никаких «висячих» файлов на диске при сбоях сети. Загрузка любого количества файлов — это строго атомарная двухфазная транзакция (**Two-Phase Commit**) с гарантированным автоматическим откатом (**Rollback**).

---

## 2. Разделение ответственности (Core vs System vs App)

Подсистема четко разделена на три слоя абстракции:

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. CORE LAYER (Транспорт и координация транзакций)                     │
│    • RSGI Streaming Handler: POST /upload (потоковая запись чанков)    │
│    • UploadTransaction & Coordinator (контроль временной директории)   │
│    • WSRPC Multi-return Stream (отправка прогресса и стадий клиенту)   │
│    • WebSocket Session Lifecycle Hook (авто-откат при дисконнекте)     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 2. SYSTEM PLATFORM LAYER (app/system/files)                            │
│    • Системный реестр файлов: таблица `file_metadata`                  │
│    • Квоты пользователей и аудит дискового пространства                │
│    • Управление доступом: Public (Nginx) vs Protected (Capability/ACL) │
│    • Сборка мусора (Garbage Collector для сиротских файлов)            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 3. APPLICATION MODULES (app/forum, app/articles, app/calculator, ...)  │
│    • Бизнес-сущности: привязка folder_hash к топику, статье, расчету   │
│    • Высокоуровневые хендлеры создания и удаления контента             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Ядро: Координатор транзакций и жизненный цикл

### 3.1. Архитектура двухфазного коммита (2PC)

```
[ Браузер ]                                    [ Сервер (Core RSGI + WSRPC) ]
    │                                                        │
    │ 1. Инициализация (WSRPC requestStream):                │
    │    rpc.requestStream('module.create_item', {           │
    │      files_count: 3, title: "..."                      │
    │    }) ────────────────────────────────────────────────►│ 
    │                                                        │ • Выделяет folder_hash: 'a8F9cK2mX1zL'
    │                                                        │ • Создает /tmp/uploads/a8F9cK2mX1zL/
    │ ◄── Чанк 1: { stage: "ready", folder: "a8F9cK2mX1zL" } │ • Регистрирует транзакцию в сессии
    │                                                        │
    │ 2. Потоковая заливка байтов (HTTP POST):               │
    │    POST /upload?folder=a8F9cK2mX1zL&index=1 ──────────►│ • Пишет 1.webp напрямую на диск
    │ ◄── Чанк 2: { stage: "progress", file_index: 1 } ──────│
    │                                                        │
    │    POST /upload?folder=a8F9cK2mX1zL&index=2 ──────────►│ • Пишет 2.webp напрямую на диск
    │ ◄── Чанк 3: { stage: "progress", file_index: 2 } ──────│
    │                                                        │
    │ 3. ФАЗА ФИКСАЦИИ (Commit):                             │
    │                                                        │ 1. Атомарный перенос:
    │                                                        │    /tmp/.../ -> /files/a8F9cK2mX1zL/ (0 ms)
    │                                                        │ 2. Регистрация в file_metadata
    │                                                        │ 3. Запись бизнес-сущности в БД
    │ ◄── ФИНАЛ: { success: true, item_id: 10 } ─────────────│
```

### 3.2. Автоматический откат при сбое (Rollback on Disconnect)

В модуле управления сессиями (`core/session.py`) каждый активный экземпляр `JsonRpcSession` отслеживает свои незавершенные `UploadTransaction`.

Если клиент закрыл браузер, потерял связь или прервал операцию:
1. Вызывается хук завершения сессии `session.on_disconnect()`.
2. Ядро опрашивает открытые транзакции загрузки.
3. Временная директория `/tmp/uploads/<folder_hash>` немедленно удаляется:
   ```python
   shutil.rmtree(temp_folder_path, ignore_errors=True)
   ```
4. Никаких «полузагруженных» файлов не попадает в постоянное хранилище `/files/`, а база данных остается кристально чистой.

---

## 4. Системный слой: Единый реестр файлов (`file_metadata`)

Все загруженные файлы в системе (независимо от того, принадлежат ли они форуму, статьям, профилям пользователей или калькулятору) регистрируются в системной таблице:

```sql
CREATE TABLE file_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_hash VARCHAR(16) NOT NULL,       -- 12-значный хэш папки бандла
    filename VARCHAR(255) NOT NULL,          -- Имя на диске: '1.webp', 'chart.png'
    original_name VARCHAR(512) NOT NULL,     -- Исходное имя: 'Поле_Север_2026.png'
    size INTEGER NOT NULL,                   -- Размер в байтах
    mime_type VARCHAR(128) NOT NULL,         -- 'image/webp', 'application/pdf'
    sha256 VARCHAR(64),                      -- Хэш содержимого (дедупликация и целостность)
    owner_id INTEGER NOT NULL,               -- ID пользователя-владельца
    is_public BOOLEAN NOT NULL DEFAULT 1,    -- 1: прямая статика Nginx, 0: защищенный доступ
    download_token VARCHAR(512),             -- Capability токен для приватного скачивания
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_file_folder ON file_metadata (folder_hash);
CREATE INDEX idx_file_owner ON file_metadata (owner_id);
```

### Задачи системного реестра:
1. **Квоты пользователей**: мгновенный подсчет занятого места `SELECT SUM(size) FROM file_metadata WHERE owner_id = :uid`.
2. **Аудит и Garbage Collection**: возможность фоновым скриптом сопоставить физические папки на диске с записями в реестре и удалить сиротские файлы.
3. **Восстановление оригинальных имен**: сохранение красивого имени файла при скачивании пользователем через заголовок `Content-Disposition`.
4. **Контроль прав (Capability Tokens)**: генерация временных подписанных токенов доступа к приватным документам.

---

## 5. Раздача файлов через Nginx (Download Flow)

### 5.1. Публичные файлы (`is_public = 1`)
Файлы раздаются веб-сервером Nginx напрямую из боевой папки без обращения к Python-процессам:

```nginx
location /files/ {
    alias /home/alex/agrita-stage/files/;
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    access_log off;
    sendfile on;
    tcp_nopush on;
}
```

### 5.2. Защищенные файлы (`is_public = 0`)
Для приватных файлов Nginx использует механизм `X-Accel-Redirect`:
1. Запрос на скачивание приходит в легкий RSGI-эндпоинт с токеном.
2. Сервер проверяет права и возвращает пустой HTTP-ответ с заголовком:
   `X-Accel-Redirect: /internal_files/<folder_hash>/<filename>`
3. Nginx отдает файл клиенту на максимальной скорости ядра ОС.

---

## 6. Пример использования в бизнес-модуле

Разработчику бизнес-модуля (например, тикетов техподдержки или калькулятора) не требуется реализовывать протокол загрузки заново.

```python
from core.session import rpc_method
from app.system.files.service import FileStorageService

@rpc_method("support.create_ticket")
async def create_ticket(session, title: str, description: str, files_count: int = 0):
    user = session.user
    
    # 1. Открываем контекст транзакции загрузки
    async with session.begin_upload(files_count=files_count, owner_id=user["user_id"]) as tx:
        # Сообщаем клиенту, что сервер ждет файлы
        yield {"stage": "upload_ready", "folder_hash": tx.folder_hash}
        
        # Ждем загрузки всех файлов через HTTP POST /upload
        await tx.wait_completed()
        
        # 2. Фиксируем файлы в постоянном хранилище и системном реестре
        saved_files = await tx.commit()
        
        # 3. Сохраняем тикет в БД модуля
        ticket = Ticket(
            title=title,
            description=description,
            author_id=user["user_id"],
            attachments_folder=tx.folder_hash
        )
        db.add(ticket)
        await db.commit()
        
        # Финальный ответ клиенту
        return {"ticket_id": ticket.id, "folder_hash": tx.folder_hash}
```

---

## 7. Преимущества для архитектуры фреймворка

| Характеристика | Традиционный подход (REST Multipart / Base64) | Архитектура Agrita Core Upload |
| :--- | :--- | :--- |
| **Память (RAM)** | Загрузка всего файла в буфер процесса | Потоковая запись чанков на диск O(1) RAM |
| **Сбои сети** | Висячие файлы на диске, засорение мусором | Автоматический откат при дисконнекте WebSocket |
| **Реактивность** | Опрос статуса полингом (Polling) | Прямой мультиретурн WSRPC (`requestStream`) |
| **Раздача** | Нагрузка на воркеры бэкенда | 100% разгрузка (Nginx Direct Alias + `sendfile`) |
| **Централизация** | Каждый модуль хранит файлы как попало | Единый системный реестр `file_metadata` |
