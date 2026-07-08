<script setup lang="ts">
import { useRouter } from "vue-router";

import { useSession } from "@/stores/session";
import { useUi } from "@/stores/ui";

const session = useSession();
const ui = useUi();
const router = useRouter();

function toggle(): void {
  ui.setTheme(ui.theme === "dark" ? "light" : "dark");
}

async function logout(): Promise<void> {
  try {
    await session.logout();
  } finally {
    router.push({ name: "login" });
  }
}
</script>

<template>
  <header class="topbar">
    <div class="topbar__title">
      <slot>Fylix Admin</slot>
    </div>
    <div class="topbar__right">
      <button class="icon-btn" aria-label="Toggle theme" @click="toggle">
        <svg v-if="ui.theme === 'dark'" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="5" />
          <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
        <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
      </button>
      <span class="admin-email">{{ session.admin?.email }}</span>
      <button class="logout-btn" @click="logout">Logout</button>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 50;
}
.topbar__title {
  font-size: 18px;
  font-weight: 700;
  color: var(--brand-navy);
}
[data-theme="dark"] .topbar__title { color: var(--brand-blue); }
.topbar__right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.icon-btn {
  padding: 8px;
  border-radius: 8px;
  color: var(--text-secondary);
  transition: background var(--transition), color var(--transition);
}
.icon-btn:hover { background: var(--bg-section); color: var(--text); }
.admin-email {
  font-size: 13px;
  color: var(--text-secondary);
}
.logout-btn {
  padding: 6px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  transition: border-color var(--transition), color var(--transition);
}
.logout-btn:hover {
  border-color: var(--brand-navy);
  color: var(--brand-navy);
}
[data-theme="dark"] .logout-btn:hover {
  border-color: var(--brand-blue);
  color: var(--brand-blue);
}
</style>
