export const formatNumber = (value: number | null | undefined): string =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value ?? 0)

export const formatCompact = (value: number | null | undefined): string =>
  new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value ?? 0)

export const formatPercent = (value: number | null | undefined, digits = 1): string =>
  `${((value ?? 0) * 100).toFixed(digits)}%`

export const formatDuration = (value: number | null | undefined): string => {
  const ms = value ?? 0
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)} s`
  return `${(ms / 60_000).toFixed(1)} min`
}

export const formatDate = (value: string | null | undefined): string => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date)
}

export const formatFullDate = (value: string | null | undefined): string => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export const truncate = (value: string | null | undefined, max = 180): string => {
  const text = value ?? ''
  return text.length <= max ? text : `${text.slice(0, max)}…`
}

export const statusType = (status: string): 'success' | 'danger' | 'warning' | 'info' => {
  if (status === 'completed' || status === 'success' || status === 'passed') return 'success'
  if (status === 'failed' || status === 'error') return 'danger'
  if (status === 'cancelled') return 'warning'
  return 'info'
}

export const sanitizeTraceValue = (value: string | null | undefined, max = 1200): string => {
  if (!value) return ''
  const redacted = value
    .replace(/("?(?:api[_-]?key|token|password|secret|authorization)"?\s*[:=]\s*)"[^"]*"/gi, '$1"[REDACTED]"')
    .replace(/(sk-[A-Za-z0-9_-]{8,})/g, 'sk-[REDACTED]')
  return truncate(redacted, max)
}
