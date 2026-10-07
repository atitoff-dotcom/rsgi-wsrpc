<script lang="ts">
  let {
    checked = $bindable(false),
    disabled = false,
    label = "",
    title = "",
    class: extraClass = "",
    onchange
  }: {
    checked?: boolean;
    disabled?: boolean;
    label?: string;
    title?: string;
    class?: string;
    onchange?: (checked: boolean) => void;
  } = $props();

  function handleChange(e: Event) {
    const target = e.target as HTMLInputElement;
    checked = target.checked;
    if (onchange) {
      onchange(checked);
    }
  }
</script>

<label class="inline-flex items-center gap-2 cursor-pointer select-none {disabled ? 'opacity-50 cursor-not-allowed' : ''} {extraClass}" {title}>
  <input
    type="checkbox"
    bind:checked={checked}
    {disabled}
    class="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-blue-600 focus:ring-blue-500 focus:ring-offset-1 dark:bg-slate-900 cursor-pointer disabled:cursor-not-allowed"
    onchange={handleChange}
  />
  {#if label}
    <span class="text-sm text-slate-800 dark:text-slate-200">{label}</span>
  {/if}
</label>
