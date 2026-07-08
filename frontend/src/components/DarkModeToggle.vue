<script setup lang="ts">
import { useSettings } from "@/stores/settings";
const s = useSettings();
function toggle(): void {
  s.setTheme(s.theme === "dark" ? "light" : "dark");
}
</script>

<template>
  <button
    class="toggle"
    :aria-label="$t('nav.darkMode')"
    :title="$t('nav.darkMode')"
    @click="toggle"
  >
    <svg
      v-if="s.theme === 'dark'"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      width="20"
      height="20"
    >
      <circle cx="12" cy="12" r="5" />
      <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
    </svg>
    <svg
      v-else
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      width="20"
      height="20"
    >
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  </button>
</template>

<style scoped>
.toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(255, 255, 255, 0.85);
  padding: 8px;
  border-radius: 8px;
  transition: background-color 220ms, color 220ms;
}
.toggle:hover { background: rgba(255, 255, 255, 0.1); color: #fff; }
.toggle:focus-visible {
  outline: 2px solid var(--brand-blue);
  outline-offset: 2px;
}
</style>
