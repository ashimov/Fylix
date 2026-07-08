import { defineStore } from "pinia";
import { ref, watch } from "vue";

const THEME_KEY = "fylix.theme";
const COOKIE_KEY = "fylix.cookie.accepted";

export type Theme = "light" | "dark";

export const useSettings = defineStore("settings", () => {
  const initialTheme: Theme =
    (localStorage.getItem(THEME_KEY) as Theme | null) ??
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

  const theme = ref<Theme>(initialTheme);
  const cookieAccepted = ref(localStorage.getItem(COOKIE_KEY) === "1");

  function setTheme(t: Theme): void {
    theme.value = t;
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem(THEME_KEY, t);
  }

  function acceptCookies(): void {
    cookieAccepted.value = true;
    localStorage.setItem(COOKIE_KEY, "1");
  }

  // Apply current theme to <html> now and on future changes.
  watch(
    theme,
    (v) => document.documentElement.setAttribute("data-theme", v),
    { immediate: true },
  );

  return { theme, cookieAccepted, setTheme, acceptCookies };
});
