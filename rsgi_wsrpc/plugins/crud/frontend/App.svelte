<script lang="ts">
  import { onMount } from "svelte";
  import { rpc, wsStatus as canonicalWsStatus } from "@wsrpc/wsrpc";
  import PermissionsModal from "./components/PermissionsModal.svelte";
  import GuestPermissionsView from "./components/GuestPermissionsView.svelte";
  import SystemCockpit from "./components/SystemCockpit.svelte";

  let wsStatus = $state<"CONNECTING" | "CONNECTED" | "DISCONNECTED">("DISCONNECTED");

  // Секции Mission Control (/admin/crud vs /admin/system)
  type AdminSection = "crud" | "system";
  let currentSection = $state<AdminSection>("crud");

  function setSection(sec: AdminSection) {
    currentSection = sec;
    try {
      window.location.hash = sec === "system" ? "system" : "crud";
    } catch {}
  }

  // Тема (светлая / темно-серая)
  let isDarkMode = $state(false);

  function toggleTheme() {
    isDarkMode = !isDarkMode;
    if (isDarkMode) {
      document.documentElement.classList.add("dark");
      localStorage.setItem("crud_admin_theme", "dark");
    } else {
      document.documentElement.classList.remove("dark");
      localStorage.setItem("crud_admin_theme", "light");
    }
  }

  // Язык интерфейса (RU / EN)
  type Lang = "ru" | "en";
  let lang = $state<Lang>("ru");

  function toggleLang() {
    lang = lang === "ru" ? "en" : "ru";
    localStorage.setItem("crud_admin_lang", lang);
  }

  const i18n = {
    ru: {
      title: "CRUD Admin",
      modelLabel: "Модель:",
      searchPlaceholder: "Поиск по строкам (Enter)...",
      refresh: "Обновить",
      create: "Создать",
      archiveOn: "Архив: Вкл",
      archiveOff: "Архив: Выкл",
      actions: "Действия",
      loadingRows: "Загрузка строк...",
      noRecords: "Записей не найдено",
      yes: "Да",
      no: "Нет",
      editCell: "Редактировать ячейку",
      deleteRecord: "Удалить",
      confirmDeleteTitle: "Подтверждение удаления",
      confirmDeleteText: (id: any) => `Вы уверены, что хотите удалить запись #${id}? Действие необратимо.`,
      cancel: "Отмена",
      delete: "Удалить",
      deleting: "Удаление...",
      createTitle: (model: string) => `Создать: ${model}`,
      save: "Сохранить",
      creating: "Создание...",
      totalRecords: "Всего записей:",
      page: "Стр.",
      of: "из",
      prev: "Назад",
      next: "Вперед",
      cellSaved: "Ячейка сохранена",
      statusUpdated: "Статус обновлен",
      recordDeleted: (id: any) => `Запись #${id} удалена`,
      recordCreated: "Запись успешно создана",
      wsOnline: "WSRPC Онлайн",
      wsConnecting: "Подключение...",
      schemaLoading: "Загрузка схемы моделей...",
      noModels: "Нет доступных моделей для отображения.",
      schemaError: (msg: string) => `Ошибка схемы: ${msg}`,
      loadError: (msg: string) => `Ошибка загрузки данных: ${msg}`,
      saveError: (msg: string) => `Ошибка сохранения: ${msg}`,
      deleteError: (msg: string) => `Ошибка удаления: ${msg}`,
      themeLight: "Включить светлую тему",
      themeDark: "Включить темно-серую тему",
      switchLang: "Switch to English",
      accessSection: "Безопасность и доступ",
      navGuests: "Гости",
      navUsers: "Пользователи",
      navRoles: "Роли",
      dataSection: "Таблицы данных",
      models: {
        showcase_tasks: "Задачи",
        showcase_documents: "Документы",
        auth_rpc_permission: "Права RPC-методов",
        auth_role: "Роли",
        auth_user: "Пользователи",
        Task: "Задачи",
        Document: "Документы",
        "RPC Permission": "Права RPC-методов",
        Role: "Роли",
        User: "Пользователи",
      } as Record<string, string>,
      fields: {
        id: "ID",
        name: "Название",
        title: "Заголовок",
        description: "Описание",
        is_public: "Публичный (гостям)",
        completed: "Завершено",
        priority: "Приоритет",
        owner_id: "Владелец (ID)",
        category: "Категория",
        views: "Просмотры",
        content: "Контент",
        created_at: "Создано",
        updated_at: "Обновлено",
        login: "Логин",
        email: "Email",
      } as Record<string, string>,
    },
    en: {
      title: "CRUD Admin",
      modelLabel: "Model:",
      searchPlaceholder: "Search rows (Enter)...",
      refresh: "Refresh",
      create: "Create",
      archiveOn: "Archive: On",
      archiveOff: "Archive: Off",
      actions: "Actions",
      loadingRows: "Loading rows...",
      noRecords: "No records found",
      yes: "Yes",
      no: "No",
      editCell: "Edit cell",
      deleteRecord: "Delete",
      confirmDeleteTitle: "Confirm Deletion",
      confirmDeleteText: (id: any) => `Are you sure you want to delete record #${id}? This action cannot be undone.`,
      cancel: "Cancel",
      delete: "Delete",
      deleting: "Deleting...",
      createTitle: (model: string) => `Create: ${model}`,
      save: "Save",
      creating: "Creating...",
      totalRecords: "Total records:",
      page: "Page",
      of: "of",
      prev: "Prev",
      next: "Next",
      cellSaved: "Cell saved",
      statusUpdated: "Status updated",
      recordDeleted: (id: any) => `Record #${id} deleted`,
      recordCreated: "Record created successfully",
      wsOnline: "WSRPC Online",
      wsConnecting: "Connecting...",
      schemaLoading: "Loading model schema...",
      noModels: "No models available for display.",
      schemaError: (msg: string) => `Schema error: ${msg}`,
      loadError: (msg: string) => `Data load error: ${msg}`,
      saveError: (msg: string) => `Save error: ${msg}`,
      deleteError: (msg: string) => `Delete error: ${msg}`,
      themeLight: "Switch to light theme",
      themeDark: "Switch to dark theme",
      switchLang: "Переключить на русский",
      accessSection: "Access & Security",
      navGuests: "Guests",
      navUsers: "Users",
      navRoles: "Roles",
      dataSection: "Data Tables",
      models: {
        showcase_tasks: "Tasks",
        showcase_documents: "Documents",
        auth_rpc_permission: "RPC Permissions",
        auth_role: "Roles",
        auth_user: "Users",
        Task: "Tasks",
        Document: "Documents",
        "RPC Permission": "RPC Permissions",
        Role: "Roles",
        User: "Users",
      } as Record<string, string>,
      fields: {
        id: "ID",
        name: "Name",
        title: "Title",
        description: "Description",
        is_public: "Public (guests)",
        completed: "Completed",
        priority: "Priority",
        owner_id: "Owner ID",
        category: "Category",
        views: "Views",
        content: "Content",
        created_at: "Created at",
        updated_at: "Updated at",
        login: "Login",
        email: "Email",
      } as Record<string, string>,
    },
  };

  let t = $derived(i18n[lang]);

  function getModelDisplayName(m: any) {
    if (!m) return "";
    if (t.models[m.key]) return t.models[m.key];
    if (m.verbose_name_plural && t.models[m.verbose_name_plural]) return t.models[m.verbose_name_plural];
    return m.verbose_name_plural || m.key;
  }

  function getFieldDisplayName(col: any) {
    if (!col) return "";
    if (t.fields[col.name]) return t.fields[col.name];
    return col.label || col.name;
  }

  // Модели и схема
  let models = $state<any[]>([]);
  let allowGuests = $state(true);
  let selectedNav = $state<"guest" | "user" | "role" | "model">("user");
  let selectedModelName = $state<string>("");
  let currentSchema = $derived(models.find((m) => m.key === selectedModelName) || null);
  let isLoadingSchema = $state(true);

  let userModel = $derived(models.find((m) => m.key === "User" || m.table_name === "auth_user" || m.key === "auth_user"));
  let roleModel = $derived(models.find((m) => m.key === "Role" || m.table_name === "auth_role" || m.key === "auth_role"));
  let otherModels = $derived(models.filter((m) => m !== userModel && m !== roleModel));

  function selectNav(nav: "guest" | "user" | "role") {
    selectedNav = nav;
    if (nav === "user" && userModel) {
      selectedModelName = userModel.key;
    } else if (nav === "role" && roleModel) {
      selectedModelName = roleModel.key;
    }
  }

  function selectOtherModel(modelKey: string) {
    selectedNav = "model";
    selectedModelName = modelKey;
  }

  // Таблица данных
  let rows = $state<any[][]>([]);
  let fields = $state<string[]>([]);
  let total = $state(0);
  let page = $state(1);
  let pageSize = $state(25);
  let sortField = $state<string>("");
  let sortDir = $state<"asc" | "desc">("desc");
  let searchQuery = $state("");
  let showArchived = $state(false);
  let isLoadingData = $state(false);

  // Инлайн редактирование
  let editingCell = $state<{ id: any; field: string; value: any } | null>(null);
  let isSavingCell = $state(false);

  // Модалка создания
  let isCreateModalOpen = $state(false);
  let createFormData = $state<Record<string, any>>({});
  let isCreating = $state(false);
  let createError = $state<string>("");

  // Модалка удаления
  let recordToDelete = $state<any | null>(null);
  let isDeleting = $state(false);

  // Модалка разрешений (CRUD + RPC)
  let permissionsModalOpen = $state(false);
  let permissionsTargetType = $state<"role" | "user">("role");
  let permissionsTargetId = $state<number>(0);
  let permissionsTargetName = $state<string>("");

  let isRoleModel = $derived(selectedModelName === "auth_role" || selectedModelName === "Role");
  let isUserModel = $derived(selectedModelName === "auth_user" || selectedModelName === "User");
  let isRoleOrUserModel = $derived(isRoleModel || isUserModel);

  function openPermissions(row: any[], recId: any) {
    permissionsTargetId = Number(recId);
    permissionsTargetType = isRoleModel ? "role" : "user";
    const nameIdx = fields.indexOf("name");
    const loginIdx = fields.indexOf("login");
    let name = "";
    if (nameIdx !== -1 && row[nameIdx]) name = String(row[nameIdx]);
    else if (loginIdx !== -1 && row[loginIdx]) name = String(row[loginIdx]);
    else name = `#${recId}`;

    permissionsTargetName = name;
    permissionsModalOpen = true;
  }

  // Определение справочных колонок (даты, технический аудит)
  function isRefColumn(colName: string): boolean {
    return colName === "created_at" || colName === "updated_at" || colName === "creator_id" || colName === "team_id" || colName === "owner_id";
  }

  // Упорядочивание колонок таблицы: основные бизнес-поля слева, справочные — справа
  let displayColumns = $derived.by(() => {
    if (!currentSchema?.fields) return [];
    const mainCols: any[] = [];
    const refCols: any[] = [];
    for (const f of currentSchema.fields) {
      if (isRefColumn(f.name)) {
        refCols.push(f);
      } else {
        mainCols.push(f);
      }
    }
    refCols.sort((a, b) => {
      const order = ["creator_id", "team_id", "owner_id", "created_at", "updated_at"];
      return order.indexOf(a.name) - order.indexOf(b.name);
    });
    return [...mainCols, ...refCols];
  });

  // Лаконичное форматирование значений ячеек (краткая дата/время без микросекунд)
  function formatCellValue(val: any, col: any): string {
    if (val === null || val === undefined) return "—";
    if (
      col.type === "datetime" ||
      col.type === "date" ||
      col.name.endsWith("_at") ||
      col.name.endsWith("_date") ||
      (typeof val === "string" && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(val))
    ) {
      try {
        const d = new Date(val);
        if (!isNaN(d.getTime())) {
          const pad = (n: number) => String(n).padStart(2, "0");
          return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        }
      } catch {}
    }
    return String(val);
  }

  // Индекс ID колонки
  let idColIdx = $derived.by(() => {
    if (fields.indexOf("id") !== -1) return fields.indexOf("id");
    if (fields.indexOf("key") !== -1) return fields.indexOf("key");
    const pkIdx = currentSchema?.fields.findIndex((f) => f.primary_key);
    if (pkIdx !== undefined && pkIdx !== -1) return pkIdx;
    return 0;
  });

  function getRowId(row: any[], rowIdx: number = 0): any {
    if (!row || !Array.isArray(row)) return `row-${rowIdx}`;
    let val: any = undefined;
    if (currentSchema && fields.length > 0) {
      const pkFields = currentSchema.fields.filter((f) => f.primary_key);
      if (pkFields.length > 1) {
        val = pkFields
          .map((f) => {
            const idx = fields.indexOf(f.name);
            return idx !== -1 && row[idx] !== undefined ? row[idx] : "";
          })
          .join("_");
      } else if (pkFields.length === 1) {
        const idx = fields.indexOf(pkFields[0].name);
        if (idx !== -1 && row[idx] !== undefined && row[idx] !== null) {
          val = row[idx];
        }
      }
    }
    if (val === undefined || val === null || val === "") {
      if (idColIdx >= 0 && idColIdx < row.length && row[idColIdx] !== undefined && row[idColIdx] !== null) {
        val = row[idColIdx];
      }
    }
    if (val === undefined || val === null || val === "") {
      return `row-${rowIdx}`;
    }
    return val;
  }

  // Уведомления (toast)
  let toastMsg = $state<{ text: string; type: "success" | "error" } | null>(null);
  let toastTimer: any = null;
  function showToast(text: string, type: "success" | "error" = "success") {
    toastMsg = { text, type };
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toastMsg = null;
    }, 4000);
  }

  // Кэш лукапов для ForeignKey и M2M связей
  let lookupCache = $state<Record<string, { id: any; label: string }[]>>({});

  async function loadLookupOptions(modelName: string) {
    if (!modelName) return [];
    if (lookupCache[modelName] && lookupCache[modelName].length > 0) {
      return lookupCache[modelName];
    }
    try {
      const res = await rpc.call("crud.lookup", { model: modelName });
      if (res && res.items) {
        lookupCache[modelName] = res.items;
        return res.items;
      }
    } catch (e: any) {
      console.warn(`[CRUD UI] Ошибка lookup для ${modelName}:`, e);
    }
    return [];
  }

  function getTargetModelFromFk(fk: any): string | null {
    if (!fk) return null;
    if (fk.target_model && models.some((m) => m.key === fk.target_model)) {
      return fk.target_model;
    }
    const found = models.find((m) => m.table_name === fk.target_table);
    return found ? found.key : null;
  }

  function openCreateModal() {
    createFormData = {};
    createError = "";
    isCreateModalOpen = true;
    if (currentSchema) {
      for (const col of currentSchema.fields) {
        if (col.type === "m2m" && col.target_model) {
          createFormData[col.name] = [];
          loadLookupOptions(col.target_model);
        } else if (col.type === "fk" || col.foreign_key) {
          const target = getTargetModelFromFk(col.foreign_key);
          if (target) loadLookupOptions(target);
        }
      }
    }
  }

  async function loadSchema() {
    isLoadingSchema = true;
    console.info("[CRUD Admin] 📋 Загрузка схемы моделей (crud.schema)...");
    try {
      const res = await rpc.call("crud.schema", {});
      console.info("[CRUD Admin] ✅ Схема получена:", res);
      if (res) {
        if (res.allow_guests !== undefined) {
          allowGuests = Boolean(res.allow_guests);
        }
        if (res.models) {
          models = res.models;
          if (!selectedModelName) {
            if (userModel) {
              selectedNav = "user";
              selectedModelName = userModel.key;
            } else if (models.length > 0) {
              selectedNav = "model";
              selectedModelName = models[0].key;
            }
          }
        }
      }
    } catch (e: any) {
      console.error("[CRUD Admin] ❌ Ошибка загрузки схемы:", e);
      showToast(t.schemaError(e.message), "error");
    } finally {
      isLoadingSchema = false;
    }
  }

  async function loadData() {
    if (!selectedModelName) return;
    isLoadingData = true;
    console.info(`[CRUD Admin] 📊 Загрузка данных для модели "${selectedModelName}" (стр. ${page}, pageSize: ${pageSize})...`);
    try {
      const res = await rpc.call("crud.list", {
        model: selectedModelName,
        page,
        page_size: pageSize,
        sort_field: sortField || undefined,
        sort_dir: sortDir,
        search: searchQuery.trim() || undefined,
        show_archived: showArchived,
      });

      console.info(`[CRUD Admin] ✅ Данные получены для "${selectedModelName}":`, res);
      if (res && res.$tabular) {
        fields = res.fields || [];
        rows = res.rows || [];
        total = res.total || 0;
      }
    } catch (e: any) {
      console.error(`[CRUD Admin] ❌ Ошибка загрузки данных для "${selectedModelName}":`, e);
      showToast(t.loadError(e.message), "error");
    } finally {
      isLoadingData = false;
    }
  }

  function handleSort(colName: string) {
    if (sortField === colName) {
      sortDir = sortDir === "asc" ? "desc" : "asc";
    } else {
      sortField = colName;
      sortDir = "asc";
    }
    loadData();
  }

  async function saveInlineCell() {
    if (!editingCell || isSavingCell) return;
    isSavingCell = true;
    const { id, field, value } = editingCell;

    try {
      await rpc.call("crud.update_cell", {
        model: selectedModelName,
        id,
        field,
        value,
      });

      // Обновляем строку локально
      const targetRow = rows.find((r) => getRowId(r) === id);
      if (targetRow) {
        const cIdx = fields.indexOf(field);
        if (cIdx !== -1) targetRow[cIdx] = value;
        rows = [...rows];
      }
      showToast(t.cellSaved);
      editingCell = null;
    } catch (e: any) {
      showToast(t.saveError(e.message), "error");
    } finally {
      isSavingCell = false;
    }
  }

  async function toggleBool(recordId: any, fieldName: string, curVal: boolean) {
    try {
      const nextVal = !curVal;
      await rpc.call("crud.update_cell", {
        model: selectedModelName,
        id: recordId,
        field: fieldName,
        value: nextVal,
      });
      const targetRow = rows.find((r) => getRowId(r) === recordId);
      if (targetRow) {
        const cIdx = fields.indexOf(fieldName);
        if (cIdx !== -1) targetRow[cIdx] = nextVal;
        rows = [...rows];
      }
      showToast(t.statusUpdated);
    } catch (e: any) {
      showToast(`Error: ${e.message}`, "error");
    }
  }

  async function confirmDelete() {
    if (!recordToDelete || isDeleting) return;
    isDeleting = true;
    try {
      await rpc.call("crud.delete", {
        model: selectedModelName,
        id: recordToDelete,
      });
      rows = rows.filter((r) => getRowId(r) !== recordToDelete);
      total = Math.max(0, total - 1);
      showToast(t.recordDeleted(recordToDelete));
      recordToDelete = null;
    } catch (e: any) {
      showToast(t.deleteError(e.message), "error");
    } finally {
      isDeleting = false;
    }
  }

  async function submitCreate() {
    isCreating = true;
    createError = "";
    try {
      await rpc.call("crud.create", {
        model: selectedModelName,
        data: createFormData,
      });
      showToast(t.recordCreated);
      isCreateModalOpen = false;
      createFormData = {};
      loadData();
    } catch (e: any) {
      createError = e.message || String(e);
    } finally {
      isCreating = false;
    }
  }

  function handleCachePatch(params: any) {
    console.info("[CRUD Admin] 🔔 Получен cache/crud патч:", params);
    if (!params || params.model !== selectedModelName) return;
    const recId = params.id;

    if (params.deleted) {
      console.info(`[CRUD Admin] 🗑 Удалена запись #${recId} из локального кэша`);
      rows = rows.filter((r) => getRowId(r) !== recId);
      total = Math.max(0, total - 1);
      return;
    }

    if (params.created) {
      console.info("[CRUD Admin] ➕ Создана новая запись, перезагрузка данных...");
      loadData();
      return;
    }

    if (params.kind === "updated" || params.changes) {
      const targetRow = rows.find((r) => getRowId(r) === recId);
      if (targetRow) {
        if (params.changes) {
          console.info(`[CRUD Admin] ✏️ Обновлены поля для #${recId}:`, params.changes);
          for (const [k, v] of Object.entries(params.changes)) {
            const cIdx = fields.indexOf(k);
            if (cIdx !== -1) targetRow[cIdx] = v;
          }
          rows = [...rows];
        } else {
          rpc.call("crud.get", { model: selectedModelName, id: recId })
            .then((res: any) => {
              if (res && res.record) {
                const rIdx = rows.findIndex((r) => getRowId(r) === recId);
                if (rIdx !== -1) {
                  rows[rIdx] = fields.map((f) => res.record[f]);
                  rows = [...rows];
                }
              }
            })
            .catch(() => {});
        }
      }
    }
  }

  onMount(() => {
    console.info("[CRUD Admin] 🚀 onMount инициализирован");
    console.info("[CRUD Admin] rpc клиент:", rpc, "typeof rpc.on:", typeof (rpc as any)?.on);

    const savedTheme = localStorage.getItem("crud_admin_theme");
    if (savedTheme === "dark") {
      isDarkMode = true;
      document.documentElement.classList.add("dark");
    }
    const savedLang = localStorage.getItem("crud_admin_lang") as Lang;
    if (savedLang === "en" || savedLang === "ru") {
      lang = savedLang;
    }

    if (window.location.hash === "#system" || window.location.pathname.endsWith("/system")) {
      currentSection = "system";
    }
    const onHashChange = () => {
      if (window.location.hash === "#system") currentSection = "system";
      else if (window.location.hash === "#crud") currentSection = "crud";
    };
    window.addEventListener("hashchange", onHashChange);

    const unsubStatus = canonicalWsStatus.subscribe((s) => {
      console.info("[CRUD Admin] 📶 Смена статуса WebSocket:", s);
      wsStatus = s;
      if (s === "CONNECTED") {
        console.info("[CRUD Admin] ✅ Соединение установлено, вызываем loadSchema()...");
        loadSchema();
      }
    });

    const unsubCache = rpc.on("cache.invalidate", (params: any) => {
      handleCachePatch(params);
    });

    const unsubCrud = rpc.on("crud.event", (params: any) => {
      handleCachePatch(params);
    });

    console.info("[CRUD Admin] 🔌 Вызов rpc.connect()...");
    rpc.connect();

    return () => {
      console.info("[CRUD Admin] 🛑 onMount cleanup (отписка и отключение)");
      window.removeEventListener("hashchange", onHashChange);
      unsubStatus();
      unsubCache();
      unsubCrud();
      rpc.disconnect();
    };
  });

  $effect(() => {
    if (selectedModelName && wsStatus === "CONNECTED") {
      page = 1;
      editingCell = null;
      rows = [];
      fields = [];
      loadData();
    }
  });
</script>

<div class="min-h-screen bg-background text-foreground flex flex-col font-sans transition-colors duration-200">
  <!-- Верхняя панель (Header) -->
  <header class="sticky top-0 z-40 border-b border-border bg-card/80 backdrop-blur-md px-6 py-2.5 flex items-center justify-between shadow-2xs">
    <div class="flex items-center gap-6">
      <div class="flex items-center gap-2.5">
        <div class="h-8 w-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center text-primary font-bold text-base shadow-2xs">
          🛡️
        </div>
        <div class="flex flex-col">
          <span class="text-sm font-bold tracking-tight text-foreground">Mission Control</span>
          <span class="text-[10px] text-muted-foreground font-mono leading-none">rsgi-wsrpc engine</span>
        </div>
      </div>

      <!-- Главный переключатель Mission Control: CRUD vs SYSTEM -->
      <nav class="flex items-center p-1 rounded-xl bg-muted/60 border border-border">
        <button
          type="button"
          onclick={() => setSection("crud")}
          class="flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer {currentSection === 'crud' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
        >
          <span>📊</span>
          <span>{lang === 'ru' ? 'Данные (CRUD)' : 'Data (CRUD)'}</span>
        </button>

        <button
          type="button"
          onclick={() => setSection("system")}
          class="flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer {currentSection === 'system' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
        >
          <span>⚙️</span>
          <span>{lang === 'ru' ? 'Система (System)' : 'System Cockpit'}</span>
        </button>
      </nav>
    </div>

    <!-- Правая часть: статус подключения, переключатель языка и темы -->
    <div class="flex items-center gap-2.5">
      <!-- Статус сокета -->
      <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-2xs font-semibold border {wsStatus === 'CONNECTED' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400' : 'bg-rose-500/10 border-rose-500/30 text-rose-600 dark:text-rose-400'}">
        <span class="h-2 w-2 rounded-full {wsStatus === 'CONNECTED' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}"></span>
        <span>{wsStatus === 'CONNECTED' ? t.wsOnline : t.wsConnecting}</span>
      </div>

      <!-- Переключатель языка RU / EN -->
      <button
        type="button"
        onclick={toggleLang}
        class="flex h-8 px-2.5 items-center justify-center rounded-lg border border-border bg-muted/60 text-foreground font-bold text-xs hover:bg-muted transition-colors cursor-pointer"
        title={t.switchLang}
      >
        🌐 {lang.toUpperCase()}
      </button>

      <!-- Переключатель светлой / темно-серой темы -->
      <button
        type="button"
        onclick={toggleTheme}
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-muted/60 text-foreground hover:bg-muted transition-colors cursor-pointer"
        title={isDarkMode ? t.themeLight : t.themeDark}
      >
        {#if isDarkMode}
          <span class="text-sm">☀️</span>
        {:else}
          <span class="text-sm">🌙</span>
        {/if}
      </button>
    </div>
  </header>

  {#if currentSection === "system"}
    <SystemCockpit {lang} />
  {:else}
  <div class="flex-1 flex overflow-hidden">
    <!-- Боковая панель навигации слева (Sidebar) -->
    <aside class="w-60 border-r border-border bg-card/40 flex flex-col p-4 gap-6 shrink-0 overflow-y-auto">
      <div class="flex flex-col gap-1.5">
        <span class="text-2xs font-bold uppercase tracking-wider text-muted-foreground px-2">
          {t.accessSection}
        </span>

        {#if allowGuests}
          <button
            type="button"
            onclick={() => selectNav("guest")}
            class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors text-left cursor-pointer {selectedNav === 'guest' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
          >
            <span class="text-sm">🌐</span>
            <span>{t.navGuests}</span>
          </button>
        {/if}

        <button
          type="button"
          onclick={() => selectNav("user")}
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors text-left cursor-pointer {selectedNav === 'user' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
        >
          <span class="text-sm">👥</span>
          <span>{t.navUsers}</span>
        </button>

        <button
          type="button"
          onclick={() => selectNav("role")}
          class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors text-left cursor-pointer {selectedNav === 'role' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
        >
          <span class="text-sm">🛡️</span>
          <span>{t.navRoles}</span>
        </button>
      </div>

      {#if otherModels.length > 0}
        <div class="flex flex-col gap-1.5 border-t border-border pt-4">
          <span class="text-2xs font-bold uppercase tracking-wider text-muted-foreground px-2">
            {t.dataSection}
          </span>
          {#each otherModels as m}
            <button
              type="button"
              onclick={() => selectOtherModel(m.key)}
              class="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-semibold transition-colors text-left cursor-pointer {selectedModelName === m.key && selectedNav === 'model' ? 'bg-primary text-primary-foreground shadow-xs' : 'text-foreground hover:bg-muted'}"
            >
              <span class="text-sm">📦</span>
              <span>{getModelDisplayName(m)}</span>
            </button>
          {/each}
        </div>
      {/if}
    </aside>

    <!-- Основное содержимое -->
    <main class="flex-1 p-6 overflow-y-auto w-full flex flex-col gap-5">
      {#if selectedNav === "guest"}
        <GuestPermissionsView
          {lang}
          rpcClient={rpc}
          onnotify={(msg, type) => showToast(msg, type)}
        />
      {:else if isLoadingSchema}
        <div class="flex h-64 items-center justify-center text-sm text-muted-foreground">
          {t.schemaLoading}
        </div>
      {:else if currentSchema}
        <!-- Панель управления таблицей: поиск, фильтры, создать -->
        <div class="flex flex-wrap items-center justify-between gap-4 bg-card p-4 rounded-xl border border-border shadow-xs">
          <div class="flex items-center gap-3 flex-1 max-w-md">
            <input
              type="text"
              bind:value={searchQuery}
              onkeydown={(e) => { if (e.key === 'Enter') loadData(); }}
              placeholder={t.searchPlaceholder}
              class="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary shadow-2xs"
            />
          {#if searchQuery}
            <button
              type="button"
              onclick={() => { searchQuery = ''; loadData(); }}
              class="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            >
              ✕
            </button>
          {/if}
        </div>

        <div class="flex items-center gap-2.5">
          {#if currentSchema.is_archivable}
            <button
              type="button"
              onclick={() => { showArchived = !showArchived; loadData(); }}
              class="px-3 py-1.5 rounded-lg text-xs font-medium border cursor-pointer transition-colors {showArchived ? 'bg-secondary text-secondary-foreground border-border' : 'bg-background text-muted-foreground border-input hover:text-foreground'}"
            >
              {showArchived ? t.archiveOn : t.archiveOff}
            </button>
          {/if}

          <button
            type="button"
            onclick={loadData}
            class="px-3 py-1.5 rounded-lg text-xs font-medium border border-input bg-background hover:bg-muted text-foreground cursor-pointer transition-colors"
            title={t.refresh}
          >
            ↻ {t.refresh}
          </button>

          {#if currentSchema.permissions?.can_create}
            <button
              type="button"
              onclick={openCreateModal}
              class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 shadow-2xs cursor-pointer transition-colors"
            >
              + {t.create}
            </button>
          {/if}
        </div>
      </div>

      <!-- Таблица данных -->
      <div class="rounded-xl border border-border bg-card overflow-hidden shadow-xs flex flex-col">
        <div class="overflow-x-auto">
          <table class="w-full text-left text-xs text-foreground border-collapse">
            <thead class="border-b border-border bg-muted/40 font-semibold text-muted-foreground">
              <tr>
                {#each displayColumns as col}
                  <th
                    scope="col"
                    class="px-4 py-3 cursor-pointer hover:bg-muted/80 transition-colors select-none {isRefColumn(col.name) ? 'text-muted-foreground/70 font-normal' : ''}"
                    onclick={() => handleSort(col.name)}
                  >
                    <div class="flex items-center gap-1">
                      <span>{getFieldDisplayName(col)}</span>
                      {#if sortField === col.name}
                        <span class="text-primary font-bold">{sortDir === 'asc' ? '▲' : '▼'}</span>
                      {/if}
                    </div>
                  </th>
                {/each}
                {#if currentSchema.permissions?.can_delete || isRoleOrUserModel}
                  <th scope="col" class="px-4 py-3 text-right">{t.actions}</th>
                {/if}
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#if isLoadingData && rows.length === 0}
                <tr>
                  <td colspan="100" class="h-40 text-center text-muted-foreground">
                    {t.loadingRows}
                  </td>
                </tr>
              {:else if rows.length === 0}
                <tr>
                  <td colspan="100" class="h-40 text-center text-muted-foreground italic">
                    {t.noRecords}
                  </td>
                </tr>
              {:else}
                {#each rows as row, rowIdx (getRowId(row, rowIdx))}
                  {@const recId = getRowId(row, rowIdx)}
                  <tr class="hover:bg-muted/30 transition-colors">
                    {#each displayColumns as col}
                      {@const cIdx = fields.indexOf(col.name)}
                      {@const val = row[cIdx]}
                      {@const isEditing = editingCell?.id === recId && editingCell?.field === col.name}

                      <td class="px-4 py-2.5 whitespace-nowrap">
                        {#if isEditing && editingCell}
                          {#if col.type === "m2m"}
                            <div class="flex flex-col gap-1.5 p-2 rounded-lg border border-primary bg-background shadow-lg z-20 min-w-48">
                              <div class="flex flex-wrap gap-1 max-h-36 overflow-y-auto">
                                {#each (lookupCache[col.target_model] || []) as opt}
                                  <label class="flex items-center gap-1.5 text-2xs px-1.5 py-0.5 rounded bg-muted/60 hover:bg-muted cursor-pointer border border-border">
                                    <input
                                      type="checkbox"
                                      checked={Array.isArray(editingCell.value) && (editingCell.value.includes(opt.id) || editingCell.value.includes(opt.label))}
                                      onchange={(e) => {
                                        const cur = Array.isArray(editingCell.value) ? [...editingCell.value] : [];
                                        if (e.currentTarget.checked) {
                                          if (!cur.includes(opt.id) && !cur.includes(opt.label)) cur.push(opt.id);
                                        } else {
                                          const idxId = cur.indexOf(opt.id);
                                          if (idxId !== -1) cur.splice(idxId, 1);
                                          const idxLabel = cur.indexOf(opt.label);
                                          if (idxLabel !== -1) cur.splice(idxLabel, 1);
                                        }
                                        editingCell.value = cur;
                                      }}
                                      class="h-3 w-3 rounded text-primary"
                                    />
                                    <span>{opt.label}</span>
                                  </label>
                                {/each}
                              </div>
                              <div class="flex justify-end gap-1.5 pt-1 border-t border-border">
                                <button type="button" onclick={saveInlineCell} class="px-2 py-0.5 rounded bg-primary text-primary-foreground text-2xs font-semibold cursor-pointer">✓ Сохранить</button>
                                <button type="button" onclick={() => (editingCell = null)} class="px-2 py-0.5 rounded bg-muted text-foreground text-2xs cursor-pointer">✕</button>
                              </div>
                            </div>
                          {:else}
                            <div class="flex items-center gap-1">
                              <input
                                type="text"
                                bind:value={editingCell.value}
                                onkeydown={(e) => {
                                  if (e.key === 'Enter') saveInlineCell();
                                  if (e.key === 'Escape') editingCell = null;
                                }}
                                class="rounded border border-primary bg-background px-2 py-0.5 text-xs text-foreground focus:outline-none"
                              />
                              <button
                                type="button"
                                onclick={saveInlineCell}
                                disabled={isSavingCell}
                                class="px-1.5 py-0.5 rounded bg-primary text-primary-foreground text-2xs cursor-pointer"
                              >
                                ✓
                              </button>
                              <button
                                type="button"
                                onclick={() => (editingCell = null)}
                                class="px-1.5 py-0.5 rounded bg-muted text-foreground text-2xs cursor-pointer"
                              >
                                ✕
                              </button>
                            </div>
                          {/if}
                        {:else}
                          <div class="flex items-center justify-between gap-2 group">
                            {#if typeof val === "boolean"}
                              <button
                                type="button"
                                onclick={() => toggleBool(recId, col.name, val)}
                                class="cursor-pointer font-semibold px-2 py-0.5 rounded text-2xs {val ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-muted text-muted-foreground'}"
                              >
                                {val ? t.yes : t.no}
                              </button>
                            {:else if Array.isArray(val)}
                              <div class="flex flex-wrap gap-1 items-center">
                                {#each val as item}
                                  <span class="inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium bg-primary/10 text-primary border border-primary/20">
                                    {typeof item === 'object' ? (item.label || item.name || item.id) : item}
                                  </span>
                                {/each}
                                {#if val.length === 0}
                                  <span class="text-muted-foreground/40 text-xs">—</span>
                                {/if}
                              </div>
                            {:else if val === null || val === undefined}
                              <span class="text-muted-foreground/40">—</span>
                            {:else}
                              <span class="truncate max-w-xs {isRefColumn(col.name) ? 'text-muted-foreground/80 font-mono text-2xs' : ''}">
                                {formatCellValue(val, col)}
                              </span>
                            {/if}

                            {#if col.editable && typeof val !== "boolean"}
                              <button
                                type="button"
                                onclick={() => {
                                  if (col.type === "m2m" && col.target_model) loadLookupOptions(col.target_model);
                                  editingCell = { id: recId, field: col.name, value: val ?? [] };
                                }}
                                class="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-primary transition-opacity text-2xs cursor-pointer"
                                title={t.editCell}
                              >
                                ✎
                              </button>
                            {/if}
                          </div>
                        {/if}
                      </td>
                    {/each}

                    {#if currentSchema.permissions?.can_delete || isRoleOrUserModel}
                      <td class="px-4 py-2.5 text-right whitespace-nowrap">
                        <div class="inline-flex items-center justify-end gap-1.5">
                          {#if isRoleOrUserModel}
                            <button
                              type="button"
                              onclick={() => openPermissions(row, recId)}
                              class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded bg-blue-50 hover:bg-blue-100 text-blue-700 dark:bg-blue-950/60 dark:hover:bg-blue-900/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800 transition-colors cursor-pointer font-medium"
                              title={lang === "ru" ? "Настроить разрешения (CRUD + RPC)" : "Configure permissions (CRUD + RPC)"}
                            >
                              <span>🛡️</span>
                              <span>{lang === "ru" ? "Права" : "Permissions"}</span>
                            </button>
                          {/if}
                          {#if currentSchema.permissions?.can_delete}
                            {@const isProtectedAdminRole = isRoleModel && row[fields.indexOf("name")] === "admin"}
                            {#if !isProtectedAdminRole}
                              <button
                                type="button"
                                onclick={() => (recordToDelete = recId)}
                                class="text-rose-500 hover:text-rose-600 dark:text-rose-400 p-1 rounded hover:bg-rose-500/10 transition-colors cursor-pointer"
                                title={t.deleteRecord}
                              >
                                🗑
                              </button>
                            {/if}
                          {/if}
                        </div>
                      </td>
                    {/if}
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>

        <!-- Подвал пагинации -->
        <div class="flex items-center justify-between border-t border-border bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
          <div>
            {t.totalRecords} <strong class="text-foreground">{total}</strong>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onclick={() => { page--; loadData(); }}
              class="px-2.5 py-1 rounded border border-input bg-background hover:bg-muted disabled:opacity-40 cursor-pointer text-foreground"
            >
              {t.prev}
            </button>
            <span>{t.page} {page} {t.of} {Math.ceil(total / pageSize) || 1}</span>
            <button
              type="button"
              disabled={page * pageSize >= total}
              onclick={() => { page++; loadData(); }}
              class="px-2.5 py-1 rounded border border-input bg-background hover:bg-muted disabled:opacity-40 cursor-pointer text-foreground"
            >
              {t.next}
            </button>
          </div>
        </div>
      </div>
    {:else}
      <div class="flex h-64 items-center justify-center text-sm text-muted-foreground">
        {t.noModels}
      </div>
    {/if}
  </main>
</div>
{/if}

  <!-- Модальное окно создания -->
  {#if isCreateModalOpen && currentSchema}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in">
      <div class="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-xl flex flex-col gap-4 text-foreground">
        <div class="flex items-center justify-between border-b border-border pb-3">
          <h3 class="text-sm font-bold text-foreground">
            {t.createTitle(getModelDisplayName(currentSchema))}
          </h3>
          <button
            type="button"
            onclick={() => (isCreateModalOpen = false)}
            class="text-muted-foreground hover:text-foreground cursor-pointer text-sm"
          >
            ✕
          </button>
        </div>

        {#if createError}
          <div class="p-3 rounded-lg border border-destructive/30 bg-destructive/10 text-destructive text-xs">
            {createError}
          </div>
        {/if}

        <div class="flex flex-col gap-3.5 max-h-[60vh] overflow-y-auto pr-1">
          {#each currentSchema.fields as col}
            {#if col.editable && !col.primary_key && col.name !== "creator_id"}
              <div class="flex flex-col gap-1">
                <label for={`create-field-${col.name}`} class="text-xs font-semibold text-muted-foreground">
                  {getFieldDisplayName(col)} {#if !col.nullable}<span class="text-rose-500">*</span>{/if}
                </label>
                {#if col.type === "boolean"}
                  <label class="flex items-center gap-2 cursor-pointer pt-1">
                    <input
                      type="checkbox"
                      bind:checked={createFormData[col.name]}
                      class="h-4 w-4 rounded border-border text-primary accent-primary"
                    />
                    <span class="text-xs font-medium">{createFormData[col.name] ? t.yes : t.no}</span>
                  </label>
                {:else if col.type === "m2m"}
                  {@const targetModel = col.target_model}
                  {@const opts = targetModel && lookupCache[targetModel] ? lookupCache[targetModel] : []}
                  <div class="flex flex-wrap gap-2 pt-1 p-2 rounded-lg border border-input bg-background/50 max-h-36 overflow-y-auto">
                    {#if opts.length === 0}
                      <span class="text-xs text-muted-foreground italic">Загрузка опций или список пуст...</span>
                    {:else}
                      {#each opts as opt}
                        <label class="flex items-center gap-1.5 px-2 py-1 rounded bg-muted/60 hover:bg-muted text-xs cursor-pointer select-none">
                          <input
                            type="checkbox"
                            checked={Array.isArray(createFormData[col.name]) && createFormData[col.name].includes(opt.id)}
                            onchange={(e) => {
                              const arr = Array.isArray(createFormData[col.name]) ? [...createFormData[col.name]] : [];
                              if (e.currentTarget.checked) {
                                if (!arr.includes(opt.id)) arr.push(opt.id);
                              } else {
                                const idx = arr.indexOf(opt.id);
                                if (idx !== -1) arr.splice(idx, 1);
                              }
                              createFormData[col.name] = arr;
                            }}
                            class="h-3.5 w-3.5 rounded border-border text-primary accent-primary"
                          />
                          <span>{opt.label}</span>
                        </label>
                      {/each}
                    {/if}
                  </div>
                {:else if col.type === "fk" || col.foreign_key}
                  {@const targetModel = getTargetModelFromFk(col.foreign_key)}
                  {@const opts = targetModel && lookupCache[targetModel] ? lookupCache[targetModel] : []}
                  <select
                    id={`create-field-${col.name}`}
                    bind:value={createFormData[col.name]}
                    class="rounded-lg border border-input bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value={null}>-- Выберите {getFieldDisplayName(col)} --</option>
                    {#each opts as opt}
                      <option value={opt.id}>{opt.label} (ID: {opt.id})</option>
                    {/each}
                  </select>
                {:else if col.type === "integer"}
                  <input
                    id={`create-field-${col.name}`}
                    type="number"
                    step="1"
                    bind:value={createFormData[col.name]}
                    placeholder={getFieldDisplayName(col)}
                    class="rounded-lg border border-input bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                {:else if col.type === "datetime" || col.type === "date"}
                  <input
                    id={`create-field-${col.name}`}
                    type={col.type === "date" ? "date" : "datetime-local"}
                    bind:value={createFormData[col.name]}
                    class="rounded-lg border border-input bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                {:else}
                  <input
                    id={`create-field-${col.name}`}
                    type="text"
                    bind:value={createFormData[col.name]}
                    placeholder={getFieldDisplayName(col)}
                    class="rounded-lg border border-input bg-background px-3 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                  />
                {/if}
              </div>
            {/if}
          {/each}
        </div>

        <div class="flex items-center justify-end gap-2 pt-3 border-t border-border">
          <button
            type="button"
            onclick={() => (isCreateModalOpen = false)}
            class="px-3.5 py-1.5 rounded-lg border border-input bg-background hover:bg-muted text-xs font-medium text-foreground cursor-pointer"
          >
            {t.cancel}
          </button>
          <button
            type="button"
            onclick={submitCreate}
            disabled={isCreating}
            class="px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            {isCreating ? t.creating : t.save}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Модальное окно удаления -->
  {#if recordToDelete !== null}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in">
      <div class="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-xl flex flex-col gap-4 text-foreground">
        <h3 class="text-sm font-bold text-foreground">{t.confirmDeleteTitle}</h3>
        <p class="text-xs text-muted-foreground">
          {t.confirmDeleteText(recordToDelete)}
        </p>
        <div class="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onclick={() => (recordToDelete = null)}
            class="px-3 py-1.5 rounded-lg border border-input bg-background hover:bg-muted text-xs font-medium text-foreground cursor-pointer"
          >
            {t.cancel}
          </button>
          <button
            type="button"
            onclick={confirmDelete}
            disabled={isDeleting}
            class="px-3.5 py-1.5 rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            {isDeleting ? t.deleting : t.delete}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Всплывающие уведомления (Toast) -->
  {#if toastMsg}
    <div class="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-2.5 rounded-lg shadow-lg border text-xs font-medium animate-in slide-in-from-bottom-3 {toastMsg.type === 'error' ? 'bg-rose-600 text-white border-rose-700' : 'bg-emerald-600 text-white border-emerald-700'}">
      <span>{toastMsg.text}</span>
    </div>
  {/if}

  <!-- Модальное окно управления разрешениями -->
  {#if permissionsModalOpen}
    <PermissionsModal
      open={permissionsModalOpen}
      targetType={permissionsTargetType}
      targetId={permissionsTargetId}
      targetName={permissionsTargetName}
      {lang}
      rpcClient={rpc}
      onclose={() => (permissionsModalOpen = false)}
      onsaved={() => {
        showToast(lang === "ru" ? "Разрешения успешно обновлены" : "Permissions updated successfully", "success");
        loadData();
      }}
    />
  {/if}
</div>
