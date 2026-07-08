<script setup lang="ts">
// Empty-state panel for admin list pages.
// Usage:
//   <EmptyState
//     title="Нет переводов"
//     message="Попробуйте изменить фильтры или дождитесь первой загрузки."
//   >
//     <template #action>
//       <button class="btn" @click="load(true)">Refresh</button>
//     </template>
//   </EmptyState>

interface Props {
  title: string;
  message?: string;
  icon?: "inbox" | "search" | "shield";
}

withDefaults(defineProps<Props>(), {
  icon: "inbox",
  message: "",
});
</script>

<template>
  <div class="empty-state">
    <div class="empty-state__icon" aria-hidden="true">
      <svg
        v-if="icon === 'inbox'"
        viewBox="0 0 24 24"
        width="48"
        height="48"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
        <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
      </svg>
      <svg
        v-else-if="icon === 'search'"
        viewBox="0 0 24 24"
        width="48"
        height="48"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <svg
        v-else
        viewBox="0 0 24 24"
        width="48"
        height="48"
        fill="none"
        stroke="currentColor"
        stroke-width="1.5"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      </svg>
    </div>
    <h3 class="empty-state__title">{{ title }}</h3>
    <p v-if="message" class="empty-state__message">{{ message }}</p>
    <div v-if="$slots.action" class="empty-state__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
  color: var(--text-secondary, #6b7280);
}
.empty-state__icon {
  color: var(--text-muted, #9ca3af);
  margin-bottom: 16px;
  opacity: 0.6;
}
.empty-state__title {
  margin: 0 0 6px;
  font-size: 16px;
  font-weight: 600;
  color: var(--text, #111827);
}
.empty-state__message {
  margin: 0 0 16px;
  font-size: 14px;
  max-width: 420px;
}
.empty-state__action {
  margin-top: 8px;
}
</style>
