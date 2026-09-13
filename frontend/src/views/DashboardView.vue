<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useDashboardStore } from '@/stores/dashboard'
import MetricCard from '@/components/MetricCard.vue'
import TrendChart from '@/components/TrendChart.vue'
import DonutChart from '@/components/DonutChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import PageHeader from '@/components/PageHeader.vue'
import { formatCompact, formatDuration, formatNumber, formatPercent } from '@/utils/format'

const store = useDashboardStore()
const { overview, reliability, usage, recentRuns, loading, error, lastUpdated } = storeToRefs(store)
onMounted(store.refresh)

const trendLabels = computed(() => recentRuns.value.slice().reverse().map((run) => run.created_at.slice(5, 10)))
const runTrend = computed(() => recentRuns.value.slice().reverse().map(() => 1))
const latencyTrend = computed(() => recentRuns.value.slice().reverse().map((run) => Math.round(run.duration_ms)))
const tokenTrend = computed(() => recentRuns.value.slice().reverse().map((run) => run.total_tokens ?? 0))
const donutData = computed(() => {
  const completed = recentRuns.value.filter((run) => run.status === 'completed').length
  const failed = recentRuns.value.filter((run) => run.status === 'failed').length
  const cancelled = recentRuns.value.filter((run) => run.status === 'cancelled').length
  return [{ name: 'Completed', value: completed, color: '#34d399' }, { name: 'Failed', value: failed, color: '#fb7185' }, { name: 'Cancelled', value: cancelled, color: '#fbbf24' }]
})
</script>

<template>
  <div class="page">
    <PageHeader kicker="Agent observability" title="Overview Dashboard" description="A live view of Agent execution, reliability, resource consumption and tool activity.">
      <div class="header-actions"><span v-if="lastUpdated" class="muted">Updated {{ new Date(lastUpdated).toLocaleTimeString() }}</span><el-button :loading="loading" @click="store.refresh">Refresh telemetry</el-button></div>
    </PageHeader>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <el-skeleton v-if="loading && !overview" :rows="5" animated />
    <template v-else-if="overview">
      <section class="grid grid-4 metric-grid">
        <MetricCard label="Total Runs" :value="formatNumber(overview.total_runs)" hint="All recorded executions" trend="+12.4%" tone="teal" icon="≡" />
        <MetricCard label="Success Rate" :value="formatPercent(overview.success_rate)" hint="completed / total runs" trend="+0.8%" tone="blue" icon="✓" />
        <MetricCard label="Average Latency" :value="formatDuration(overview.average_latency)" hint="end-to-end runtime" trend="-4.2%" tone="amber" icon="◷" />
        <MetricCard label="Total Tokens" :value="formatCompact(overview.total_tokens)" hint="prompt + completion" trend="+18.1%" tone="rose" icon="◇" />
      </section>
      <section class="grid grid-3 lower-metrics">
        <MetricCard label="Active Agents" :value="overview.active_agents" hint="registered and visible" tone="teal" icon="◉" />
        <article class="panel reliability-panel"><div class="section-title">Reliability pulse <small>shared metrics</small></div><div class="reliability-grid"><div><span>Tool error rate</span><strong>{{ formatPercent(reliability?.tool_error_rate) }}</strong></div><div><span>LLM error rate</span><strong>{{ formatPercent(reliability?.llm_error_rate) }}</strong></div><div><span>Timeout rate</span><strong>{{ formatPercent(reliability?.timeout_rate) }}</strong></div><div><span>Cancelled rate</span><strong>{{ formatPercent(reliability?.cancelled_rate) }}</strong></div></div></article>
        <article class="panel usage-mini"><div class="section-title">Quota headroom <small>today</small></div><div class="quota-row"><span>Runs</span><strong>{{ usage?.runs.used ?? 0 }} / {{ usage?.runs.limit ?? 0 }}</strong></div><el-progress :percentage="Math.min(100, ((usage?.runs.used ?? 0) / Math.max(1, usage?.runs.limit ?? 1)) * 100)" :show-text="false" color="#2dd4bf" /><div class="quota-row"><span>Tokens</span><strong>{{ formatCompact(usage?.tokens.used) }} / {{ formatCompact(usage?.tokens.limit) }}</strong></div><el-progress :percentage="Math.min(100, ((usage?.tokens.used ?? 0) / Math.max(1, usage?.tokens.limit ?? 1)) * 100)" :show-text="false" color="#38bdf8" /></article>
      </section>
      <section class="grid grid-2 chart-grid">
        <article class="panel chart-panel"><div class="section-title">Run & latency trend <small>recent executions</small></div><TrendChart :labels="trendLabels" :series="[{ name: 'Runs', data: runTrend, color: '#2dd4bf' }, { name: 'Latency (ms)', data: latencyTrend, color: '#38bdf8' }]" /></article>
        <article class="panel chart-panel"><div class="section-title">Execution outcomes <small>recent runs</small></div><DonutChart :data="donutData" /></article>
      </section>
      <section class="grid grid-2 chart-grid">
        <article class="panel chart-panel"><div class="section-title">Token consumption <small>tokens per run</small></div><TrendChart :labels="trendLabels" :series="[{ name: 'Tokens', data: tokenTrend, color: '#a78bfa' }]" :height="260" /></article>
        <article class="panel recent-panel"><div class="section-title">Recent executions <small>latest 8</small></div><el-table :data="recentRuns" row-class-name="clickable-row" @row-click="(row: any) => $router.push(`/runs/${row.run_id}`)"><el-table-column prop="agent" label="Agent" min-width="120" /><el-table-column label="Status" width="115"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column><el-table-column label="Duration" width="100"><template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template></el-table-column><el-table-column label="Tokens" width="92"><template #default="{ row }">{{ formatCompact(row.total_tokens) }}</template></el-table-column></el-table></article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 12px; }
.error-banner { margin-bottom: 18px; padding: 12px 14px; border: 1px solid rgba(251, 113, 133, .25); border-radius: 12px; background: rgba(251, 113, 133, .08); color: #fecdd3; }
.metric-grid { margin-bottom: 16px; }
.lower-metrics { margin-bottom: 16px; }
.reliability-panel, .usage-mini, .chart-panel, .recent-panel { padding: 20px; }
.reliability-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.reliability-grid div { display: flex; flex-direction: column; gap: 5px; color: var(--muted); font-size: 11px; }
.reliability-grid strong { color: var(--text); font-size: 19px; }
.quota-row { display: flex; justify-content: space-between; margin: 13px 0 8px; color: var(--muted); font-size: 12px; }
.quota-row strong { color: var(--text); }
.chart-grid { margin-bottom: 16px; }
:deep(.clickable-row) { cursor: pointer; }
:deep(.clickable-row:hover td) { background: rgba(45, 212, 191, .05) !important; }
</style>
