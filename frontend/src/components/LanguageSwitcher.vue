<script setup lang="ts">
import { useI18n } from "vue-i18n";
import { setLocale, type Locale } from "@/i18n";

const { locale } = useI18n();
const languages: { code: Locale; label: string }[] = [
  { code: "ru", label: "RU" },
  { code: "kk", label: "KZ" },
  { code: "en", label: "EN" },
];
</script>

<template>
  <div class="lang" role="group" :aria-label="$t('nav.language')">
    <button
      v-for="l in languages"
      :key="l.code"
      class="lang__btn"
      :class="{ 'lang__btn--active': locale === l.code }"
      @click="setLocale(l.code)"
    >
      {{ l.label }}
    </button>
  </div>
</template>

<style scoped>
.lang { display: inline-flex; gap: 2px; }
.lang__btn {
  color: rgba(255, 255, 255, 0.7);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  transition: color 220ms, background-color 220ms;
}
.lang__btn:hover { color: #fff; }
.lang__btn:focus-visible {
  outline: 2px solid var(--brand-blue);
  outline-offset: 2px;
}
.lang__btn--active {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}
</style>
