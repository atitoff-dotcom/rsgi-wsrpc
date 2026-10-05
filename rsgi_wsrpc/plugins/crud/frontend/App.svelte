<script lang="ts">
  import { onMount } from "svelte";
  import { StandaloneWSRPC } from "./wsrpc_client";

  // WSRPC клиент
  const rpc = new StandaloneWSRPC();
  let wsStatus = $state<"CONNECTING" | "CONNECTED" | "DISCONNECTED">("DISCONNECTED");

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

  // Модели и схема
  let models = $state<any[]>([]);
  let selectedModelName = $state<string>("");
  let currentSchema = $derived(models.find((m) => m.key === selectedModelName) || null);
  let isLoadingSchema = $state(true);

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

  // Индекс ID
  let idColIdx = $derived(
    fields.indexOf("id") !== -1 ? fields.indexOf("id") : fields.indexOf("key")
  );

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

  async function loadSchema() {
    isLoadingSchema = true;
    try {
      const res = await rpc.call("crud.schema", {});
      if (res && res.models) {
        models = res.models;
        if (!models.some((m) => m.key === selectedModelName) && models.length > 0) {
          selectedModelName = models[0].key;
        }
      }
    } catch (e: any) {
      showToast(`Ошибка схемы: ${e.message}`, "error");
    } finally {
      isLoadingSchema = false;
    }
  }

  async function loadData() {
    if (!selectedModelName) return;
    isLoadingData = true;
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

      if (res && res.$tabular) {
        fields = res.fields || [];
        rows = res.rows || [];
        total = res.total || 0;
      }
    } catch (e: any) {
      showToast(`Ошибка загрузки данных: ${e.message}`, "error");
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
      const targetRow = rows.find((r) => r[idColIdx] === id);
      if (targetRow) {
        const cIdx = fields.indexOf(field);
        if (cIdx !== -1) targetRow[cIdx] = value;
        rows = [...rows];
      }
      showToast("Ячейка сохранена");
      editingCell = null;
    } catch (e: any) {
      showToast(`Ошибка сохранения: ${e.message}`, "error");
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
      const targetRow = rows.find((r) => r[idColIdx] === recordId);
      if (targetRow) {
        const cIdx = fields.indexOf(fieldName);
        if (cIdx !== -1) targetRow[cIdx] = nextVal;
        rows = [...rows];
      }
      showToast("Статус обновлен");
    } catch (e: any) {
      showToast(`Ошибка: ${e.message}`, "error");
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
      rows = rows.filter((r) => r[idColIdx] !== recordToDelete);
      total = Math.max(0, total - 1);
      showToast(`Запись #${recordToDelete} удалена`);
      recordToDelete = null;
    } catch (e: any) {
      showToast(`Ошибка удаления: ${e.message}`, "error");
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
      showToast("Запись успешно создана");
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
    if (!params || params.model !== selectedModelName) return;
    const recId = params.id;

    if (params.deleted) {
      rows = rows.filter((r) => r[idColIdx] !== recId);
      total = Math.max(0, total - 1);
      return;
    }

    if (params.created) {
      loadData();
      return;
    }

    if (params.kind === "updated" || params.changes) {
      const targetRow = rows.find((r) => r[idColIdx] === recId);
      if (targetRow) {
        if (params.changes) {
          for (const [k, v] of Object.entries(params.changes)) {
            const cIdx = fields.indexOf(k);
            if (cIdx !== -1) targetRow[cIdx] = v;
          }
          rows = [...rows];
        } else {
          // Безопасное дочитывание через RLS-защищенный get
          rpc.call("crud.get", { model: selectedModelName, id: recId })
            .then((res: any) => {
              if (res && res.record) {
                const rIdx = rows.findIndex((r) => r[idColIdx] === recId);
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
    // Инициализация темы из localStorage или системных настроек
    const savedTheme = localStorage.getItem("crud_admin_theme");
    if (savedTheme === "dark" || (!savedTheme && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      isDarkMode = true;
      document.documentElement.classList.add("dark");
    } else {
      isDarkMode = false;
      document.documentElement.classList.remove("dark");
    }

    rpc.onStatusChange = (status) => {
      wsStatus = status;
      if (status === "CONNECTED") {
        loadSchema().then(() => loadData());
      }
    };
    rpc.register("cache.patch", handleCachePatch);
    rpc.connect();
  });

  $effect(() => {
    if (selectedModelName && wsStatus === "CONNECTED") {
      page = 1;
      loadData();
    }
  });
</script>

<div class="min-h-screen flex flex-col bg-background text-foreground antialiased selection:bg-primary/20">
  <!-- Верхняя панель (Header) -->
  <header class="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-card/90 px-6 py-3.5 backdrop-blur-md shadow-xs">
    <div class="flex items-center gap-4">
      <div class="flex items-center gap-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground font-bold shadow-xs">
          ⚡
        </div>
        <span class="text-base font-bold tracking-tight text-foreground">CRUD Admin</span>
      </div>

      <!-- Селектор модели -->
      {#if models.length > 0}
        <div class="flex items-center gap-2 pl-4 border-l border-border">
          <span class="text-xs text-muted-foreground font-medium">Модель:</span>
          <select
            bind:value={selectedModelName}
            class="rounded-md border border-input bg-background px-3 py-1.5 text-xs font-semibold text-foreground focus:outline-none focus:ring-2 focus:ring-primary shadow-2xs"
          >
            {#each models as m}
              <option value={m.key}>{m.verbose_name_plural || m.key}</option>
            {/each}
          </select>
        </div>
      {/if}
    </div>

    <!-- Правая часть: статус подключения и тумблер темы -->
    <div class="flex items-center gap-3">
      <!-- Статус сокета -->
      <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-2xs font-semibold border {wsStatus === 'CONNECTED' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600 dark:text-emerald-400' : 'bg-rose-500/10 border-rose-500/30 text-rose-600 dark:text-rose-400'}">
        <span class="h-2 w-2 rounded-full {wsStatus === 'CONNECTED' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}"></span>
        <span>{wsStatus === 'CONNECTED' ? 'WSRPC Онлайн' : 'Подключение...'}</span>
      </div>

      <!-- Переключатель светлой / темно-серой темы -->
      <button
        type="button"
        onclick={toggleTheme}
        class="flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-muted/60 text-foreground hover:bg-muted transition-colors cursor-pointer"
        title={isDarkMode ? "Включить светлую тему" : "Включить темно-серую тему"}
      >
        {#if isDarkMode}
          <span class="text-sm">☀️</span>
        {:else}
          <span class="text-sm">🌙</span>
        {/if}
      </button>
    </div>
  </header>

  <!-- Основное содержимое -->
  <main class="flex-1 p-6 max-w-7xl mx-auto w-full flex flex-col gap-5">
    {#if isLoadingSchema}
      <div class="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Загрузка схемы моделей...
      </div>
    {:else if currentSchema}
      <!-- Панель управления таблицей: поиск, фильтры, создать -->
      <div class="flex flex-wrap items-center justify-between gap-4 bg-card p-4 rounded-xl border border-border shadow-xs">
        <div class="flex items-center gap-3 flex-1 max-w-md">
          <input
            type="text"
            bind:value={searchQuery}
            onkeydown={(e) => { if (e.key === 'Enter') loadData(); }}
            placeholder="Поиск по строкам (Enter)..."
            class="w-full rounded-lg border border-input bg-background px-3.5 py-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary shadow-2xs"
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
              {showArchived ? "Архив: Вкл" : "Архив: Выкл"}
            </button>
          {/if}

          <button
            type="button"
            onclick={loadData}
            class="px-3 py-1.5 rounded-lg text-xs font-medium border border-input bg-background hover:bg-muted text-foreground cursor-pointer transition-colors"
            title="Обновить данные"
          >
            ↻ Обновить
          </button>

          {#if currentSchema.permissions?.can_create}
            <button
              type="button"
              onclick={() => { createFormData = {}; createError = ''; isCreateModalOpen = true; }}
              class="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 shadow-2xs cursor-pointer transition-colors"
            >
              + Создать
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
                {#each currentSchema.fields as col}
                  <th
                    scope="col"
                    class="px-4 py-3 cursor-pointer hover:bg-muted/80 transition-colors select-none"
                    onclick={() => handleSort(col.name)}
                  >
                    <div class="flex items-center gap-1">
                      <span>{col.label || col.name}</span>
                      {#if sortField === col.name}
                        <span class="text-primary font-bold">{sortDir === 'asc' ? '▲' : '▼'}</span>
                      {/if}
                    </div>
                  </th>
                {/each}
                {#if currentSchema.permissions?.can_delete}
                  <th scope="col" class="px-4 py-3 text-right">Действия</th>
                {/if}
              </tr>
            </thead>
            <tbody class="divide-y divide-border">
              {#if isLoadingData && rows.length === 0}
                <tr>
                  <td colspan="100" class="h-40 text-center text-muted-foreground">
                    Загрузка строк...
                  </td>
                </tr>
              {:else if rows.length === 0}
                <tr>
                  <td colspan="100" class="h-40 text-center text-muted-foreground italic">
                    Записей не найдено
                  </td>
                </tr>
              {:else}
                {#each rows as row (row[idColIdx])}
                  {@const recId = row[idColIdx]}
                  <tr class="hover:bg-muted/30 transition-colors">
                    {#each currentSchema.fields as col}
                      {@const cIdx = fields.indexOf(col.name)}
                      {@const val = row[cIdx]}
                      {@const isEditing = editingCell?.id === recId && editingCell?.field === col.name}

                      <td class="px-4 py-2.5 whitespace-nowrap">
                        {#if isEditing && editingCell}
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
                        {:else}
                          <div class="flex items-center justify-between gap-2 group">
                            {#if typeof val === "boolean"}
                              <button
                                type="button"
                                onclick={() => toggleBool(recId, col.name, val)}
                                class="cursor-pointer font-semibold px-2 py-0.5 rounded text-2xs {val ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400' : 'bg-muted text-muted-foreground'}"
                              >
                                {val ? "Да" : "Нет"}
                              </button>
                            {:else if val === null || val === undefined}
                              <span class="text-muted-foreground/40">—</span>
                            {:else}
                              <span class="truncate max-w-xs">{String(val)}</span>
                            {/if}

                            {#if col.editable && typeof val !== "boolean"}
                              <button
                                type="button"
                                onclick={() => (editingCell = { id: recId, field: col.name, value: val ?? '' })}
                                class="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-primary transition-opacity text-2xs cursor-pointer"
                                title="Редактировать ячейку"
                              >
                                ✎
                              </button>
                            {/if}
                          </div>
                        {/if}
                      </td>
                    {/each}

                    {#if currentSchema.permissions?.can_delete}
                      <td class="px-4 py-2.5 text-right whitespace-nowrap">
                        <button
                          type="button"
                          onclick={() => (recordToDelete = recId)}
                          class="text-rose-500 hover:text-rose-600 dark:text-rose-400 p-1 rounded hover:bg-rose-500/10 transition-colors cursor-pointer"
                          title="Удалить"
                        >
                          🗑
                        </button>
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
            Всего записей: <strong class="text-foreground">{total}</strong>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onclick={() => { page--; loadData(); }}
              class="px-2.5 py-1 rounded border border-input bg-background hover:bg-muted disabled:opacity-40 cursor-pointer text-foreground"
            >
              Назад
            </button>
            <span>Стр. {page} из {Math.ceil(total / pageSize) || 1}</span>
            <button
              type="button"
              disabled={page * pageSize >= total}
              onclick={() => { page++; loadData(); }}
              class="px-2.5 py-1 rounded border border-input bg-background hover:bg-muted disabled:opacity-40 cursor-pointer text-foreground"
            >
              Вперед
            </button>
          </div>
        </div>
      </div>
    {:else}
      <div class="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Нет доступных моделей для отображения.
      </div>
    {/if}
  </main>

  <!-- Модальное окно создания -->
  {#if isCreateModalOpen && currentSchema}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in">
      <div class="w-full max-w-lg rounded-xl border border-border bg-card p-6 shadow-xl flex flex-col gap-4 text-foreground">
        <div class="flex items-center justify-between border-b border-border pb-3">
          <h3 class="text-sm font-bold text-foreground">
            Создать: {currentSchema.verbose_name || currentSchema.key}
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
                  {col.label || col.name} {#if !col.nullable}<span class="text-rose-500">*</span>{/if}
                </label>
                {#if col.type === "boolean"}
                  <label class="flex items-center gap-2 cursor-pointer pt-1">
                    <input
                      type="checkbox"
                      bind:checked={createFormData[col.name]}
                      class="h-4 w-4 rounded border-border text-primary accent-primary"
                    />
                    <span class="text-xs font-medium">{createFormData[col.name] ? 'Да' : 'Нет'}</span>
                  </label>
                {:else if col.type === "integer"}
                  <input
                    id={`create-field-${col.name}`}
                    type="number"
                    step="1"
                    bind:value={createFormData[col.name]}
                    placeholder={col.label}
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
                    placeholder={col.label}
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
            Отмена
          </button>
          <button
            type="button"
            onclick={submitCreate}
            disabled={isCreating}
            class="px-4 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            {isCreating ? 'Создание...' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- Модальное окно удаления -->
  {#if recordToDelete !== null}
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in">
      <div class="w-full max-w-sm rounded-xl border border-border bg-card p-5 shadow-xl flex flex-col gap-4 text-foreground">
        <h3 class="text-sm font-bold text-foreground">Подтверждение удаления</h3>
        <p class="text-xs text-muted-foreground">
          Вы уверены, что хотите удалить запись <strong class="text-foreground">#{recordToDelete}</strong>? Это действие нельзя отменить.
        </p>
        <div class="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onclick={() => (recordToDelete = null)}
            class="px-3 py-1.5 rounded-lg border border-input bg-background hover:bg-muted text-xs font-medium text-foreground cursor-pointer"
          >
            Отмена
          </button>
          <button
            type="button"
            onclick={confirmDelete}
            disabled={isDeleting}
            class="px-3.5 py-1.5 rounded-lg bg-destructive text-destructive-foreground hover:bg-destructive/90 text-xs font-semibold cursor-pointer disabled:opacity-50"
          >
            {isDeleting ? 'Удаление...' : 'Удалить'}
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
</div>
