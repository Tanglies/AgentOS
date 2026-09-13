<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getRunDetail } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import MetricCard from '@/components/MetricCard.vue'
import TraceTimeline from '@/components/TraceTimeline.vue'
import { formatCompact, formatDuration, formatPercent } from '@/utils/format'
import type { RunDetail, TraceStep } from '@/types'

const route = useRoute()
const router = useRouter()
const run = ref<RunDetail | null>(null)
const loading = ref(true)
const error = ref('')

const traceSteps = computed<TraceStep[]>(() => {
  if (!run.value) return []
  const steps: TraceStep[] = []
  const messages = run.value.messages.filter((message) => message.role !== 'system')
  messages.forEach((message, index) => {
    if (message.role === 'user') {
      steps.push({ id: `request-${index}`, type: 'request', title: 'User request', subtitle: 'Incoming task', content: message.content, status: 'success' })
      steps.push({ id: `runtime-${index}`, type: 'runtime', title: 'Agent Runtime', subtitle: `${run.value?.agent} prepared the execution loop`, status: 'success', duration: index === 0 ? run.value?.duration_ms : undefined })
    }
    if (message.role === 'assistant' && message.tool_calls?.length) {
      steps.push({ id: `llm-${index}`, type: 'llm', title: 'LLM decision', subtitle: 'Model requested tool execution', status: 'success', model: run.value?.agent, tokens: run.value?.total_tokens })
      message.tool_calls.forEach((call) => {
        const result = messages.find((candidate) => candidate.role === 'tool' && candidate.tool_call_id === call.id)
        steps.push({ id: `tool-${call.id}`, type: 'tool', title: `Tool call · ${call.name}`, subtitle: 'Executed inside AgentOS ToolRegistry', status: result ? 'success' : 'warning', toolName: call.name, arguments: call.arguments })
        if (result) steps.push({ id: `result-${call.id}`, type: 'result', title: 'Tool result', subtitle: `Response from ${call.name}`, content: result.content, result: result.content, status: 'success', toolName: call.name })
      })
    }
    if (message.role === 'assistant' && message.content.trim() && !message.tool_calls?.length) {
      steps.push({ id: `answer-${index}`, type: 'answer', title: 'Final answer', subtitle: 'Assistant response delivered to the client', content: message.content, status: 'success' })
    }
  })
  if (run.value.error) steps.push({ id: 'error', type: 'error', title: 'Run error', subtitle: run.value.error, content: run.value.error, status: 'error' })
  return steps
})

onMounted(async () => {
  try { run.value = await getRunDetail(String(route.params.id)) } catch (err) { error.value = err instanceof Error ? err.message : 'Failed to load run detail' } finally { loading.value = false }
})
</script>
<template>
  <div class="page">
    <PageHeader kicker="Execution trace" title="Run Detail" :description="run ? `${run.agent} · ${run.run_id}` : 'Loading execution trace...'">
      <el-button @click="router.push('/runs')">← Back to runs</el-button>
    </PageHeader>
    <div v-if="error" class="error-banner">{{ error }}</div>
    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else-if="run">
      <section class="grid grid-4 detail-metrics">
        <MetricCard label="Status" :value="run.status" :hint="`${run.iterations} runtime iterations`" :tone="run.status === 'completed' ? 'teal' : 'rose'" icon="✓" />
        <MetricCard label="Duration" :value="formatDuration(run.duration_ms)" hint="end-to-end" tone="blue" icon="◷" />
        <MetricCard label="Tokens" :value="formatCompact(run.total_tokens)" hint="prompt + completion" tone="amber" icon="◇" />
        <MetricCard label="Tool calls" :value="run.tool_call_count" :hint="`${formatPercent((run.tool_error_count ?? 0) / Math.max(1, run.tool_call_count))} error rate`" tone="rose" icon="⌘" />
      </section>
      <section class="trace-layout">
        <article class="panel trace-panel">
          <div class="section-title">Execution timeline <small>{{ traceSteps.length }} steps</small></div>
          <TraceTimeline :steps="traceSteps" />
        </article>
        <aside class="trace-side">
          <article class="panel side-card"><div class="section-title">Run metadata</div><dl><div><dt>Agent</dt><dd>{{ run.agent }}</dd></div><div><dt>Status</dt><dd><StatusTag :status="run.status" /></dd></div><div><dt>Session</dt><dd class="mono">{{ run.session_id || 'stateless' }}</dd></div><div><dt>Created</dt><dd>{{ new Date(run.created_at).toLocaleString() }}</dd></div><div><dt>Finish reason</dt><dd>{{ run.finish_reason || '—' }}</dd></div></dl></article>
          <article class="panel side-card"><div class="section-title">Safety boundary</div><p class="safety-copy">Only request, tool metadata, truncated payloads and final answer are shown. System prompts, API keys and sensitive memory are filtered.</p><div class="safety-line" /><p class="safety-copy">Tool error count: {{ run.tool_error_count ?? 0 }} · timeouts: {{ run.tool_timeout_count ?? 0 }}</p></article>
        </aside>
      </section>
    </template>
  </div>
</template>
<style scoped>
.error-banner { margin-bottom: 18px; padding: 12px 14px; border: 1px solid rgba(251, 113, 133, .25); border-radius: 12px; background: rgba(251, 113, 133, .08); color: #fecdd3; }
.detail-metrics { margin-bottom: 16px; }
.trace-layout { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 16px; align-items: start; }
.trace-panel { padding: 20px; }
.trace-side { display: grid; gap: 16px; }
.side-card { padding: 20px; }
dl { display: grid; gap: 13px; margin: 0; }
dl div { display: flex; justify-content: space-between; gap: 12px; }
dt { color: var(--muted); font-size: 12px; } dd { margin: 0; text-align: right; color: var(--text); font-size: 12px; }
.safety-copy { margin: 0; color: var(--muted); line-height: 1.65; font-size: 12px; }
.safety-line { height: 1px; margin: 14px 0; background: var(--line); }
@media (max-width: 1000px) { .trace-layout { grid-template-columns: 1fr; } }
</style>