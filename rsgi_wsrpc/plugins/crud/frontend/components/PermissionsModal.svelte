<script lang="ts">
  import { onMount } from "svelte";
  import Modal from "./ui/Modal.svelte";
  import Button from "./ui/Button.svelte";
  import Input from "./ui/Input.svelte";
  import Select from "./ui/Select.svelte";
  import Checkbox from "./ui/Checkbox.svelte";
  import Badge from "./ui/Badge.svelte";
  import RpcHelpModal, { type RpcMethodDoc } from "./RpcHelpModal.svelte";

  interface Props {
    open: boolean;
    targetType: "role" | "user" | "guest";
    targetId: number;
    targetName: string;
    lang?: "ru" | "en";
    rpcClient: any;
    onclose: () => void;
    onsaved?: () => void;
  }

  let {
    open = false,
    targetType,
    targetId,
    targetName,
    lang = "ru",
    rpcClient,
    onclose,
    onsaved
  }: Props = $props();

  let activeTab = $state<"crud" | "rpc">("crud");
  let isLoading = $state(true);
  let isSaving = $state(false);
  let errorMessage = $state("");
  let successMessage = $state("");

  // Поисковые строки
  let modelSearch = $state("");
  let rpcSearch = $state("");

  // Схема из permissions.get_schema
  interface ModelMetaItem {
    key: string;
    verbose_name: string;
    table_name: string;
    is_row_secure: boolean;
  }

  interface RpcMethodItem extends RpcMethodDoc {}

  let availableModels = $state<ModelMetaItem[]>([]);
  let availableRpcs = $state<RpcMethodItem[]>([]);

  let helpModalOpen = $state(false);
  let selectedHelpMethod = $state<RpcMethodDoc | null>(null);

  function openHelp(m: RpcMethodItem) {
    selectedHelpMethod = m;
    helpModalOpen = true;
  }

  // Текущее редактируемое состояние прав
  interface CrudPermState {
    can_create: boolean;
    can_read: boolean;
    can_update: boolean;
    can_delete: boolean;
    row_level_only: boolean;
  }

  let crudPerms = $state<Record<string, CrudPermState>>({});
  let rpcPerms = $state<Set<string>>(new Set());

  // Унаследованные ролевые права (только при targetType === 'user')
  let inheritedCrud = $state<Record<string, CrudPermState>>({});
  let inheritedRpc = $state<Set<string>>(new Set());
  let targetRoles = $state<string[]>([]);
  let isSuperadmin = $state(false);

  const t = $derived({
    ru: {
      modalTitle: targetType === "role" 
        ? `Настройка прав: Роль «${targetName}»`
        : targetType === "guest"
          ? "Настройка прав: Гости (Публичный доступ)"
          : `Настройка прав: Пользователь «${targetName}»`,
      tabCrud: "📦 Таблицы данных (CRUD)",
      tabRpc: "⚡ Действия и функции (RPC)",
      searchModel: "Поиск таблицы...",
      searchRpc: "Поиск действия / функции...",
      presetReadOnly: "Только чтение",
      presetFull: "Полный доступ",
      presetReset: "Сбросить всё",
      colModel: "Таблица данных",
      colCreate: "Создание",
      colRead: "Чтение",
      colUpdate: "Изменение",
      colDelete: "Удаление",
      colScope: "Область доступа",
      scopeRow: "Только свои записи",
      scopeGlobal: "Все записи",
      inheritedFromRole: "из ролей",
      personalOverride: "Персонально",
      cancel: "Отмена",
      save: "Сохранить",
      saving: "Сохранение...",
      loading: "Загрузка прав...",
      publicBadge: "Открыто гостям",
      noModels: "Таблицы не найдены",
      noRpcs: "Действия не найдены",
      selectAllGroup: "Выбрать всю группу",
      savedOk: "Права успешно сохранены",
      superadminNotice: "Пользователь является администратором — полный доступ ко всем ресурсам системы."
    },
    en: {
      modalTitle: targetType === "role"
        ? `Permissions: Role "${targetName}"`
        : targetType === "guest"
          ? "Permissions: Guests (Public Access)"
          : `Permissions: User "${targetName}"`,
      tabCrud: "📦 Data Tables (CRUD)",
      tabRpc: "⚡ Actions & Functions (RPC)",
      searchModel: "Search table...",
      searchRpc: "Search action / function...",
      presetReadOnly: "Read Only",
      presetFull: "Full Access",
      presetReset: "Reset All",
      colModel: "Data Table",
      colCreate: "Create",
      colRead: "Read",
      colUpdate: "Update",
      colDelete: "Delete",
      colScope: "Access Scope",
      scopeRow: "Own Records Only",
      scopeGlobal: "All Records",
      inheritedFromRole: "from roles",
      personalOverride: "Personal",
      cancel: "Cancel",
      save: "Save",
      saving: "Saving...",
      loading: "Loading permissions...",
      publicBadge: "Public",
      noModels: "No tables found",
      noRpcs: "No actions found",
      selectAllGroup: "Select group",
      savedOk: "Permissions saved successfully",
      superadminNotice: "User is an administrator with full access to all resources."
    }
  }[lang]);

  async function loadData() {
    isLoading = true;
    errorMessage = "";
    successMessage = "";
    try {
      // 1. Получаем общую схему моделей и процедур
      const schema = await rpcClient.call("permissions.get_schema");
      availableModels = schema.models || [];
      availableRpcs = schema.rpc_methods || [];

      // 2. Получаем текущие права цели
      const data = await rpcClient.call("permissions.get", {
        target_type: targetType,
        target_id: targetId
      });

      // Инициализируем CRUD-права
      const newCrud: Record<string, CrudPermState> = {};
      for (const m of availableModels) {
        newCrud[m.key] = {
          can_create: false,
          can_read: false,
          can_update: false,
          can_delete: false,
          row_level_only: true
        };
      }

      if (targetType === "role") {
        const roleCrud = data.crud_permissions || {};
        for (const [mName, p] of Object.entries<any>(roleCrud)) {
          if (newCrud[mName]) {
            newCrud[mName] = {
              can_create: Boolean(p.can_create),
              can_read: Boolean(p.can_read),
              can_update: Boolean(p.can_update),
              can_delete: Boolean(p.can_delete),
              row_level_only: Boolean(p.row_level_only)
            };
          }
        }
        crudPerms = newCrud;
        rpcPerms = new Set(data.rpc_permissions || []);
      } else {
        // targetType === 'user'
        targetRoles = data.target_roles || [];
        isSuperadmin = Boolean(data.is_superadmin);
        inheritedCrud = data.inherited_crud || {};
        inheritedRpc = new Set(data.inherited_rpc || []);

        const personal = data.personal_crud || {};
        for (const [mName, p] of Object.entries<any>(personal)) {
          if (newCrud[mName]) {
            newCrud[mName] = {
              can_create: Boolean(p.can_create),
              can_read: Boolean(p.can_read),
              can_update: Boolean(p.can_update),
              can_delete: Boolean(p.can_delete),
              row_level_only: Boolean(p.row_level_only)
            };
          }
        }
        crudPerms = newCrud;
        rpcPerms = new Set(data.personal_rpc || []);
      }
    } catch (err: any) {
      errorMessage = err?.message || String(err);
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    if (open && targetId) {
      loadData();
    }
  });

  // Пресеты
  function applyPreset(preset: "readonly" | "full" | "reset") {
    for (const m of availableModels) {
      if (preset === "readonly") {
        crudPerms[m.key] = {
          can_create: false,
          can_read: true,
          can_update: false,
          can_delete: false,
          row_level_only: true
        };
      } else if (preset === "full") {
        crudPerms[m.key] = {
          can_create: true,
          can_read: true,
          can_update: true,
          can_delete: true,
          row_level_only: false
        };
      } else if (preset === "reset") {
        crudPerms[m.key] = {
          can_create: false,
          can_read: false,
          can_update: false,
          can_delete: false,
          row_level_only: true
        };
      }
    }
  }

  // Фильтрация моделей
  const filteredModels = $derived(
    availableModels.filter((m) => {
      const q = modelSearch.toLowerCase().trim();
      if (!q) return true;
      return (
        m.key.toLowerCase().includes(q) ||
        (m.verbose_name && m.verbose_name.toLowerCase().includes(q)) ||
        m.table_name.toLowerCase().includes(q)
      );
    })
  );

  // Группировка RPC методов
  const rpcGroups = $derived(() => {
    const q = rpcSearch.toLowerCase().trim();
    const map = new Map<string, RpcMethodItem[]>();
    for (const rpc of availableRpcs) {
      if (q && !rpc.name.toLowerCase().includes(q) && !rpc.group.toLowerCase().includes(q)) {
        continue;
      }
      if (!map.has(rpc.group)) {
        map.set(rpc.group, []);
      }
      map.get(rpc.group)!.push(rpc);
    }
    return Array.from(map.entries()).map(([group, methods]) => ({ group, methods }));
  });

  function toggleRpcMethod(name: string) {
    if (rpcPerms.has(name)) {
      rpcPerms.delete(name);
    } else {
      rpcPerms.add(name);
    }
    rpcPerms = new Set(rpcPerms);
  }

  function toggleRpcGroup(methods: RpcMethodItem[]) {
    const allSelected = methods.every((m) => rpcPerms.has(m.name));
    if (allSelected) {
      for (const m of methods) {
        rpcPerms.delete(m.name);
      }
    } else {
      for (const m of methods) {
        rpcPerms.add(m.name);
      }
    }
    rpcPerms = new Set(rpcPerms);
  }

  async function handleSave() {
    isSaving = true;
    errorMessage = "";
    successMessage = "";
    try {
      await rpcClient.call("permissions.save", {
        target_type: targetType,
        target_id: targetId,
        crud_permissions: crudPerms,
        rpc_permissions: Array.from(rpcPerms)
      });
      successMessage = t.savedOk;
      if (onsaved) {
        onsaved();
      }
      setTimeout(() => {
        onclose();
      }, 700);
    } catch (err: any) {
      errorMessage = err?.message || String(err);
    } finally {
      isSaving = false;
    }
  }
</script>

<Modal {open} title={t.modalTitle} size="3xl" {onclose}>
  {#if isSuperadmin}
    <div class="mb-4 p-3 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded text-amber-800 dark:text-amber-200 text-sm">
      {t.superadminNotice}
    </div>
  {/if}

  <!-- Вкладки -->
  <div class="flex items-center gap-2 border-b border-slate-200 dark:border-slate-800 mb-4 pb-2">
    <Button
      variant={activeTab === "crud" ? "primary" : "ghost"}
      size="sm"
      onclick={() => (activeTab = "crud")}
    >
      {t.tabCrud}
    </Button>
    <Button
      variant={activeTab === "rpc" ? "primary" : "ghost"}
      size="sm"
      onclick={() => (activeTab = "rpc")}
    >
      {t.tabRpc}
    </Button>

    {#if targetType === "user" && targetRoles.length > 0}
      <div class="ml-auto flex items-center gap-1.5 text-xs text-slate-500">
        <span>Роли:</span>
        {#each targetRoles as role}
          <Badge variant="secondary" size="xs">{role}</Badge>
        {/each}
      </div>
    {/if}
  </div>

  {#if isLoading}
    <div class="py-12 text-center text-slate-500 text-sm">
      {t.loading}
    </div>
  {:else}
    {#if errorMessage}
      <div class="mb-4 p-3 bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 rounded text-red-700 dark:text-red-300 text-sm">
        {errorMessage}
      </div>
    {/if}
    {#if successMessage}
      <div class="mb-4 p-3 bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 rounded text-emerald-700 dark:text-emerald-300 text-sm">
        {successMessage}
      </div>
    {/if}

    <!-- ВКЛАДКА 1: CRUD -->
    {#if activeTab === "crud"}
      <div class="flex flex-col gap-3">
        <!-- Тулбар пресетов и поиска -->
        <div class="flex items-center justify-between gap-3">
          <div class="w-64">
            <Input
              bind:value={modelSearch}
              placeholder={t.searchModel}
              size="sm"
            />
          </div>
          <div class="flex items-center gap-2">
            <Button variant="secondary" size="sm" onclick={() => applyPreset("readonly")}>
              {t.presetReadOnly}
            </Button>
            <Button variant="secondary" size="sm" onclick={() => applyPreset("full")}>
              {t.presetFull}
            </Button>
            <Button variant="outline" size="sm" onclick={() => applyPreset("reset")}>
              {t.presetReset}
            </Button>
          </div>
        </div>

        <!-- Таблица матрицы прав -->
        <div class="border border-slate-200 dark:border-slate-800 rounded-md overflow-hidden">
          <table class="w-full text-left text-sm border-collapse">
            <thead class="bg-slate-50 dark:bg-slate-800/60 border-b border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300">
              <tr>
                <th class="p-2.5 font-medium">{t.colModel}</th>
                <th class="p-2.5 font-medium text-center w-24">{t.colCreate}</th>
                <th class="p-2.5 font-medium text-center w-24">{t.colRead}</th>
                <th class="p-2.5 font-medium text-center w-24">{t.colUpdate}</th>
                <th class="p-2.5 font-medium text-center w-24">{t.colDelete}</th>
                <th class="p-2.5 font-medium w-56">{t.colScope}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 dark:divide-slate-800/60 font-mono text-xs">
              {#if filteredModels.length === 0}
                <tr>
                  <td colspan="6" class="p-4 text-center text-slate-400 font-sans text-sm">
                    {t.noModels}
                  </td>
                </tr>
              {:else}
                {#each filteredModels as model}
                  {@const p = crudPerms[model.key]}
                  {@const inh = inheritedCrud[model.key]}
                  {#if p}
                    <tr class="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors">
                      <!-- Модель -->
                      <td class="p-2.5">
                        <div class="font-sans font-medium text-slate-900 dark:text-slate-100 text-sm">
                          {model.verbose_name || model.key}
                        </div>
                        <div class="text-[11px] text-slate-400 font-mono">
                          {model.key} ({model.table_name})
                        </div>
                        {#if inh && targetType === "user" && (inh.can_read || inh.can_create || inh.can_update || inh.can_delete)}
                          <div class="mt-0.5">
                            <Badge variant="purple" size="xs">🔒 {t.inheritedFromRole}</Badge>
                          </div>
                        {/if}
                      </td>

                      <!-- C -->
                      <td class="p-2.5 text-center">
                        <div class="inline-flex flex-col items-center">
                          <Checkbox bind:checked={p.can_create} />
                          {#if inh?.can_create && targetType === "user"}
                            <span class="text-[10px] text-purple-600 dark:text-purple-400 font-sans">🔒</span>
                          {/if}
                        </div>
                      </td>

                      <!-- R -->
                      <td class="p-2.5 text-center">
                        <div class="inline-flex flex-col items-center">
                          <Checkbox bind:checked={p.can_read} />
                          {#if inh?.can_read && targetType === "user"}
                            <span class="text-[10px] text-purple-600 dark:text-purple-400 font-sans">🔒</span>
                          {/if}
                        </div>
                      </td>

                      <!-- U -->
                      <td class="p-2.5 text-center">
                        <div class="inline-flex flex-col items-center">
                          <Checkbox bind:checked={p.can_update} />
                          {#if inh?.can_update && targetType === "user"}
                            <span class="text-[10px] text-purple-600 dark:text-purple-400 font-sans">🔒</span>
                          {/if}
                        </div>
                      </td>

                      <!-- D -->
                      <td class="p-2.5 text-center">
                        <div class="inline-flex flex-col items-center">
                          <Checkbox bind:checked={p.can_delete} />
                          {#if inh?.can_delete && targetType === "user"}
                            <span class="text-[10px] text-purple-600 dark:text-purple-400 font-sans">🔒</span>
                          {/if}
                        </div>
                      </td>

                      <!-- Область действия (Row-Level vs Global) -->
                      <td class="p-2.5 font-sans">
                        <Select
                          size="sm"
                          value={p.row_level_only ? "row" : "global"}
                          onchange={(e: any) => {
                            p.row_level_only = e.target.value === "row";
                          }}
                          options={[
                            { value: "row", label: t.scopeRow },
                            { value: "global", label: t.scopeGlobal }
                          ]}
                        />
                      </td>
                    </tr>
                  {/if}
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </div>

    <!-- ВКЛАДКА 2: RPC -->
    {:else if activeTab === "rpc"}
      <div class="flex flex-col gap-3">
        <div class="w-72">
          <Input
            bind:value={rpcSearch}
            placeholder={t.searchRpc}
            size="sm"
          />
        </div>

        <div class="flex flex-col gap-3 max-h-[50vh] overflow-y-auto pr-1">
          {#if rpcGroups().length === 0}
            <div class="py-8 text-center text-slate-400 text-sm">
              {t.noRpcs}
            </div>
          {:else}
            {#each rpcGroups() as groupItem}
              {@const allInGroupSelected = groupItem.methods.every((m) => rpcPerms.has(m.name))}
              <div class="border border-slate-200 dark:border-slate-800 rounded-md p-3 bg-white dark:bg-slate-900">
                <!-- Заголовок группы с возможностью выбрать всю группу -->
                <div class="flex items-center justify-between pb-2 mb-2 border-b border-slate-100 dark:border-slate-800">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-slate-900 dark:text-slate-100 text-sm">
                      {groupItem.group}.*
                    </span>
                    <Badge variant="neutral" size="xs">
                      {groupItem.methods.length}
                    </Badge>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onclick={() => toggleRpcGroup(groupItem.methods)}
                  >
                    {allInGroupSelected ? "Снять выбор" : t.selectAllGroup}
                  </Button>
                </div>

                <!-- Список методов в группе -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {#each groupItem.methods as method}
                    {@const isChecked = rpcPerms.has(method.name)}
                    {@const isInherited = inheritedRpc.has(method.name)}
                    <label class="flex items-start gap-2 p-1.5 rounded hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer select-none">
                      <input
                        type="checkbox"
                        checked={isChecked}
                        class="w-4 h-4 mt-0.5 rounded border-slate-300 dark:border-slate-700 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        onchange={() => toggleRpcMethod(method.name)}
                      />
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center justify-between gap-1.5">
                          <div class="flex items-center gap-1.5 flex-wrap">
                            <span class="font-mono text-xs text-slate-800 dark:text-slate-200 truncate">
                              {method.name}
                            </span>
                            {#if method.is_public}
                              <Badge variant="success" size="xs">{t.publicBadge}</Badge>
                            {/if}
                            {#if isInherited && targetType === "user"}
                              <Badge variant="purple" size="xs">🔒 {t.inheritedFromRole}</Badge>
                            {/if}
                          </div>
                          <button
                            type="button"
                            class="inline-flex items-center justify-center w-5 h-5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-800 dark:hover:text-slate-200 text-xs transition-colors cursor-pointer shrink-0"
                            onclick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              openHelp(method);
                            }}
                            title="Справка по методу"
                          >
                            ℹ️
                          </button>
                        </div>
                        {#if method.description}
                          <p class="text-[11px] text-slate-400 truncate">
                            {method.description}
                          </p>
                        {/if}
                      </div>
                    </label>
                  {/each}
                </div>
              </div>
            {/each}
          {/if}
        </div>
      </div>
    {/if}
  {/if}

  {#snippet footer()}
    <Button variant="outline" size="md" onclick={onclose} disabled={isSaving}>
      {t.cancel}
    </Button>
    <Button variant="primary" size="md" onclick={handleSave} disabled={isSaving || isLoading}>
      {isSaving ? t.saving : t.save}
    </Button>
  {/snippet}
</Modal>

<RpcHelpModal
  open={helpModalOpen}
  method={selectedHelpMethod}
  onclose={() => {
    helpModalOpen = false;
    selectedHelpMethod = null;
  }}
/>
