<script lang="ts">
  import Modal from "./ui/Modal.svelte";
  import Button from "./ui/Button.svelte";
  import Badge from "./ui/Badge.svelte";

  export interface RpcMethodDoc {
    name: string;
    group: string;
    is_public: boolean;
    description: string;
    help?: string;
  }

  let {
    open = false,
    method = null,
    onclose
  }: {
    open: boolean;
    method: RpcMethodDoc | null;
    onclose: () => void;
  } = $props();
</script>

<Modal
  {open}
  title={method ? `Справка: ${method.name}` : "Справка по методу"}
  size="lg"
  {onclose}
>
  {#if method}
    <div class="flex flex-col gap-4">
      <!-- Мета-информация о методе -->
      <div class="flex items-center justify-between gap-3 p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-border">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="font-mono text-xs font-bold px-2 py-1 rounded bg-primary/10 text-primary">
            {method.name}
          </span>
          <Badge variant="neutral" size="xs">Группа: {method.group}</Badge>
          {#if method.is_public}
            <Badge variant="success" size="xs">Публичный доступ</Badge>
          {/if}
        </div>
      </div>

      <!-- Краткое описание -->
      {#if method.description}
        <div class="flex flex-col gap-1">
          <span class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            Назначение
          </span>
          <p class="text-sm font-medium text-foreground bg-muted/30 p-2.5 rounded-md border border-border/50">
            {method.description}
          </p>
        </div>
      {/if}

      <!-- Полный Docstring / Справка по параметрам -->
      <div class="flex flex-col gap-1.5">
        <span class="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Документация и сигнатура (Docstring)
        </span>
        {#if method.help && method.help.trim()}
          <pre class="p-3.5 rounded-lg bg-slate-900 text-slate-100 dark:bg-slate-950 text-xs font-mono whitespace-pre-wrap leading-relaxed overflow-x-auto border border-slate-800 max-h-80 shadow-inner select-text">{method.help.trim()}</pre>
        {:else}
          <div class="p-4 rounded-lg bg-muted/20 border border-dashed border-border text-center text-xs text-muted-foreground">
            Полный docstring не указан в исходном коде хендлера.
          </div>
        {/if}
      </div>
    </div>
  {/if}

  {#snippet footer()}
    <Button variant="outline" size="sm" onclick={onclose}>
      Закрыть
    </Button>
  {/snippet}
</Modal>
