<script setup lang="ts">
import { onMounted, ref } from "vue";

import { getSettings, patchSettings, type SettingsPayload } from "@/api/settings";
import { useSession } from "@/stores/session";

const session = useSession();
const settings = ref<SettingsPayload>({});
const loading = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);
const saved = ref(false);

const EDITABLE = [
  "max_transfer_size_gb",
  "max_ttl_days",
  "rate_hourly",
  "rate_daily",
  "rate_download_hourly",
  "geoip_enabled",
  "geoip_countries",
  "max_recipients",
  "max_message_length",
  "audit_retention_days",
];

async function load(): Promise<void> {
  loading.value = true;
  try {
    settings.value = await getSettings();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    loading.value = false;
  }
}

async function save(): Promise<void> {
  saving.value = true;
  error.value = null;
  saved.value = false;
  try {
    const payload: SettingsPayload = {};
    for (const k of EDITABLE) {
      payload[k] = settings.value[k];
    }
    await patchSettings(payload);
    saved.value = true;
    setTimeout(() => { saved.value = false; }, 2000);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    saving.value = false;
  }
}

onMounted(load);

function asArray(v: unknown): string[] {
  return Array.isArray(v) ? v.map(String) : [];
}
</script>

<template>
  <section>
    <h1>Limits &amp; Policies</h1>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="Object.keys(settings).length" class="form">
      <div class="field">
        <label>Max transfer size (GB)</label>
        <input v-model.number="settings.max_transfer_size_gb" type="number" min="1" max="100" />
      </div>
      <div class="field">
        <label>Max TTL (days)</label>
        <input v-model.number="settings.max_ttl_days" type="number" min="1" max="90" />
      </div>
      <div class="field">
        <label>Rate-limit hourly (uploads)</label>
        <input v-model.number="settings.rate_hourly" type="number" min="1" />
      </div>
      <div class="field">
        <label>Rate-limit daily (uploads)</label>
        <input v-model.number="settings.rate_daily" type="number" min="1" />
      </div>
      <div class="field">
        <label>Rate-limit hourly (downloads)</label>
        <input v-model.number="settings.rate_download_hourly" type="number" min="1" />
      </div>
      <div class="field">
        <label>Max recipients per transfer</label>
        <input v-model.number="settings.max_recipients" type="number" min="1" max="100" />
      </div>
      <div class="field">
        <label>Max message length (chars)</label>
        <input v-model.number="settings.max_message_length" type="number" min="0" max="10000" />
      </div>
      <div class="field">
        <label>Audit retention (days)</label>
        <input v-model.number="settings.audit_retention_days" type="number" min="30" max="3650" />
      </div>
      <div class="field field--checkbox">
        <label>
          <input v-model="settings.geoip_enabled" type="checkbox" />
          Enable GeoIP country restriction
        </label>
      </div>
      <div class="field field--wide">
        <label>Allowed countries (comma-separated ISO codes)</label>
        <input
          :value="asArray(settings.geoip_countries).join(', ')"
          @change="(e) => settings.geoip_countries = ((e.target as HTMLInputElement).value).split(',').map((s) => s.trim()).filter(Boolean)"
          placeholder="KZ, UZ, KG"
        />
      </div>

      <div class="actions">
        <button
          v-if="session.admin?.role === 'admin'"
          class="btn"
          :disabled="saving"
          @click="save"
        >
          {{ saving ? "Saving…" : "Save" }}
        </button>
        <span v-if="saved" class="saved">Saved ✓</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
h1 { font-size: 28px; margin: 0 0 20px; }
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); margin-bottom: 16px; }
.form {
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  padding: 24px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 18px;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.field input[type="number"], .field input[type="text"], .field input:not([type]) {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
}
.field--checkbox label { display: flex; align-items: center; gap: 8px; color: var(--text); font-weight: 500; }
.field--wide { grid-column: 1 / -1; }
.actions { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.btn {
  padding: 10px 24px;
  background: var(--brand-navy);
  color: #fff;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 13px;
}
.btn:hover:not(:disabled) { background: var(--brand-navy-dark); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.saved { color: var(--success); font-weight: 600; font-size: 13px; }
</style>
