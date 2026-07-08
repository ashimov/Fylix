<script setup lang="ts">
import { ref } from "vue";

defineProps<{ value: string; label?: string }>();
const copied = ref(false);

async function copy(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1500);
  } catch {
    // clipboard may be blocked in insecure contexts; ignore
  }
}
</script>

<template>
  <button type="button" class="copy" :aria-label="label" @click="copy(value)">
    <svg
      v-if="!copied"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      width="16"
      height="16"
    >
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
    <svg
      v-else
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      width="16"
      height="16"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
    <span>{{ copied ? $t("success.copied") : $t("success.copy") }}</span>
  </button>
</template>

<style scoped>
.copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: var(--radius);
  background: var(--bg-section);
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  border: 1px solid var(--border);
  transition: background var(--transition), border-color var(--transition);
}
.copy:hover {
  background: var(--blue-light);
  border-color: var(--brand-blue);
}
.copy:focus-visible {
  outline: 2px solid var(--brand-blue);
  outline-offset: 2px;
}
</style>
