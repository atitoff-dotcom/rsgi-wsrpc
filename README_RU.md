# rsgi-wsrpc

[![Лицензия: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![RSGI: Granian](https://img.shields.io/badge/engine-Rust%20Granian%20RSGI-orange.svg)](https://github.com/emmett-framework/granian)

[🇬🇧 Read in English (README.md)](README.md)

> **«Всё, чем должен был стать Django, и всё, о чем забыл FastAPI»**  
> Реактивный полнофункциональный Python-фреймворк на базе **Rust (Granian RSGI)** с симметричной шиной **WSRPC (JSON-RPC 2.0)**, встроенной базой данных, авторизацией и транзакционной двухфазной загрузкой файлов.

---

## ⚡ Почему rsgi-wsrpc?

* **Отклик 1–3 мс**: одно постоянное мультиплексированное WebSocket-соединение вместо постоянных рукопожатий HTTP REST.
* **Сетевой движок на Rust**: работает поверх Granian RSGI — максимальная пропускная способность без ограничений GIL.
* **Симметричный протокол**: и клиент, и сервер могут вызывать RPC-методы друг друга и отправлять Push-уведомления.
* **Нативный мультиретурн (`stream: true`)**: потоковая передача прогресса тяжелых вычислений прямо в сокет без стороннего Redis.
* **Двухфазная загрузка файлов (Two-Phase Commit)**: потоковый прием чанков с расходом **O(1) RAM**, автоматический откат (удаление мусора) при обрыве связи и Nginx Zero-Copy раздача.
* **Батарейки включены**: преднастроенная асинхронная БД (SQLite / PostgreSQL), авторизация по JWT + RefreshToken, разграничение прав и Row-Level Security.

---

## 🚀 Быстрый старт

### 1. Клонирование и установка
```bash
git clone https://github.com/atitoff-dotcom/rsgi-wsrpc.git
cd rsgi-wsrpc
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Запуск сервера
```bash
granian --interface rsgi --host 127.0.0.1 --port 8080 main:app
```

### 3. Вызов из JavaScript / TypeScript
```typescript
import { WsrpcClient } from './client/wsrpc';

const client = new WsrpcClient('ws://127.0.0.1:8080');
await client.connect();

// Вызов RPC-метода
const res = await client.call('system.echo', { message: 'Привет, WSRPC!' });
console.log(res);
```

---

## 📚 Документация

Подробная архитектура, разбор модулей и туториалы доступны в:
* **[Русская документация](docs_ru/readme.md)**
  * [Архитектура загрузки и хранения файлов (Two-Phase Commit)](docs_ru/files.md)
* **[English Documentation](docs/readme.md)**
  * [Two-Phase Upload & File Architecture](docs/files.md)

---

## 📄 Лицензия
Распространяется под свободной лицензией [MIT](LICENSE).
