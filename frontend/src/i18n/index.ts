import { createI18n } from "vue-i18n";
import ru from "./ru.json";
import kk from "./kk.json";
import en from "./en.json";

export type Locale = "ru" | "kk" | "en";

const STORAGE_KEY = "fylix.locale";

function detectLocale(): Locale {
  const stored = localStorage.getItem(STORAGE_KEY) as Locale | null;
  if (stored && ["ru", "kk", "en"].includes(stored)) return stored;
  const browser = navigator.language.slice(0, 2).toLowerCase();
  if (browser === "kk") return "kk";
  if (browser === "en") return "en";
  return "ru";
}

export const i18n = createI18n<false>({
  legacy: false,
  locale: detectLocale(),
  fallbackLocale: "en",
  messages: { ru, kk, en },
});

export function setLocale(locale: Locale): void {
  i18n.global.locale.value = locale;
  localStorage.setItem(STORAGE_KEY, locale);
  document.documentElement.lang = locale;
}
