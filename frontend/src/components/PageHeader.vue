<script setup lang="ts">
defineProps<{ kicker: string; title: string; description?: string }>()
</script>

<template>
  <header class="page-header">
    <div>
      <div class="page-kicker">{{ kicker }}</div>
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="description" class="page-description">{{ description }}</p>
    </div>
    <slot />
  </header>
</template>
