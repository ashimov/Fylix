<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { ApiError } from "@/api/client";
import { useSession } from "@/stores/session";

const router = useRouter();
const route = useRoute();
const session = useSession();

const email = ref("");
const password = ref("");
const totpCode = ref("");
const submitting = ref(false);
const errorKey = ref<string | null>(null);

const ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials: "Неверный email, пароль или TOTP-код.",
  disabled: "Аккаунт отключён.",
  locked: "Аккаунт временно заблокирован из-за множественных неудачных попыток. Попробуйте через 15 минут.",
  totp_not_enrolled: "TOTP не настроен. Обратитесь к администратору.",
  network: "Не удалось связаться с сервером.",
};

function safeRedirect(raw: string | string[] | undefined | null): string {
  // Only allow same-origin, absolute internal paths. Reject anything that
  // could navigate off-site: protocol URLs, protocol-relative //host,
  // bare hostnames, or values that aren't a leading-slash path.
  const value = typeof raw === "string" ? raw : "";
  if (!value.startsWith("/")) return "/dashboard";
  if (value.startsWith("//")) return "/dashboard";
  if (value.includes("://")) return "/dashboard";
  return value;
}

async function submit(): Promise<void> {
  if (submitting.value) return;
  submitting.value = true;
  errorKey.value = null;
  try {
    await session.login({
      email: email.value.trim(),
      password: password.value,
      totp_code: totpCode.value.trim(),
    });
    router.push(safeRedirect(route.query.redirect as string | undefined));
  } catch (e) {
    if (e instanceof ApiError) {
      errorKey.value = session.error;
    } else {
      errorKey.value = "network";
    }
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="card">
      <h1 class="title">Fylix Admin</h1>
      <p class="subtitle">Вход в панель управления</p>

      <form class="form" @submit.prevent="submit">
        <label class="field">
          <span>Email</span>
          <input
            v-model="email"
            type="email"
            autocomplete="username"
            required
            :disabled="submitting"
          />
        </label>

        <label class="field">
          <span>Пароль</span>
          <input
            v-model="password"
            type="password"
            autocomplete="current-password"
            required
            :disabled="submitting"
          />
        </label>

        <label class="field">
          <span>TOTP код</span>
          <input
            v-model="totpCode"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            maxlength="8"
            autocomplete="one-time-code"
            required
            :disabled="submitting"
          />
        </label>

        <p v-if="errorKey" class="error">
          {{ ERROR_MESSAGES[errorKey] ?? errorKey }}
        </p>

        <button type="submit" class="btn" :disabled="submitting">
          {{ submitting ? "Вход…" : "Войти" }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #272666 0%, #1c1c50 100%);
  padding: 24px;
}
.card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border-radius: var(--radius-lg);
  padding: 36px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}
.title {
  font-size: 24px;
  margin: 0 0 8px;
  color: var(--brand-navy);
}
.subtitle {
  margin: 0 0 28px;
  color: var(--text-secondary);
  font-size: 14px;
}
.form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field span {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}
.field input {
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
  transition: border-color var(--transition), box-shadow var(--transition);
}
.field input:focus {
  outline: none;
  border-color: var(--brand-blue);
  box-shadow: 0 0 0 3px var(--blue-ring);
}
.error {
  margin: 0;
  padding: 10px 14px;
  background: rgba(239, 68, 68, 0.08);
  color: var(--danger);
  border-radius: var(--radius);
  font-size: 13px;
}
.btn {
  padding: 12px 20px;
  background: var(--brand-navy);
  color: #fff;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 14px;
  transition: background var(--transition);
  margin-top: 8px;
}
.btn:hover:not(:disabled) {
  background: var(--brand-navy-dark);
}
.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
