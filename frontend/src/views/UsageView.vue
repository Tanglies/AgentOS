<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getUsage } from '@/api/dashboard'
import PageHeader from '@/components/PageHeader.vue'
import MetricCard from '@/components/MetricCard.vue'
import { formatCompact, formatNumber, formatPercent } from '@/utils/format'
import type { DashboardUsage } from '@/types'

const usage = ref<DashboardUsage | null>(null)
const loading = ref(true)
const runPercent = computed(() => ((usage.value?.runs.used ?? 0) / Math.max(1, usage.value?.runs.limit ?? 1)) * 100)
const tokenPercent = computed(() => ((usage.value?.tokens.used ?? 0) / Math.max(1, usage.value?.tokens.limit ?? 1)) * 100)
onMounted(async () => { try { usage.value = await getUsage() } finally { loading.value = false } })
</script>
<template>
  <div class="page">
    <PageHeader kicker="Resource budget" title="Usage" description="Runs, tokens and quota headroom for the current Workspace." />
    <el-skeleton v-if="loading" :rows="5" animated />
    <template v-else-if="usage">
      <section class="grid grid-4 usage-metrics">
        <MetricCard label="Runs used" :value="formatNumber(usage.runs.used)" :hint="`${formatNumber(usage.runs.limit)} limit`" tone="teal" icon="≡" />
        <MetricCard label="Run headroom" :value="formatPercent(Math.max(0, 1 - runPercent / 100))" hint="remaining quota" tone="blue" icon="↗" />
        <MetricCard label="Tokens used" :value="formatCompact(usage.tokens.used)" :hint="`${formatCompact(usage.tokens.limit)} limit`" tone="amber" icon="◇" />
        <MetricCard label="Token headroom" :value="formatPercent(Math.max(0, 1 - tokenPercent / 100))" hint="remaining budget" tone="rose" icon="◒" />
      </section>
      <section class="grid grid-2 usage-grid">
        <article class="panel usage-card"><div class="section-title">Runs quota <small>today</small></div><div class="big-number">{{ formatNumber(usage.runs.used) }}<span>/ {{ formatNumber(usage.runs.limit) }}</span></div><el-progress :percentage="Math.min(100, runPercent)" :stroke-width="14" color="#2dd4bf" /><p class="usage-note">Each completed, failed, cancelled or interrupted run consumes one quota unit.</p></article>
        <article class="panel usage-card"><div class="section-title">Token budget <small>today</small></div><div class="big-number">{{ formatCompact(usage.tokens.used) }}<span>/ {{ formatCompact(usage.tokens.limit) }}</span></div><el-progress :percentage="Math.min(100, tokenPercent)" :stroke-width="14" color="#38bdf8" /><p class="usage-note">Token usage is aggregated from Run History and is enforced before a run starts.</p></article>
      </section>
      <section class="panel limits-panel"><div class="section-title">Runtime guardrails <small>current Workspace</small></div><div class="limits-grid"><div><span>Requests / minute</span><strong>{{ usage.requests_per_minute ?? '—' }}</strong></div><div><span>Max iterations / run</span><strong>{{ usage.max_iterations_per_run ?? '—' }}</strong></div><div><span>Max tool calls / run</span><strong>{{ usage.max_tool_calls_per_run ?? '—' }}</strong></div></div></section>
    </template>
  </div>
</template>
<style scoped>
.usage-metrics { margin-bottom: 16px; }
.usage-grid { margin-bottom: 16px; }
.usage-card, .limits-panel { padding: 22px; }
.big-number { margin: 14px 0; font-size: 34px; font-weight: 760; letter-spacing: -.04em; }
.big-number span { margin-left: 8px; color: var(--muted); font-size: 15px; font-weight: 450; }
.usage-note { margin: 14px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.limits-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.limits-grid div { display: flex; flex-direction: column; gap: 6px; padding: 15px; border: 1px solid var(--line); border-radius: 13px; color: var(--muted); font-size: 12px; }
.limits-grid strong { color: var(--text); font-size: 22px; }
@media (max-width: 700px) { .limits-grid { grid-template-columns: 1fr; } }
</style>