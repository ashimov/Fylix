<script setup lang="ts">
import { onMounted, ref } from "vue";

import { addExtension, getExtensions, removeExtension } from "@/api/settings";
import { useSession } from "@/stores/session";

const session = useSession();
const extensions = ref<string[]>([]);
const newExt = ref("");
const error = ref<string | null>(null);

async function load(): Promise<void> {
  try {
    extensions.value = await getExtensions();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function add(): Promise<void> {
  let ext = newExt.value.trim().toLowerCase();
  if (!ext) return;
  if (!ext.startsWith(".")) ext = "." + ext;
  try {
    await addExtension(ext);
    newExt.value = "";
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function remove(ext: string): Promise<void> {
  if (!window.confirm(`Remove ${ext}?`)) return;
  try {
    await removeExtension(ext);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

onMounted(load);
</script>

<template>
  <section>
    <h1>Extension blacklist</h1>

    <p v-if="error" class="error">{{ error }}</p>

    <p class="hint">Files with these extensions are rejected at upload time.</p>

    <div v-if="session.admin?.role === 'admin'" class="form">
      <input v-model="newExt" placeholder=".exe" @keydown.enter="add" />
      <button class="btn" @click="add" :disabled="!newExt.trim()">Add</button>
    </div>

    <div class="chips">
      <span v-for="ext in extensions" :key="ext" class="chip">
        {{ ext }}
        <button
          v-if="session.admin?.role === 'admin'"
          class="chip__remove"
          aria-label="Remove"
          @click="remove(ext)"
        >×</button>
      </span>
      <span v-if="extensions.length === 0" class="muted">No extensions blocked.</span>
    </div>
  </section>
</template>

<style scoped>
h1 { font-size: 28px; margin: 0 0 12px; }
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); margin-bottom: 16px; }
.hint { color: var(--text-secondary); margin-bottom: 20px; font-size: 14px; }
.form { display: flex; gap: 10px; margin-bottom: 24px; }
.form input {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  min-width: 200px;
}
.btn { padding: 8px 18px; background: var(--brand-navy); color: #fff; border-radius: var(--radius); font-weight: 600; font-size: 13px; }
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  background: var(--surface);
  padding: 20px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--tag-bg);
  color: var(--brand-navy);
  border-radius: 999px;
  font-size: 14px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-weight: 600;
}
[data-theme="dark"] .chip { color: var(--brand-blue); }
.chip__remove {
  background: none;
  border: none;
  font-size: 18px;
  line-height: 1;
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
  padding: 0 2px;
  transition: opacity var(--transition);
}
.chip__remove:hover { opacity: 1; }
.muted { color: var(--text-secondary); font-size: 14px; padding: 20px; text-align: center; width: 100%; }
</style>
