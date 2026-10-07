<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    variant = "neutral",
    size = "sm",
    class: extraClass = "",
    children
  }: {
    variant?: "primary" | "secondary" | "success" | "warning" | "danger" | "neutral" | "purple";
    size?: "xs" | "sm" | "md";
    class?: string;
    children?: Snippet;
  } = $props();

  const variantClasses = {
    primary: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border-blue-200 dark:border-blue-800",
    secondary: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-slate-700",
    success: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800",
    warning: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-800",
    danger: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 border-red-200 dark:border-red-800",
    neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border-slate-200 dark:border-slate-700",
    purple: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300 border-purple-200 dark:border-purple-800"
  };

  const sizeClasses = {
    xs: "px-1.5 py-0.2 text-[11px] font-medium rounded",
    sm: "px-2 py-0.5 text-xs font-medium rounded",
    md: "px-2.5 py-1 text-sm font-medium rounded-md"
  };
</script>

<span class="inline-flex items-center gap-1 border {variantClasses[variant]} {sizeClasses[size]} {extraClass}">
  {#if children}
    {@render children()}
  {/if}
</span>
