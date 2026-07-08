<script setup lang="ts">
// Table-row skeleton for the loading state on admin list pages.
// Usage:
//   <tbody v-if="loading && !rows.length">
//     <SkeletonRow v-for="n in 5" :key="n" :columns="9" />
//   </tbody>
//   <tbody v-else-if="!rows.length">
//     <tr><td :colspan="9"><EmptyState .../></td></tr>
//   </tbody>
//   <tbody v-else>
//     <tr v-for="row in rows" ...>
//   </tbody>

interface Props {
  columns: number;
}

defineProps<Props>();
</script>

<template>
  <tr class="skeleton-row">
    <td v-for="i in columns" :key="i">
      <span class="skeleton-bar" :style="{ width: `${40 + ((i * 13) % 50)}%` }" />
    </td>
  </tr>
</template>

<style scoped>
.skeleton-row td {
  padding: 10px 12px;
}
.skeleton-bar {
  display: inline-block;
  height: 12px;
  border-radius: 6px;
  background: linear-gradient(
    90deg,
    var(--border, #e5e7eb) 0%,
    var(--surface, #f3f4f6) 50%,
    var(--border, #e5e7eb) 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.4s ease-in-out infinite;
}
@keyframes skeleton-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}
</style>
