<script lang="ts">
  import { onMount } from "svelte";
  import { rpc, wsStatus as canonicalWsStatus, unpackTabular } from "@wsrpc/wsrpc";
  import docsManifest from "@content/showcase_docs.json";

  import Button from "./components/ui/Button.svelte";
  import Input from "./components/ui/Input.svelte";
  import Badge from "./components/ui/Badge.svelte";
  import Modal from "./components/ui/Modal.svelte";
  import CodeInspector from "./components/CodeInspector.svelte";

  // Язык витрины (RU / EN)
  type Lang = "ru" | "en";
  let lang = $state<Lang>((localStorage.getItem("showcase_lang") as Lang) || "ru");

  function toggleLang() {
    lang = lang === "ru" ? "en" : "ru";
    localStorage.setItem("showcase_lang", lang);
  }

  // WSRPC Состояние сети и метрики
  let wsState = $state<"CONNECTING" | "CONNECTED" | "DISCONNECTED">("CONNECTING");
  let rttMs = $state<number | null>(null);
  let activeSocketsCount = $state<number>(1);

  // Текущий пользователь и роль
  interface AuthState {
    authenticated: boolean;
    role: string;
    username: string;
    userId: number | null;
  }
  let auth = $state<AuthState>({
    authenticated: false,
    role: "guest",
    username: "Гость",
    userId: null
  });

  // Модалка авторизации
  let isLoginModalOpen = $state(false);
  let loginUsername = $state("");
  let loginPassword = $state("");
  let loginError = $state("");
  let isLoggingIn = $state(false);

  // Логи событий для песочниц
  interface LogItem {
    time: string;
    text: string;
    type?: "info" | "success" | "warn" | "error";
  }

  function getTimeStr() {
    return new Date().toTimeString().split(" ")[0];
  }

  // Состояния песочниц
  // 1. Overview
  let overviewLogs = $state<LogItem[]>([]);
  // 2. Tabular
  let tabularTasks = $state<any[]>([]);
  let rawJsonBytes = $state<number>(0);
  let tabularWireBytes = $state<number>(0);
  let compressionRatio = $state<string>("0%");
  let tabularWireSnippet = $state<string>("");
  // 3. Cache
  let cacheLogs = $state<LogItem[]>([]);
  let cacheVersion = $state<number>(1);
  // 4. CRUD
  let crudLogs = $state<LogItem[]>([]);
  // 5. Streaming
  let streamProgress = $state<number>(0);
  let streamLogs = $state<LogItem[]>([]);
  let isStreaming = $state(false);
  // 6. Reverse RPC
  let reverseRpcLogs = $state<LogItem[]>([]);
  // 7. Broadcast
  let broadcastLogs = $state<LogItem[]>([]);
  let alertMessage = $state("Серверное уведомление в реальном времени!");
  // 8. 2PC Files
  let uploadStatus = $state("");
  let uploadedFilesCount = $state(0);
  let currentFolderHash = $state("");
  // 9. RBAC
  let rbacLogs = $state<LogItem[]>([]);
  // 10. SEO
  let seoLogs = $state<LogItem[]>([]);

  // Тексты UI
  const t = $derived({
    ru: {
      brandSub: "Интерактивная витрина и живая документация",
      connecting: "Подключение к WSRPC...",
      online: "WSRPC Онлайн",
      disconnected: "Нет соединения",
      rtt: (ms: number | null) => `RTT: ${ms !== null ? ms : "--"} мс`,
      sockets: (cnt: number) => `Активные сокеты: ${cnt}`,
      guest: "Гость",
      signIn: "🔑 Войти",
      signOut: "Выйти",
      openCrud: "🗄️ Панель CRUD",
      navArch: "Архитектура и протокол",
      navPlugins: "Плагины и возможности",
      btnPing: "📡 Вызвать system.ping",
      btnSysInfo: "🔍 Запросить system.info",
      btnTabular: "🔄 Запросить tasks.list (Tabular)",
      btnRawJson: "Сравнить tasks.list_raw_json",
      rawSize: "Размер сырого JSON:",
      tabularSize: "Размер Tabular пакета:",
      savedPct: "Сэкономлено трафика:",
      btnFetchCache: "Запросить с кэшем",
      btnInvalidate: "Инвалидировать тег",
      btnOpenCrudUi: "Открыть CRUD UI (/crud)",
      btnCrudSchema: "Запросить crud.schema",
      btnStartStream: "Запустить стриминг",
      btnTriggerReverse: "Вызвать Reverse RPC с сервера",
      btnSendBroadcast: "Отправить Broadcast",
      btnTestCreateTask: "Создать задачу (tasks.create)",
      btnSimGoogle: "Проверить как Googlebot",
      btnSimBrowser: "Проверить как Браузер",
      loginModalTitle: "🔐 Вход в демонстрационную систему",
      username: "Логин",
      password: "Пароль",
      quickPresets: "Быстрый выбор роли:",
      cancel: "Отмена",
      loginSubmit: "Войти",
      footerText: "rsgi-wsrpc framework • На базе Granian (Rust) и SQLAlchemy 2.0 • 2026",
      wireFrame: "Сырой сетевой пакет:",
      trafficComparison: "Сравнение сетевого трафика:"
    },
    en: {
      brandSub: "Interactive Showcase & Living Documentation",
      connecting: "Connecting to WSRPC...",
      online: "WSRPC Online",
      disconnected: "Disconnected",
      rtt: (ms: number | null) => `RTT: ${ms !== null ? ms : "--"} ms`,
      sockets: (cnt: number) => `Active Sockets: ${cnt}`,
      guest: "Guest",
      signIn: "🔑 Sign In",
      signOut: "Sign Out",
      openCrud: "🗄️ Open CRUD UI",
      navArch: "Architecture & Protocol",
      navPlugins: "Plugins & Capabilities",
      btnPing: "📡 Call system.ping",
      btnSysInfo: "🔍 Request system.info",
      btnTabular: "🔄 Fetch tasks.list (Tabular)",
      btnRawJson: "Compare tasks.list_raw_json",
      rawSize: "Raw JSON Wire Size:",
      tabularSize: "Tabular Wire Size:",
      savedPct: "Bandwidth Saved:",
      btnFetchCache: "Fetch with Cache",
      btnInvalidate: "Invalidate Tag",
      btnOpenCrudUi: "Open CRUD UI (/crud)",
      btnCrudSchema: "Request crud.schema",
      btnStartStream: "Start Streaming",
      btnTriggerReverse: "Trigger Server-to-Client RPC",
      btnSendBroadcast: "Send Broadcast Alert",
      btnTestCreateTask: "Create Task (tasks.create)",
      btnSimGoogle: "Simulate Googlebot",
      btnSimBrowser: "Simulate Browser",
      loginModalTitle: "🔐 Sign In to Showcase",
      username: "Username",
      password: "Password",
      quickPresets: "Quick Role Presets:",
      cancel: "Cancel",
      loginSubmit: "Sign In",
      footerText: "rsgi-wsrpc framework • Powered by Granian (Rust) & SQLAlchemy 2.0 • 2026",
      wireFrame: "Raw Network Frame:",
      trafficComparison: "Network Traffic Comparison:"
    }
  }[lang]);

  onMount(() => {
    // Регистрация Reverse RPC метода (браузер отвечает серверу)
    rpc.register("client.get_env", () => {
      const info = {
        userAgent: navigator.userAgent,
        language: navigator.language,
        screenWidth: window.screen.width,
        screenHeight: window.screen.height,
        time: new Date().toISOString()
      };
      reverseRpcLogs = [
        ...reverseRpcLogs,
        { time: getTimeStr(), text: `[REVERSE RPC] Сервер запросил окружение: ${JSON.stringify(info)}`, type: "success" }
      ];
      return info;
    });

    // Прослушивание Broadcast уведомлений
    rpc.on("system.alert", (data: any) => {
      broadcastLogs = [
        ...broadcastLogs,
        { time: getTimeStr(), text: `📢 Broadcast: ${data.message || JSON.stringify(data)}`, type: "warn" }
      ];
    });

    // Прослушивание инвалидации кэша
    rpc.on("cache.invalidate", (data: any) => {
      cacheLogs = [
        ...cacheLogs,
        { time: getTimeStr(), text: `🔄 Сброс кэша по тегам: ${JSON.stringify(data.tags)} (v${data.version || '?'})`, type: "info" }
      ];
    });

    // Статус сокета
    canonicalWsStatus.subscribe((s) => {
      if (s === "CONNECTED") {
        wsState = "CONNECTED";
        measureRtt();
        checkAuthMe();
      } else if (s === "CONNECTING") {
        wsState = "CONNECTING";
      } else {
        wsState = "DISCONNECTED";
      }
    });

    // Периодический пинг RTT
    const rttInterval = setInterval(() => {
      if (wsState === "CONNECTED") {
        measureRtt();
      }
    }, 5000);

    return () => clearInterval(rttInterval);
  });

  async function measureRtt() {
    const t0 = performance.now();
    try {
      await rpc.call("system.ping");
      rttMs = Math.round(performance.now() - t0);
    } catch {
      rttMs = null;
    }
  }

  async function checkAuthMe() {
    try {
      const res = await rpc.call("auth.me");
      if (res && res.authenticated) {
        auth = {
          authenticated: true,
          role: res.role || "user",
          username: res.name || res.username || "User",
          userId: res.user_id || null
        };
      } else {
        auth = { authenticated: false, role: "guest", username: t.guest, userId: null };
      }
    } catch {
      auth = { authenticated: false, role: "guest", username: t.guest, userId: null };
    }
  }

  // Действия песочниц
  async function testPing() {
    const t0 = performance.now();
    try {
      const res = await rpc.call("system.ping");
      const elapsed = Math.round(performance.now() - t0);
      overviewLogs = [
        ...overviewLogs,
        { time: getTimeStr(), text: `✔ system.ping -> ${JSON.stringify(res)} (${elapsed} ms)`, type: "success" }
      ];
    } catch (e: any) {
      overviewLogs = [...overviewLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function testSystemInfo() {
    try {
      const res = await rpc.call("system.info");
      activeSocketsCount = res.active_sessions_count || 1;
      overviewLogs = [
        ...overviewLogs,
        { time: getTimeStr(), text: `✔ system.info: Python ${res.python_version}, OS: ${res.os_platform}, Сервер: ${res.rsgi_server}`, type: "info" }
      ];
    } catch (e: any) {
      overviewLogs = [...overviewLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function loadTabularTasks() {
    try {
      const rawRes = await rpc.call("tasks.list_raw_json");
      const rawStr = JSON.stringify(rawRes);
      rawJsonBytes = new Blob([rawStr]).size;

      const tabRes = await rpc.call("tasks.list");
      tabularWireSnippet = JSON.stringify(tabRes);
      tabularWireBytes = new Blob([tabularWireSnippet]).size;

      const saved = rawJsonBytes > 0 ? Math.round(((rawJsonBytes - tabularWireBytes) / rawJsonBytes) * 100) : 0;
      compressionRatio = `${saved}%`;

      tabularTasks = unpackTabular(tabRes);
    } catch (e: any) {
      tabularWireSnippet = `Ошибка: ${e.message}`;
    }
  }

  async function loadCacheData() {
    const t0 = performance.now();
    try {
      const res = await rpc.call("tasks.list");
      const elapsed = Math.round(performance.now() - t0);
      cacheLogs = [
        ...cacheLogs,
        { time: getTimeStr(), text: `✔ Данные получены за ${elapsed} ms (записей: ${Array.isArray(res) ? res.length : res?.rows?.length || 0})`, type: "success" }
      ];
    } catch (e: any) {
      cacheLogs = [...cacheLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function invalidateCacheTag() {
    try {
      await rpc.call("tasks.invalidate_cache", { tag: "tasks.list" });
      cacheLogs = [
        ...cacheLogs,
        { time: getTimeStr(), text: `⚡ Сервер инициировал инвалидацию тега 'tasks.list'`, type: "warn" }
      ];
    } catch (e: any) {
      cacheLogs = [...cacheLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function testCrudSchema() {
    try {
      const res = await rpc.call("crud.schema");
      crudLogs = [
        ...crudLogs,
        { time: getTimeStr(), text: `✔ crud.schema вернул ${res.models?.length || 0} моделей: ${res.models?.map((m: any) => m.key).join(", ")}`, type: "info" }
      ];
    } catch (e: any) {
      crudLogs = [...crudLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function startStreaming() {
    if (isStreaming) return;
    isStreaming = true;
    streamProgress = 0;
    streamLogs = [{ time: getTimeStr(), text: `🚀 Запуск потоковой аналитики analytics.generate...`, type: "info" }];

    try {
      await rpc.call("analytics.generate", {}, {
        onChunk: (chunk: any) => {
          streamProgress = chunk.progress || streamProgress;
          streamLogs = [
            ...streamLogs,
            { time: getTimeStr(), text: `🌊 Чанк: шаг ${chunk.step}, прогресс ${chunk.progress}%`, type: "info" }
          ];
        }
      });
      streamProgress = 100;
      streamLogs = [
        ...streamLogs,
        { time: getTimeStr(), text: `✔ Поток завершен успешно (100%)`, type: "success" }
      ];
    } catch (e: any) {
      streamLogs = [...streamLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    } finally {
      isStreaming = false;
    }
  }

  async function triggerReverseRpc() {
    try {
      const res = await rpc.call("admin.inspect_client");
      reverseRpcLogs = [
        ...reverseRpcLogs,
        { time: getTimeStr(), text: `✔ Бэкенд успешно опросил браузер: ${JSON.stringify(res)}`, type: "success" }
      ];
    } catch (e: any) {
      reverseRpcLogs = [...reverseRpcLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function sendBroadcast() {
    try {
      await rpc.call("alerts.publish", { message: alertMessage });
    } catch (e: any) {
      broadcastLogs = [...broadcastLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  async function testCreateTask() {
    try {
      const res = await rpc.call("tasks.create", { title: `Задача от ${auth.username} (${getTimeStr()})` });
      rbacLogs = [
        ...rbacLogs,
        { time: getTimeStr(), text: `✔ tasks.create успешно: ${JSON.stringify(res)}`, type: "success" }
      ];
    } catch (e: any) {
      rbacLogs = [
        ...rbacLogs,
        { time: getTimeStr(), text: `🔒 Отказ в доступе: ${e.message}`, type: "error" }
      ];
    }
  }

  async function testSeoSimulation(botType: "google" | "browser") {
    try {
      const res = await rpc.call("seo.simulate", { bot: botType });
      seoLogs = [
        ...seoLogs,
        { time: getTimeStr(), text: `✔ [${botType}] Ответ: ${res.type} (${res.content_preview})`, type: "info" }
      ];
    } catch (e: any) {
      seoLogs = [...seoLogs, { time: getTimeStr(), text: `✖ Ошибка: ${e.message}`, type: "error" }];
    }
  }

  // Авторизация
  async function submitLogin() {
    isLoggingIn = true;
    loginError = "";
    try {
      const res: any = await rpc.call("auth.login", {
        username: loginUsername,
        password: loginPassword
      });
      if (res && res.token) {
        document.cookie = `rsgi_crud_session=${res.token}; path=/; max-age=86400; SameSite=Lax`;
        document.cookie = `rsgi_session=${res.token}; path=/; max-age=86400; SameSite=Lax`;
      }
      await checkAuthMe();
      isLoginModalOpen = false;
    } catch (e: any) {
      loginError = e.message || "Ошибка авторизации";
    } finally {
      isLoggingIn = false;
    }
  }

  async function performLogout() {
    try {
      await rpc.call("auth.logout", {});
    } catch {}
    document.cookie = "rsgi_crud_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    document.cookie = "rsgi_session=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    auth = { authenticated: false, role: "guest", username: t.guest, userId: null };
  }

  function setPreset(role: "admin" | "user" | "guest") {
    if (role === "admin") {
      loginUsername = "admin";
      loginPassword = "admin123";
    } else if (role === "user") {
      loginUsername = "user";
      loginPassword = "user123";
    } else {
      performLogout();
      isLoginModalOpen = false;
    }
  }
</script>

<div class="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
  <!-- TOPBAR -->
  <header class="sticky top-0 z-40 bg-slate-900/90 backdrop-blur-md border-b border-slate-800 px-6 py-3">
    <div class="max-w-7xl mx-auto flex items-center justify-between gap-4">
      <!-- Brand -->
      <div class="flex items-center gap-3">
        <span class="text-lg font-bold tracking-tight text-white flex items-center gap-1.5">
          <span>⚡ rsgi-wsrpc</span>
          <span class="text-xs px-2 py-0.5 rounded bg-blue-600/20 text-blue-400 border border-blue-500/30 font-mono">Showcase</span>
        </span>
        <span class="hidden md:inline-block text-xs text-slate-400 border-l border-slate-700 pl-3">
          {t.brandSub}
        </span>
      </div>

      <!-- Status cluster & Actions -->
      <div class="flex items-center gap-2.5 text-xs">
        <!-- Dot status -->
        <div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800/80 border border-slate-700">
          <span class="w-2 h-2 rounded-full {wsState === 'CONNECTED' ? 'bg-emerald-500 animate-pulse' : wsState === 'CONNECTING' ? 'bg-amber-500' : 'bg-red-500'}"></span>
          <span>{wsState === "CONNECTED" ? t.online : wsState === "CONNECTING" ? t.connecting : t.disconnected}</span>
        </div>

        <!-- RTT -->
        <div class="hidden sm:inline-flex items-center px-2.5 py-1 rounded bg-slate-800/80 border border-slate-700 font-mono">
          {t.rtt(rttMs)}
        </div>

        <!-- User badge -->
        <div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-slate-800/80 border border-slate-700">
          <span>👤 {auth.username}</span>
          <Badge variant={auth.role === "admin" ? "danger" : auth.role === "user" ? "primary" : "neutral"} size="xs">
            {auth.role}
          </Badge>
        </div>

        {#if auth.authenticated}
          <Button variant="ghost" size="sm" onclick={performLogout}>
            {t.signOut}
          </Button>
        {:else}
          <Button variant="secondary" size="sm" onclick={() => (isLoginModalOpen = true)}>
            {t.signIn}
          </Button>
        {/if}

        <!-- Lang switcher -->
        <Button variant="outline" size="sm" onclick={toggleLang} class="font-bold">
          {lang === "ru" ? "🌐 RU" : "🌐 EN"}
        </Button>

        <a href="/crud" target="_blank" class="hidden lg:inline-flex">
          <Button variant="primary" size="sm">
            {t.openCrud}
          </Button>
        </a>
      </div>
    </div>
  </header>

  <!-- MAIN LAYOUT -->
  <div class="max-w-7xl mx-auto w-full flex-1 flex flex-col md:flex-row gap-6 p-6">
    <!-- SIDEBAR -->
    <aside class="w-full md:w-64 shrink-0 flex flex-col gap-5 sticky top-20 self-start">
      <div>
        <div class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2 px-2">
          {t.navArch}
        </div>
        <nav class="flex flex-col gap-1 text-sm">
          {#each docsManifest.sections.slice(0, 5) as s}
            <a
              href="#{s.id}"
              class="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-slate-800/70 text-slate-300 hover:text-white transition-colors"
            >
              <span>{s.icon}</span>
              <span class="truncate">{s.number}. {s.title[lang]}</span>
            </a>
          {/each}
        </nav>
      </div>

      <div>
        <div class="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2 px-2">
          {t.navPlugins}
        </div>
        <nav class="flex flex-col gap-1 text-sm">
          {#each docsManifest.sections.slice(5) as s}
            <a
              href="#{s.id}"
              class="flex items-center gap-2 px-3 py-1.5 rounded hover:bg-slate-800/70 text-slate-300 hover:text-white transition-colors"
            >
              <span>{s.icon}</span>
              <span class="truncate">{s.number}. {s.title[lang]}</span>
            </a>
          {/each}
        </nav>
      </div>
    </aside>

    <!-- CONTENT SECTIONS -->
    <main class="flex-1 flex flex-col gap-8 min-w-0">
      {#each docsManifest.sections as section}
        <section id={section.id} class="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-sm flex flex-col gap-4">
          <!-- Section header -->
          <div class="flex items-start justify-between gap-4 border-b border-slate-800 pb-4">
            <div>
              <h2 class="text-lg font-bold text-white flex items-center gap-2">
                <span>{section.icon}</span>
                <span>{section.number}. {section.title[lang]}</span>
              </h2>
              <p class="text-sm text-slate-400 mt-1">
                {section.summary[lang]}
              </p>
            </div>
            <Badge variant="primary" size="sm">
              {section.tag}
            </Badge>
          </div>

          <!-- Section callout -->
          <div class="p-3.5 bg-blue-950/30 border border-blue-900/40 rounded-lg text-xs leading-relaxed text-blue-200">
            {section.callout[lang]}
          </div>

          <!-- Split grid: Sandbox (left) & Code (right) -->
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-stretch">
            <!-- Sandbox panel -->
            <div class="bg-slate-950/60 border border-slate-800/80 rounded-lg p-4 flex flex-col gap-3">
              <div class="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Песочница / Live Sandbox
              </div>

              <!-- 1. OVERVIEW -->
              {#if section.id === "overview"}
                <div class="flex gap-2">
                  <Button variant="primary" size="sm" onclick={testPing}>{t.btnPing}</Button>
                  <Button variant="secondary" size="sm" onclick={testSystemInfo}>{t.btnSysInfo}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if overviewLogs.length === 0}
                    <div class="text-slate-500 py-1">Нажмите кнопку для проверки...</div>
                  {/if}
                  {#each overviewLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 2. TABULAR -->
              {:else if section.id === "tabular"}
                <div class="flex gap-2">
                  <Button variant="primary" size="sm" onclick={loadTabularTasks}>{t.btnTabular}</Button>
                </div>
                <div class="grid grid-cols-3 gap-2 text-xs text-center font-mono">
                  <div class="p-2 bg-slate-900 border border-slate-800 rounded">
                    <div class="text-[10px] text-slate-500">Raw JSON</div>
                    <div class="font-bold text-slate-300">{rawJsonBytes} B</div>
                  </div>
                  <div class="p-2 bg-slate-900 border border-slate-800 rounded">
                    <div class="text-[10px] text-slate-500">Tabular Wire</div>
                    <div class="font-bold text-blue-400">{tabularWireBytes} B</div>
                  </div>
                  <div class="p-2 bg-slate-900 border border-slate-800 rounded">
                    <div class="text-[10px] text-slate-500">Saved</div>
                    <div class="font-bold text-emerald-400">{compressionRatio}</div>
                  </div>
                </div>
                {#if tabularWireSnippet}
                  <div class="bg-slate-900 border border-slate-800 rounded p-2 text-[11px] font-mono text-slate-300 truncate">
                    {tabularWireSnippet}
                  </div>
                {/if}

              <!-- 3. CACHE -->
              {:else if section.id === "cache"}
                <div class="flex gap-2">
                  <Button variant="primary" size="sm" onclick={loadCacheData}>{t.btnFetchCache}</Button>
                  <Button variant="secondary" size="sm" onclick={invalidateCacheTag}>{t.btnInvalidate}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if cacheLogs.length === 0}
                    <div class="text-slate-500 py-1">Ожидание запросов кэша...</div>
                  {/if}
                  {#each cacheLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 4. CRUD -->
              {:else if section.id === "crud"}
                <div class="flex gap-2">
                  <a href="/crud" target="_blank">
                    <Button variant="primary" size="sm">{t.btnOpenCrudUi}</Button>
                  </a>
                  <Button variant="secondary" size="sm" onclick={testCrudSchema}>{t.btnCrudSchema}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if crudLogs.length === 0}
                    <div class="text-slate-500 py-1">Нажмите кнопку для запроса схемы CRUD...</div>
                  {/if}
                  {#each crudLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 5. STREAM -->
              {:else if section.id === "stream"}
                <div class="flex gap-2 items-center">
                  <Button variant="primary" size="sm" onclick={startStreaming} disabled={isStreaming}>
                    {isStreaming ? "Стриминг..." : t.btnStartStream}
                  </Button>
                  <div class="flex-1 bg-slate-800 h-2 rounded-full overflow-hidden">
                    <div class="bg-blue-500 h-full transition-all duration-300" style="width: {streamProgress}%"></div>
                  </div>
                  <span class="text-xs font-mono">{streamProgress}%</span>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if streamLogs.length === 0}
                    <div class="text-slate-500 py-1">Нажмите для запуска потока...</div>
                  {/if}
                  {#each streamLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 6. REVERSE RPC -->
              {:else if section.id === "reverse-rpc"}
                <div class="flex gap-2">
                  <Button variant="primary" size="sm" onclick={triggerReverseRpc}>{t.btnTriggerReverse}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if reverseRpcLogs.length === 0}
                    <div class="text-slate-500 py-1">Ожидание запроса с сервера...</div>
                  {/if}
                  {#each reverseRpcLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 7. BROADCAST -->
              {:else if section.id === "broadcast"}
                <div class="flex gap-2">
                  <Input bind:value={alertMessage} size="sm" class="flex-1" />
                  <Button variant="primary" size="sm" onclick={sendBroadcast}>{t.btnSendBroadcast}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if broadcastLogs.length === 0}
                    <div class="text-slate-500 py-1">Ожидание рассылок (Broadcast)...</div>
                  {/if}
                  {#each broadcastLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 8. FILES -->
              {:else if section.id === "files"}
                <div class="p-4 border-2 border-dashed border-slate-800 rounded-lg text-center text-xs text-slate-400">
                  Потоковая загрузка 2PC: файлы стримятся на диск в POST /upload и фиксируются через WSRPC files.commit.
                </div>

              <!-- 9. RBAC -->
              {:else if section.id === "rbac"}
                <div class="flex gap-2 items-center">
                  <Button variant="primary" size="sm" onclick={testCreateTask}>{t.btnTestCreateTask}</Button>
                  <Button variant="secondary" size="sm" onclick={() => (isLoginModalOpen = true)}>
                    Сменить роль ({auth.role})
                  </Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if rbacLogs.length === 0}
                    <div class="text-slate-500 py-1">Проверьте права на вызов методов...</div>
                  {/if}
                  {#each rbacLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>

              <!-- 10. SEO -->
              {:else if section.id === "seo"}
                <div class="flex gap-2">
                  <Button variant="secondary" size="sm" onclick={() => testSeoSimulation("google")}>{t.btnSimGoogle}</Button>
                  <Button variant="secondary" size="sm" onclick={() => testSeoSimulation("browser")}>{t.btnSimBrowser}</Button>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded p-2 text-xs font-mono max-h-36 overflow-y-auto divide-y divide-slate-800/50">
                  {#if seoLogs.length === 0}
                    <div class="text-slate-500 py-1">Запустите симуляцию краулера...</div>
                  {/if}
                  {#each seoLogs as item}
                    <div class="py-1 text-slate-300">[{item.time}] {item.text}</div>
                  {/each}
                </div>
              {/if}
            </div>

            <!-- Code Inspector (right) -->
            <CodeInspector
              python={section.code.python}
              typescript={section.code.typescript}
              wire={section.code.wire}
              {lang}
            />
          </div>
        </section>
      {/each}
    </main>
  </div>

  <!-- FOOTER -->
  <footer class="border-t border-slate-800 py-6 text-center text-xs text-slate-500 bg-slate-900/50">
    {t.footerText}
  </footer>

  <!-- LOGIN MODAL -->
  <Modal open={isLoginModalOpen} title={t.loginModalTitle} size="md" onclose={() => (isLoginModalOpen = false)}>
    <div class="flex flex-col gap-3">
      {#if loginError}
        <div class="p-2.5 bg-red-950/50 border border-red-800 rounded text-red-200 text-xs">
          {loginError}
        </div>
      {/if}

      <div>
        <span class="block text-xs font-medium text-slate-300 mb-1">{t.username}</span>
        <Input bind:value={loginUsername} size="sm" placeholder="admin, user..." />
      </div>

      <div>
        <span class="block text-xs font-medium text-slate-300 mb-1">{t.password}</span>
        <Input type="password" bind:value={loginPassword} size="sm" placeholder="••••••" />
      </div>

      <div>
        <div class="text-xs font-medium text-slate-400 mb-1.5">{t.quickPresets}</div>
        <div class="flex gap-2">
          <Button variant="secondary" size="sm" onclick={() => setPreset("admin")}>Admin</Button>
          <Button variant="secondary" size="sm" onclick={() => setPreset("user")}>User</Button>
          <Button variant="outline" size="sm" onclick={() => setPreset("guest")}>Guest</Button>
        </div>
      </div>
    </div>

    {#snippet footer()}
      <Button variant="outline" size="sm" onclick={() => (isLoginModalOpen = false)}>{t.cancel}</Button>
      <Button variant="primary" size="sm" onclick={submitLogin} disabled={isLoggingIn}>
        {isLoggingIn ? "Вход..." : t.loginSubmit}
      </Button>
    {/snippet}
  </Modal>
</div>
