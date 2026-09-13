<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getToolStats } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import MetricCard from '@/components/MetricCard.vue'
import { formatDuration, formatNumber, formatPercent } from '@/utils/format'
import type { ToolStat } from '@/types'

const tools = ref<ToolStat[]>([])
const loading = ref(true)
const totalCalls = computed(() => tools.value.reduce((sum, tool) => sum + tool.calls, 0))
const measured = computed(() => tools.value.filter((tool) => tool.successRate !== null))
const avgSuccess = computed(() => measured.value.reduce((sum, tool) => sum + (tool.successRate ?? 0), 0) / Math.max(1, measured.value.length))
const measuredDuration = computed(() => tools.value.filter((tool) => tool.averageDuration !== null))
const avgDuration = computed(() => measuredDuration.value.reduce((sum, tool) => sum + (tool.averageDuration ?? 0), 0) / Math.max(1, measuredDuration.value.length))
onMounted(async () => { try { tools.value = await getToolStats() } finally { loading.value = false } })
</script>

<template>
  <div class="page">
    <PageHeader kicker="Tool analytics" title="Tools" description="Tool inventory, call volume, success signals and execution cost across the Agent platform." />
    <section class="grid grid-4 tool-metrics">
      <MetricCard label="Tool calls" :value="formatNumber(totalCalls)" hint="observed invocations" tone="teal" icon="⌘" />
      <MetricCard label="Enabled tools" :value="tools.filter((tool) => tool.enabled).length" hint="visible to Agents" tone="blue" icon="✓" />
      <MetricCard label="Avg success" :value="formatPercent(avgSuccess)" hint="weighted by tools" tone="amber" icon="↗" />
      <MetricCard label="Avg duration" :value="formatDuration(avgDuration)" hint="per tool execution" tone="rose" icon="◷" />
    </section>
    <section class="panel table-panel">
      <div class="section-title">Tool registry analytics <small>live metrics when available</small></div>
      <el-table v-loading="loading" :data="tools">
        <el-table-column label="Tool" min-width="190"><template #default="{ row }"><div class="tool-name"><span class="tool-glyph">⌘</span><div><strong>{{ row.name }}</strong><small>{{ row.category }} · risk {{ row.riskLevel }}</small></div></div></template></el-table-column>
        <el-table-column label="Calls" width="100"><template #default="{ row }">{{ formatNumber(row.calls) }}</template></el-table-column>
        <el-table-column label="Share" min-width="220"><template #default="{ row }"><el-progress :percentage="Math.min(100, row.calls / Math.max(1, totalCalls) * 100)" :show-text="false" color="#2dd4bf" /><small class="progress-copy">{{ formatPercent(row.calls / Math.max(1, totalCalls)) }}</small></template></el-table-column>
        <el-table-column label="Success" width="110"><template #default="{ row }">{{ row.successRate === null ? '—' : formatPercent(row.successRate) }}</template></el-table-column>
        <el-table-column label="Avg duration" width="130"><template #default="{ row }">{{ row.averageDuration === null ? '—' : formatDuration(row.averageDuration) }}</template></el-table-column>
        <el-table-column label="State" width="100"><template #default="{ row }"><span :class="['state', row.enabled ? 'enabled' : 'disabled']">{{ row.enabled ? 'enabled' : 'disabled' }}</span></template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.tool-metrics { margin-bottom: 16px; }
.table-panel { padding: 20px; }
.tool-name { display: flex; align-items: center; gap: 11px; }
.tool-name > div { display: flex; flex-direction: column; gap: 3px; }
.tool-name small { color: var(--muted); }
.tool-glyph { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 10px; background: rgba(56, 189, 248, .1); color: var(--accent-blue); }
.progress-copy { color: var(--muted); font-size: 10px; }
.state { padding: 4px 8px; border-radius: 999px; font-size: 11px; }
.enabled { color: var(--success); background: rgba(52, 211, 153, .1); }
.disabled { color: var(--muted); background: rgba(148, 163, 184, .1); }
</style>