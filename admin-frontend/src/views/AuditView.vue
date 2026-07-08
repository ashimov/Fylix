<script setup lang="ts">
import { onMounted, ref } from "vue";

import { listAudit, type AuditRow } from "@/api/audit";

const rows = ref<AuditRow[]>([]);
const nextCursor = ref<string | null>(null);
const loading = ref(false);

const filters = ref({
  event_type: "",
  severity: "",
  ip: "",
});

async function load(reset = true): Promise<void> {
  loading.value = true;
  try {
    const resp = await listAudit({
      event_type: filters.value.event_type || undefined,
      severity: filters.value.severity || undefined,
      ip: filters.value.ip || undefined,
      cursor: reset ? undefined : nextCursor.value ?? undefined,
    });
    rows.value = reset ? resp.items : [...rows.value, ...resp.items];
    nextCursor.value = resp.next_cursor;
  } finally {
    loading.value = false;
  }
}

function exportCsv(): void {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(filters.value)) {
    if (v) qs.set(k, v);
  }
  window.location.assign(`/api/admin/audit.csv${qs.toString() ? "?" + qs : ""}`);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

onMounted(() => load(true));
</script>

<template>
  <section>
    <div class="header">
      <h1>Audit log</h1>
      <button class="btn btn--outline" @click="exportCsv">Export CSV</button>
    </div>

    <div class="filters">
      <select v-model="filters.severity" @change="load(true)">
        <option value="">all severities</option>
        <option value="info">info</option>
        <option value="warn">warn</option>
        <option value="error">error</option>
        <option value="critical">critical</option>
      </select>
      <input v-model="filters.event_type" placeholder="event type" @keydown.enter="load(true)" />
      <input v-model="filters.ip" placeholder="IP" @keydown.enter="load(true)" />
      <button class="btn" @click="load(true)" :disabled="loading">Refresh</button>
    </div>

    <table class="table">
      <thead>
        <tr><th>Time</th><th>Event</th><th>Severity</th><th>IP</th><th>Transfer</th><th>Details</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ formatDate(r.ts) }}</td>
          <td class="mono">{{ r.event_type }}</td>
          <td><span class="sev" :data-sev="r.severity">{{ r.severity }}</span></td>
          <td class="mono">{{ r.ip ?? "—" }}</td>
          <td class="mono">{{ r.transfer_id ? r.transfer_id.slice(0, 8) + "…" : "—" }}</td>
          <td class="mono small">{{ r.details ? JSON.stringify(r.details) : "—" }}</td>
        </tr>
      </tbody>
    </table>

    <div class="pagination">
      <button class="btn" :disabled="!nextCursor || loading" @click="load(false)">Load more</button>
    </div>
  </section>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
h1 { font-size: 28px; margin: 0; }
.filters { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
.filters select, .filters input {
  padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius);
  background: var(--surface); color: var(--text); font-size: 14px;
}
.btn { padding: 8px 16px; background: var(--brand-navy); color: #fff; border-radius: var(--radius); font-weight: 600; font-size: 13px; }
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn--outline { background: transparent; color: var(--brand-navy); border: 1px solid var(--brand-navy); }
.btn--outline:hover { background: var(--brand-navy); color: #fff; }
[data-theme="dark"] .btn--outline { color: var(--brand-blue); border-color: var(--brand-blue); }
.table {
  width: 100%; border-collapse: collapse; background: var(--surface);
  border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-card); font-size: 13px;
}
.table th { text-align: left; padding: 10px 12px; background: var(--bg-section); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 600; }
.table td { padding: 10px 12px; border-top: 1px solid var(--border-light); vertical-align: top; }
.mono { font-family: ui-monospace, SFMono-Regular, monospace; }
.mono.small { font-size: 12px; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sev { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; text-transform: uppercase; }
.sev[data-sev="info"] { background: rgba(148,189,229,0.2); color: #0369a1; }
.sev[data-sev="warn"] { background: rgba(245,158,11,0.15); color: var(--warning); }
.sev[data-sev="error"] { background: rgba(239,68,68,0.15); color: var(--danger); }
.sev[data-sev="critical"] { background: var(--danger); color: #fff; }
.pagination { margin: 16px 0; display: flex; justify-content: center; }
</style>
