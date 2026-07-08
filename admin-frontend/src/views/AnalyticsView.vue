<script setup lang="ts">
import { onMounted, ref } from "vue";

import { getAnalytics, type AnalyticsResponse } from "@/api/analytics";
import Chart from "@/components/Chart.vue";
import KpiCard from "@/components/KpiCard.vue";

const days = ref(30);
const data = ref<AnalyticsResponse | null>(null);
const loading = ref(false);
const error = ref<string | null>(null);

async function refresh(): Promise<void> {
  loading.value = true;
  error.value = null;
  try {
    data.value = await getAnalytics(days.value);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Failed to load analytics";
  } finally {
    loading.value = false;
  }
}

onMounted(refresh);
</script>

<template>
  <section>
    <div class="header">
      <h1>Analytics</h1>
      <div class="controls">
        <select v-model.number="days" @change="refresh">
          <option :value="7">Last 7 days</option>
          <option :value="30">Last 30 days</option>
          <option :value="90">Last 90 days</option>
        </select>
      </div>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <template v-if="data">
      <div class="kpi-grid">
        <KpiCard label="Active" :value="data.kpi.active_transfers" />
        <KpiCard label="Traffic today (GB)" :value="data.kpi.traffic_today_gb.toFixed(2)" />
        <KpiCard label="Traffic week (GB)" :value="data.kpi.traffic_week_gb.toFixed(2)" />
        <KpiCard label="Infected" :value="data.kpi.infected_count" :accent="data.kpi.infected_count > 0 ? 'danger' : 'ok'" />
        <KpiCard label="RL blocks today" :value="data.kpi.rate_limit_blocks_today" :accent="data.kpi.rate_limit_blocks_today > 0 ? 'warn' : 'ok'" />
      </div>

      <div class="charts-grid">
        <div class="card"><h3>Transfers per day</h3><Chart kind="line" label="count" :labels="data.daily_transfers.map((d) => d.date)" :data="data.daily_transfers.map((d) => d.count)" /></div>
        <div class="card"><h3>Traffic (bytes) per day</h3><Chart kind="bar" label="bytes" :labels="data.daily_transfers.map((d) => d.date)" :data="data.daily_transfers.map((d) => d.bytes)" /></div>
        <div class="card"><h3>Top countries</h3><Chart kind="pie" :labels="data.top_countries.map((c) => c.country || '—')" :data="data.top_countries.map((c) => c.count)" /></div>
        <div class="card"><h3>Top MIME types</h3><Chart kind="bar" label="files" :labels="data.top_mime.map((m) => m.mime)" :data="data.top_mime.map((m) => m.count)" /></div>
        <div class="card"><h3>Top sender domains</h3><Chart kind="bar" label="transfers" :labels="data.top_sender_domains.map((d) => d.domain)" :data="data.top_sender_domains.map((d) => d.count)" /></div>
        <div class="card"><h3>Top IPs</h3><Chart kind="bar" label="transfers" :labels="data.top_ips.map((i) => i.ip)" :data="data.top_ips.map((i) => i.count)" /></div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
h1 { font-size: 28px; margin: 0; }
.controls select {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text);
  font-size: 14px;
}
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px; }
.charts-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 20px; }
.card { background: var(--surface); border-radius: var(--radius-lg); padding: 20px; box-shadow: var(--shadow-card); }
.card h3 { margin: 0 0 16px; font-size: 14px; color: var(--text); }
.error { margin: 0 0 16px; padding: 10px 14px; background: rgba(239, 68, 68, 0.08); color: var(--danger); border-radius: var(--radius); font-size: 13px; }
</style>
