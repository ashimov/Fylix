<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  createAdmin,
  deleteAdmin,
  listAdmins,
  resetTotp,
  updateAdmin,
  type AdminRow,
} from "@/api/admins";
import { useSession } from "@/stores/session";

const session = useSession();
const admins = ref<AdminRow[]>([]);
const loading = ref(false);
const error = ref<string | null>(null);

const showCreateModal = ref(false);
const showTotpModal = ref(false);
const totpUri = ref("");
const totpTitle = ref("");

const newEmail = ref("");
const newPassword = ref("");
const newRole = ref<"admin" | "viewer">("admin");

const activeAdminCount = computed(
  () => admins.value.filter((a) => !a.disabled && a.role === "admin").length,
);

async function load(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    admins.value = await listAdmins();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    loading.value = false;
  }
}

async function onCreate(): Promise<void> {
  try {
    const resp = await createAdmin({
      email: newEmail.value.trim(),
      password: newPassword.value,
      role: newRole.value,
    });
    showCreateModal.value = false;
    newEmail.value = "";
    newPassword.value = "";
    totpUri.value = resp.totp_uri;
    totpTitle.value = `TOTP for ${resp.admin.email}`;
    showTotpModal.value = true;
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function onToggleDisabled(a: AdminRow): Promise<void> {
  const willDisable = !a.disabled;
  if (willDisable && !window.confirm(`Disable ${a.email}?`)) return;
  try {
    await updateAdmin(a.id, { disabled: willDisable });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function onRoleChange(a: AdminRow, value: string): Promise<void> {
  try {
    await updateAdmin(a.id, { role: value as "admin" | "viewer" });
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
    await load();
  }
}

async function onResetTotp(a: AdminRow): Promise<void> {
  if (!window.confirm(`Reset TOTP for ${a.email}? The old TOTP will stop working immediately.`)) return;
  try {
    const resp = await resetTotp(a.id);
    totpUri.value = resp.totp_uri;
    totpTitle.value = `New TOTP for ${a.email}`;
    showTotpModal.value = true;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function onDelete(a: AdminRow): Promise<void> {
  if (!window.confirm(`Delete ${a.email}? This cannot be undone.`)) return;
  try {
    await deleteAdmin(a.id);
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

function copyUri(): void {
  void navigator.clipboard.writeText(totpUri.value);
}

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

const readonly = computed(() => session.admin?.role !== "admin");

onMounted(load);
</script>

<template>
  <section>
    <div class="header">
      <h1>Admins</h1>
      <button v-if="!readonly" class="btn" @click="showCreateModal = true">Add admin</button>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="activeAdminCount <= 1" class="hint">
      Only 1 active admin — you can't delete or disable them. Add another admin first.
    </div>

    <table class="table">
      <thead>
        <tr>
          <th>Email</th>
          <th>Role</th>
          <th>Status</th>
          <th>Last login</th>
          <th>Created</th>
          <th v-if="!readonly"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in admins" :key="a.id">
          <td>{{ a.email }}</td>
          <td>
            <select
              v-if="!readonly"
              :value="a.role"
              @change="(e) => onRoleChange(a, (e.target as HTMLSelectElement).value)"
            >
              <option value="admin">admin</option>
              <option value="viewer">viewer</option>
            </select>
            <span v-else>{{ a.role }}</span>
          </td>
          <td>
            <span :class="['pill', a.disabled ? 'pill--off' : 'pill--on']">
              {{ a.disabled ? "disabled" : "active" }}
            </span>
          </td>
          <td>{{ formatDate(a.last_login_at) }}</td>
          <td>{{ formatDate(a.created_at) }}</td>
          <td v-if="!readonly" class="actions">
            <button class="link" @click="onToggleDisabled(a)">
              {{ a.disabled ? "Enable" : "Disable" }}
            </button>
            <button class="link" @click="onResetTotp(a)">Reset TOTP</button>
            <button class="link-danger" @click="onDelete(a)">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreateModal" class="modal" @click.self="showCreateModal = false">
      <div class="modal__panel">
        <h2>Add admin</h2>
        <form @submit.prevent="onCreate">
          <label class="field">
            <span>Email</span>
            <input v-model="newEmail" type="email" required />
          </label>
          <label class="field">
            <span>Password (min 12 chars)</span>
            <input v-model="newPassword" type="password" minlength="12" required />
          </label>
          <label class="field">
            <span>Role</span>
            <select v-model="newRole">
              <option value="admin">admin</option>
              <option value="viewer">viewer</option>
            </select>
          </label>
          <div class="actions">
            <button type="button" class="btn btn--secondary" @click="showCreateModal = false">Cancel</button>
            <button type="submit" class="btn">Create</button>
          </div>
        </form>
      </div>
    </div>

    <div v-if="showTotpModal" class="modal" @click.self="showTotpModal = false">
      <div class="modal__panel">
        <h2>{{ totpTitle }}</h2>
        <p>Scan this URI in Google Authenticator / Authy. It will <strong>not</strong> be shown again.</p>
        <pre class="totp-uri">{{ totpUri }}</pre>
        <div class="actions">
          <button class="btn btn--secondary" @click="copyUri">Copy</button>
          <button class="btn" @click="showTotpModal = false">Done</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
h1 { font-size: 28px; margin: 0; }
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); margin-bottom: 12px; }
.hint {
  padding: 10px 14px;
  background: rgba(245,158,11,0.12);
  color: #92400e;
  border-radius: var(--radius);
  margin-bottom: 16px;
  font-size: 13px;
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
.btn--secondary { background: transparent; color: var(--text); border: 1px solid var(--border); }
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
.table td { padding: 10px 12px; border-top: 1px solid var(--border-light); vertical-align: middle; }
.table select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text); font-size: 13px; }
.pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}
.pill--on { background: rgba(34,197,94,0.15); color: var(--success); }
.pill--off { background: rgba(148,163,184,0.2); color: #475569; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }
.link {
  background: none; border: none; color: var(--brand-navy);
  font-weight: 600; font-size: 13px; padding: 0; cursor: pointer;
}
[data-theme="dark"] .link { color: var(--brand-blue); }
.link-danger {
  background: none; border: none; color: var(--danger);
  font-weight: 600; font-size: 13px; padding: 0; cursor: pointer;
}

.modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 300;
}
.modal__panel {
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 28px;
  width: min(500px, 100vw);
  box-shadow: 0 20px 60px rgba(0,0,0,0.3);
}
.modal__panel h2 { margin: 0 0 16px; font-size: 18px; }
.modal__panel .field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.modal__panel .field span { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.modal__panel .field input, .modal__panel .field select {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-size: 14px;
  background: var(--surface);
  color: var(--text);
}
.modal__panel .actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.totp-uri {
  background: var(--bg-section);
  padding: 12px;
  border-radius: var(--radius);
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  word-break: break-all;
  white-space: pre-wrap;
  max-height: 200px;
  overflow: auto;
  color: var(--text);
}
</style>
