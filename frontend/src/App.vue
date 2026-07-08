<script setup lang="ts">
import TopBar from "@/components/TopBar.vue";
import AppFooter from "@/components/AppFooter.vue";
import CookieBanner from "@/components/CookieBanner.vue";
</script>

<template>
  <div class="layout">
    <TopBar />
    <main class="main"><router-view /></main>
    <AppFooter />
    <CookieBanner />
  </div>
</template>

<style scoped>
.layout {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}
.main {
  flex: 1;
  max-width: 900px;
  margin: 0 auto;
  padding: 32px 24px;
  width: 100%;
}
</style>
