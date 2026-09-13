<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

interface Slice { name: string; value: number; color: string }
const props = withDefaults(defineProps<{ data: Slice[]; height?: number }>(), { height: 240 })
const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const total = props.data.reduce((sum, item) => sum + item.value, 0)
  const option: EChartsOption = {
    tooltip: { trigger: 'item', backgroundColor: '#0d1b2f', borderColor: 'rgba(148,163,184,.2)', textStyle: { color: '#e5edf7' } },
    legend: { bottom: 0, textStyle: { color: '#8aa0b8' }, icon: 'circle' },
    series: [{
      type: 'pie', radius: ['58%', '78%'], center: ['50%', '43%'], avoidLabelOverlap: true,
      label: { show: false }, itemStyle: { borderColor: '#0b1728', borderWidth: 4, borderRadius: 8 },
      data: props.data.map((item) => ({ name: item.name, value: item.value, itemStyle: { color: item.color } })),
    }],
    graphic: [{ type: 'text', left: 'center', top: '34%', style: { text: String(total), fill: '#e5edf7', font: '700 26px Inter' } }, { type: 'text', left: 'center', top: '44%', style: { text: 'runs', fill: '#8aa0b8', font: '12px Inter' } }],
  }
  chart.setOption(option, true)
}

onMounted(() => { render(); window.addEventListener('resize', render) })
onBeforeUnmount(() => { window.removeEventListener('resize', render); chart?.dispose(); chart = null })
watch(() => props.data, () => nextTick(render), { deep: true })
</script>

<template><div ref="chartRef" class="donut-chart" :style="{ height: `${height}px` }" /></template>

<style scoped>.donut-chart { width: 100%; }</style>
