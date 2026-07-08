<script setup lang="ts">
defineProps<{ percent: number; label?: string }>();
</script>

<template>
  <div class="progress" :aria-label="label" role="progressbar" :aria-valuenow="Math.round(percent)" aria-valuemin="0" aria-valuemax="100">
    <div class="progress__bar" :style="{ width: `${Math.max(0, Math.min(100, percent))}%` }"></div>
    <span class="progress__text">{{ Math.round(percent) }}%</span>
  </div>
</template>

<style scoped>
.progress {
  position: relative;
  height: 24px;
  background: var(--bg-section);
  border-radius: 999px;
  overflow: hidden;
  border: 1px solid var(--border);
}
.progress__bar {
  height: 100%;
  background: linear-gradient(90deg, var(--brand-navy) 0%, var(--brand-blue) 100%);
  transition: width 300ms ease;
}
.progress__text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  text-shadow: 0 0 2px var(--surface);
}
</style>
