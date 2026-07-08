import { createRouter, createWebHistory } from "vue-router";

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "upload", component: () => import("@/views/UploadView.vue") },
    {
      path: "/uploaded",
      name: "uploaded",
      component: () => import("@/views/UploadSuccessView.vue"),
    },
    { path: "/legal", name: "legal", component: () => import("@/views/LegalView.vue") },
    {
      path: "/:pathMatch(.*)*",
      name: "notFound",
      component: () => import("@/views/NotFoundView.vue"),
    },
  ],
});
