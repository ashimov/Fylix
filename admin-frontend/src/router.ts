import { createRouter, createWebHistory } from "vue-router";
import { useSession } from "@/stores/session";

export const router = createRouter({
  history: createWebHistory("/admin/"),
  routes: [
    { path: "/login", name: "login", component: () => import("@/views/LoginView.vue") },
    {
      path: "/",
      component: () => import("@/components/AppShell.vue"),
      meta: { requiresAuth: true },
      children: [
        { path: "", redirect: { name: "dashboard" } },
        { path: "dashboard", name: "dashboard", component: () => import("@/views/DashboardView.vue") },
        { path: "transfers", name: "transfers", component: () => import("@/views/TransfersView.vue") },
        { path: "search", name: "search", component: () => import("@/views/SearchView.vue") },
        { path: "blocklist", name: "blocklist", component: () => import("@/views/BlocklistView.vue") },
        { path: "limits", name: "limits", component: () => import("@/views/LimitsView.vue") },
        { path: "extensions", name: "extensions", component: () => import("@/views/ExtensionsView.vue") },
        { path: "analytics", name: "analytics", component: () => import("@/views/AnalyticsView.vue") },
        { path: "audit", name: "audit", component: () => import("@/views/AuditView.vue") },
        { path: "admin-actions", name: "admin-actions", component: () => import("@/views/AdminActionsView.vue") },
        { path: "admins", name: "admins", component: () => import("@/views/AdminsView.vue") },
        { path: "telegram", name: "telegram", component: () => import("@/views/TelegramView.vue") },
      ],
    },
  ],
});

router.beforeEach(async (to) => {
  if (!to.meta.requiresAuth) return true;
  const s = useSession();
  if (!s.hydrated) {
    await s.refresh();
  }
  if (!s.admin) {
    return { name: "login", query: { redirect: to.fullPath } };
  }
  return true;
});
