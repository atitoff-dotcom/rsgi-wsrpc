<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { rpc } from "../wsrpc_client";

  interface Props {
    lang: "ru" | "en";
  }

  let { lang }: Props = $props();

  type SystemTab = "sessions" | "cache" | "broadcast" | "logs" | "config";
  let activeTab = $state<SystemTab>("sessions");

  // --- Состояния вкладок ---
  // 1. Сессии
  let sessions = $state<any[]>([]);
  let loadingSessions = $state(false);
  let sessionActionMsg = $state<string | null>(null);

  // 2. Smart Cache
  let cacheStats = $state<any[]>([]);
  let loadingCache = $state(false);
  let customTagInput = $state("");
  let cacheActionMsg = $state<string | null>(null);

  // 3. Broadcast
  const BROADCAST_LEVELS = ["info", "success", "warning", "error"] as const;
  let broadcastMsg = $state("");
  let broadcastTitle = $state("");
  let broadcastLevel = $state<"info" | "warning" | "error" | "success">("info");
  let sendingBroadcast = $state(false);
  let broadcastResult = $state<string | null>(null);

  // 4. Логи
  let logs = $state<any[]>([]);
  let loadingLogs = $state(false);
  let logFilterLevel = $state<string>("ALL");
  let logSearch = $state("");
  let autoRefreshLogs = $state(true);
  let logTimer: any = null;

  // 5. Конфигурация
  let configData = $state<any>(null);
  let loadingConfig = $state(false);

  const t = $derived({
    ru: {
      tabs: {
        sessions: "Активные сессии",
        cache: "Smart Cache (RFC 0001)",
        broadcast: "Системные оповещения",
        logs: "Системные логи",
        config: "Конфигурация ядра",
      },
      refresh: "Обновить",
      autoRefresh: "Авто-обновление (2с)",
      sessions: {
        title: "Мониторинг WebSocket-сессий",
        subtitle: "Список открытых дуплексных подключений к серверу Granian RSGI.",
        id: "ID сессии",
        ip: "IP адрес",
        user: "Пользователь",
        role: "Роль",
        idle: "Бездействие",
        status: "Статус",
        action: "Действие",
        currentSession: "Текущая сессия",
        connected: "Подключен",
        kick: "Отключить",
        kickConfirm: "Принудительно разорвать соединение с сессией",
        noSessions: "Нет активных сессий",
        secAgo: "сек. назад",
      },
      cache: {
        title: "Smart Cache (RFC 0001)",
        subtitle: "Инспекция монотонных версий тегов и мгновенная реактивная инвалидация.",
        tag: "Тег кэша",
        version: "Монотонная версия",
        invalidate: "Сбросить тег",
        customTagPlaceholder: "Введите имя тега (например, tasks или forum.topic.42)...",
        invalidateBtn: "Инвалидировать тег",
        noTags: "Реестр тегов пуст",
      },
      broadcast: {
        title: "Системная O(1) Zero-Copy Рассылка",
        subtitle: "Мгновенное всплывающее оповещение всем подключенным сокетам без блокировки.",
        titleLabel: "Заголовок уведомления:",
        titlePlaceholder: "Например: Плановые технические работы",
        msgLabel: "Текст сообщения:",
        msgPlaceholder: "Введите важное системное сообщение для пользователей...",
        levelLabel: "Уровень важности:",
        sendBtn: "Отправить оповещение",
        sending: "Отправка...",
      },
      logs: {
        title: "Оперативный журнал сервера",
        subtitle: "Кольцевой буфер событий ядра и RPC-запросов из памяти приложения.",
        filterAll: "Все уровни",
        searchPlaceholder: "Поиск по логам...",
        noLogs: "Записей в журнале нет",
      },
      config: {
        title: "Параметры ядра (Runtime Config)",
        subtitle: "Конфигурация Code-First / 12-Factor App с защитой секретных ключей.",
        security: "Безопасность и таймауты",
        database: "База данных и хранилище",
      }
    },
    en: {
      tabs: {
        sessions: "Active Sessions",
        cache: "Smart Cache (RFC 0001)",
        broadcast: "Broadcast Alerts",
        logs: "Live Logs",
        config: "Runtime Config",
      },
      refresh: "Refresh",
      autoRefresh: "Auto-refresh (2s)",
      sessions: {
        title: "WebSocket Sessions Monitor",
        subtitle: "Active duplex client connections on Granian RSGI server.",
        id: "Session ID",
        ip: "IP Address",
        user: "User",
        role: "Role",
        idle: "Idle Time",
        status: "Status",
        action: "Action",
        currentSession: "Current session",
        connected: "Connected",
        kick: "Disconnect",
        kickConfirm: "Force disconnect session",
        noSessions: "No active sessions",
        secAgo: "sec ago",
      },
      cache: {
        title: "Smart Cache (RFC 0001)",
        subtitle: "Tag version registry inspection and instant reactive invalidation.",
        tag: "Cache Tag",
        version: "Monotonic Version",
        invalidate: "Invalidate",
        customTagPlaceholder: "Enter cache tag name...",
        invalidateBtn: "Invalidate Tag",
        noTags: "Tag registry is empty",
      },
      broadcast: {
        title: "System O(1) Zero-Copy Broadcast",
        subtitle: "Instant non-blocking notification to all connected WebSockets.",
        titleLabel: "Alert Title:",
        titlePlaceholder: "e.g. Scheduled Maintenance",
        msgLabel: "Message Body:",
        msgPlaceholder: "Enter urgent system broadcast message...",
        levelLabel: "Severity Level:",
        sendBtn: "Send Broadcast",
        sending: "Sending...",
      },
      logs: {
        title: "Live Server Log Streamer",
        subtitle: "Ring buffer of core events and RPC calls in server memory.",
        filterAll: "All levels",
        searchPlaceholder: "Search logs...",
        noLogs: "No log records found",
      },
      config: {
        title: "Runtime Engine Config",
        subtitle: "Code-First / 12-Factor App settings with masked secrets.",
        security: "Security & Timeouts",
        database: "Database & Storage",
      }
    }
  }[lang]);

  // Загрузка активных сессий
  async function loadSessions() {
    loadingSessions = true;
    sessionActionMsg = null;
    try {
      const res = await rpc.call("admin.sessions_list", {});
      sessions = Array.isArray(res) ? res : [];
    } catch (e: any) {
      console.error("[System Cockpit] Ошибка загрузки сессий:", e);
      sessionActionMsg = e?.message || "Ошибка загрузки сессий";
    } finally {
      loadingSessions = false;
    }
  }

  // Принудительное отключение сессии (Kick)
  async function killSession(sessionId: number, username: string) {
    if (!confirm(`${t.sessions.kickConfirm} #${sessionId} (${username})?`)) return;
    try {
      await rpc.call("admin.session_kill", { session_id: sessionId });
      sessionActionMsg = `Сессия #${sessionId} успешно отключена`;
      await loadSessions();
    } catch (e: any) {
      alert(`Ошибка отключения: ${e?.message || e}`);
    }
  }

  // Загрузка статистики Smart Cache
  async function loadCacheStats() {
    loadingCache = true;
    cacheActionMsg = null;
    try {
      const res = await rpc.call("system.cache_stats", {});
      cacheStats = Array.isArray(res) ? res : [];
    } catch (e: any) {
      console.error("[System Cockpit] Ошибка кэша:", e);
      cacheActionMsg = e?.message || "Ошибка загрузки кэша";
    } finally {
      loadingCache = false;
    }
  }

  // Инвалидация тега
  async function invalidateTags(tagNames: string[]) {
    try {
      const res = await rpc.call("system.cache_invalidate", { tags: tagNames });
      cacheActionMsg = `Теги успешно инвалидированы: ${tagNames.join(", ")}`;
      customTagInput = "";
      await loadCacheStats();
    } catch (e: any) {
      alert(`Ошибка инвалидации: ${e?.message || e}`);
    }
  }

  // Отправка системного Broadcast
  async function sendBroadcast() {
    if (!broadcastMsg.trim()) return;
    sendingBroadcast = true;
    broadcastResult = null;
    try {
      const res: any = await rpc.call("system.broadcast", {
        message: broadcastMsg.trim(),
        title: broadcastTitle.trim() || undefined,
        level: broadcastLevel,
      });
      broadcastResult = `Оповещение успешно доставлено ${res?.delivered_count ?? 0} клиентам!`;
      broadcastMsg = "";
      broadcastTitle = "";
    } catch (e: any) {
      broadcastResult = `Ошибка отправки: ${e?.message || e}`;
    } finally {
      sendingBroadcast = false;
    }
  }

  // Загрузка системных логов
  async function loadLogs() {
    loadingLogs = true;
    try {
      const res = await rpc.call("system.recent_logs", { limit: 120 });
      logs = Array.isArray(res) ? res : [];
    } catch (e: any) {
      console.error("[System Cockpit] Ошибка загрузки логов:", e);
    } finally {
      loadingLogs = false;
    }
  }

  // Загрузка конфигурации ядра
  async function loadConfig() {
    loadingConfig = true;
    try {
      const res = await rpc.call("system.get_config", {});
      configData = res || {};
    } catch (e: any) {
      console.error("[System Cockpit] Ошибка конфигурации:", e);
    } finally {
      loadingConfig = false;
    }
  }

  // Реакция на переключение вкладок
  $effect(() => {
    if (activeTab === "sessions") loadSessions();
    else if (activeTab === "cache") loadCacheStats();
    else if (activeTab === "logs") loadLogs();
    else if (activeTab === "config") loadConfig();
  });

  // Авто-обновление логов
  $effect(() => {
    if (activeTab === "logs" && autoRefreshLogs) {
      logTimer = setInterval(() => {
        loadLogs();
      }, 2000);
    } else {
      if (logTimer) clearInterval(logTimer);
    }
    return () => {
      if (logTimer) clearInterval(logTimer);
    };
  });

  const filteredLogs = $derived(
    logs.filter((item) => {
      if (logFilterLevel !== "ALL" && item.level !== logFilterLevel) return false;
      if (logSearch.trim()) {
        const q = logSearch.toLowerCase();
        const m = (item.message || "").toLowerCase();
        const c = (item.ctx || "").toLowerCase();
        const l = (item.logger || "").toLowerCase();
        return m.includes(q) || c.includes(q) || l.includes(q);
      }
      return true;
    })
  );

  onMount(() => {
    loadSessions();
  });

  onDestroy(() => {
    if (logTimer) clearInterval(logTimer);
  });
</script>

<div class="flex-1 flex flex-col p-6 overflow-y-auto gap-6 bg-background">
  <!-- Верхний блок переключения системных инструментов -->
  <div class="flex flex-wrap items-center justify-between gap-4 pb-4 border-b border-border">
    <div class="flex items-center gap-2">
      <span class="text-xl">⚙️</span>
      <div>
        <h2 class="text-lg font-bold tracking-tight text-foreground">Mission Control Cockpit</h2>
        <p class="text-xs text-muted-foreground">Управление сетевым ядром, сессиями, кэшем и системными событиями</p>
      </div>
    </div>

    <!-- Вкладки подраздела System -->
    <div class="flex items-center gap-1.5 p-1 rounded-xl bg-card border border-border">
      <button
        type="button"
        onclick={() => (activeTab = "sessions")}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer {activeTab === 'sessions' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
      >
        👥 {t.tabs.sessions}
      </button>
      <button
        type="button"
        onclick={() => (activeTab = "cache")}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer {activeTab === 'cache' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
      >
        ⚡ {t.tabs.cache}
      </button>
      <button
        type="button"
        onclick={() => (activeTab = "broadcast")}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer {activeTab === 'broadcast' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
      >
        📢 {t.tabs.broadcast}
      </button>
      <button
        type="button"
        onclick={() => (activeTab = "logs")}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer {activeTab === 'logs' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
      >
        📜 {t.tabs.logs}
      </button>
      <button
        type="button"
        onclick={() => (activeTab = "config")}
        class="px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer {activeTab === 'config' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
      >
        🛠️ {t.tabs.config}
      </button>
    </div>
  </div>

  <!-- ВКЛАДКА 1: АКТИВНЫЕ СЕССИИ -->
  {#if activeTab === "sessions"}
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-sm font-bold text-foreground">{t.sessions.title}</h3>
          <p class="text-xs text-muted-foreground">{t.sessions.subtitle}</p>
        </div>
        <button
          type="button"
          onclick={loadSessions}
          disabled={loadingSessions}
          class="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs font-semibold hover:bg-muted transition-colors cursor-pointer disabled:opacity-50"
        >
          🔄 {t.refresh}
        </button>
      </div>

      {#if sessionActionMsg}
        <div class="p-3 rounded-lg border border-border bg-card text-xs text-foreground font-medium">
          ℹ️ {sessionActionMsg}
        </div>
      {/if}

      <div class="border border-border rounded-xl bg-card overflow-hidden shadow-2xs">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-border bg-muted/40 text-muted-foreground font-semibold">
              <th class="py-2.5 px-4">{t.sessions.id}</th>
              <th class="py-2.5 px-4">{t.sessions.ip}</th>
              <th class="py-2.5 px-4">{t.sessions.user}</th>
              <th class="py-2.5 px-4">{t.sessions.role}</th>
              <th class="py-2.5 px-4">{t.sessions.idle}</th>
              <th class="py-2.5 px-4">{t.sessions.status}</th>
              <th class="py-2.5 px-4 text-right">{t.sessions.action}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#if loadingSessions}
              <tr>
                <td colspan="7" class="py-8 text-center text-muted-foreground">Загрузка сессий...</td>
              </tr>
            {:else if sessions.length === 0}
              <tr>
                <td colspan="7" class="py-8 text-center text-muted-foreground">{t.sessions.noSessions}</td>
              </tr>
            {:else}
              {#each sessions as s (s.session_id)}
                <tr class="hover:bg-muted/20 transition-colors">
                  <td class="py-2.5 px-4 font-mono font-medium text-foreground">
                    #{s.session_id}
                  </td>
                  <td class="py-2.5 px-4 font-mono text-muted-foreground">
                    {s.ip}
                  </td>
                  <td class="py-2.5 px-4 font-semibold text-foreground">
                    {s.username}
                  </td>
                  <td class="py-2.5 px-4">
                    <span class="px-2 py-0.5 rounded-full text-2xs font-semibold border {s.role === 'admin' ? 'bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-400' : 'bg-muted border-border text-muted-foreground'}">
                      {s.role}
                    </span>
                  </td>
                  <td class="py-2.5 px-4 font-mono text-muted-foreground">
                    {s.idle_seconds} {t.sessions.secAgo}
                  </td>
                  <td class="py-2.5 px-4">
                    {#if s.is_current}
                      <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-2xs font-bold bg-emerald-500/10 border border-emerald-500/30 text-emerald-700 dark:text-emerald-400">
                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                        {t.sessions.currentSession}
                      </span>
                    {:else}
                      <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-2xs font-semibold bg-primary/10 border border-primary/30 text-primary">
                        <span class="w-1.5 h-1.5 rounded-full bg-primary"></span>
                        {t.sessions.connected}
                      </span>
                    {/if}
                  </td>
                  <td class="py-2.5 px-4 text-right">
                    {#if !s.is_current}
                      <button
                        type="button"
                        onclick={() => killSession(s.session_id, s.username)}
                        class="px-2.5 py-1 rounded-md text-2xs font-semibold bg-destructive/10 border border-destructive/20 text-destructive hover:bg-destructive hover:text-destructive-foreground transition-all cursor-pointer"
                      >
                        🔌 {t.sessions.kick}
                      </button>
                    {:else}
                      <span class="text-2xs text-muted-foreground italic">—</span>
                    {/if}
                  </td>
                </tr>
              {/each}
            {/if}
          </tbody>
        </table>
      </div>
    </div>

  <!-- ВКЛАДКА 2: SMART CACHE -->
  {:else if activeTab === "cache"}
    <div class="flex flex-col gap-4">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-sm font-bold text-foreground">{t.cache.title}</h3>
          <p class="text-xs text-muted-foreground">{t.cache.subtitle}</p>
        </div>
        <button
          type="button"
          onclick={loadCacheStats}
          disabled={loadingCache}
          class="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs font-semibold hover:bg-muted transition-colors cursor-pointer disabled:opacity-50"
        >
          🔄 {t.refresh}
        </button>
      </div>

      <!-- Ручной сброс тегов -->
      <div class="flex items-center gap-2 p-3 rounded-xl border border-border bg-card shadow-2xs">
        <input
          type="text"
          bind:value={customTagInput}
          placeholder={t.cache.customTagPlaceholder}
          class="flex-1 px-3 py-1.5 rounded-lg border border-border bg-background text-foreground text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          type="button"
          onclick={() => {
            if (customTagInput.trim()) {
              const tags = customTagInput.split(",").map((x) => x.trim()).filter(Boolean);
              invalidateTags(tags);
            }
          }}
          class="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:opacity-90 transition-opacity cursor-pointer"
        >
          ⚡ {t.cache.invalidateBtn}
        </button>
      </div>

      {#if cacheActionMsg}
        <div class="p-3 rounded-lg border border-border bg-card text-xs text-foreground font-medium">
          ✅ {cacheActionMsg}
        </div>
      {/if}

      <div class="border border-border rounded-xl bg-card overflow-hidden shadow-2xs">
        <table class="w-full text-left text-xs border-collapse">
          <thead>
            <tr class="border-b border-border bg-muted/40 text-muted-foreground font-semibold">
              <th class="py-2.5 px-4">{t.cache.tag}</th>
              <th class="py-2.5 px-4">{t.cache.version}</th>
              <th class="py-2.5 px-4 text-right">Действие</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#if loadingCache}
              <tr>
                <td colspan="3" class="py-8 text-center text-muted-foreground">Загрузка тегов кэша...</td>
              </tr>
            {:else if cacheStats.length === 0}
              <tr>
                <td colspan="3" class="py-8 text-center text-muted-foreground">{t.cache.noTags}</td>
              </tr>
            {:else}
              {#each cacheStats as c (c.tag)}
                <tr class="hover:bg-muted/20 transition-colors">
                  <td class="py-2.5 px-4 font-mono font-medium text-foreground">
                    🏷️ {c.tag}
                  </td>
                  <td class="py-2.5 px-4 font-mono font-bold text-primary">
                    v{c.version}
                  </td>
                  <td class="py-2.5 px-4 text-right">
                    <button
                      type="button"
                      onclick={() => invalidateTags([c.tag])}
                      class="px-2.5 py-1 rounded-md text-2xs font-semibold border border-primary/30 text-primary hover:bg-primary hover:text-primary-foreground transition-all cursor-pointer"
                    >
                      ⚡ {t.cache.invalidate}
                    </button>
                  </td>
                </tr>
              {/each}
            {/if}
          </tbody>
        </table>
      </div>
    </div>

  <!-- ВКЛАДКА 3: BROADCAST -->
  {:else if activeTab === "broadcast"}
    <div class="flex flex-col gap-4 max-w-2xl">
      <div>
        <h3 class="text-sm font-bold text-foreground">{t.broadcast.title}</h3>
        <p class="text-xs text-muted-foreground">{t.broadcast.subtitle}</p>
      </div>

      <div class="flex flex-col gap-4 p-5 rounded-xl border border-border bg-card shadow-2xs">
        <div class="flex flex-col gap-1.5">
          <label for="broadcast-title-input" class="text-xs font-semibold text-foreground">{t.broadcast.titleLabel}</label>
          <input
            id="broadcast-title-input"
            type="text"
            bind:value={broadcastTitle}
            placeholder={t.broadcast.titlePlaceholder}
            class="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>

        <div class="flex flex-col gap-1.5">
          <span class="text-xs font-semibold text-foreground">{t.broadcast.levelLabel}</span>
          <div class="flex items-center gap-2">
            {#each BROADCAST_LEVELS as lvl}
              <button
                type="button"
                onclick={() => (broadcastLevel = lvl)}
                class="px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all cursor-pointer {broadcastLevel === lvl ? 'bg-primary text-primary-foreground border-primary' : 'bg-background text-foreground border-border hover:bg-muted'}"
              >
                {lvl.toUpperCase()}
              </button>
            {/each}
          </div>
        </div>

        <div class="flex flex-col gap-1.5">
          <label for="broadcast-msg-input" class="text-xs font-semibold text-foreground">{t.broadcast.msgLabel}</label>
          <textarea
            id="broadcast-msg-input"
            bind:value={broadcastMsg}
            rows="3"
            placeholder={t.broadcast.msgPlaceholder}
            class="px-3 py-2 rounded-lg border border-border bg-background text-foreground text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary resize-none"
          ></textarea>
        </div>


        {#if broadcastResult}
          <div class="p-3 rounded-lg border border-border bg-muted/40 text-xs text-foreground font-medium">
            📢 {broadcastResult}
          </div>
        {/if}

        <div class="flex items-center justify-end">
          <button
            type="button"
            onclick={sendBroadcast}
            disabled={sendingBroadcast || !broadcastMsg.trim()}
            class="px-4 py-2 rounded-lg text-xs font-bold bg-primary text-primary-foreground hover:opacity-90 transition-opacity cursor-pointer disabled:opacity-50 shadow-xs"
          >
            {sendingBroadcast ? t.broadcast.sending : t.broadcast.sendBtn}
          </button>
        </div>
      </div>
    </div>

  <!-- ВКЛАДКА 4: СИСТЕМНЫЕ ЛОГИ -->
  {:else if activeTab === "logs"}
    <div class="flex flex-col gap-4">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 class="text-sm font-bold text-foreground">{t.logs.title}</h3>
          <p class="text-xs text-muted-foreground">{t.logs.subtitle}</p>
        </div>

        <div class="flex items-center gap-2">
          <!-- Фильтр уровня -->
          <select
            bind:value={logFilterLevel}
            class="px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs font-semibold focus:outline-none cursor-pointer"
          >
            <option value="ALL">{t.logs.filterAll}</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="DEBUG">DEBUG</option>
          </select>

          <!-- Поиск -->
          <input
            type="text"
            bind:value={logSearch}
            placeholder={t.logs.searchPlaceholder}
            class="px-3 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs placeholder:text-muted-foreground focus:outline-none"
          />

          <!-- Тумблер авто-обновления -->
          <button
            type="button"
            onclick={() => (autoRefreshLogs = !autoRefreshLogs)}
            class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border text-xs font-semibold transition-all cursor-pointer {autoRefreshLogs ? 'bg-primary/10 border-primary/30 text-primary' : 'bg-card text-muted-foreground'}"
          >
            <span class="w-2 h-2 rounded-full {autoRefreshLogs ? 'bg-primary animate-pulse' : 'bg-muted-foreground'}"></span>
            {t.autoRefresh}
          </button>

          <button
            type="button"
            onclick={loadLogs}
            class="px-3 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs font-semibold hover:bg-muted transition-colors cursor-pointer"
          >
            🔄
          </button>
        </div>
      </div>

      <!-- Терминал логов -->
      <div class="rounded-xl border border-border bg-[#1f1611] text-[#ece4d9] font-mono text-xs p-4 overflow-x-auto max-h-[600px] overflow-y-auto shadow-inner flex flex-col gap-1.5">
        {#if filteredLogs.length === 0}
          <div class="py-12 text-center text-[#8e7e72] italic font-sans">{t.logs.noLogs}</div>
        {:else}
          {#each filteredLogs as l}
            <div class="leading-relaxed hover:bg-white/5 px-2 py-0.5 rounded transition-colors flex items-start gap-2">
              <span class="text-[#8e7e72] shrink-0 select-none">[{l.time_str || ""}]</span>
              <span class="font-bold shrink-0 {l.level === 'ERROR' ? 'text-red-400' : l.level === 'WARNING' ? 'text-amber-400' : l.level === 'INFO' ? 'text-emerald-400' : 'text-cyan-400'}">
                [{l.level}]
              </span>
              <span class="text-[#ab9c90] shrink-0 font-semibold">{l.ctx}</span>
              <span class="text-[#dfd7cc] break-all">{l.message}</span>
            </div>
          {/each}
        {/if}
      </div>
    </div>

  <!-- ВКЛАДКА 5: КОНФИГУРАЦИЯ -->
  {:else if activeTab === "config"}
    <div class="flex flex-col gap-4 max-w-3xl">
      <div class="flex items-center justify-between">
        <div>
          <h3 class="text-sm font-bold text-foreground">{t.config.title}</h3>
          <p class="text-xs text-muted-foreground">{t.config.subtitle}</p>
        </div>
        <button
          type="button"
          onclick={loadConfig}
          disabled={loadingConfig}
          class="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-card text-foreground text-xs font-semibold hover:bg-muted transition-colors cursor-pointer disabled:opacity-50"
        >
          🔄 {t.refresh}
        </button>
      </div>

      {#if loadingConfig || !configData}
        <div class="py-12 text-center text-muted-foreground">Загрузка параметров ядра...</div>
      {:else}
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <!-- Секция Безопасность -->
          <div class="flex flex-col gap-3 p-4 rounded-xl border border-border bg-card shadow-2xs">
            <h4 class="text-xs font-bold uppercase tracking-wider text-primary">🛡️ {t.config.security}</h4>
            <div class="flex flex-col gap-2 text-xs">
              {#if configData.security}
                <div class="flex justify-between py-1 border-b border-border">
                  <span class="text-muted-foreground">Secret Key:</span>
                  <span class="font-mono font-medium text-foreground">{configData.security.secret_key || "••••••••"}</span>
                </div>
                <div class="flex justify-between py-1 border-b border-border">
                  <span class="text-muted-foreground">Гостевой доступ:</span>
                  <span class="font-semibold {configData.security.allow_guests ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-500'}">
                    {configData.security.allow_guests ? "Разрешен" : "Запрещен"}
                  </span>
                </div>
                <div class="flex justify-between py-1 border-b border-border">
                  <span class="text-muted-foreground">Таймаут гостей:</span>
                  <span class="font-mono text-foreground">{configData.security.guest_idle_timeout} сек.</span>
                </div>
                <div class="flex justify-between py-1 border-b border-border">
                  <span class="text-muted-foreground">Таймаут пользователей:</span>
                  <span class="font-mono text-foreground">{configData.security.user_idle_timeout} сек.</span>
                </div>
                <div class="flex justify-between py-1 border-b border-border">
                  <span class="text-muted-foreground">Итерации паролей:</span>
                  <span class="font-mono text-foreground">{configData.security.password_iterations}</span>
                </div>
                <div class="flex justify-between py-1">
                  <span class="text-muted-foreground">Срок JWT токена:</span>
                  <span class="font-mono text-foreground">{configData.security.token_expire_hours} ч.</span>
                </div>
              {/if}
            </div>
          </div>

          <!-- Секция Хранилище -->
          <div class="flex flex-col gap-3 p-4 rounded-xl border border-border bg-card shadow-2xs">
            <h4 class="text-xs font-bold uppercase tracking-wider text-primary">🗄️ {t.config.database}</h4>
            <div class="flex flex-col gap-2 text-xs">
              <div class="flex flex-col gap-1 py-1 border-b border-border">
                <span class="text-muted-foreground">Database URL:</span>
                <span class="font-mono text-foreground break-all">{configData.database_url || "sqlite:///..."}</span>
              </div>
              <div class="flex flex-col gap-1 py-1">
                <span class="text-muted-foreground">Каталог файлов:</span>
                <span class="font-mono text-foreground">{configData.files_path || "./files"}</span>
              </div>
            </div>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>
