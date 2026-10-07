<script lang="ts">
  let {
    value = $bindable(""),
    type = "text",
    placeholder = "",
    disabled = false,
    readonly = false,
    size = "md",
    class: extraClass = "",
    oninput,
    onkeydown,
    onchange
  }: {
    value?: any;
    type?: string;
    placeholder?: string;
    disabled?: boolean;
    readonly?: boolean;
    size?: "sm" | "md" | "lg";
    class?: string;
    oninput?: (e: Event) => void;
    onkeydown?: (e: KeyboardEvent) => void;
    onchange?: (e: Event) => void;
  } = $props();

  const sizeClasses = {
    sm: "px-2 py-1 text-xs rounded",
    md: "px-3 py-1.5 text-sm rounded-md",
    lg: "px-3.5 py-2 text-base rounded-md"
  };
</script>

<input
  {type}
  bind:value={value}
  {placeholder}
  {disabled}
  {readonly}
  class="w-full border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors disabled:opacity-50 disabled:bg-slate-100 dark:disabled:bg-slate-800 {sizeClasses[size]} {extraClass}"
  oninput={oninput}
  onkeydown={onkeydown}
  onchange={onchange}
/>
