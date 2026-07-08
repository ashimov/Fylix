<script setup lang="ts">
defineProps<{
  label: string;
  value: string | number;
  accent?: "ok" | "warn" | "danger" | "default";
}>();
</script>

<template>
  <div class="kpi" :data-accent="accent ?? 'default'">
    <div class="kpi__value">{{ value }}</div>
    <div class="kpi__label">{{ label }}</div>
  </div>
</template>

<style scoped>
.kpi {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition), box-shadow var(--transition);
}
.kpi:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-hover);
}
.kpi__value {
  font-size: 28px;
  font-weight: 800;
  color: var(--brand-navy);
  line-height: 1;
  margin-bottom: 6px;
}
[data-theme="dark"] .kpi__value { color: var(--brand-blue); }
.kpi[data-accent="danger"] .kpi__value { color: var(--danger); }
.kpi[data-accent="warn"] .kpi__value { color: var(--warning); }
.kpi[data-accent="ok"] .kpi__value { color: var(--success); }
.kpi__label {
  font-size: 13px;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  font-weight: 600;
}
</style>
