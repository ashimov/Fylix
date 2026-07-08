<script setup lang="ts">
import { ref, watch } from "vue";

import { listTransfers, type TransferRow } from "@/api/transfers";
import Badge from "@/components/Badge.vue";

const q = ref("");
const rows = ref<TransferRow[]>([]);
const loading = ref(false);

let timer: number | null = null;

function schedule(): void {
  if (timer !== null) clearTimeout(timer);
  timer = window.setTimeout(runSearch, 300);
}

async function runSearch(): Promise<void> {
  if (!q.value.trim()) {
    rows.value = [];
    return;
  }
  loading.value = true;
  try {
    const resp = await listTransfers({ q: q.value.trim(), limit: 50 });
    rows.value = resp.items;
  } finally {
    loading.value = false;
  }
}

watch(q, schedule);

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}
</script>

<template>
  <section class="search">
    <h1>Search</h1>

    <input
      v-model="q"
      placeholder="Email, filename, or IP…"
      class="search__input"
    />

    <p v-if="loading" class="muted">Searching…</p>
    <p v-else-if="q && rows.length === 0" class="muted">No results.</p>

    <table v-if="rows.length" class="table">
      <thead>
        <tr><th>Created</th><th>Sender</th><th>IP</th><th>Status</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in rows" :key="t.id">
          <td>{{ formatDate(t.created_at) }}</td>
          <td>{{ t.sender_email }}</td>
          <td class="mono">{{ t.sender_ip }}</td>
          <td><Badge :status="t.status" /></td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
.search h1 { font-size: 28px; margin: 0 0 20px; }
.search__input {
  width: 100%;
  max-width: 600px;
  padding: 12px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 15px;
  background: var(--surface);
  color: var(--text);
  margin-bottom: 20px;
}
.search__input:focus { outline: none; border-color: var(--brand-blue); box-shadow: 0 0 0 3px var(--blue-ring); }
.table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  font-size: 13px;
}
.table th { text-align: left; padding: 10px 12px; background: var(--bg-section); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 600; }
.table td { padding: 10px 12px; border-top: 1px solid var(--border-light); }
.mono { font-family: ui-monospace, SFMono-Regular, monospace; }
.muted { color: var(--text-secondary); }
</style>
