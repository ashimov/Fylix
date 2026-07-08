<script setup lang="ts">
import { onMounted, ref } from "vue";

import { listAdminActions, type AdminActionRow } from "@/api/audit";

const rows = ref<AdminActionRow[]>([]);
const nextCursor = ref<string | null>(null);
const loading = ref(false);

async function load(reset = true): Promise<void> {
  loading.value = true;
  try {
    const resp = await listAdminActions({
      cursor: reset ? undefined : nextCursor.value ?? undefined,
    });
    rows.value = reset ? resp.items : [...rows.value, ...resp.items];
    nextCursor.value = resp.next_cursor;
  } finally {
    loading.value = false;
  }
}

function formatDate(iso: string): string { return new Date(iso).toLocaleString(); }

onMounted(() => load(true));
</script>

<template>
  <section>
    <h1>Admin actions</h1>
    <p class="hint">Immutable log of every mutating admin action.</p>

    <table class="table">
      <thead>
        <tr><th>Time</th><th>Admin</th><th>Action</th><th>Target</th><th>IP</th><th>Details</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ formatDate(r.ts) }}</td>
          <td class="mono">{{ r.admin_id.slice(0, 8) }}…</td>
          <td class="mono">{{ r.action }}</td>
          <td class="mono">{{ r.target_type }}{{ r.target_id ? " " + r.target_id.slice(0, 12) + "…" : "" }}</td>
          <td class="mono">{{ r.ip ?? "—" }}</td>
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
h1 { font-size: 28px; margin: 0 0 8px; }
.hint { color: var(--text-secondary); margin-bottom: 20px; font-size: 14px; }
.btn { padding: 8px 16px; background: var(--brand-navy); color: #fff; border-radius: var(--radius); font-weight: 600; font-size: 13px; }
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.table {
  width: 100%; border-collapse: collapse; background: var(--surface);
  border-radius: var(--radius-lg); overflow: hidden; box-shadow: var(--shadow-card); font-size: 13px;
}
.table th { text-align: left; padding: 10px 12px; background: var(--bg-section); font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); font-weight: 600; }
.table td { padding: 10px 12px; border-top: 1px solid var(--border-light); vertical-align: top; }
.mono { font-family: ui-monospace, SFMono-Regular, monospace; }
.mono.small { font-size: 12px; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pagination { margin: 16px 0; display: flex; justify-content: center; }
</style>
