<script setup lang="ts">
import DarkModeToggle from "./DarkModeToggle.vue";
import LanguageSwitcher from "./LanguageSwitcher.vue";
</script>

<template>
  <header class="topbar">
    <div class="topbar__inner">
      <router-link to="/" class="logo" aria-label="Fylix">
        <img
          src="/fylix.png"
          alt="Fylix"
          class="logo__img"
          fetchpriority="high"
        />
      </router-link>
      <div class="topbar__right">
        <LanguageSwitcher />
        <DarkModeToggle />
      </div>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  background: linear-gradient(135deg, #272666 0%, #1c1c50 100%);
  padding: 0 24px;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 8px rgba(39, 38, 102, 0.18);
}
.topbar__inner {
  max-width: 1240px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 80px;
}
.logo { display: inline-flex; align-items: center; text-decoration: none; }
.logo__img {
  height: 96px;
  width: auto;
}
.topbar__right {
  display: flex;
  gap: 12px;
  align-items: center;
}

@media (max-width: 500px) {
  .topbar { padding: 0 16px; }
  .topbar__inner { height: 64px; }
  .logo__img { height: 72px; }
}
</style>
