<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  value: string | number
  hint?: string
  trend?: string
  tone?: 'teal' | 'blue' | 'amber' | 'rose'
  icon?: string
}>(), { tone: 'teal', hint: '', trend: '', icon: '•' })
</script>

<template>
  <article class="metric-card" :class="`tone-${tone}`">
    <div class="metric-top">
      <span class="metric-icon">{{ icon }}</span>
      <span v-if="trend" class="metric-trend">{{ trend }}</span>
    </div>
    <div class="metric-value">{{ value }}</div>
    <div class="metric-label">{{ label }}</div>
    <div v-if="hint" class="metric-hint">{{ hint }}</div>
  </article>
</template>

<style scoped>
.metric-card { position: relative; overflow: hidden; min-height: 134px; padding: 18px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(145deg, rgba(18, 36, 61, .96), rgba(10, 23, 42, .94)); box-shadow: 0 18px 38px rgba(0, 0, 0, .18); }
.metric-card::after { content: ''; position: absolute; inset: auto -24px -50px auto; width: 120px; height: 120px; border-radius: 50%; background: currentColor; opacity: .06; }
.metric-top { display: flex; justify-content: space-between; color: var(--muted); font-size: 12px; }
.metric-icon { display: grid; place-items: center; width: 26px; height: 26px; border-radius: 9px; background: color-mix(in srgb, currentColor 18%, transparent); font-weight: 800; }
.metric-trend { padding: 4px 8px; border-radius: 999px; background: rgba(52, 211, 153, .1); color: var(--success); }
.metric-value { margin-top: 16px; font-size: clamp(25px, 2.3vw, 34px); font-weight: 760; letter-spacing: -.04em; color: var(--text); }
.metric-label { margin-top: 5px; color: var(--muted); font-size: 13px; }
.metric-hint { margin-top: 8px; color: var(--muted); font-size: 11px; }
.tone-teal { color: var(--accent); } .tone-blue { color: var(--accent-blue); } .tone-amber { color: var(--warning); } .tone-rose { color: var(--danger); }
</style>
