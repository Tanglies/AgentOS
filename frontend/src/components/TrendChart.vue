<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

interface Series { name: string; data: number[]; color: string }
const props = withDefaults(defineProps<{ labels: string[]; series: Series[]; height?: number; unit?: string }>(), { height: 280, unit: '' })
const chartRef = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

function render() {
  if (!chartRef.value) return
  if (!chart) chart = echarts.init(chartRef.value)
  const option: EChartsOption = {
    animationDuration: 500,
    color: props.series.map((item) => item.color),
    tooltip: { trigger: 'axis', backgroundColor: '#0d1b2f', borderColor: 'rgba(148,163,184,.2)', textStyle: { color: '#e5edf7' } },
    legend: { top: 0, right: 0, textStyle: { color: '#8aa0b8' }, icon: 'roundRect' },
    grid: { top: 42, left: 12, right: 12, bottom: 8, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: props.labels, axisLine: { lineStyle: { color: 'rgba(148,163,184,.16)' } }, axisLabel: { color: '#7e93aa' }, axisTick: { show: false } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: 'rgba(148,163,184,.09)' } }, axisLabel: { color: '#7e93aa', formatter: props.unit ? `{value}${props.unit}` : '{value}' } },
    series: props.series.map((item) => ({
      name: item.name, type: 'line', smooth: true, symbol: 'none', data: item.data,
      lineStyle: { width: 2.5, color: item.color },
      areaStyle: { opacity: .1, color: item.color },
    })),
  }
  chart.setOption(option, true)
}

onMounted(() => { render(); window.addEventListener('resize', render) })
onBeforeUnmount(() => { window.removeEventListener('resize', render); chart?.dispose(); chart = null })
watch(() => [props.labels, props.series], () => nextTick(render), { deep: true })
</script>

<template><div ref="chartRef" class="trend-chart" :style="{ height: `${height}px` }" /></template>

<style scoped>.trend-chart { width: 100%; }</style>
