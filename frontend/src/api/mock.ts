import type {
  AgentSummary, DashboardOverview, DashboardReliability, DashboardUsage,
  EvaluationRunDetail, EvaluationRunSummary, EvaluationSummary, RunDetail,
  RunSummary, ToolStat, ToolSummary,
} from '@/types'

const now = new Date('2026-09-13T12:00:00+08:00').getTime()
const iso = (minutesAgo: number) => new Date(now - minutesAgo * 60_000).toISOString()

export const mockOverview: DashboardOverview = {
  total_runs: 284,
  success_rate: 0.963,
  average_latency: 1842.6,
  total_tokens: 428_640,
  active_agents: 6,
}

export const mockReliability: DashboardReliability = {
  total_runs: 284,
  tool_calls: 612,
  tool_errors: 17,
  tool_timeouts: 4,
  llm_calls: 531,
  llm_errors: 9,
  max_iteration_runs: 3,
  cancelled_runs: 4,
  timeout_rate: 0.0065,
  tool_error_rate: 0.0278,
  llm_error_rate: 0.0169,
  max_iteration_rate: 0.0106,
  cancelled_rate: 0.0141,
}

export const mockUsage: DashboardUsage = {
  runs: { used: 284, limit: 1000 },
  tokens: { used: 428_640, limit: 1_000_000 },
  requests_per_minute: 60,
  max_iterations_per_run: 8,
  max_tool_calls_per_run: 10,
}

export const mockAgents: AgentSummary[] = [
  { id: 1, name: 'assistant', description: 'General-purpose AgentOS assistant', model: 'qwen3.8-max', tools: ['calculate', 'get_current_time', 'fetch_url', 'remember', 'recall'], created_at: iso(43_200), updated_at: iso(120) },
  { id: 2, name: 'researcher', description: 'Web research and source collection specialist', model: 'qwen3.8-plus', tools: ['web_search', 'fetch_url', 'remember', 'recall'], created_at: iso(25_920), updated_at: iso(380) },
  { id: 3, name: 'code-reviewer', description: 'Reviews code for correctness and maintainability', model: 'qwen3.7-plus', tools: ['read_file', 'search_text', 'list_directory'], created_at: iso(20_160), updated_at: iso(720) },
  { id: 4, name: 'planner', description: 'Breaks complex goals into executable plans', model: 'qwen3.8-max', tools: ['create_plan', 'update_plan_step'], created_at: iso(14_400), updated_at: iso(900) },
  { id: 5, name: 'data-analyst', description: 'Analyzes structured data and summarizes findings', model: 'qwen3.8-flash', tools: ['calculate', 'read_file', 'search_text'], created_at: iso(7_200), updated_at: iso(1_100) },
  { id: 6, name: 'ops-observer', description: 'Inspects runtime reliability and failures', model: 'qwen3.7-plus', tools: ['list_directory', 'read_file', 'recall'], created_at: iso(3_600), updated_at: iso(60) },
]
const runTemplates = [
  ['assistant', 'Calculate the projected cost for 12.4M prompt tokens and 2.1M completion tokens.', 'The estimated cost is based on the configured model pricing map.', 'completed', 2180, 35420, 2],
  ['researcher', 'Collect current best practices for production agent observability.', 'I gathered the key practices and organized them into six themes.', 'completed', 8430, 52180, 3],
  ['code-reviewer', 'Review the latest runtime cancellation change for race conditions.', 'The cancellation path is sound; two edge cases need tests.', 'completed', 3050, 31900, 1],
  ['planner', 'Build a migration plan from SQLite to PostgreSQL.', 'The plan contains five phases with rollback checkpoints.', 'completed', 2740, 28400, 1],
  ['data-analyst', 'Summarize weekly tool usage and identify anomalies.', 'Tool usage increased 18%; fetch_url dominates the growth.', 'completed', 4120, 39110, 2],
  ['assistant', 'Fetch the AgentOS architecture document and summarize it.', 'The architecture separates API, runtime, database and observability.', 'completed', 5660, 47520, 1],
  ['researcher', 'Find recent Model Context Protocol updates.', 'I found four relevant updates and linked the primary sources.', 'completed', 9180, 61420, 4],
  ['ops-observer', 'Inspect the last failed run and identify the likely cause.', 'The failure was caused by an upstream timeout.', 'failed', 15200, 21300, 2],
  ['assistant', 'Remember that the production workspace uses Tokyo timezone.', 'I stored the workspace preference in long-term memory.', 'completed', 1830, 24480, 1],
  ['planner', 'Create a plan for evaluating a new model provider.', 'The plan covers quality, latency, cost and failure handling.', 'completed', 2390, 27760, 1],
  ['researcher', 'Search for changes to OpenAI-compatible tool calling.', 'The specification is stable; one streaming detail changed.', 'completed', 7640, 44900, 3],
  ['code-reviewer', 'Check whether tool timeout preserves contextvars.', 'The new asyncio.timeout implementation preserves context.', 'completed', 2880, 29600, 2],
  ['data-analyst', 'Identify the slowest agent by p95 latency.', 'The researcher Agent has the highest p95 at 9.8s.', 'completed', 3970, 36700, 1],
  ['assistant', 'What happened in the cancelled run?', 'The client disconnected while streaming, so the run was cancelled.', 'cancelled', 4820, 18300, 1],
  ['ops-observer', 'Check the tool timeout rate for this week.', 'Four timeouts were recorded across 612 tool calls.', 'completed', 2460, 25900, 1],
  ['researcher', 'Compare two evaluation datasets and report regressions.', 'The candidate pass rate improved 4.6% with a 120ms latency cost.', 'completed', 6410, 49200, 2],
  ['assistant', 'Summarize all tools currently registered.', 'The registry exposes fourteen tools; run_command is disabled.', 'completed', 1720, 22600, 1],
  ['planner', 'Update the migration plan after rollback review.', 'Two steps were reordered and one rollback gate was added.', 'completed', 2950, 30100, 2],
] as const

export const mockRuns: RunSummary[] = runTemplates.map((template, index) => {
  const [agent, input, output, status, duration, tokens, tools] = template
  return {
    run_id: `run_demo_${String(index + 1).padStart(4, '0')}`,
    workspace_id: 1,
    user_id: 1,
    agent,
    session_id: index % 3 === 0 ? 'default' : `session_${index % 5}`,
    status: status as RunSummary['status'],
    input,
    output,
    error: status === 'failed' ? 'UpstreamTimeout: model provider exceeded 60s' : status === 'cancelled' ? 'cancelled' : null,
    iterations: Math.max(1, tools),
    duration_ms: duration,
    tool_call_count: tools,
    tool_error_count: status === 'failed' ? 1 : 0,
    tool_timeout_count: status === 'failed' ? 1 : 0,
    llm_call_count: tools + 1,
    llm_error_count: status === 'failed' ? 1 : 0,
    memory_recall_count: index % 4 === 0 ? 2 : 0,
    memory_context_chars: index % 4 === 0 ? 480 : 0,
    estimated_cost: tokens * 0.0000042,
    finish_reason: status === 'completed' ? 'stop' : status,
    total_tokens: tokens,
    token_usage: { prompt_tokens: Math.round(tokens * 0.72), completion_tokens: Math.round(tokens * 0.28), total_tokens: tokens },
    created_at: iso(index * 47 + 12),
  }
})
export const mockTools: ToolSummary[] = [
  { name: 'calculate', description: 'Evaluate a safe arithmetic expression.', category: 'general', risk_level: 'low', enabled: true },
  { name: 'get_current_time', description: 'Return the current time for a UTC offset.', category: 'general', risk_level: 'low', enabled: true },
  { name: 'fetch_url', description: 'Fetch a public URL and convert it to text.', category: 'network', risk_level: 'medium', enabled: true },
  { name: 'web_search', description: 'Search the web through a Tavily-compatible API.', category: 'network', risk_level: 'medium', enabled: true },
  { name: 'read_file', description: 'Read a text file inside the workspace sandbox.', category: 'local', risk_level: 'medium', enabled: true },
  { name: 'write_file', description: 'Write a text file inside the workspace sandbox.', category: 'local', risk_level: 'medium', enabled: true },
  { name: 'run_command', description: 'Execute a shell command. Disabled by default.', category: 'local', risk_level: 'high', enabled: false },
  { name: 'remember', description: 'Persist a long-term memory record.', category: 'memory', risk_level: 'low', enabled: true },
  { name: 'recall', description: 'Recall relevant long-term memory.', category: 'memory', risk_level: 'low', enabled: true },
  { name: 'create_plan', description: 'Create an execution plan with ordered steps.', category: 'planning', risk_level: 'low', enabled: true },
  { name: 'update_plan_step', description: 'Update a plan step status.', category: 'planning', risk_level: 'low', enabled: true },
  { name: 'delegate_to_agent', description: 'Delegate a self-contained task to another Agent.', category: 'multi-agent', risk_level: 'medium', enabled: true },
  { name: 'list_directory', description: 'List files in a workspace directory.', category: 'local', risk_level: 'low', enabled: true },
  { name: 'search_text', description: 'Search workspace text using a regular expression.', category: 'local', risk_level: 'medium', enabled: true },
]

const toolCounts: Record<string, number> = { calculate: 176, get_current_time: 92, fetch_url: 118, web_search: 74, read_file: 63, write_file: 21, run_command: 0, remember: 38, recall: 41, create_plan: 29, update_plan_step: 52, delegate_to_agent: 18, list_directory: 34, search_text: 46 }
const toolDurations: Record<string, number> = { calculate: 18, get_current_time: 8, fetch_url: 840, web_search: 1240, read_file: 42, write_file: 35, remember: 22, recall: 48, create_plan: 16, update_plan_step: 14, delegate_to_agent: 1860, list_directory: 28, search_text: 76 }
export const mockToolStats: ToolStat[] = mockTools.map((tool) => ({
  name: tool.name,
  calls: toolCounts[tool.name] ?? 0,
  successRate: tool.enabled ? (tool.risk_level === 'high' ? 0.84 : 0.976) : 0,
  averageDuration: tool.enabled ? toolDurations[tool.name] ?? 120 : null,
  category: tool.category,
  riskLevel: tool.risk_level,
  enabled: tool.enabled,
}))
export const mockEvaluationSummary: EvaluationSummary = {
  runs: 284, succeeded: 273, failed: 11, success_rate: 0.9613,
  average_latency: 1842.6, average_tokens: 1509.3, average_tool_calls: 2.15,
  latency: { avg: 1842.6, p50: 1420.4, p95: 4380.2, max: 15200 },
  tokens: { prompt: 305420, completion: 123220, total: 428640, avg_per_run: 1509.3 },
  tool_calls: { total: 612, avg_per_run: 2.15, max_in_run: 4, runs_with_tools: 198 },
  reliability: mockReliability,
  cost: { total: 1.803, priced_runs: 284 },
}

export const mockEvaluationRuns: EvaluationRunSummary[] = [
  { id: 'eval_demo_0003', dataset_name: 'tool_calling.jsonl', status: 'completed', total_cases: 20, completed_cases: 20, passed_cases: 19, failed_cases: 1, created_at: iso(120), started_at: iso(119), finished_at: iso(114) },
  { id: 'eval_demo_0002', dataset_name: 'safety.jsonl', status: 'completed', total_cases: 20, completed_cases: 20, passed_cases: 20, failed_cases: 0, created_at: iso(1500), started_at: iso(1499), finished_at: iso(1492) },
  { id: 'eval_demo_0001', dataset_name: 'planning.jsonl', status: 'completed', total_cases: 20, completed_cases: 20, passed_cases: 17, failed_cases: 3, created_at: iso(3000), started_at: iso(2999), finished_at: iso(2990) },
]

export const mockEvaluationDetails: Record<string, EvaluationRunDetail> = Object.fromEntries(
  mockEvaluationRuns.map((run, index) => [run.id, {
    ...run,
    dataset_path: `evals/${run.dataset_name}`,
    config: { baseline: index === 1, judge_enabled: false },
    report: { pass_rate: run.passed_cases / run.total_cases, average_score: index === 0 ? 0.972 : 0.946, average_latency: 1830 + index * 90, average_tokens: 1480 + index * 80, estimated_cost: 0.014, priced_cases: 20, reliability: mockReliability },
    results: Array.from({ length: run.total_cases }, (_, caseIndex) => ({
      case_id: `${run.dataset_name.replace('.jsonl', '')}-${String(caseIndex + 1).padStart(3, '0')}`,
      agent: 'assistant', input: `Demo evaluation case ${caseIndex + 1}`,
      output: caseIndex === 0 && index === 0 ? 'The response missed the expected tool call.' : 'The response matched the expected behavior.',
      status: 'completed',
      latency_ms: 1100 + caseIndex * 57,
      token_usage: { prompt_tokens: 820, completion_tokens: 240, total_tokens: 1060 },
      estimated_cost: 0.0000045,
      scores: [
        { metric: 'contains', score: caseIndex === 0 && index === 0 ? 0 : 1, passed: !(caseIndex === 0 && index === 0), applicable: true, reason: 'Output content check' },
        { metric: 'tool_call', score: caseIndex === 0 && index === 0 ? 0 : 1, passed: !(caseIndex === 0 && index === 0), applicable: true, reason: 'Expected tool trajectory' },
      ],
    })),
  }]),
)
export function mockRunDetail(runId: string): RunDetail {
  const run = mockRuns.find((item) => item.run_id === runId) ?? mockRuns[0]
  return {
    ...run,
    prompt_tokens: run.token_usage?.prompt_tokens,
    completion_tokens: run.token_usage?.completion_tokens,
    messages: [
      { role: 'user', content: run.input, created_at: run.created_at },
      {
        role: 'assistant', content: '',
        tool_calls: [{ id: `${run.run_id}-tool-1`, name: run.tool_call_count > 0 ? 'calculate' : 'get_current_time', arguments: '{"expression":"(12 + 8) * 3"}' }],
        created_at: run.created_at,
      },
      { role: 'tool', name: 'calculate', tool_call_id: `${run.run_id}-tool-1`, content: '(12 + 8) * 3 = 60', created_at: run.created_at },
      { role: 'assistant', content: run.output, created_at: run.created_at },
    ],
  }
}