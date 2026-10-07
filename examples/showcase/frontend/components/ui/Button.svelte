<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    variant = "primary",
    size = "md",
    type = "button",
    disabled = false,
    title = "",
    class: extraClass = "",
    onclick,
    children
  }: {
    variant?: "primary" | "secondary" | "danger" | "ghost" | "outline";
    size?: "sm" | "md" | "lg";
    type?: "button" | "submit" | "reset";
    disabled?: boolean;
    title?: string;
    class?: string;
    onclick?: (e: MouseEvent) => void;
    children?: Snippet;
  } = $props();

  const variantClasses = {
    primary: "bg-blue-600 hover:bg-blue-700 text-white shadow-sm border-transparent",
    secondary: "bg-slate-100 hover:bg-slate-200 text-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-200 border-slate-200 dark:border-slate-700",
    danger: "bg-red-600 hover:bg-red-700 text-white shadow-sm border-transparent",
    ghost: "bg-transparent hover:bg-slate-100 text-slate-700 dark:hover:bg-slate-800 dark:text-slate-300 border-transparent",
    outline: "bg-transparent hover:bg-slate-50 text-slate-700 border-slate-300 dark:hover:bg-slate-800 dark:text-slate-200 dark:border-slate-700"
  };

  const sizeClasses = {
    sm: "px-2.5 py-1 text-xs font-medium rounded",
    md: "px-3.5 py-1.5 text-sm font-medium rounded-md",
    lg: "px-5 py-2.5 text-base font-semibold rounded-lg"
  };
</script>

<button
  {type}
  {disabled}
  {title}
  class="inline-flex items-center justify-center gap-1.5 border transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed select-none cursor-pointer {variantClasses[variant]} {sizeClasses[size]} {extraClass}"
  onclick={onclick}
>
  {#if children}
    {@render children()}
  {/if}
</button>
