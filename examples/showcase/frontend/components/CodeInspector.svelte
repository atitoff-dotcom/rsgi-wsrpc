<script lang="ts">
  import Button from "./ui/Button.svelte";
  import Badge from "./ui/Badge.svelte";

  let {
    python = "",
    typescript = "",
    wire = "",
    lang = "ru"
  }: {
    python?: string;
    typescript?: string;
    wire?: string;
    lang?: "ru" | "en";
  } = $props();

  let activeTab = $state<"py" | "ts" | "wire">("py");
  let copied = $state(false);

  const currentCode = $derived(
    activeTab === "py" ? python : activeTab === "ts" ? typescript : wire
  );

  async function copyToClipboard() {
    try {
      await navigator.clipboard.writeText(currentCode);
      copied = true;
      setTimeout(() => {
        copied = false;
      }, 1500);
    } catch (e) {
      console.error(e);
    }
  }
</script>

<div class="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden font-mono text-xs shadow-inner">
  <!-- Tabs header -->
  <div class="flex items-center justify-between px-3 py-2 bg-slate-950/70 border-b border-slate-800">
    <div class="flex items-center gap-1.5 font-sans">
      <Button
        variant={activeTab === "py" ? "primary" : "ghost"}
        size="sm"
        onclick={() => (activeTab = "py")}
      >
        Python (Server)
      </Button>
      <Button
        variant={activeTab === "ts" ? "primary" : "ghost"}
        size="sm"
        onclick={() => (activeTab = "ts")}
      >
        TypeScript / JS
      </Button>
      <Button
        variant={activeTab === "wire" ? "primary" : "ghost"}
        size="sm"
        onclick={() => (activeTab = "wire")}
      >
        Wire JSON-RPC 2.0
      </Button>
    </div>

    <Button variant="outline" size="sm" onclick={copyToClipboard}>
      {copied ? (lang === "ru" ? "Скопировано!" : "Copied!") : (lang === "ru" ? "Копировать" : "Copy")}
    </Button>
  </div>

  <!-- Code area -->
  <div class="p-3.5 overflow-x-auto flex-1 leading-relaxed text-slate-200 bg-slate-950/40">
    <pre class="m-0 whitespace-pre font-mono text-xs">{currentCode}</pre>
  </div>
</div>
