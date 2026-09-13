import { defineStore } from 'pinia'
import { isDemoMode } from '@/api/client'

export const useAppStore = defineStore('app', {
  state: () => ({
    sidebarCollapsed: false,
    demoMode: isDemoMode,
    apiKey: typeof window !== 'undefined' ? window.localStorage.getItem('agentos-api-key') || '' : '',
  }),
  actions: {
    toggleSidebar() { this.sidebarCollapsed = !this.sidebarCollapsed },
    setApiKey(value: string) {
      this.apiKey = value
      if (typeof window !== 'undefined') {
        if (value) window.localStorage.setItem('agentos-api-key', value)
        else window.localStorage.removeItem('agentos-api-key')
      }
    },
  },
})
