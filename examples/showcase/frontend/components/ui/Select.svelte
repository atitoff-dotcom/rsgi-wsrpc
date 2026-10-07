<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    value = $bindable(""),
    disabled = false,
    size = "md",
    class: extraClass = "",
    onchange,
    options = [],
    children
  }: {
    value?: any;
    disabled?: boolean;
    size?: "sm" | "md" | "lg";
    class?: string;
    onchange?: (e: Event) => void;
    options?: Array<{ value: any; label: string }>;
    children?: Snippet;
  } = $props();

  const sizeClasses = {
    sm: "px-2 py-1 text-xs rounded",
    md: "px-3 py-1.5 text-sm rounded-md",
    lg: "px-3.5 py-2 text-base rounded-md"
  };
</script>

<select
  bind:value={value}
  {disabled}
  class="border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors disabled:opacity-50 cursor-pointer {sizeClasses[size]} {extraClass}"
  onchange={onchange}
>
  {#if children}
    {@render children()}
  {:else}
    {#each options as opt}
      <option value={opt.value}>{opt.label}</option>
    {/each}
  {/if}
</select>
