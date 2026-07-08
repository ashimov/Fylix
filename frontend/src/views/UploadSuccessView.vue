<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import CopyButton from "@/components/CopyButton.vue";

// Token is stashed in sessionStorage by UploadView (see commit rationale)
// so it doesn't leak via URL/history/Referer. Read once and remove.
const router = useRouter();
const token = ref("");

onMounted(() => {
  const stored = sessionStorage.getItem("fylix:last-upload-token");
  if (!stored) {
    // Direct navigation (e.g., F5 or pasted URL) — no token to show.
    router.replace({ name: "upload" });
    return;
  }
  token.value = stored;
  sessionStorage.removeItem("fylix:last-upload-token");
});

const downloadUrl = computed(() => `${window.location.origin}/t/${token.value}`);
</script>

<template>
  <section class="success">
    <div class="success__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="40" height="40">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </div>
    <h1 class="success__title">{{ $t("success.title") }}</h1>
    <p class="success__message">{{ $t("success.message") }}</p>

    <div class="link-group">
      <label class="link-group__label">{{ $t("success.downloadLink") }}</label>
      <div class="link-group__row">
        <input class="link-group__input" :value="downloadUrl" readonly />
        <CopyButton :value="downloadUrl" :label="$t('success.copy')" />
      </div>
    </div>

    <router-link to="/" class="btn btn--outline">
      {{ $t("success.sendAnother") }}
    </router-link>
  </section>
</template>

<style scoped>
.success {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 40px 32px;
  box-shadow: var(--shadow-card);
  text-align: center;
}
.success__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: rgba(34, 197, 94, 0.1);
  color: var(--success);
  margin-bottom: 20px;
}
.success__title {
  margin: 0 0 8px;
  font-size: 28px;
}
.success__message {
  color: var(--text-secondary);
  margin-bottom: 32px;
}
.link-group {
  text-align: left;
  margin-bottom: 20px;
}
.link-group__label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.link-group__row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.link-group__input {
  flex: 1;
  padding: 10px 12px;
  background: var(--bg-section);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
  color: var(--text);
  min-width: 0;
}
.link-group__input:focus {
  outline: none;
  border-color: var(--brand-blue);
  box-shadow: 0 0 0 3px var(--blue-ring);
}
.btn {
  display: inline-block;
  padding: 12px 28px;
  border-radius: var(--radius);
  font-weight: 600;
  font-size: 14px;
  text-decoration: none;
  transition: background var(--transition), color var(--transition), transform var(--transition);
  margin-top: 16px;
}
.btn--outline {
  background: transparent;
  color: var(--brand-navy);
  border: 1px solid var(--brand-navy);
}
[data-theme="dark"] .btn--outline {
  color: var(--brand-blue);
  border-color: var(--brand-blue);
}
.btn--outline:hover {
  background: var(--brand-navy);
  color: #fff;
  transform: translateY(-1px);
}
[data-theme="dark"] .btn--outline:hover {
  background: var(--brand-blue);
  color: var(--brand-navy);
}
</style>
