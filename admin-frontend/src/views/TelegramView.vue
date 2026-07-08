<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getTelegram, patchTelegram, type TelegramConfig } from "@/api/telegram";
import { useSession } from "@/stores/session";

const session = useSession();
const config = ref<TelegramConfig | null>(null);
const error = ref<string | null>(null);
const saved = ref(false);
const saving = ref(false);

const newBotToken = ref("");
const newChatId = ref("");

async function load(): Promise<void> {
  try {
    config.value = await getTelegram();
    newChatId.value = config.value.chat_id;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

async function save(): Promise<void> {
  if (!config.value) return;
  saving.value = true;
  error.value = null;
  saved.value = false;
  try {
    const body: Partial<TelegramConfig> & { bot_token?: string } = {
      chat_id: newChatId.value,
      alert_on_infected: config.value.alert_on_infected,
      alert_on_rate_limit_spike: config.value.alert_on_rate_limit_spike,
      alert_on_admin_login_fail_spike: config.value.alert_on_admin_login_fail_spike,
      alert_on_storage_high: config.value.alert_on_storage_high,
      alert_on_defender_event: config.value.alert_on_defender_event,
      rate_limit_spike_threshold: config.value.rate_limit_spike_threshold,
    };
    if (newBotToken.value.trim()) {
      body.bot_token = newBotToken.value.trim();
    }
    config.value = await patchTelegram(body);
    newBotToken.value = "";
    saved.value = true;
    setTimeout(() => { saved.value = false; }, 2500);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section>
    <h1>Telegram alerts</h1>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="config" class="form">
      <div class="field">
        <label>Bot token</label>
        <input
          v-model="newBotToken"
          type="password"
          autocomplete="off"
          :placeholder="config.bot_token_is_set ? '•••••• (set)' : 'paste bot token…'"
          :disabled="saving || session.admin?.role !== 'admin'"
        />
      </div>

      <div class="field">
        <label>Chat ID</label>
        <input
          v-model="newChatId"
          type="text"
          placeholder="-100999999999"
          :disabled="saving || session.admin?.role !== 'admin'"
        />
      </div>

      <div class="toggles">
        <label class="toggle">
          <input v-model="config.alert_on_infected" type="checkbox" :disabled="session.admin?.role !== 'admin'" />
          <span>Alert on infected files</span>
        </label>
        <label class="toggle">
          <input v-model="config.alert_on_rate_limit_spike" type="checkbox" :disabled="session.admin?.role !== 'admin'" />
          <span>Alert on rate-limit spike</span>
        </label>
        <label class="toggle">
          <input v-model="config.alert_on_admin_login_fail_spike" type="checkbox" :disabled="session.admin?.role !== 'admin'" />
          <span>Alert on admin login failure spike</span>
        </label>
        <label class="toggle">
          <input v-model="config.alert_on_storage_high" type="checkbox" :disabled="session.admin?.role !== 'admin'" />
          <span>Alert on storage high</span>
        </label>
        <label class="toggle">
          <input v-model="config.alert_on_defender_event" type="checkbox" :disabled="session.admin?.role !== 'admin'" />
          <span>Alert on Defender quarantine event</span>
        </label>
      </div>

      <div class="field field--narrow">
        <label>Rate-limit spike threshold (hits/min)</label>
        <input
          v-model.number="config.rate_limit_spike_threshold"
          type="number"
          min="1"
          max="1000"
          :disabled="saving || session.admin?.role !== 'admin'"
        />
      </div>

      <div class="actions" v-if="session.admin?.role === 'admin'">
        <button class="btn" :disabled="saving" @click="save">
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
  padding: 24px;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 640px;
}
.field { display: flex; flex-direction: column; gap: 6px; }
.field label { font-size: 13px; font-weight: 600; color: var(--text-secondary); }
.field input {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
}
.field--narrow { max-width: 280px; }
.toggles { display: flex; flex-direction: column; gap: 10px; padding: 16px; background: var(--bg-section); border-radius: var(--radius); }
.toggle { display: flex; align-items: center; gap: 10px; color: var(--text); font-size: 14px; cursor: pointer; }
.actions { display: flex; align-items: center; gap: 14px; margin-top: 4px; }
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
