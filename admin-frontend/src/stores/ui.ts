import { defineStore } from "pinia";
import { ref, watch } from "vue";

const THEME_KEY = "fylix-admin.theme";

export type Theme = "light" | "dark";

export const useUi = defineStore("ui", () => {
  const theme = ref<Theme>(
    (localStorage.getItem(THEME_KEY) as Theme | null) ??
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"),
  );
  const sidebarOpen = ref(true);

  function setTheme(t: Theme): void {
    theme.value = t;
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.setAttribute("data-theme", t);
  }

  watch(theme, (v) => document.documentElement.setAttribute("data-theme", v), {
    immediate: true,
  });

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value;
  }

  return { theme, sidebarOpen, setTheme, toggleSidebar };
});
