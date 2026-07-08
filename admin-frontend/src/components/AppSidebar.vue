<script setup lang="ts">
import { useSession } from "@/stores/session";
const session = useSession();

interface NavItem {
  name: string;
  label: string;
  icon: string;
  adminOnly?: boolean;
}

const items: NavItem[] = [
  { name: "dashboard", label: "Dashboard", icon: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z" },
  { name: "transfers", label: "Transfers", icon: "M5 3a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V7l-4-4H5zm0 2h9v4h4v10H5V5z" },
  { name: "search", label: "Search", icon: "M21 21l-4.35-4.35M11 18a7 7 0 100-14 7 7 0 000 14z" },
  { name: "blocklist", label: "Blocklist", icon: "M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-1.85.63-3.55 1.69-4.9L16.9 18.31C15.55 19.37 13.85 20 12 20zm6.31-3.1L7.1 5.69C8.45 4.63 10.15 4 12 4c4.41 0 8 3.59 8 8 0 1.85-.63 3.55-1.69 4.9z" },
  { name: "limits", label: "Limits", icon: "M3 3h18v18H3V3zm2 2v14h14V5H5zm2 2h10v2H7V7zm0 4h10v2H7v-2zm0 4h7v2H7v-2z", adminOnly: true },
  { name: "extensions", label: "Extensions", icon: "M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5C13 2.12 11.88 1 10.5 1S8 2.12 8 3.5V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7s2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5c1.38 0 2.5-1.12 2.5-2.5S21.88 11 20.5 11z", adminOnly: true },
  { name: "analytics", label: "Analytics", icon: "M5 9.2h3V19H5V9.2zM10.6 5h2.8v14h-2.8V5zm5.6 8H19v6h-2.8v-6z" },
  { name: "audit", label: "Audit log", icon: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z" },
  { name: "admin-actions", label: "Admin actions", icon: "M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm-2 16l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z" },
  { name: "admins", label: "Admins", icon: "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z", adminOnly: true },
  { name: "telegram", label: "Telegram", icon: "M20 4l-16 8 5 2 2 6 3-4 5 4 3-16z", adminOnly: true },
];

function visible(item: NavItem): boolean {
  if (item.adminOnly && session.admin?.role !== "admin") return false;
  return true;
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar__brand">
      <img src="/fylix.png" alt="Fylix" class="sidebar__logo" />
      <span class="sidebar__name">Admin</span>
    </div>
    <nav class="sidebar__nav">
      <router-link
        v-for="item in items.filter(visible)"
        :key="item.name"
        :to="{ name: item.name }"
        class="nav-item"
        active-class="nav-item--active"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" class="nav-item__icon">
          <path :d="item.icon" />
        </svg>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 240px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: sticky;
  top: 0;
  padding: 16px 12px;
}
.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px 20px;
  border-bottom: 1px solid var(--border-light);
  margin-bottom: 12px;
}
.sidebar__logo { height: 32px; width: auto; }
.sidebar__name {
  font-weight: 700;
  color: var(--brand-navy);
  font-size: 15px;
  letter-spacing: 0.02em;
}
[data-theme="dark"] .sidebar__name { color: var(--brand-blue); }
.sidebar__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: var(--radius);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: background var(--transition), color var(--transition);
}
.nav-item:hover { background: var(--bg-section); color: var(--text); }
.nav-item--active {
  background: var(--accent-light);
  color: var(--brand-navy);
  font-weight: 600;
}
[data-theme="dark"] .nav-item--active {
  background: var(--blue-light);
  color: var(--brand-blue);
}
.nav-item__icon { flex-shrink: 0; }
</style>
