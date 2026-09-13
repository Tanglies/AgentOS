export type RunStatus = 'completed' | 'failed' | 'cancelled' | 'running' | 'queued'

export interface DashboardOverview {
  total_runs: number
  success_rate: number
  average_latency: number
  total_tokens: number
  active_agents: number
}

export interface DashboardReliability {
  total_runs: number
  tool_calls: number
  tool_errors: number
  tool_timeouts: number
  llm_calls: number
  llm_errors: number
  max_iteration_runs: number
  cancelled_runs: number
  timeout_rate: number
  tool_error_rate: number
  llm_error_rate: number
  max_iteration_rate: number
  cancelled_rate: number
}

export interface UsageSection { used: number; limit: number }
export interface DashboardUsage {
  runs: UsageSection
  tokens: UsageSection
  requests_per_minute?: number
  max_iterations_per_run?: number
  max_tool_calls_per_run?: number
}

export interface TokenUsage {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface AgentSummary {
  id?: number | null
  workspace_id?: number
  name: string
  description?: string
  system_prompt?: string | null
  model?: string | null
  temperature?: number | null
  max_iterations?: number | null
  tools?: string[]
  metadata?: Record<string, unknown>
  created_at?: string | null
  updated_at?: string | null
}

export interface RunSummary {
  run_id: string
  workspace_id?: number
  user_id?: number | null
  agent: string
  session_id?: string | null
  status: RunStatus
  input: string
  output: string
  error?: string | null
  iterations: number
  duration_ms: number
  tool_call_count: number
  tool_error_count?: number
  tool_timeout_count?: number
  llm_call_count?: number
  llm_error_count?: number
  memory_recall_count?: number
  memory_context_chars?: number
  estimated_cost?: number | null
  max_iterations_reached?: boolean
  finish_reason?: string | null
  total_tokens?: number
  token_usage?: TokenUsage | null
  created_at: string
}

export interface MessageToolCall {
  id: string
  name: string
  arguments: string
}

export interface RunMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string
  name?: string | null
  tool_call_id?: string | null
  tool_calls?: MessageToolCall[] | null
  metadata?: Record<string, unknown>
  created_at?: string
}

export interface RunDetail extends RunSummary {
  prompt_tokens?: number
  completion_tokens?: number
  messages: RunMessage[]
}

export interface ToolSummary {
  name: string
  description: string
  category: string
  risk_level: 'low' | 'medium' | 'high' | string
  enabled: boolean
  parameters?: Record<string, unknown>
}

export interface ToolStat {
  name: string
  calls: number
  successRate: number | null
  averageDuration: number | null
  category: string
  riskLevel: string
  enabled: boolean
}

export interface EvaluationSummary {
  runs: number
  succeeded: number
  failed: number
  success_rate: number
  average_latency: number
  average_tokens: number
  average_tool_calls: number
  latency?: { avg: number; p50: number; p95: number; max: number }
  tokens?: { prompt: number; completion: number; total: number; avg_per_run: number }
  tool_calls?: { total: number; avg_per_run: number; max_in_run: number; runs_with_tools: number }
  reliability?: Partial<DashboardReliability>
  cost?: { total: number | null; priced_runs: number }
}

export interface EvaluationRunSummary {
  id: string
  dataset_name: string
  status: string
  total_cases: number
  completed_cases: number
  passed_cases: number
  failed_cases: number
  created_at: string
  started_at?: string | null
  finished_at?: string | null
}

export interface EvaluationScore {
  metric: string
  score: number
  passed: boolean
  applicable: boolean
  reason?: string
}

export interface EvaluationResult {
  case_id: string
  agent: string
  input: string
  output: string
  status: string
  error?: string | null
  latency_ms: number
  token_usage?: TokenUsage
  estimated_cost?: number | null
  scores: EvaluationScore[]
}

export interface EvaluationRunDetail extends EvaluationRunSummary {
  dataset_path?: string | null
  config?: Record<string, unknown>
  results: EvaluationResult[]
  report?: Record<string, any> | null
  error?: string | null
}

export interface TraceStep {
  id: string
  type: 'request' | 'runtime' | 'planning' | 'llm' | 'tool' | 'result' | 'answer' | 'error'
  title: string
  subtitle?: string
  content?: string
  status: 'success' | 'error' | 'info' | 'warning'
  duration?: number
  toolName?: string
  arguments?: string
  result?: string
  model?: string
  tokens?: number
}
