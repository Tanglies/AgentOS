import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '@/views/DashboardView.vue'
import AgentsView from '@/views/AgentsView.vue'
import RunsView from '@/views/RunsView.vue'
import RunDetailView from '@/views/RunDetailView.vue'
import ToolsView from '@/views/ToolsView.vue'
import EvaluationView from '@/views/EvaluationView.vue'
import UsageView from '@/views/UsageView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', name: 'dashboard', component: DashboardView, meta: { title: 'Overview' } },
    { path: '/agents', name: 'agents', component: AgentsView, meta: { title: 'Agents' } },
    { path: '/runs', name: 'runs', component: RunsView, meta: { title: 'Run History' } },
    { path: '/runs/:id', name: 'run-detail', component: RunDetailView, meta: { title: 'Trace' } },
    { path: '/tools', name: 'tools', component: ToolsView, meta: { title: 'Tools' } },
    { path: '/evaluation', name: 'evaluation', component: EvaluationView, meta: { title: 'Evaluation' } },
    { path: '/usage', name: 'usage', component: UsageView, meta: { title: 'Usage' } },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || 'Dashboard')} · AgentOS`
})

export default router
