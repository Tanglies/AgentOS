<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getAgents, getRuns } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { formatCompact, formatDate, formatDuration, truncate } from '@/utils/format'
import type { AgentSummary, RunSummary } from '@/types'

const router = useRouter()
const runs = ref<RunSummary[]>([])
const agents = ref<AgentSummary[]>([])
const total = ref(0)
const loading = ref(true)
const filters = reactive({ page: 1, page_size: 10, agent: '', status: '' })
async function load() {
  loading.value = true
  try {
    const result = await getRuns(filters)
    runs.value = result.items
    total.value = result.total
  } finally {
    loading.value = false
  }
}
function reset() { filters.page = 1; filters.agent = ''; filters.status = ''; load() }
onMounted(async () => {
  agents.value = await getAgents()
  await load()
})
</script>
<template>
  <div class="page">
    <PageHeader kicker="Execution log" title="Run History" description="Every Agent execution, with status, latency, token usage and the full trace handoff." />
    <section class="panel filter-panel">
      <el-select v-model="filters.agent" clearable placeholder="All agents" class="filter">
        <el-option v-for="agent in agents" :key="agent.name" :label="agent.name" :value="agent.name" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="All statuses" class="filter">
        <el-option label="Completed" value="completed" /><el-option label="Failed" value="failed" /><el-option label="Cancelled" value="cancelled" />
      </el-select>
      <el-button type="primary" @click="filters.page = 1; load()">Apply filters</el-button>
      <el-button @click="reset">Reset</el-button>
      <span class="result-count">{{ total }} runs</span>
    </section>
    <section class="panel table-panel">
      <el-table v-loading="loading" :data="runs" row-class-name="clickable-row" @row-click="(row: RunSummary) => router.push(`/runs/${row.run_id}`)">
        <el-table-column label="Run ID" min-width="170"><template #default="{ row }"><span class="mono run-id">{{ row.run_id }}</span></template></el-table-column>
        <el-table-column prop="agent" label="Agent" min-width="130" />
        <el-table-column label="Status" width="116"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column>
        <el-table-column label="Request" min-width="260"><template #default="{ row }"><span class="request">{{ truncate(row.input, 76) }}</span></template></el-table-column>
        <el-table-column label="Duration" width="106"><template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template></el-table-column>
        <el-table-column label="Tokens" width="92"><template #default="{ row }">{{ formatCompact(row.total_tokens) }}</template></el-table-column>
        <el-table-column label="Tools" width="78"><template #default="{ row }">{{ row.tool_call_count }}</template></el-table-column>
        <el-table-column label="Created" width="130"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="filters.page" v-model:page-size="filters.page_size" layout="prev, pager, next, sizes" :total="total" @current-change="load" @size-change="filters.page = 1; load()" />
    </section>
  </div>
</template>
<style scoped>
.filter-panel { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; padding: 14px; }
.filter { width: 190px; }
.result-count { margin-left: auto; color: var(--muted); font-size: 12px; }
.table-panel { padding: 20px; }
.run-id { color: var(--accent-blue); font-size: 12px; }
.request { color: #c7d4e4; font-size: 12px; }
:deep(.clickable-row) { cursor: pointer; }
:deep(.clickable-row:hover td) { background: rgba(45, 212, 191, .05) !important; }
</style>