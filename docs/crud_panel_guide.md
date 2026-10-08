# Руководство по интеграции CRUD-панели в rsgi-wsrpc

> **Целевая аудитория:** Разработчики и ИИ-ассистенты (Cursor, Antigravity, Claude, ChatGPT, Windsurf, Copilot).  
> **Цель документа:** Объяснить самый простой, правильный и идиоматичный способ подключения встроенной панели управления CRUD в любое приложение на базе `rsgi-wsrpc`, а также разобрать типичные ошибки (включая причину `404 Not Found`).

---

## 1. В чём проблема: почему у ИИ возникает ступор?

При попытке подключить CRUD-панель разработчики и ИИ часто сталкиваются с двумя «неожиданностями»:

1. **Симптом: при открытии `http://localhost:8080/crud` сервер возвращает `404 Not Found`**  
   *Ложная реакция ИИ:* «Роут сломан! Сборки нет! Granian не отдает статику! Надо написать свой хендлер или сделать monkey-patching!».  
   *Реальность:* Это фундаментальный архитектурный принцип безопасности фреймворка — **Zero-Leakage (404)**.  
   Панель управления **намеренно скрыта от неавторизованных пользователей и сканеров уязвимостей**. Если в запросе нет валидной сессии администратора, сервер отвечает строгим `404 Not Found`, а не `401/403`, не выдавая самого факта существования админки. Отдельной HTML-формы `/crud/login` во фреймворке нет — вход реализован бесшовно через SSO/сессию приложения.

2. **Симптом: методы `crud.*` или роут `/crud` отсутствуют в таблице маршрутов**  
   *Реальность:* Плагин активируется **при первом импорте**. Если в коде приложения нигде не импортирован модуль `rsgi_wsrpc.plugins.crud` (или `ModelRegistry`), роуты и RPC-методы не регистрируются в приложении.

---

## 2. Быстрый старт: Включение CRUD за 3 шага

### Шаг 1. Импортировать плагин и зарегистрировать модели

Достаточно импортировать плагин и передать базовый декларативный класс SQLAlchemy `Base` в `ModelRegistry`:

```python
from rsgi_wsrpc import RsgiWsrpcApp
from rsgi_wsrpc.plugins.db import Base
import rsgi_wsrpc.plugins.crud as crud  # 👈 Активирует HTTP /crud и RPC crud.*

# Автоматически регистрирует все модели, унаследованные от Base
crud.ModelRegistry.auto_discover(Base)

# Или зарегистрировать конкретную модель вручную:
# crud.ModelRegistry.register(Task)
```

---

### Шаг 2. Настроить отображение модели (`class Crud:`)

Внутри SQLAlchemy модели задаются человекочитаемые названия и правила безопасности:

```python
from sqlalchemy import Integer, String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from rsgi_wsrpc.plugins.db import Base

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), info={"label": "Название задачи"})
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, info={"label": "Выполнено"})
    password_hash: Mapped[str] = mapped_column(String(255)) # скроется автоматически!
    owner_id: Mapped[int] = mapped_column(Integer, nullable=True)

    class Crud:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"
        hidden = {"secret_notes"}        # Полностью скрыть из интерфейса и схем
        readonly = {"created_at"}        # Запретить редактирование в таблице
        protected = {"owner_id"}         # Защитить от изменения не-суперпользователем
```

> **Безопасность полей «из коробки»:**  
> Все поля, содержащие в имени `password`, `hash`, `secret`, `token`, `key`, **автоматически исключаются** из схем и ответов панели CRUD.

---

### Шаг 3. Обеспечить доступ к панели (Преодоление Zero-Leakage 404)

Чтобы панель открылась по адресу `/crud/` (или `/admin/`), браузер должен передать Cookie с сессией администратора:
- `rsgi_crud_session=<token>` или `rsgi_session=<token>`

Выберите один из трех сценариев:

---

#### Вариант А: Управление паролем администратора через CLI (`--set-admin-password`)

Для безопасной смены или установки пароля администратора используйте встроенный CLI:

```bash
# Интерактивный ввод пароля с подтверждением:
python server.py --set-admin-password

# Или прямая передача пароля (например, в CI/CD):
python server.py --set-admin-password "my_strong_pass" --login admin
```

Утилита работает строго на уровне DML (обновляет `password_hash` в БД по алгоритму PBKDF2-SHA256) без опасных бэкдоров и без DDL-мутаций. После смены пароля войдите через стандартную форму логина приложения.

---

#### Вариант Б: Каноническая интеграция с логином приложения (Production / Showcase)

Если в приложении есть свой RPC-метод входа (например, `auth.login`):

1. **На бэкенде** при авторизации пользователя с ролью `admin` зарегистрируйте сессию в CRUD:
   ```python
   # server.py / handlers.py
   @app.rpc("auth.login", public=True)
   async def login(username: str, password: str):
       user = authenticate(username, password)
       token = generate_token()
       
       # Если пользователь администратор — регистрируем в сессиях CRUD
       if user.role == "admin":
           crud.create_crud_session({"username": user.username, "role": "admin"}, token=token)
           
       return {"token": token, "username": user.username, "role": user.role}
   ```

2. **На фронтенде** при успешном ответе установите Cookie:
   ```javascript
   const res = await rpc.call("auth.login", { username, password });
   if (res.token) {
       document.cookie = `rsgi_crud_session=${res.token}; path=/; max-age=86400; SameSite=Lax`;
   }
   ```

3. После этого ссылка `<a href="/crud" target="_blank">Панель управления</a>` откроет админку без 404.

---

#### Вариант В: Бесшовный SSO-мост (`set_crud_session_validator`)

Если в приложении уже есть готовое хранилище сессий (в БД, Redis или JWT), вам не нужно вызывать `create_crud_session` вручную. Достаточно один раз объявить функцию валидатора:

```python
from rsgi_wsrpc.plugins.crud import set_crud_session_validator

def validate_app_session(token: str):
    # Извлеките пользователя из вашего хранилища по токену
    user = my_session_store.get(token)
    if user and user.is_superuser:
        return {"username": user.username, "role": "admin"}
    return None

# Регистрируем глобальный мост
set_crud_session_validator(validate_app_session)
```

Теперь любой запрос с кукой `rsgi_crud_session` или `rsgi_session` автоматически валидируется через ваш мост!

---

## 3. Полный минимальный пример приложения (`minimal_admin.py`)

Этот код можно скопировать в один файл и запустить:

```python
# minimal_admin.py
import asyncio
from sqlalchemy import Integer, String, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from rsgi_wsrpc import RsgiWsrpcApp
from rsgi_wsrpc.plugins.db import Base, engine
import rsgi_wsrpc.plugins.crud as crud

# 1. Объявляем модель данных
class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), info={"label": "Название"})
    completed: Mapped[bool] = mapped_column(Boolean, default=False, info={"label": "Завершено"})

    class Crud:
        verbose_name = "Задача"
        verbose_name_plural = "Задачи"

# 2. Регистрируем модель в реестре CRUD
crud.ModelRegistry.register(Task)

# 3. Инициализируем приложение rsgi-wsrpc
app = RsgiWsrpcApp(
    database_url="sqlite+aiosqlite:///dev.db",
    cors=True
)

# 4. Хук инициализации таблиц при старте
@app.on_startup
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
```

**Установка пароля администратора:**
```bash
python minimal_admin.py --set-admin-password
```

---

## 4. Как CRUD-панель работает под капотом

1. **Раздача статики (Rust Zero-Copy):**  
   HTML, CSS и JS бандлы админки (Svelte 5 + Tailwind v4) скомпилированы и находятся внутри пакета `rsgi_wsrpc/plugins/crud/static/`.  
   Обработчик `static_handler.py` раздаёт их через `proto.response_file`, обеспечивая максимальную скорость и изоляцию.
2. **WebSocket Соединение (WSRPC):**  
   При загрузке страницы интерфейс открывает соединение по адресу `/ws`. Браузер автоматически отправляет сохраненную куку `rsgi_crud_session` в HTTP-заголовках рукопожатия WebSocket.
3. **Провайдер Идентификации (`DefaultIdentityProvider`):**  
   При каждом вызове RPC-методов (`crud.schema`, `crud.list`, `crud.update_cell`) провайдер проверяет куку в сокете и наделяет сессию правами `is_superuser = True`.
4. **Сжатие трафика (RFC 0002 Tabular Compression):**  
   Метод `crud.list` передает строки таблиц в виде матриц `{"$tabular": true, "fields": [...], "rows": [[...]]}`, экономя до 70% трафика в реальном времени.

---

## 5. Чек-лист и устранение частых ошибок (Troubleshooting)

| Проблема / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **`404 Not Found`** при переходе на `/crud` | Защита Zero-Leakage: нет Cookie администратора `rsgi_crud_session` | Авторизуйтесь под администратором в приложении или установите Cookie с токеном администратора. |
| **`404 Not Found`** даже при наличии куки | Модуль `rsgi_wsrpc.plugins.crud` не был импортирован в Python | Добавьте `import rsgi_wsrpc.plugins.crud as crud` в основной файл запуска. |
| **Пустой экран** в панели (нет таблиц) | Модели SQLAlchemy не зарегистрированы в `ModelRegistry` | Вызовите `crud.ModelRegistry.auto_discover(Base)` или `crud.ModelRegistry.register(MyModel)`. |
| **Ошибка валидации** при редактировании ячейки | Введено значение, не соответствующее типу колонки | Плагин использует `coerce_value`. Убедитесь, что числа, булевы флаги и даты вводятся в корректном формате. |
| **WebSocket Disconnected** в панели | Ошибки соединения или сервер завершил процесс | Проверьте консоль сервера и убедитесь, что порт `8080` доступен. |

---

## 6. 🚫 Анти-паттерны (Чего делать НЕЛЬЗЯ)

1. ❌ **НЕ ПИШИТЕ кастомные роуты `@app.route("/crud")` и НЕ копируйте статику панели вручную в `./public`.**  
   Плагин `crud` уже содержит полноценный обработчик раздачи статики и Zero-Leakage защиты.
2. ❌ **НЕ ПРИМЕНЯЙТЕ monkey-patching к `serve_crud_static` или `auth.py`.**  
   Архитектура предоставляет официальные точки расширения: `create_crud_session` и `set_crud_session_validator`.
3. ❌ **НЕ ДЕЛАЙТЕ синхронных блокирующих вызовов в `class Crud:` или валидаторах сессий.**
4. ❌ **НЕ ЗАБЫВАЙТЕ вызывать `ModelRegistry.auto_discover(Base)`.**  
   Модели не регистрируются «магически» сами по себе — реестр должен их проинтроспектировать.
