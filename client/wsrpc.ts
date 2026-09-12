const isBrowser = typeof window !== 'undefined';

/**
 * Легковесный реактивный стор с нулевыми зависимостями.
 * Полностью совместим со стандартом Svelte store contract ($store),
 * React (useSyncExternalStore), Vue и Vanilla JS (subscribe).
 */
type Listener<T> = (val: T) => void;
export class SimpleStore<T> {
    private value: T;
    private listeners = new Set<Listener<T>>();
    constructor(val: T) { this.value = val; }
    get(): T { return this.value; }
    set(val: T) { this.value = val; this.listeners.forEach(fn => fn(val)); }
    update(updater: (val: T) => T) { this.set(updater(this.value)); }
    subscribe(fn: Listener<T>): () => void {
        fn(this.value);
        this.listeners.add(fn);
        return () => { this.listeners.delete(fn); };
    }
}

// Реактивные сторы состояния соединения
export const wsConnected = new SimpleStore<boolean>(false);
export const wsStatus = new SimpleStore<'CONNECTING' | 'CONNECTED' | 'DISCONNECTED'>('DISCONNECTED');

// Описание структуры для отслеживания ожидающих ответа RPC-запросов (Promises)
interface PendingRequest {
    resolve: (value: any) => void;
    reject: (reason: any) => void;
    timeoutId: number; // ID таймера ожидания таймаута
}

/**
 * Определение адреса WebSocket для подключения
 */
export function getWsUrl(): string {
    if (typeof window !== 'undefined') {
        const isHttps = window.location.protocol === 'https:';
        const wsProto = isHttps ? 'wss:' : 'ws:';
        
        // На удаленном сервере (stage.agrita.ru и др.) проксируем через Nginx /ws
        if (isHttps || (!['5173', '4173'].includes(window.location.port) && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1')) {
            return `${wsProto}//${window.location.host}/ws`;
        }
        // Локальная разработка: бэкенд Granian на порту 8080
        return 'ws://127.0.0.1:8080/';
    }
    return 'ws://127.0.0.1:8080/';
}

/**
 * Реактивный JSON-RPC 2.0 клиент на Svelte 5 (BinaryWSRPC).
 * Обеспечивает полную обратную совместимость с интерфейсом старого wsrpc.ts.
 */
/**
 * WSRPC Tabular Payload Decompression (RFC 0002).
 * Автоматически распаковывает компактный табличный формат {$tabular: true, fields: [...], rows: [...]}
 * в плоские JavaScript-объекты. Рекурсивно обрабатывает списки и словари.
 */
export function unpackTabular(data: any): any {
    if (!data || typeof data !== "object") return data;

    if (data.$tabular === true && Array.isArray(data.fields) && Array.isArray(data.rows)) {
        const fields = data.fields;
        return data.rows.map((row: any[]) => {
            const obj: Record<string, any> = {};
            for (let i = 0; i < fields.length; i++) {
                obj[fields[i]] = row[i];
            }
            return obj;
        });
    }

    if (Array.isArray(data)) {
        return data.map(item => unpackTabular(item));
    }

    const res: Record<string, any> = {};
    for (const key of Object.keys(data)) {
        res[key] = unpackTabular(data[key]);
    }
    return res;
}

export class BinaryWSRPC {
    // Статус подключения
    public status: 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' = 'DISCONNECTED';
    // Настройка времени переподключения (в секундах). 0 - отключить автореконнект.
    public reconnectWs = 3;

    private ws: WebSocket | null = null;
    private idCounter = 0; // Инкрементальный счетчик ID для JSON-RPC запросов
    
    // Хранилище Promises для ожидающих ответа запросов (ID -> PendingRequest)
    private pendingRequests = new Map<number | string, PendingRequest>();
    
    // Реестр зарегистрированных на клиенте методов, которые может вызывать сервер (симметричный RPC)
    private serverMethods = new Map<string, (params: any) => Promise<any>>();
    
    // Реестр активных подписок на стримы (ID -> колбэк для чанков данных)
    private streamListeners = new Map<number | string, (data: any) => void>();
 
    private url = '';
    private reconnectTimerId: number | null = null;
    private isIntentionallyClosed = false; // Флаг ручного закрытия (чтобы не запускать реконнект)
 
    // Коллбеки для совместимости со старой кодовой базой
    private connectingPromise: Promise<void> | null = null;
    public onConnect: (() => void) | null = null; // Вызывается при каждом успешном коннекте
    public onStatusChange: ((connected: boolean) => void) | null = null; // Вызывается при изменении состояния сети (true/false)

    // Системный шлюз авторизации сессии (Gatekeeper): гарантирует авторизацию сессии на сокете до отправки бизнес-запросов
    public authInterceptor: (() => Promise<any>) | null = null;
 
    constructor(url?: string) {
        this.url = url || getWsUrl();
        if (isBrowser) {
            console.log('[WSRPC] Клиент WSRPC инициализирован для URL:', this.url);
        }
    }
 
    /**
     * Установка соединения с WebSocket-сервером.
     * Возвращает Promise, который разрешается при успешном подключении (onopen).
     */
    connect(url?: string): Promise<void> {
        if (!isBrowser) return Promise.resolve();
        if (this.status === 'CONNECTED' && this.ws && this.ws.readyState === WebSocket.OPEN) {
            return Promise.resolve();
        }
        if (this.connectingPromise) {
            return this.connectingPromise;
        }
        if (url) {
            this.url = url;
        }
        
        this.isIntentionallyClosed = false;
        this.status = 'CONNECTING';
        wsStatus.set('CONNECTING');
        wsConnected.set(false);
 
        console.info(`[WSRPC] Подключение к ${this.url}...`);
 
        this.connectingPromise = new Promise((resolve, reject) => {
            // Создаем таймер таймаута соединения (5 секунд)
            const connectionTimeout = window.setTimeout(() => {
                if (this.status === 'CONNECTING') {
                    console.warn(`[WSRPC] ⏰ Превышен таймаут подключения к ${this.url}`);
                    this.status = 'DISCONNECTED';
                    this.connectingPromise = null;
                    if (this.onStatusChange) this.onStatusChange(false);
                    if (this.ws) {
                        this.ws.onopen = null;
                        this.ws.onmessage = null;
                        this.ws.onclose = null;
                        this.ws.onerror = null;
                        this.ws.close();
                        this.ws = null;
                    }
                    reject(new Error('WebSocket connection timeout'));
                }
            }, 5000);

            try {
                this.ws = new WebSocket(this.url);
            } catch (err) {
                clearTimeout(connectionTimeout);
                this.status = 'DISCONNECTED';
                this.connectingPromise = null;
                if (this.onStatusChange) this.onStatusChange(false);
                reject(err);
                return;
            }
 
            this.ws.onopen = () => {
                clearTimeout(connectionTimeout);
                this.connectingPromise = null;
                console.info('[WSRPC] ✅ Соединение с сервером установлено.');
                this.status = 'CONNECTED';
                wsStatus.set('CONNECTED');
                wsConnected.set(true);
 
                // Оповещаем UI о подключении
                if (this.onStatusChange) this.onStatusChange(true);
 
                // Очищаем таймер переподключения
                if (this.reconnectTimerId) {
                    clearTimeout(this.reconnectTimerId);
                    this.reconnectTimerId = null;
                }
 
                // Вызываем триггер на подключение
                if (this.onConnect) this.onConnect();
                
                resolve();
            };
 
            this.ws.onmessage = async (event: MessageEvent) => {
                console.debug('[WSRPC] ⬇️ Входящий пакет:', event.data);
                try {
                    const data = JSON.parse(event.data);
                    await this.handleIncomingMessage(data);
                } catch (err) {
                    console.error('[WSRPC] ❌ Ошибка парсинга входящего JSON:', err);
                }
            };
 
            this.ws.onclose = (event) => {
                clearTimeout(connectionTimeout);
                this.connectingPromise = null;
                this.status = 'DISCONNECTED';
                wsStatus.set('DISCONNECTED');
                wsConnected.set(false);
                
                if (this.onStatusChange) this.onStatusChange(false);
                
                // Отклоняем промис подключения, если оно завершилось до открытия (onopen)
                reject(new Error(`WebSocket connection closed (code: ${event.code})`));

                // Отклоняем все зависшие RPC-запросы
                this.cleanup(new Error('WebSocket disconnected'));
 
                // Запускаем авто-реконнект, если сокет не закрыт вручную и он включен
                if (!this.isIntentionallyClosed && this.reconnectWs > 0) {
                    console.warn(`[WSRPC] 🔌 Соединение потеряно (код: ${event.code}). Реконнект через ${this.reconnectWs} сек...`);
                    if (!this.reconnectTimerId) {
                        this.reconnectTimerId = window.setTimeout(() => {
                            this.reconnectTimerId = null;
                            this.connect();
                        }, this.reconnectWs * 1000);
                    }
                }
            };
 
            this.ws.onerror = (error) => {
                clearTimeout(connectionTimeout);
                this.connectingPromise = null;
                console.error('[WSRPC] 🚨 Ошибка сокета:', error);
                reject(error);
            };
        });
        return this.connectingPromise;
    }

    /** 
     * Принудительное закрытие соединения 
     */
    disconnect() {
        this.isIntentionallyClosed = true;
        if (this.ws) {
            this.ws.close();
        }
    }

    /**
     * Регистрация клиентского метода для вызова сервером (совместимость со старым wsrpc.ts)
     * Поддерживает передачу позиционных (массив) и именованных (объект) аргументов.
     */
    register(rpcName: string, handlerFunc: Function) {
        this.serverMethods.set(rpcName, async (params) => {
            if (Array.isArray(params)) {
                return handlerFunc(...params); // Раскрываем массив аргументов
            }
            return handlerFunc(params); // Передаем объект
        });
    }

    /**
     * Алиас для register (декларативное имя)
     */
    registerMethod(rpcName: string, handlerFunc: Function) {
        this.register(rpcName, handlerFunc);
    }

    /**
     * Подписка на событие / нотификацию от сервера с возвратом функции отписки
     */
    on(event: string, handler: (data: any) => void): () => void {
        this.register(event, handler);
        return () => {
            this.serverMethods.delete(event);
        };
    }

    /**
     * Отправка запроса к серверу. Возвращает Promise с результатом.
     */
    async request(method: string, params: any = {}, timeoutMs = 15000): Promise<any> {
        if (this.status !== 'CONNECTED' || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
            try {
                await this.connect();
            } catch (err) {
                return Promise.reject(err);
            }
        }


        // Системный шлюз (Gatekeeper): гарантирует авторизацию сессии на сокете до выполнения бизнес-запросов
        const isBypassMethod = method.startsWith("login.") || method.startsWith("system.") || method.startsWith("auth.");
        if (!isBypassMethod && this.authInterceptor) {
            try {
                await this.authInterceptor();
            } catch (authErr) {
                console.warn("[WSRPC Gatekeeper] Ошибка ожидания авторизации сессии:", authErr);
            }
        }

        return new Promise((resolve, reject) => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return reject(new Error('WSRPC: Not connected to server'));
            }

            const rpcId = this.idCounter++;
            const payload = { jsonrpc: '2.0', method, params, id: rpcId };

            // Таймер таймаута для предотвращения утечки промисов
            const timeoutId = window.setTimeout(() => {
                console.warn(`[WSRPC] ⏰ Таймаут запроса [ID: ${rpcId}] -> "${method}"`);
                const pending = this.pendingRequests.get(rpcId);
                if (pending) {
                    pending.reject(new Error(`Timeout for ${method}`));
                    this.pendingRequests.delete(rpcId);
                }
            }, timeoutMs);

            this.pendingRequests.set(rpcId, { resolve, reject, timeoutId });
            this.ws.send(JSON.stringify(payload));
        });
    }

    /**
     * Совместимость со старым rpc.call
     */
    call<T = any>(rpcName: string, args: any = {}, timeoutMs = 15000): Promise<T> {
        return this.request(rpcName, args, timeoutMs);
    }

    /**
     * Вызов метода со стримингом прогресса (мультиретурн).
     * Вызывает onChunkCallback для каждого промежуточного чанка (stream: true)
     * и возвращает Promise, который резолвится финальным результатом операции.
     */
    async callStream<T = any>(
        rpcName: string,
        args: any = {},
        onChunkCallback?: (chunk: any) => void,
        timeoutMs = 60000
    ): Promise<T> {
        if (this.status !== 'CONNECTED' || !this.ws || this.ws.readyState !== WebSocket.OPEN) {
            try {
                await this.connect();
            } catch (err) {
                return Promise.reject(err);
            }
        }


        // Системный шлюз (Gatekeeper) для потоковых запросов
        const isBypassMethod = rpcName.startsWith("login.") || rpcName.startsWith("system.") || rpcName.startsWith("auth.");
        if (!isBypassMethod && this.authInterceptor) {
            try {
                await this.authInterceptor();
            } catch (authErr) {
                console.warn("[WSRPC Gatekeeper] Ошибка ожидания авторизации сессии (stream):", authErr);
            }
        }

        return new Promise((resolve, reject) => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return reject(new Error('WSRPC: Not connected to server'));
            }

            const rpcId = this.idCounter++;
            const payload = { jsonrpc: '2.0', method: rpcName, params: args, id: rpcId };

            if (onChunkCallback) {
                this.streamListeners.set(rpcId, onChunkCallback);
            }

            const timeoutId = window.setTimeout(() => {
                console.warn(`[WSRPC] ⏰ Таймаут стрим-запроса [ID: ${rpcId}] -> "${rpcName}"`);
                const pending = this.pendingRequests.get(rpcId);
                if (pending) {
                    pending.reject(new Error(`Timeout for ${rpcName}`));
                    this.pendingRequests.delete(rpcId);
                    this.streamListeners.delete(rpcId);
                }
            }, timeoutMs);

            this.pendingRequests.set(rpcId, { resolve, reject, timeoutId });
            this.ws.send(JSON.stringify(payload));
        });
    }

    /**
     * Подписка на стрим (совместимость со старым rpc.subscribeStream в wsrpc.ts).
     * Сервер будет присылать пакеты с результатом, помеченным как {"stream": true}.
     */
    subscribeStream(rpcName: string, args: any = {}, onChunkCallback: (data: any) => void) {
        if (!this.ws || this.status !== 'CONNECTED') {
            throw new Error('WSRPC: Not connected to server');
        }

        const rpcId = this.idCounter++;
        const payload = { jsonrpc: '2.0', method: rpcName, params: args, id: rpcId };

        this.streamListeners.set(rpcId, onChunkCallback);
        this.ws.send(JSON.stringify(payload));

        // Возвращаем функцию отписки
        return () => {
            this.streamListeners.delete(rpcId);
        };
    }

    /**
     * Обработка всех входящих сообщений
     */
    private async handleIncomingMessage(data: any) {
        const rpcId = data.id;

        // 1. Проверяем, не является ли ответ чанком стрима (stream: true)
        if (rpcId !== undefined && data.result && data.result.stream) {
            const listener = this.streamListeners.get(rpcId);
            if (listener) {
                listener(unpackTabular(data.result.data));
                return;
            }
        }

        // 2. Стандартный ответ сервера на наш запрос (содержит result или error)
        if (rpcId !== undefined && ('result' in data || 'error' in data)) {
            const pending = this.pendingRequests.get(rpcId);
            if (!pending) return;
            clearTimeout(pending.timeoutId);
            this.pendingRequests.delete(rpcId);
            this.streamListeners.delete(rpcId);

            if ('error' in data) {
                pending.reject(data.error.message || data.error);
            } else {
                pending.resolve(unpackTabular(data.result));
            }
            return;
        }

        // 3. Запрос от сервера к нам (симметричный RPC)
        if ('method' in data) {
            const method = data.method;
            const handler = this.serverMethods.get(method);
            if (!handler) {
                if (rpcId !== null && rpcId !== undefined) {
                    this.sendRaw({ 
                        jsonrpc: '2.0', 
                        error: { code: -32601, message: `Method '${method}' not found` }, 
                        id: rpcId 
                    });
                }
                return;
            }
            try {
                const result = await handler(unpackTabular(data.params || {}));
                if (rpcId !== null && rpcId !== undefined) {
                    this.sendRaw({ jsonrpc: '2.0', result, id: rpcId });
                }
            } catch (err: any) {
                if (rpcId !== null && rpcId !== undefined) {
                    this.sendRaw({ 
                        jsonrpc: '2.0', 
                        error: { code: -32603, message: err.message || String(err) }, 
                        id: rpcId 
                    });
                }
            }
        }
    }

    /**
     * Отправка сырого сообщения в вебсокет
     */
    private sendRaw(payload: any) {
        if (this.ws && this.status === 'CONNECTED') {
            this.ws.send(JSON.stringify(payload));
        }
    }

    /**
     * Очистка реестра ожидающих промисов при разрыве соединения
     */
    private cleanup(error: Error) {
        for (const pending of this.pendingRequests.values()) {
            clearTimeout(pending.timeoutId);
            pending.reject(error);
        }
        this.pendingRequests.clear();
        this.streamListeners.clear();
    }
}

// Глобальный синглтон-клиент WSRPC
export const rpc = new BinaryWSRPC();
export default rpc;
