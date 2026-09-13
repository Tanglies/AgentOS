<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getEvaluationRuns, getEvaluationSummary } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import MetricCard from '@/components/MetricCard.vue'
import DonutChart from '@/components/DonutChart.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatCompact, formatDate, formatDuration, formatPercent } from '@/utils/format'
import type { EvaluationRunSummary, EvaluationSummary } from '@/types'

const summary = ref<EvaluationSummary | null>(null)
const runs = ref<EvaluationRunSummary[]>([])
const loading = ref(true)
const passDonut = computed(() => summary.value ? [
  { name: 'Passed', value: summary.value.succeeded, color: '#34d399' },
  { name: 'Failed', value: summary.value.failed, color: '#fb7185' },
] : [])
onMounted(async () => {
  try { [summary.value, runs.value] = await Promise.all([getEvaluationSummary(), getEvaluationRuns()]) }
  finally { loading.value = false }
})
</script>

<template>
  <div class="page">
    <PageHeader kicker="Quality signals" title="Evaluation" description="Dataset execution, pass rate, score quality, latency and regression signals for the Agent platform." />
    <el-skeleton v-if="loading" :rows="6" animated />
    <template v-else-if="summary">
      <section class="grid grid-4 eval-metrics">
        <MetricCard label="Total cases" :value="formatCompact(summary.runs)" hint="recorded executions" tone="teal" icon="✦" />
        <MetricCard label="Pass rate" :value="formatPercent(summary.success_rate)" hint="successful cases" tone="blue" icon="✓" />
        <MetricCard label="Average latency" :value="formatDuration(summary.average_latency)" hint="evaluation runtime" tone="amber" icon="◷" />
        <MetricCard label="Estimated cost" :value="summary.cost?.total ? summary.cost.total.toFixed(4) : '—'" hint="configured pricing map" tone="rose" icon="◇" />
      </section>
      <section class="grid grid-2 eval-charts">
        <article class="panel chart-panel"><div class="section-title">Pass / fail distribution <small>run outcomes</small></div><DonutChart :data="passDonut" /></article>
        <article class="panel chart-panel"><div class="section-title">Evaluation reliability <small>shared runtime metrics</small></div><div class="reliability-grid"><div><span>Tool error rate</span><strong>{{ formatPercent(summary.reliability?.tool_error_rate) }}</strong></div><div><span>LLM error rate</span><strong>{{ formatPercent(summary.reliability?.llm_error_rate) }}</strong></div><div><span>Timeout rate</span><strong>{{ formatPercent(summary.reliability?.timeout_rate) }}</strong></div><div><span>Cancelled rate</span><strong>{{ formatPercent(summary.reliability?.cancelled_rate) }}</strong></div></div></article>
      </section>
      <section class="panel table-panel">
        <div class="section-title">Dataset runs <small>{{ runs.length }} recorded</small></div>
        <el-table :data="runs">
          <el-table-column prop="dataset_name" label="Dataset" min-width="210" />
          <el-table-column label="Status" width="120"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
          <el-table-column label="Cases" width="90"><template #default="{ row }">{{ row.completed_cases }} / {{ row.total_cases }}</template></el-table-column>
          <el-table-column label="Pass rate" width="120"><template #default="{ row }">{{ formatPercent(row.passed_cases / Math.max(1, row.total_cases)) }}</template></el-table-column>
          <el-table-column label="Failed" width="90"><template #default="{ row }">{{ row.failed_cases }}</template></el-table-column>
          <el-table-column label="Created" width="150"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
        </el-table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.eval-metrics { margin-bottom: 16px; }
.eval-charts { margin-bottom: 16px; }
.chart-panel, .table-panel { padding: 20px; }
.reliability-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.reliability-grid div { display: flex; flex-direction: column; gap: 5px; color: var(--muted); font-size: 11px; }
.reliability-grid strong { color: var(--text); font-size: 19px; }
</style>