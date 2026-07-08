<script setup lang="ts">
import AppSidebar from "./AppSidebar.vue";
import AppTopbar from "./AppTopbar.vue";
</script>

<template>
  <div class="shell">
    <AppSidebar />
    <div class="shell__main">
      <AppTopbar />
      <main class="shell__content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
}
.shell__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.shell__content {
  flex: 1;
  padding: 24px 28px;
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}
</style>
