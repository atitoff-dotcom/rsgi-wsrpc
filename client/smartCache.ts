/**
 * SmartCache: Реактивный клиентский умный кэш с двухуровневым хранением (L1 RAM + L2 Storage),
 * мгновенным откликом 0 мс, серверной инвалидацией и поддержкой точечных патчей.
 * 
 * Официальный клиент плагина rsgi-wsrpc (plugins/smart_cache).
 */

import { rpc, type BinaryWSRPC } from './wsrpc';

export interface SmartCacheOptions {
    /** Список тегов, привязанных к этой записи кэша (например: ['forum.topics', 'forum.category.5']) */
    tags?: string[];
    /** Сохранять ли в L2 (IndexedDB / localStorage) между перезагрузками страницы */
    persist?: boolean;
    /** Время жизни кэша в секундах (резервный TTL, по умолчанию 1 час) */
    ttlSec?: number;
}

export interface CacheEntry<T = any> {
    data: T;
    tags: string[];
    version: number;
    fetchedAt: number;
    ttlMs: number;
    stale: boolean;
    fetcher?: () => Promise<T>;
}

export interface InvalidatePayload {
    tags: string[];
    versions?: Record<string, number>;
    reason?: string;
}

export interface PatchPayload {
    tag: string;
    action: 'append' | 'prepend' | 'update' | 'remove' | 'inc' | string;
    data: any;
    field?: string;
    version?: number;
}

const STORAGE_PREFIX = 'rsgi_cache_';
const isBrowser = typeof window !== 'undefined';

export class SmartCache {
    /** L1: Мгновенное хранилище в оперативной памяти (0 мс доступ) */
    private l1Map = new Map<string, CacheEntry>();

    /** Реестр активных слушателей ключей (UI-компоненты на экране) */
    private observers = new Map<string, Set<(data: any) => void>>();

    /** Слушатели глобальных событий инвалидации */
    private invalidateListeners = new Set<(tags: string[]) => void>();

    /** Пользовательские редюсеры патчей по префиксу ключа */
    private patchReducers = new Map<string, (current: any, action: string, patchData: any) => any>();

    /** Карта версий известных тегов */
    private tagVersions = new Map<string, number>();

    private rpcClient: BinaryWSRPC;

    constructor(client: BinaryWSRPC = rpc) {
        this.rpcClient = client;
        this.initEventListeners();
    }

    /**
     * Инициализация слушателей входящих push-событий от сервера WSRPC
     */
    private initEventListeners() {
        if (!isBrowser) return;

        // 1. Слушаем сигнал инвалидации от сервера
        this.rpcClient.on('cache.invalidate', (payload: InvalidatePayload) => {
            console.debug('[SmartCache] ⚡ Получен сигнал cache.invalidate:', payload.tags);
            if (payload.versions) {
                for (const [tag, ver] of Object.entries(payload.versions)) {
                    this.tagVersions.set(tag, ver);
                }
            }
            this.invalidateByTags(payload.tags);
        });

        // 2. Слушаем точечные патчи от сервера (cache.patch)
        this.rpcClient.on('cache.patch', (payload: PatchPayload) => {
            console.debug('[SmartCache] 🩹 Получен точечный патч cache.patch:', payload.tag, payload.action);
            if (payload.version) {
                this.tagVersions.set(payload.tag, payload.version);
            }
            this.applyPatch(payload.tag, payload.action, payload.data, payload.field);
        });

        // 3. Автоматическое рукопожатие при подключении / переподключении (Sync Handshake)
        const prevOnConnect = this.rpcClient.onConnect;
        this.rpcClient.onConnect = () => {
            if (prevOnConnect) prevOnConnect();
            this.syncWithServer().catch(err => {
                console.warn('[SmartCache] Ошибка рукопожатия версий при реконнекте:', err);
            });
        };
    }

    /**
     * Главный интерфейс: получить из кэша мгновенно или загрузить с сервера
     */
    async getOrFetch<T = any>(
        key: string,
        fetcher: () => Promise<T>,
        options: SmartCacheOptions = {}
    ): Promise<T> {
        const tags = options.tags || [key];
        const persist = options.persist ?? true;
        const ttlMs = (options.ttlSec || 3600) * 1000;
        const now = Date.now();

        // 1. Проверяем L1 RAM (0 мс)
        const l1Entry = this.l1Map.get(key);
        if (l1Entry) {
            l1Entry.fetcher = fetcher; // обновляем fetcher для фонового обновления
            const isExpired = (now - l1Entry.fetchedAt) > l1Entry.ttlMs;

            if (!l1Entry.stale && !isExpired) {
                return l1Entry.data as T;
            }

            // Данные помечены как stale или истекли: возвращаем текущие мгновенно, но запускаем тихий рефетч в фоне!
            this.revalidateInBackground(key, fetcher, tags, persist, ttlMs);
            return l1Entry.data as T;
        }

        // 2. Проверяем L2 (IndexedDB / localStorage)
        if (persist && isBrowser) {
            const l2Data = this.readFromL2(key);
            if (l2Data) {
                const entry: CacheEntry<T> = {
                    data: l2Data.data,
                    tags: l2Data.tags || tags,
                    version: l2Data.version || 1,
                    fetchedAt: l2Data.fetchedAt,
                    ttlMs: l2Data.ttlMs || ttlMs,
                    stale: l2Data.stale || false,
                    fetcher
                };
                this.l1Map.set(key, entry);

                const isExpired = (now - entry.fetchedAt) > entry.ttlMs;
                if (entry.stale || isExpired) {
                    this.revalidateInBackground(key, fetcher, tags, persist, ttlMs);
                }
                return entry.data;
            }
        }

        // 3. Промах кэша: выполняем прямой вызов
        return this.fetchAndStore(key, fetcher, tags, persist, ttlMs);
    }

    /**
     * Загрузка данных и сохранение в L1 и L2
     */
    private async fetchAndStore<T>(
        key: string,
        fetcher: () => Promise<T>,
        tags: string[],
        persist: boolean,
        ttlMs: number
    ): Promise<T> {
        const data = await fetcher();
        const entry: CacheEntry<T> = {
            data,
            tags,
            version: 1,
            fetchedAt: Date.now(),
            ttlMs,
            stale: false,
            fetcher
        };

        this.l1Map.set(key, entry);
        if (persist && isBrowser) {
            this.saveToL2(key, entry);
        }

        this.notifyObservers(key, data);
        return data;
    }

    /**
     * Фоновая тихая ревалидация (Stale-While-Revalidate)
     */
    private async revalidateInBackground<T>(
        key: string,
        fetcher: () => Promise<T>,
        tags: string[],
        persist: boolean,
        ttlMs: number
    ) {
        try {
            const freshData = await fetcher();
            const entry = this.l1Map.get(key);
            if (entry) {
                entry.data = freshData;
                entry.fetchedAt = Date.now();
                entry.stale = false;
                if (persist && isBrowser) {
                    this.saveToL2(key, entry);
                }
                this.notifyObservers(key, freshData);
            }
        } catch (err) {
            console.warn(`[SmartCache] Фоновое обновление ключа "${key}" завершилось с ошибкой:`, err);
        }
    }

    /**
     * Быстрое синхронное чтение из кэша (L1 RAM -> L2 Storage) без отправки запроса
     */
    public peek<T = any>(key: string): T | null {
        const l1 = this.l1Map.get(key);
        if (l1) return l1.data as T;
        if (isBrowser) {
            const l2 = this.readFromL2(key);
            if (l2) {
                const entry: CacheEntry<T> = {
                    data: l2.data,
                    tags: l2.tags || [key],
                    version: l2.version || 1,
                    fetchedAt: l2.fetchedAt,
                    ttlMs: l2.ttlMs || 3600000,
                    stale: l2.stale || false
                };
                this.l1Map.set(key, entry);
                return l2.data as T;
            }
        }
        return null;
    }

    /**
     * Прямая запись данных в кэш
     */
    public set<T = any>(key: string, data: T, options: SmartCacheOptions = {}): void {
        const tags = options.tags || [key];
        const persist = options.persist ?? true;
        const ttlMs = (options.ttlSec || 3600) * 1000;
        const entry: CacheEntry<T> = {
            data,
            tags,
            version: 1,
            fetchedAt: Date.now(),
            ttlMs,
            stale: false
        };
        this.l1Map.set(key, entry);
        if (persist && isBrowser) {
            this.saveToL2(key, entry);
        }
        this.notifyObservers(key, data);
    }

    /**
     * Регистрация пользовательского редюсера для точечных патчей
     */
    public registerPatchReducer(prefix: string, reducer: (current: any, action: string, patchData: any) => any) {
        this.patchReducers.set(prefix, reducer);
    }

    /**
     * Подписка на глобальные события инвалидации
     */
    public onInvalidate(callback: (tags: string[]) => void): () => void {
        this.invalidateListeners.add(callback);
        return () => {
            this.invalidateListeners.delete(callback);
        };
    }

    /**
     * Инвалидация кэша по тегам
     */
    public invalidateByTags(tags: string[]) {
        const tagSet = new Set(tags);

        // Оповещаем подписчиков на событие инвалидации
        for (const listener of this.invalidateListeners) {
            try {
                listener(tags);
            } catch (e) {
                console.error('[SmartCache] Ошибка в listener onInvalidate:', e);
            }
        }

        for (const [key, entry] of this.l1Map.entries()) {
            const hasMatch = entry.tags.some(t => tagSet.has(t));
            if (hasMatch) {
                entry.stale = true;

                // Если есть активные подписчики на экране — запускаем немедленное тихое фоновое обновление!
                const hasActiveViewers = (this.observers.get(key)?.size || 0) > 0;
                if (hasActiveViewers && entry.fetcher) {
                    console.debug(`[SmartCache] Реактивное обновление отображаемого ключа: "${key}"`);
                    this.revalidateInBackground(key, entry.fetcher, entry.tags, true, entry.ttlMs);
                }
            }
        }
    }

    /**
     * Алиас для invalidateByTags
     */
    public invalidateTags(tags: string[]) {
        this.invalidateByTags(tags);
    }

    /**
     * Применение точечного патча данных (без повторного сетевого запроса к БД)
     */
    public applyPatch(tag: string, action: string, data: any, field?: string) {
        // 1. Проверяем кастомные редюсеры патчей
        for (const [prefix, reducer] of this.patchReducers.entries()) {
            for (const [key, entry] of this.l1Map.entries()) {
                if (key.startsWith(prefix) || entry.tags.some(t => t.startsWith(prefix))) {
                    try {
                        const updated = reducer(entry.data, action, data);
                        if (updated !== undefined) {
                            entry.data = updated;
                            this.notifyObservers(key, entry.data);
                            this.saveToL2(key, entry);
                        }
                    } catch (e) {
                        console.error('[SmartCache] Ошибка в custom patch reducer:', e);
                    }
                }
            }
        }

        // 2. Стандартная обработка массивов и объектов
        for (const [key, entry] of this.l1Map.entries()) {
            if (!entry.tags.includes(tag)) continue;

            let target = entry.data;
            if (field && target && typeof target === 'object') {
                target = target[field];
            }

            if (Array.isArray(target)) {
                if (action === 'append' || action === 'push') {
                    target.push(data);
                } else if (action === 'prepend') {
                    target.unshift(data);
                } else if (action === 'remove' || action === 'delete') {
                    const id = typeof data === 'object' ? data.id : data;
                    const idx = target.findIndex(item => (typeof item === 'object' ? item.id : item) === id);
                    if (idx !== -1) target.splice(idx, 1);
                } else if (action === 'update') {
                    const id = data?.id;
                    const idx = target.findIndex(item => item?.id === id);
                    if (idx !== -1) {
                        target[idx] = { ...target[idx], ...data };
                    }
                }
            } else if (target && typeof target === 'object') {
                if (action === 'update' || action === 'merge') {
                    Object.assign(target, data);
                } else if (action === 'inc' || action === 'increment') {
                    const fieldName = data.field || field;
                    if (fieldName && typeof target[fieldName] === 'number') {
                        target[fieldName] += (data.amount || 1);
                    }
                }
            }

            this.notifyObservers(key, entry.data);
            this.saveToL2(key, entry);
        }
    }

    /**
     * Подписка компонента на изменение кэшированного ключа
     */
    public observe<T = any>(key: string, callback: (data: T) => void): () => void {
        if (!this.observers.has(key)) {
            this.observers.set(key, new Set());
        }
        this.observers.get(key)!.add(callback);

        // Если данные уже есть — сразу передаем текущее значение
        const current = this.l1Map.get(key);
        if (current) {
            callback(current.data);
        }

        return () => {
            const set = this.observers.get(key);
            if (set) {
                set.delete(callback);
                if (set.size === 0) this.observers.delete(key);
            }
        };
    }

    /**
     * Алиас для observe (совместимость с watch)
     */
    public watch<T = any>(key: string, callback: (data: T) => void): () => void {
        return this.observe(key, callback);
    }

    /**
     * Рукопожатие версий с сервером при коннекте (Sync Handshake)
     */
    public async syncWithServer() {
        // Собираем все теги из L1
        const manifest: Record<string, number> = {};
        for (const entry of this.l1Map.values()) {
            for (const t of entry.tags) {
                manifest[t] = this.tagVersions.get(t) || 1;
            }
        }

        if (Object.keys(manifest).length === 0) return;

        console.debug('[SmartCache] 🤝 Рукопожатие версий тегов с сервером...', manifest);
        const res = await this.rpcClient.call<{ stale_tags: string[]; current_versions: Record<string, number> }>(
            'cache.sync_check',
            { tags: manifest }
        );

        if (res && res.current_versions) {
            for (const [tag, ver] of Object.entries(res.current_versions)) {
                this.tagVersions.set(tag, ver);
            }
        }

        if (res && res.stale_tags && res.stale_tags.length > 0) {
            console.info('[SmartCache] 🔄 Сервер сообщил об устаревших тегах после реконнекта:', res.stale_tags);
            this.invalidateByTags(res.stale_tags);
        }
    }

    private notifyObservers(key: string, data: any) {
        const set = this.observers.get(key);
        if (set) {
            for (const cb of set) {
                try {
                    cb(data);
                } catch (e) {
                    console.error(`[SmartCache] Ошибка в observe-колбэке ключа ${key}:`, e);
                }
            }
        }
    }

    private saveToL2(key: string, entry: CacheEntry) {
        try {
            const payload = JSON.stringify({
                data: entry.data,
                tags: entry.tags,
                version: entry.version,
                fetchedAt: entry.fetchedAt,
                ttlMs: entry.ttlMs,
                stale: entry.stale,
            });
            localStorage.setItem(STORAGE_PREFIX + key, payload);
        } catch (e) {
            // Превышение квоты localStorage или приватный режим
        }
    }

    private readFromL2(key: string): any {
        try {
            const raw = localStorage.getItem(STORAGE_PREFIX + key);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    }
}

// Глобальный синглтон умного кэша
export const smartCache = new SmartCache();
export default smartCache;
