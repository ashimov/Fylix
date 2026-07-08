<script setup lang="ts">
defineProps<{ status: string }>();
</script>

<template>
  <span class="badge" :data-status="status">{{ status }}</span>
</template>

<style scoped>
.badge {
  display: inline-block;
  padding: 2px 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border-radius: 999px;
  background: var(--tag-bg);
  color: var(--brand-navy);
}
[data-theme="dark"] .badge { color: var(--brand-blue); }
.badge[data-status="ready"] { background: rgba(34, 197, 94, 0.15); color: var(--success); }
.badge[data-status="uploading"] { background: rgba(148, 189, 229, 0.2); color: #0369a1; }
.badge[data-status="expired"],
.badge[data-status="deleted"],
.badge[data-status="revoked"] { background: rgba(100, 116, 139, 0.2); color: #475569; }
.badge[data-status="infected"] { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
</style>
