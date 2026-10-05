export class StandaloneWSRPC {
    public status: 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED' = 'DISCONNECTED';
    public onStatusChange: ((status: 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED') => void) | null = null;
    
    private ws: WebSocket | null = null;
    private idCounter = 0;
    private pendingRequests = new Map<number | string, { resolve: (val: any) => void; reject: (err: any) => void; timer: any }>();
    private handlers = new Map<string, (params: any) => void>();
    private url: string;
    private reconnectTimer: any = null;

    constructor(url?: string) {
        if (url) {
            this.url = url;
        } else if (typeof window !== 'undefined') {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.url = `${proto}//${window.location.host}`;
        } else {
            this.url = 'ws://127.0.0.1:8080';
        }
    }

    connect(): Promise<void> {
        return new Promise((resolve) => {
            if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
                return resolve();
            }

            this.setStatus('CONNECTING');
            try {
                this.ws = new WebSocket(this.url);
            } catch (e) {
                this.scheduleReconnect();
                return resolve();
            }

            this.ws.onopen = () => {
                this.setStatus('CONNECTED');
                if (this.reconnectTimer) {
                    clearTimeout(this.reconnectTimer);
                    this.reconnectTimer = null;
                }
                resolve();
            };

            this.ws.onmessage = (event) => {
                this.handleMessage(event.data);
            };

            this.ws.onclose = () => {
                this.setStatus('DISCONNECTED');
                this.scheduleReconnect();
            };

            this.ws.onerror = () => {
                this.setStatus('DISCONNECTED');
            };
        });
    }

    private setStatus(s: 'CONNECTING' | 'CONNECTED' | 'DISCONNECTED') {
        this.status = s;
        if (this.onStatusChange) {
            this.onStatusChange(s);
        }
    }

    private scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, 3000);
    }

    private handleMessage(data: string) {
        try {
            const msg = JSON.parse(data);
            // Ответ на запрос (response)
            if (msg.id !== undefined && (msg.result !== undefined || msg.error !== undefined)) {
                const req = this.pendingRequests.get(msg.id);
                if (req) {
                    clearTimeout(req.timer);
                    this.pendingRequests.delete(msg.id);
                    if (msg.error) {
                        req.reject(new Error(msg.error.message || msg.error));
                    } else {
                        req.resolve(msg.result);
                    }
                }
                return;
            }

            // Уведомление или входящий метод от сервера (например, cache.patch)
            if (msg.method) {
                const handler = this.handlers.get(msg.method);
                if (handler) {
                    handler(msg.params);
                }
            }
        } catch (e) {
            console.error('[WSRPC] Ошибка парсинга сообщения:', e);
        }
    }

    call(method: string, params: any = {}): Promise<any> {
        return new Promise((resolve, reject) => {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
                return reject(new Error('WebSocket не подключен'));
            }

            const id = ++this.idCounter;
            const timer = setTimeout(() => {
                this.pendingRequests.delete(id);
                reject(new Error(`Превышено время ожидания ответа от метода '${method}'`));
            }, 15000);

            this.pendingRequests.set(id, { resolve, reject, timer });

            const payload = JSON.stringify({
                jsonrpc: '2.0',
                id,
                method,
                params
            });

            this.ws.send(payload);
        });
    }

    register(method: string, handler: (params: any) => void) {
        this.handlers.set(method, handler);
    }

    unregister(method: string) {
        this.handlers.delete(method);
    }
}
