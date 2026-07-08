<script setup lang="ts">
import { useSettings } from "@/stores/settings";
const s = useSettings();
</script>

<template>
  <transition name="cookie-slide">
    <div v-if="!s.cookieAccepted" class="banner" role="dialog" aria-labelledby="cookie-text">
      <p id="cookie-text" class="banner__text">
        {{ $t("legal.cookieBanner") }}
        <router-link to="/legal" class="banner__link">{{ $t("legal.title") }}</router-link>
      </p>
      <button class="banner__btn" @click="s.acceptCookies()">
        {{ $t("legal.accept") }}
      </button>
    </div>
  </transition>
</template>

<style scoped>
.banner {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 16px 24px;
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  box-shadow: 0 -4px 24px rgba(0, 0, 0, 0.05);
  z-index: 200;
}
.banner__text {
  color: var(--text-secondary);
  font-size: 14px;
  max-width: 800px;
  margin: 0;
}
.banner__link {
  color: var(--brand-navy);
  font-weight: 600;
  text-decoration: underline;
  margin-left: 4px;
}
[data-theme="dark"] .banner__link { color: var(--brand-blue); }
.banner__btn {
  background: var(--brand-navy);
  color: #fff;
  padding: 10px 20px;
  border-radius: var(--radius);
  font-weight: 600;
  transition: background var(--transition);
}
.banner__btn:hover { background: var(--brand-navy-dark); }
.banner__btn:focus-visible {
  outline: 2px solid var(--brand-blue);
  outline-offset: 2px;
}

.cookie-slide-enter-active,
.cookie-slide-leave-active { transition: transform 300ms ease, opacity 300ms ease; }
.cookie-slide-enter-from,
.cookie-slide-leave-to { transform: translateY(100%); opacity: 0; }

@media (max-width: 600px) {
  .banner { flex-direction: column; align-items: stretch; }
  .banner__btn { width: 100%; }
}
</style>
