# ⚡ Smart Cache: Реактивный умный кэш с обратной связью

Официальный системный плагин фреймворка `rsgi-wsrpc` (`plugins/smart_cache` + `client/smartCache.ts`).

> **«Сервер знает, когда данные изменились. Клиент хранит всё локально и обновляется с задержкой 0 мс только тогда, когда сервер явно командует это сделать.»**

---

## 🧭 Содержание
1. [Главная идея и преимущества](#1-главная-идея-и-преимущества)
2. [Архитектура и потоки данных](#2-архитектура-и-потоки-данных)
3. [Серверная часть (Python)](#3-серверная-часть-python)
   * [Декоратор @invalidates](#декоратор-invalidates)
   * [Точечные патчи patch_tag](#точечные-патчи-patch_tag)
   * [Программная инвалидация invalidate_tags](#программная-инвалидация-invalidate_tags)
4. [Клиентская часть (TypeScript: smartCache.ts)](#4-клиентская-часть-typescript-smartcachets)
   * [Метод getOrFetch (0 мс доступ)](#метод-getorfetch-0-мс-доступ)
   * [Автоматическая фоновая ревалидация](#автоматическая-фоновая-ревалидация)
   * [Подписка компонентов observe](#подписка-компонентов-observe)
5. [Рукопожатие версий при реконнекте (Sync Handshake)](#5-рукопожатие-версий-при-реконнекте-sync-handshake)
6. [Практический пример: Модуль форума](#6-практический-пример-модуль-форума)

---

## 1. Главная идея и преимущества

Традиционный веб страдает от двух крайностей:
* **Либо белый экран/скелетоны** при каждом переходе между страницами (пока идет запрос к БД 100–300 мс).
* **Либо слепой polling** (как в SWR или TanStack Query), когда тысячи браузеров каждую секунду опрашивают сервер *«нет ли чего нового?»*, нагружая базу данных и высаживая аккумуляторы смартфонов.

**Smart Cache решает обе проблемы раз и навсегда:**
1. **Мгновенный отклик 0 мс**: Любой экран рендерится синхронно из L1 RAM (или L2 IndexedDB) без ожидания сетевого ответа.
2. **Нулевой лишний трафик**: Нет фонового поллинга. Сокет молчит, пока данные на сервере не изменились.
3. **100% свежесть данных**: В момент мутации (создание комментария, изменение статуса) сервер толкает крошечный push-сигнал инвалидации или готовый патч.

---

## 2. Архитектура и потоки данных

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        ФРОНТЕНД (smartCache.ts)                        │
│                                                                        │
│   1. getOrFetch() ──────► [ L1 RAM Map (0 мс) ] ───► Возврат данных    │
│                                   │ (если пусто)                       │
│                                   ▼                                    │
│                           [ L2 Storage (IndexedDB) ]                   │
│                                   │ (если пусто)                       │
│                                   ▼                                    │
│   2. RPC Call ──────────► [ WSRPC Socket ]                             │
│                                   ▲                                    │
│   3. Push Invalidate ─────────────┤ (cache.invalidate / cache.patch)   │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │ WebSocket (JSON-RPC 2.0)
┌───────────────────────────────────┼────────────────────────────────────┐
│                        БЭКЕНД (Python)                                 │
│                                   │                                    │
│   @invalidates(tags=...) ─────────┤ 1. Инкремент версии в реестре      │
│                                   │ 2. Broadcast push в сокеты         │
│   VersionRegistry ────────────────┤ Хранение версий (RAM + SQLite)     │
│   cache.sync_check ───────────────┘ Сверка версий при реконнекте       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Серверная часть (Python)

### Декоратор `@invalidates`

Декоратор вешается на любой мутирующий RPC-метод. Теги могут быть как фиксированным списком, так и динамической функцией от входных параметров и результата:

```python
from core.session import rpc_method
from app.system.smart_cache import invalidates

# Статический тег: при создании темы инвалидируется общий список тем
@rpc_method("forum.create_topic")
@invalidates(tags=["forum.topics"])
async def create_topic(session, params):
    ...
    return {"topic_id": new_id}

# Динамические теги: инвалидирует как список тем, так и конкретную тему по ID
@rpc_method("forum.create_reply")
@invalidates(tags=lambda p, res: [f"topic:{p.get('topic_id')}", "forum.topics"])
async def create_reply(session, params):
    topic_id = params.get("topic_id")
    ...
    return {"reply_id": reply.id}
```

### Точечные патчи `patch_tag`

Для счетчиков просмотров, лайков или чатов можно применить патч без повторного чтения всей темы из БД:

```python
from app.system.smart_cache import patch_tag

@rpc_method("forum.like_post")
async def like_post(session, params):
    post_id = params.get("post_id")
    topic_id = params.get("topic_id")
    
    # Добавляем лайк в БД...
    
    # Отправляем точечный патч всем открытым браузерам:
    await patch_tag(
        tag=f"topic:{topic_id}",
        action="inc",
        field="likes_count",
        data={"amount": 1}
    )
    return {"status": "ok"}
```

### Программная инвалидация `invalidate_tags`

Если мутация произошла вне RPC-хендлера (например, в фоновой задаче или webhook-обработчике):

```python
from app.system.smart_cache import invalidate_tags

# Инвалидация списка заказов после успешного вебхука оплаты от банка
await invalidate_tags(["orders.list", f"order:{order_id}"])
```

---

## 4. Клиентская часть (TypeScript: `smartCache.ts`)

### Метод `getOrFetch` (0 мс доступ)

```typescript
import { smartCache } from '$lib/smartCache';
import { rpc } from '$lib/wsrpc';

// Запрос списка тем форума
const topics = await smartCache.getOrFetch(
    'forum.topics', // Уникальный ключ записи
    () => rpc.call('forum.get_topics', {}), // Функция загрузки при промахе
    {
        tags: ['forum.topics'], // Теги, привязанные к записи
        persist: true,          // Сохранять в IndexedDB между F5
        ttlSec: 3600            // Резервный тайм-аут (1 час)
    }
);
```

### Подписка компонентов `observe`

Чтобы экран автоматически и плавно обновлялся, когда сервер присылает сигнал инвалидации или патч:

```typescript
import { onDestroy } from 'svelte';
import { smartCache } from '$lib/smartCache';

let topics = [];

// Подписываемся на реактивные изменения ключа
const unsubscribe = smartCache.observe('forum.topics', (data) => {
    topics = data;
});

onDestroy(unsubscribe);
```

---

## 5. Рукопожатие версий при реконнекте (Sync Handshake)

Если пользователь закрыл вкладку или потерял связь на несколько часов, при повторном подключении:
1. `smartCache` автоматически собирает карту версий локально сохраненных тегов:
   `{"forum.topics": 105, "profile": 12}`.
2. Отправляет запрос `cache.sync_check`.
3. Сервер сравнивает версии и возвращает **только те теги, где данные реально изменились**.
4. Клиент фоново перезапрашивает только изменившиеся экраны. Если ничего не менялось — не скачивается ни единого байта!

---

## 6. Практический пример: Модуль форума

```svelte
<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { smartCache } from '$lib/smartCache';
    import { rpc } from '$lib/wsrpc';

    let topics = [];
    let unobserve;

    onMount(async () => {
        // Мгновенно получаем список тем (0 мс)
        topics = await smartCache.getOrFetch(
            'forum.topics',
            () => rpc.call('forum.get_topics'),
            { tags: ['forum.topics'] }
        );

        // Подписываемся на обновления на лету
        unobserve = smartCache.observe('forum.topics', (freshTopics) => {
            topics = freshTopics;
        });
    });

    onDestroy(() => {
        if (unobserve) unobserve();
    });

    async function addTopic(title: string) {
        await rpc.call('forum.create_topic', { title });
        // Ручной перезагрузки не требуется! Сервер сам инвалидирует тег forum.topics,
        // и smartCache обновит список автоматически!
    }
</script>
```
