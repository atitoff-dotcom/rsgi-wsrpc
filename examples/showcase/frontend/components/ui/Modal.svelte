<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    open = false,
    title = "",
    size = "xl",
    onclose,
    children,
    footer
  }: {
    open: boolean;
    title?: string;
    size?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl";
    onclose: () => void;
    children?: Snippet;
    footer?: Snippet;
  } = $props();

  const sizeClasses = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-2xl",
    "2xl": "max-w-4xl",
    "3xl": "max-w-5xl"
  };

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && open) {
      onclose();
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-in fade-in duration-150">
    <!-- svelte-ignore a11y_click_events_have_key_events -->
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="w-full {sizeClasses[size]} bg-white dark:bg-slate-900 rounded-lg shadow-xl border border-slate-200 dark:border-slate-800 flex flex-col max-h-[90vh] overflow-hidden animate-in zoom-in-95 duration-150"
      onclick={(e) => e.stopPropagation()}
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40">
        <h3 class="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        <button
          type="button"
          class="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 text-lg leading-none p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer"
          onclick={onclose}
          title="Закрыть (Esc)"
        >
          ✕
        </button>
      </div>

      <!-- Content -->
      <div class="p-5 overflow-y-auto flex-1 text-slate-800 dark:text-slate-200 text-sm">
        {#if children}
          {@render children()}
        {/if}
      </div>

      <!-- Footer -->
      {#if footer}
        <div class="flex items-center justify-end gap-2.5 px-5 py-3 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/40">
          {@render footer()}
        </div>
      {/if}
    </div>
  </div>
{/if}
