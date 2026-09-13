<script setup lang="ts">
import { statusType } from '@/utils/format'
defineProps<{ status: string }>()
</script>

<template>
  <span class="status-tag" :class="`status-${statusType(status)}`">
    <span class="dot" />{{ status }}
  </span>
</template>

<style scoped>
.status-tag { display: inline-flex; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 999px; font-size: 11px; text-transform: capitalize; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; box-shadow: 0 0 10px currentColor; }
.status-success { color: var(--success); background: rgba(52, 211, 153, .1); }
.status-danger { color: var(--danger); background: rgba(251, 113, 133, .1); }
.status-warning { color: var(--warning); background: rgba(251, 191, 36, .1); }
.status-info { color: var(--accent-blue); background: rgba(56, 189, 248, .1); }
</style>
