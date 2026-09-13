<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const route = useRoute()
const apiDialog = ref(false)
const apiKeyDraft = ref(app.apiKey)
const nav = [
  { label: 'Overview', path: '/dashboard', glyph: '◈', hint: 'Runtime pulse' },
  { label: 'Agents', path: '/agents', glyph: '◉', hint: 'Active roster' },
  { label: 'Run History', path: '/runs', glyph: '≡', hint: 'Execution log' },
  { label: 'Tools', path: '/tools', glyph: '⌘', hint: 'Tool analytics' },
  { label: 'Evaluation', path: '/evaluation', glyph: '✦', hint: 'Quality signals' },
  { label: 'Usage', path: '/usage', glyph: '◒', hint: 'Resource budget' },
]
const active = computed(() => route.path)
const currentTitle = computed(() => String(route.meta.title || 'Dashboard'))
function saveApiKey() { app.setApiKey(apiKeyDraft.value.trim()); apiDialog.value = false }
</script>

<template>
  <div class="app-shell" :class="{ collapsed: app.sidebarCollapsed }">
    <aside class="sidebar">
      <RouterLink to="/dashboard" class="brand"><span class="brand-mark">AO</span><span class="brand-copy"><strong>AgentOS</strong><small>Observability</small></span></RouterLink>
      <div class="workspace-chip"><span class="status-dot" /> workspace / default</div>
      <nav class="nav-list">
        <RouterLink v-for="item in nav" :key="item.path" :to="item.path" class="nav-item" :class="{ active: active === item.path || route.path.startsWith(`${item.path}/`) }">
          <span class="nav-glyph">{{ item.glyph }}</span><span class="nav-copy"><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <div class="agent-status"><span class="status-dot" /><span><strong>Runtime online</strong><small>Telemetry streaming</small></span></div>
        <button class="key-button" @click="apiDialog = true">API key</button>
      </div>
    </aside>
    <main class="main-area">
      <header class="topbar">
        <div class="topbar-left"><button class="collapse-button" @click="app.toggleSidebar()">☰</button><div><span class="topbar-label">AgentOS / </span><strong>{{ currentTitle }}</strong></div></div>
        <div class="topbar-right"><span v-if="app.demoMode" class="demo-badge">DEMO MODE</span><span class="live-badge"><span class="status-dot" /> live telemetry</span><button class="avatar">AO</button></div>
      </header>
      <div class="content"><RouterView /></div>
    </main>
    <el-dialog v-model="apiDialog" title="Backend API key" width="440px">
      <p class="dialog-copy">Optional when backend auth is enabled. The key is stored only in this browser.</p>
      <el-input v-model="apiKeyDraft" type="password" show-password placeholder="sk-..." />
      <template #footer><el-button @click="apiDialog = false">Cancel</el-button><el-button type="primary" @click="saveApiKey">Save</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.app-shell { display: grid; grid-template-columns: 246px minmax(0, 1fr); min-height: 100vh; transition: grid-template-columns 180ms ease; }
.app-shell.collapsed { grid-template-columns: 76px minmax(0, 1fr); }
.sidebar { display: flex; flex-direction: column; padding: 22px 14px 16px; border-right: 1px solid var(--line); background: rgba(7, 17, 31, .86); backdrop-filter: blur(20px); }
.brand { display: flex; align-items: center; gap: 11px; padding: 0 8px 22px; }
.brand-mark { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 12px; background: linear-gradient(135deg, #2dd4bf, #38bdf8); color: #06111d; font-size: 12px; font-weight: 900; box-shadow: 0 0 24px rgba(45, 212, 191, .24); }
.brand-copy { display: flex; flex-direction: column; gap: 2px; }
.brand-copy strong { letter-spacing: -.03em; }
.brand-copy small, .nav-copy small, .agent-status small { color: var(--muted); font-size: 10px; }
.workspace-chip { display: flex; align-items: center; gap: 7px; margin: 0 6px 20px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px; color: var(--muted); font-family: monospace; font-size: 10px; white-space: nowrap; overflow: hidden; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 12px var(--success); flex: 0 0 auto; }
.nav-list { display: grid; gap: 5px; }
.nav-item { display: flex; align-items: center; gap: 11px; min-height: 48px; padding: 8px 10px; border: 1px solid transparent; border-radius: 12px; color: var(--muted); transition: 160ms ease; }
.nav-item:hover { color: var(--text); background: rgba(148, 163, 184, .06); }
.nav-item.active { color: var(--text); border-color: rgba(45, 212, 191, .18); background: linear-gradient(90deg, rgba(45, 212, 191, .13), rgba(45, 212, 191, .02)); }
.nav-glyph { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 9px; background: rgba(148, 163, 184, .08); color: var(--accent); font-size: 14px; }
.nav-copy { display: flex; flex-direction: column; gap: 2px; white-space: nowrap; overflow: hidden; }
.nav-copy strong { font-size: 13px; font-weight: 620; }
.sidebar-footer { margin-top: auto; display: grid; gap: 12px; padding: 10px 6px 0; border-top: 1px solid var(--line); }
.agent-status { display: flex; gap: 9px; align-items: center; color: var(--muted); font-size: 11px; }
.agent-status span:last-child { display: flex; flex-direction: column; gap: 2px; }
.agent-status strong { color: var(--text); font-weight: 600; }
.key-button { padding: 8px 10px; border: 1px solid var(--line); border-radius: 9px; background: transparent; color: var(--muted); cursor: pointer; text-align: left; }
.key-button:hover { color: var(--text); border-color: rgba(45, 212, 191, .35); }
.main-area { min-width: 0; }
.topbar { display: flex; justify-content: space-between; align-items: center; min-height: 72px; padding: 0 30px; border-bottom: 1px solid var(--line); background: rgba(7, 17, 31, .6); backdrop-filter: blur(18px); }
.topbar-left, .topbar-right { display: flex; align-items: center; gap: 12px; color: var(--muted); font-size: 13px; }
.topbar-left strong { color: var(--text); font-weight: 650; }
.collapse-button { width: 32px; height: 32px; border: 1px solid var(--line); border-radius: 9px; background: transparent; color: var(--muted); cursor: pointer; }
.live-badge, .demo-badge { display: inline-flex; align-items: center; gap: 7px; padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; font-size: 10px; color: var(--muted); }
.demo-badge { color: var(--accent); border-color: rgba(45, 212, 191, .25); background: rgba(45, 212, 191, .07); }
.avatar { width: 31px; height: 31px; border: 0; border-radius: 10px; background: #17344a; color: #bfefff; font-size: 10px; font-weight: 800; }
.content { max-width: 1600px; margin: 0 auto; padding: 30px; }
.dialog-copy { color: var(--muted); line-height: 1.6; }
@media (max-width: 850px) { .app-shell { grid-template-columns: 72px minmax(0, 1fr); } .brand-copy, .workspace-chip, .nav-copy, .sidebar-footer { display: none; } .brand { justify-content: center; padding-left: 0; padding-right: 0; } .nav-item { justify-content: center; padding: 8px 0; } .content { padding: 20px 16px; } .topbar { padding: 0 16px; } }
</style>
