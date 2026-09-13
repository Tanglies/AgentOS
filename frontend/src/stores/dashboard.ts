import { defineStore } from 'pinia'
import { getOverview, getReliability, getRuns, getUsage } from '@/api/dashboard'
import type { DashboardOverview, DashboardReliability, DashboardUsage, RunSummary } from '@/types'

export const useDashboardStore = defineStore('dashboard', {
  state: () => ({
    overview: null as DashboardOverview | null,
    reliability: null as DashboardReliability | null,
    usage: null as DashboardUsage | null,
    recentRuns: [] as RunSummary[],
    loading: false,
    error: '' as string,
    lastUpdated: '' as string,
  }),
  actions: {
    async refresh() {
      this.loading = true
      this.error = ''
      try {
        const [overview, reliability, usage, runs] = await Promise.all([
          getOverview(), getReliability(), getUsage(), getRuns({ page: 1, page_size: 8 }),
        ])
        this.overview = overview
        this.reliability = reliability
        this.usage = usage
        this.recentRuns = runs.items
        this.lastUpdated = new Date().toISOString()
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Failed to load dashboard'
      } finally {
        this.loading = false
      }
    },
  },
})
