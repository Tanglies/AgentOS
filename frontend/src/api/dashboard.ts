import { apiRequest, isDemoMode } from './client'
import {
  mockAgents, mockEvaluationDetails, mockEvaluationRuns, mockEvaluationSummary,
  mockOverview, mockReliability, mockRunDetail, mockRuns, mockToolStats,
  mockTools, mockUsage,
} from './mock'
import type {
  AgentSummary, DashboardOverview, DashboardReliability, DashboardUsage,
  EvaluationRunDetail, EvaluationRunSummary, EvaluationSummary, RunDetail,
  RunSummary, ToolStat, ToolSummary,
} from '@/types'

export interface RunQuery {
  page?: number
  page_size?: number
  agent?: string
  status?: string
  session_id?: string
  order?: 'asc' | 'desc'
}

const wait = (value: unknown, ms = 180) => new Promise((resolve) => window.setTimeout(() => resolve(value), ms))

export async function getOverview(): Promise<DashboardOverview> {
  if (isDemoMode) return wait(mockOverview) as Promise<DashboardOverview>
  return apiRequest<DashboardOverview>('/dashboard/overview')
}

export async function getReliability(): Promise<DashboardReliability> {
  if (isDemoMode) return wait(mockReliability) as Promise<DashboardReliability>
  return apiRequest<DashboardReliability>('/dashboard/reliability')
}

export async function getUsage(): Promise<DashboardUsage> {
  if (isDemoMode) return wait(mockUsage) as Promise<DashboardUsage>
  return apiRequest<DashboardUsage>('/dashboard/usage')
}

export async function getAgents(): Promise<AgentSummary[]> {
  if (isDemoMode) return wait(mockAgents) as Promise<AgentSummary[]>
  const response = await apiRequest<{ items: AgentSummary[] }>('/agents', { page: 1, page_size: 200 })
  return response.items
}

export async function getRuns(query: RunQuery = {}): Promise<{ items: RunSummary[]; total: number }> {
  if (isDemoMode) {
    const page = query.page ?? 1
    const pageSize = query.page_size ?? 20
    const filtered = mockRuns.filter((run) => {
      const matchesAgent = !query.agent || run.agent === query.agent
      const matchesStatus = !query.status || run.status === query.status
      return matchesAgent && matchesStatus
    })
    return wait({ items: filtered.slice((page - 1) * pageSize, page * pageSize), total: filtered.length }) as Promise<{ items: RunSummary[]; total: number }>
  }
  return apiRequest<{ items: RunSummary[]; total: number }>('/runs', {
    page: query.page ?? 1,
    page_size: query.page_size ?? 20,
    agent: query.agent,
    status: query.status,
    session_id: query.session_id,
    order: query.order ?? 'desc',
  })
}

export async function getRunDetail(runId: string): Promise<RunDetail> {
  if (isDemoMode) return wait(mockRunDetail(runId)) as Promise<RunDetail>
  return apiRequest<RunDetail>(`/runs/${encodeURIComponent(runId)}`)
}

export async function getTools(): Promise<ToolSummary[]> {
  if (isDemoMode) return wait(mockTools) as Promise<ToolSummary[]>
  const response = await apiRequest<{ items: ToolSummary[] }>('/tools')
  return response.items
}

export async function getToolStats(): Promise<ToolStat[]> {
  if (isDemoMode) return wait(mockToolStats) as Promise<ToolStat[]>
  const [tools, counts] = await Promise.all([
    getTools(),
    apiRequest<Record<string, number>>('/dashboard/tools', { limit: 500 }),
  ])
  return tools.map((tool) => ({
    name: tool.name,
    calls: counts[tool.name] ?? 0,
    successRate: null,
    averageDuration: null,
    category: tool.category,
    riskLevel: tool.risk_level,
    enabled: tool.enabled,
  }))
}

export async function getEvaluationSummary(): Promise<EvaluationSummary> {
  if (isDemoMode) return wait(mockEvaluationSummary) as Promise<EvaluationSummary>
  return apiRequest<EvaluationSummary>('/evaluation/summary')
}

export async function getEvaluationRuns(): Promise<EvaluationRunSummary[]> {
  if (isDemoMode) return wait(mockEvaluationRuns) as Promise<EvaluationRunSummary[]>
  const response = await apiRequest<{ items: EvaluationRunSummary[] }>('/evaluations', { limit: 100, offset: 0 })
  return response.items
}

export async function getEvaluationDetail(runId: string): Promise<EvaluationRunDetail> {
  if (isDemoMode) return wait(mockEvaluationDetails[runId] ?? Object.values(mockEvaluationDetails)[0]) as Promise<EvaluationRunDetail>
  return apiRequest<EvaluationRunDetail>(`/evaluations/${encodeURIComponent(runId)}`)
}
