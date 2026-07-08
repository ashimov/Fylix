<script setup lang="ts">
import { onMounted, ref } from "vue";

import {
  deleteTransfer,
  getTransfer,
  listTransfers,
  revokeTransfer,
  type TransferDetailResponse,
  type TransferRow,
} from "@/api/transfers";
import Badge from "@/components/Badge.vue";
import EmptyState from "@/components/EmptyState.vue";
import SkeletonRow from "@/components/SkeletonRow.vue";
import { useSession } from "@/stores/session";

const session = useSession();

const rows = ref<TransferRow[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const filters = ref({
  status: "",
  country: "",
  q: "",
});
const nextCursor = ref<string | null>(null);
const detail = ref<TransferDetailResponse | null>(null);
const busy = ref(false);

async function load(reset = true): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    const resp = await listTransfers({
      status: filters.value.status || undefined,
      country: filters.value.country || undefined,
      q: filters.value.q || undefined,
      cursor: reset ? undefined : nextCursor.value ?? undefined,
    });
    rows.value = reset ? resp.items : [...rows.value, ...resp.items];
    nextCursor.value = resp.next_cursor;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    loading.value = false;
  }
}

async function openDetail(id: string): Promise<void> {
  detail.value = await getTransfer(id);
}

function closeDetail(): void {
  detail.value = null;
}

async function onDelete(id: string): Promise<void> {
  if (!window.confirm("Delete this transfer? Crypto-shred is immediate.")) return;
  busy.value = true;
  try {
    await deleteTransfer(id);
    await load(true);
    if (detail.value?.id === id) closeDetail();
  } finally {
    busy.value = false;
  }
}

async function onRevoke(id: string): Promise<void> {
  if (!window.confirm("Revoke this transfer's link?")) return;
  busy.value = true;
  try {
    await revokeTransfer(id);
    await load(true);
    if (detail.value?.id === id) detail.value = await getTransfer(id);
  } finally {
    busy.value = false;
  }
}

function formatSize(n: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let v = n, u = 0;
  while (v >= 1024 && u < units.length - 1) { v /= 1024; u++; }
  return `${v.toFixed(v < 10 ? 1 : 0)} ${units[u]}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

onMounted(() => load(true));
</script>

<template>
  <section>
    <h1>Transfers</h1>

    <div class="filters">
      <select v-model="filters.status" @change="load(true)">
        <option value="">all statuses</option>
        <option value="ready">ready</option>
        <option value="uploading">uploading</option>
        <option value="expired">expired</option>
        <option value="deleted">deleted</option>
        <option value="revoked">revoked</option>
        <option value="infected">infected</option>
      </select>
      <input v-model="filters.country" placeholder="Country (KZ)" @change="load(true)" maxlength="2" />
      <input v-model="filters.q" placeholder="Search email or filename…" @keydown.enter="load(true)" />
      <button class="btn" @click="load(true)" :disabled="loading">Refresh</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <table class="table">
      <thead>
        <tr>
          <th>Created</th>
          <th>Sender</th>
          <th>IP</th>
          <th>Country</th>
          <th>Size</th>
          <th>Files</th>
          <th>Status</th>
          <th>Expires</th>
          <th></th>
        </tr>
      </thead>
      <tbody v-if="loading && !rows.length">
        <SkeletonRow v-for="n in 5" :key="`skel-${n}`" :columns="9" />
      </tbody>
      <tbody v-else-if="!rows.length">
        <tr>
          <td colspan="9">
            <EmptyState
              title="Нет переводов"
              message="Попробуйте изменить фильтры или обновите страницу."
              icon="inbox"
            >
              <template #action>
                <button class="btn" @click="load(true)" :disabled="loading">Обновить</button>
              </template>
            </EmptyState>
          </td>
        </tr>
      </tbody>
      <tbody v-else>
        <tr v-for="t in rows" :key="t.id" class="row">
          <td>{{ formatDate(t.created_at) }}</td>
          <td>{{ t.sender_email }}</td>
          <td class="mono">{{ t.sender_ip }}</td>
          <td>{{ t.sender_country ?? "—" }}</td>
          <td class="mono">{{ formatSize(t.total_size) }}</td>
          <td>{{ t.file_count }}</td>
          <td><Badge :status="t.status" /></td>
          <td>{{ formatDate(t.expires_at) }}</td>
          <td><button class="link" @click="openDetail(t.id)">Detail</button></td>
        </tr>
      </tbody>
    </table>

    <div class="pagination">
      <button
        class="btn"
        :disabled="loading || nextCursor === null"
        @click="load(false)"
      >
        Load more
      </button>
    </div>

    <div v-if="detail" class="drawer" @click.self="closeDetail">
      <div class="drawer__panel">
        <div class="drawer__header">
          <h2>Transfer {{ detail.id.slice(0, 8) }}…</h2>
          <button class="close-btn" @click="closeDetail">×</button>
        </div>

        <div class="drawer__meta">
          <div><strong>Status:</strong> <Badge :status="detail.status" /></div>
          <div><strong>From:</strong> {{ detail.sender_email }} ({{ detail.sender_ip }}, {{ detail.sender_country ?? "—" }})</div>
          <div><strong>Created:</strong> {{ formatDate(detail.created_at) }}</div>
          <div><strong>Expires:</strong> {{ formatDate(detail.expires_at) }}</div>
          <div v-if="detail.message"><strong>Message:</strong> {{ detail.message }}</div>
        </div>

        <h3>Files</h3>
        <ul class="list">
          <li v-for="f in detail.files" :key="f.id">
            {{ f.filename }}
            <span class="muted">{{ formatSize(f.size_bytes) }} · {{ f.mime_type }}</span>
          </li>
        </ul>

        <h3>Recipients</h3>
        <ul class="list">
          <li v-for="r in detail.recipients" :key="r.email">
            {{ r.email }}
            <span class="muted">{{ r.email_status ?? "—" }}</span>
          </li>
        </ul>

        <h3>Downloads</h3>
        <p v-if="detail.downloads.length === 0" class="muted">None yet.</p>
        <table v-else class="table table--nested">
          <thead>
            <tr><th>When</th><th>IP</th><th>Country</th><th>Bytes</th><th>State</th></tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in detail.downloads" :key="i">
              <td>{{ formatDate(d.started_at) }}</td>
              <td class="mono">{{ d.ip }}</td>
              <td>{{ d.country ?? "—" }}</td>
              <td class="mono">{{ d.bytes_sent != null ? formatSize(d.bytes_sent) : "—" }}</td>
              <td>{{ d.aborted ? "aborted" : d.completed_at ? "ok" : "in progress" }}</td>
            </tr>
          </tbody>
        </table>

        <div v-if="session.admin?.role === 'admin' && detail.status === 'ready'" class="drawer__actions">
          <button class="btn btn--danger" :disabled="busy" @click="onDelete(detail.id)">Delete now</button>
          <button class="btn btn--secondary" :disabled="busy" @click="onRevoke(detail.id)">Revoke link</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
h1 { font-size: 28px; margin: 0 0 20px; }
.filters {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.filters select, .filters input {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
}
.btn {
  padding: 8px 16px;
  background: var(--brand-navy);
  color: #fff;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 13px;
  transition: background var(--transition);
}
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn--danger { background: var(--danger); }
.btn--danger:hover:not(:disabled) { background: #dc2626; }
.btn--secondary {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--border);
}
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); }
.table {
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  border-radius: var(--radius-lg);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  font-size: 13px;
}
.table th {
  text-align: left;
  padding: 10px 12px;
  background: var(--bg-section);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-secondary);
  font-weight: 600;
}
.table td { padding: 10px 12px; border-top: 1px solid var(--border-light); }
.table tr:hover { background: var(--bg-section); }
.table--nested { box-shadow: none; border: 1px solid var(--border-light); }
.mono { font-family: ui-monospace, SFMono-Regular, monospace; }
.link { background: none; border: none; color: var(--brand-navy); font-weight: 600; font-size: 13px; padding: 0; cursor: pointer; }
[data-theme="dark"] .link { color: var(--brand-blue); }
.pagination { margin: 16px 0; display: flex; justify-content: center; }

.drawer {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  justify-content: flex-end;
  z-index: 200;
}
.drawer__panel {
  width: min(640px, 100vw);
  height: 100vh;
  background: var(--surface);
  overflow-y: auto;
  padding: 24px;
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.15);
}
.drawer__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.drawer__header h2 { margin: 0; font-size: 18px; }
.close-btn {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  background: var(--bg-section);
  font-size: 20px;
  line-height: 1;
  color: var(--text-secondary);
}
.close-btn:hover { background: var(--border); color: var(--text); }
.drawer__meta > div { margin-bottom: 6px; font-size: 14px; }
.drawer__meta strong { color: var(--text-secondary); font-weight: 600; margin-right: 6px; }
.drawer__panel h3 { margin: 20px 0 8px; font-size: 14px; }
.list { list-style: none; padding: 0; margin: 0; }
.list li { padding: 6px 0; display: flex; justify-content: space-between; font-size: 13px; border-bottom: 1px solid var(--border-light); }
.muted { color: var(--text-secondary); font-size: 13px; }
.drawer__actions {
  display: flex;
  gap: 10px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
</style>
