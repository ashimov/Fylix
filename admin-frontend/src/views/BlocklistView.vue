<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

import {
  addBlocklist,
  listBlocklist,
  removeBlocklist,
  type BlocklistEntry,
  type BlocklistKind,
} from "@/api/blocklist";
import { useSession } from "@/stores/session";

const session = useSession();
const kind = ref<BlocklistKind>("ips");
const entries = ref<BlocklistEntry[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const newValue = ref("");
const newReason = ref("");
const newExpires = ref("");

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    entries.value = await listBlocklist(kind.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    loading.value = false;
  }
}

async function add(): Promise<void> {
  if (!newValue.value.trim()) return;
  try {
    await addBlocklist(kind.value, {
      value: newValue.value.trim(),
      reason: newReason.value.trim() || null,
      expires_at: newExpires.value || null,
    });
    newValue.value = "";
    newReason.value = "";
    newExpires.value = "";
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function remove(value: string): Promise<void> {
  if (!window.confirm(`Remove ${value}?`)) return;
  try {
    await removeBlocklist(kind.value, value);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

watch(kind, load);
onMounted(load);

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

const TABS: { key: BlocklistKind; label: string; placeholder: string }[] = [
  { key: "ips", label: "IPs / CIDRs", placeholder: "10.0.0.0/8 or 1.2.3.4" },
  { key: "domains", label: "Email domains", placeholder: "badcorp.com" },
  { key: "emails", label: "Emails", placeholder: "evil@user.net" },
];
</script>

<template>
  <section>
    <h1>Blocklist</h1>

    <div class="tabs">
      <button
        v-for="t in TABS"
        :key="t.key"
        class="tab"
        :class="{ 'tab--active': kind === t.key }"
        @click="kind = t.key"
      >
        {{ t.label }}
      </button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="session.admin?.role === 'admin'" class="form">
      <input v-model="newValue" :placeholder="TABS.find((t) => t.key === kind)?.placeholder" />
      <input v-model="newReason" placeholder="Reason (optional)" />
      <input v-model="newExpires" type="datetime-local" placeholder="Expires at" />
      <button class="btn" @click="add" :disabled="!newValue.trim()">Add</button>
    </div>

    <table class="table">
      <thead>
        <tr>
          <th>Value</th>
          <th>Reason</th>
          <th>Added</th>
          <th>Expires</th>
          <th v-if="session.admin?.role === 'admin'"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="e in entries" :key="e.value">
          <td class="mono">{{ e.value }}</td>
          <td>{{ e.reason ?? "—" }}</td>
          <td>{{ formatDate(e.added_at) }}</td>
          <td>{{ formatDate(e.expires_at) }}</td>
          <td v-if="session.admin?.role === 'admin'">
            <button class="link-danger" @click="remove(e.value)">Remove</button>
          </td>
        </tr>
        <tr v-if="entries.length === 0"><td colspan="5" class="muted">Empty.</td></tr>
      </tbody>
    </table>
  </section>
</template>

<style scoped>
h1 { font-size: 28px; margin: 0 0 20px; }
.tabs { display: flex; gap: 4px; margin-bottom: 20px; border-bottom: 1px solid var(--border); }
.tab {
  padding: 10px 18px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 600;
  transition: color var(--transition), border-color var(--transition);
  cursor: pointer;
}
.tab:hover { color: var(--text); }
.tab--active { color: var(--brand-navy); border-bottom-color: var(--brand-navy); }
[data-theme="dark"] .tab--active { color: var(--brand-blue); border-bottom-color: var(--brand-blue); }
.form {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}
.form input {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  min-width: 200px;
  flex: 1;
}
.btn {
  padding: 8px 18px;
  background: var(--brand-navy);
  color: #fff;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 13px;
  transition: background var(--transition);
}
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); margin-bottom: 16px; }
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
.muted { color: var(--text-secondary); text-align: center; padding: 20px; }
.link-danger {
  background: none;
  border: none;
  color: var(--danger);
  font-weight: 600;
  cursor: pointer;
  font-size: 13px;
}
</style>
