<script setup lang="ts"></script>

<template>
  <section class="not-found">
    <div class="not-found__num">404</div>
    <h1 class="not-found__title">{{ $t("errors.notFound") }}</h1>
    <router-link to="/" class="btn">
      ← Fylix
    </router-link>
  </section>
</template>

<style scoped>
.not-found {
  text-align: center;
  padding: 64px 32px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-card);
}
.not-found__num {
  font-size: 72px;
  font-weight: 800;
  line-height: 1;
  background: linear-gradient(135deg, var(--brand-navy) 0%, var(--brand-blue) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 16px;
}
.not-found__title {
  margin: 0 0 24px;
  font-size: 24px;
  color: var(--text);
}
.btn {
  display: inline-block;
  padding: 12px 28px;
  border-radius: var(--radius);
  background: var(--brand-navy);
  color: #fff;
  font-weight: 600;
  text-decoration: none;
  transition: background var(--transition), transform var(--transition);
}
.btn:hover {
  background: var(--brand-navy-dark);
  transform: translateY(-1px);
}
</style>
