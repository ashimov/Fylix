<script setup lang="ts">
import { Bar, Line, Pie } from "vue-chartjs";
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import { computed } from "vue";

ChartJS.register(
  ArcElement,
  BarElement,
  CategoryScale,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
);

const props = defineProps<{
  kind: "line" | "bar" | "pie";
  labels: string[];
  data: number[];
  label?: string;
}>();

const NAVY = "#272666";
const BLUE = "#94BDE5";

const chartData = computed(() => ({
  labels: props.labels,
  datasets: [
    {
      label: props.label ?? "",
      data: props.data,
      borderColor: NAVY,
      backgroundColor:
        props.kind === "pie"
          ? [NAVY, BLUE, "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4", "#64748b", "#eab308", "#ec4899"]
          : NAVY + "20",
      borderWidth: 2,
      pointRadius: props.kind === "line" ? 3 : undefined,
      tension: 0.3,
    },
  ],
}));

const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: props.kind === "pie" },
  },
  scales:
    props.kind === "pie"
      ? {}
      : {
          y: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
          x: { grid: { display: false } },
        },
}));
</script>

<template>
  <div class="chart">
    <Line v-if="kind === 'line'" :data="chartData" :options="chartOptions" />
    <Bar v-else-if="kind === 'bar'" :data="chartData" :options="chartOptions" />
    <Pie v-else :data="chartData" :options="chartOptions" />
  </div>
</template>

<style scoped>
.chart {
  position: relative;
  height: 280px;
}
</style>
