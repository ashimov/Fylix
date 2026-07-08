<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

import type { AnalyticsResponse } from "@/api/analytics";
import { getAnalytics } from "@/api/analytics";
import Chart from "@/components/Chart.vue";
import KpiCard from "@/components/KpiCard.vue";

const data = ref<AnalyticsResponse | null>(null);
const error = ref<string | null>(null);
const days = ref(30);

let timer: number | null = null;

async function refresh(): Promise<void> {
  try {
    data.value = await getAnalytics(days.value);
    error.value = null;
  } catch (e) {
    error.value = e instanceof Error ? e.message : "error";
  }
}

onMounted(() => {
  void refresh();
  timer = window.setInterval(refresh, 60_000);
});

onUnmounted(() => {
  if (timer !== null) clearInterval(timer);
});
</script>

<template>
  <section class="dashboard">
    <h1>Dashboard</h1>

    <p v-if="error" class="error">{{ error }}</p>

    <template v-if="data">
      <div class="kpi-grid">
        <KpiCard label="Active transfers" :value="data.kpi.active_transfers" />
        <KpiCard label="Traffic today (GB)" :value="data.kpi.traffic_today_gb.toFixed(2)" />
        <KpiCard label="Traffic week (GB)" :value="data.kpi.traffic_week_gb.toFixed(2)" />
        <KpiCard
          label="Infected"
          :value="data.kpi.infected_count"
          :accent="data.kpi.infected_count > 0 ? 'danger' : 'ok'"
        />
        <KpiCard
          label="Rate-limit blocks today"
          :value="data.kpi.rate_limit_blocks_today"
          :accent="data.kpi.rate_limit_blocks_today > 0 ? 'warn' : 'ok'"
        />
      </div>

      <div class="charts-grid">
        <div class="chart-card">
          <h3>Transfers per day</h3>
          <Chart
            kind="line"
            label="count"
            :labels="data.daily_transfers.map((d) => d.date)"
            :data="data.daily_transfers.map((d) => d.count)"
          />
        </div>
        <div class="chart-card">
          <h3>Top countries</h3>
          <Chart
            kind="pie"
            :labels="data.top_countries.map((c) => c.country || '—')"
            :data="data.top_countries.map((c) => c.count)"
          />
        </div>
        <div class="chart-card">
          <h3>Top MIME types</h3>
          <Chart
            kind="bar"
            label="files"
            :labels="data.top_mime.map((m) => m.mime)"
            :data="data.top_mime.map((m) => m.count)"
          />
        </div>
        <div class="chart-card">
          <h3>Infected timeline</h3>
          <Chart
            kind="line"
            label="infected"
            :labels="data.infected_timeline.map((d) => d.date)"
            :data="data.infected_timeline.map((d) => d.count)"
          />
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.dashboard h1 { font-size: 28px; margin: 0 0 24px; }
.error { padding: 10px 14px; background: rgba(239,68,68,0.08); color: var(--danger); border-radius: var(--radius); margin-bottom: 16px; }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 20px;
}
.chart-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  box-shadow: var(--shadow-card);
}
.chart-card h3 { font-size: 15px; margin: 0 0 16px; color: var(--text); }
</style>
