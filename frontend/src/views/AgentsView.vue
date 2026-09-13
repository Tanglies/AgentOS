<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getAgents, getRuns } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatDate, formatPercent } from '@/utils/format'
import type { AgentSummary, RunSummary } from '@/types'

const agents = ref<AgentSummary[]>([])
const runs = ref<RunSummary[]>([])
const loading = ref(true)
const search = ref('')
const filteredAgents = computed(() => agents.value.filter((agent) => !search.value || `${agent.name} ${agent.model ?? ''} ${agent.description ?? ''}`.toLowerCase().includes(search.value.toLowerCase())))
const runStats = computed(() => {
  const map = new Map<string, { runs: number; success: number }>()
  runs.value.forEach((run) => {
    const entry = map.get(run.agent) ?? { runs: 0, success: 0 }
    entry.runs += 1
    if (run.status === 'completed') entry.success += 1
    map.set(run.agent, entry)
  })
  return map
})

onMounted(async () => {
  try {
    agents.value = await getAgents()
    runs.value = (await getRuns({ page: 1, page_size: 500 })).items
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="page">
    <PageHeader kicker="Agent fleet" title="Agents" description="Registered Agents, model routing, available tools and observed execution health.">
      <el-input v-model="search" class="search-input" placeholder="Search agents..." clearable />
    </PageHeader>
    <section class="grid grid-4 agent-summary">
      <el-card shadow="never"><div class="summary-label">Registered</div><strong>{{ agents.length }}</strong><span>Agent definitions</span></el-card>
      <el-card shadow="never"><div class="summary-label">Observed runs</div><strong>{{ runs.length }}</strong><span>Across all agents</span></el-card>
      <el-card shadow="never"><div class="summary-label">Healthy</div><strong>{{ agents.length }}</strong><span>With execution history</span></el-card>
      <el-card shadow="never"><div class="summary-label">Tool-enabled</div><strong>{{ agents.filter((agent) => (agent.tools?.length ?? 0) > 0).length }}</strong><span>Can call tools</span></el-card>
    </section>
    <section class="panel table-panel">
      <div class="section-title">Agent roster <small>{{ filteredAgents.length }} visible</small></div>
      <el-table v-loading="loading" :data="filteredAgents">
        <el-table-column label="Agent" min-width="220">
          <template #default="{ row }"><div class="agent-cell"><span class="agent-avatar">{{ row.name.slice(0, 2).toUpperCase() }}</span><div><strong>{{ row.name }}</strong><small>{{ row.description || 'No description' }}</small></div></div></template>
        </el-table-column>
        <el-table-column prop="model" label="Model" min-width="160"><template #default="{ row }"><span class="mono">{{ row.model || 'provider default' }}</span></template></el-table-column>
        <el-table-column label="Tools" width="90"><template #default="{ row }">{{ row.tools?.length ?? 0 }}</template></el-table-column>
        <el-table-column label="Runs" width="90"><template #default="{ row }">{{ runStats.get(row.name)?.runs ?? 0 }}</template></el-table-column>
        <el-table-column label="Success" width="130"><template #default="{ row }"><StatusTag :status="(runStats.get(row.name)?.runs ?? 0) ? ((runStats.get(row.name)?.success ?? 0) === runStats.get(row.name)?.runs ? 'completed' : 'failed') : 'queued'" /><span class="success-copy">{{ formatPercent((runStats.get(row.name)?.success ?? 0) / Math.max(1, runStats.get(row.name)?.runs ?? 1)) }}</span></template></el-table-column>
        <el-table-column label="Created" width="150"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.search-input { width: 260px; }
.agent-summary { margin-bottom: 16px; }
.agent-summary :deep(.el-card__body) { display: flex; flex-direction: column; gap: 6px; color: var(--muted); }
.agent-summary strong { color: var(--text); font-size: 28px; }
.agent-summary span { font-size: 11px; }
.summary-label { color: var(--muted); font-size: 12px; }
.table-panel { padding: 20px; }
.agent-cell { display: flex; align-items: center; gap: 11px; }
.agent-cell > div { display: flex; flex-direction: column; gap: 3px; }
.agent-cell small { color: var(--muted); }
.agent-avatar { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: rgba(45, 212, 191, .11); color: var(--accent); font-size: 11px; font-weight: 800; }
.success-copy { margin-left: 7px; color: var(--muted); font-size: 11px; }
</style>