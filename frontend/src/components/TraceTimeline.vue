<script setup lang="ts">
import type { TraceStep } from '@/types'
import StatusTag from './StatusTag.vue'
import { formatDuration, sanitizeTraceValue } from '@/utils/format'

defineProps<{ steps: TraceStep[] }>()

const iconMap: Record<TraceStep['type'], string> = {
  request: 'YOU', runtime: 'RT', planning: 'PLAN', llm: 'LLM', tool: 'TOOL', result: 'OUT', answer: 'AI', error: 'ERR',
}
</script>

<template>
  <div class="trace-timeline">
    <section v-for="(step, index) in steps" :key="step.id" class="trace-step" :class="`step-${step.type}`">
      <div class="trace-rail">
        <div class="trace-icon">{{ iconMap[step.type] }}</div>
        <div v-if="index < steps.length - 1" class="trace-line" />
      </div>
      <div class="trace-card">
        <div class="trace-head">
          <div>
            <div class="trace-title">{{ step.title }}</div>
            <div v-if="step.subtitle" class="trace-subtitle">{{ step.subtitle }}</div>
          </div>
          <div class="trace-meta"><StatusTag :status="step.status" /><span v-if="step.duration !== undefined">{{ formatDuration(step.duration) }}</span></div>
        </div>
        <div v-if="step.toolName" class="trace-tool"><span class="mono">{{ step.toolName }}</span><span v-if="step.arguments" class="trace-args mono">{{ sanitizeTraceValue(step.arguments, 180) }}</span></div>
        <p v-if="step.content" class="trace-content">{{ sanitizeTraceValue(step.content) }}</p>
        <el-collapse v-if="step.arguments || step.result" class="trace-collapse">
          <el-collapse-item title="Inspect payload">
            <div v-if="step.arguments" class="payload-block"><strong>Arguments</strong><pre>{{ sanitizeTraceValue(step.arguments) }}</pre></div>
            <div v-if="step.result" class="payload-block"><strong>Result</strong><pre>{{ sanitizeTraceValue(step.result) }}</pre></div>
          </el-collapse-item>
        </el-collapse>
      </div>
    </section>
  </div>
</template>

<style scoped>
.trace-timeline { display: grid; gap: 0; }
.trace-step { display: grid; grid-template-columns: 48px minmax(0, 1fr); }
.trace-rail { position: relative; display: flex; justify-content: center; }
.trace-icon { z-index: 1; display: grid; place-items: center; width: 38px; height: 38px; border: 1px solid rgba(45, 212, 191, .3); border-radius: 12px; background: #0d2435; color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .04em; }
.trace-line { position: absolute; top: 38px; bottom: -1px; width: 1px; background: linear-gradient(var(--accent), rgba(148, 163, 184, .08)); }
.trace-card { margin: 0 0 16px 10px; padding: 16px 18px; border: 1px solid var(--line); border-radius: 16px; background: rgba(13, 27, 47, .72); }
.trace-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.trace-title { font-weight: 680; }
.trace-subtitle { color: var(--muted); font-size: 12px; margin-top: 4px; }
.trace-meta { display: flex; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; white-space: nowrap; }
.trace-tool { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 12px; color: var(--accent-blue); font-size: 12px; }
.trace-args { color: var(--muted); }
.trace-content { margin: 13px 0 0; color: #b7c5d7; line-height: 1.65; white-space: pre-wrap; }
.trace-collapse { margin-top: 10px; --el-collapse-border-color: transparent; --el-collapse-header-bg-color: transparent; --el-collapse-content-bg-color: transparent; --el-collapse-header-text-color: var(--muted); --el-collapse-content-text-color: var(--text); }
.payload-block strong { display: block; margin-bottom: 6px; color: var(--muted); font-size: 11px; text-transform: uppercase; }
pre { margin: 0 0 12px; padding: 12px; overflow: auto; border-radius: 10px; background: #07111f; color: #cce6ff; font-size: 12px; white-space: pre-wrap; }
.step-error .trace-icon { border-color: rgba(251, 113, 133, .45); background: rgba(251, 113, 133, .1); color: var(--danger); }
.step-answer .trace-icon { border-color: rgba(52, 211, 153, .35); background: rgba(52, 211, 153, .1); color: var(--success); }
@media (max-width: 700px) { .trace-head { flex-direction: column; } }
</style>
