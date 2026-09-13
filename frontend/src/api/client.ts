const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'
export const isDemoMode = import.meta.env.VITE_DEMO_MODE === 'true'

export class ApiError extends Error {
  readonly status: number
  readonly details?: unknown

  constructor(message: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

export async function apiRequest<T>(
  path: string,
  params?: Record<string, string | number | boolean | null | undefined>,
): Promise<T> {
  const query = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const suffix = query.toString() ? `?${query.toString()}` : ''
  const apiKey = typeof window !== 'undefined' ? window.localStorage.getItem('agentos-api-key') : null
  const response = await fetch(`${API_BASE}${path}${suffix}`, {
    headers: {
      Accept: 'application/json',
      ...(apiKey ? { 'X-API-Key': apiKey } : {}),
    },
  })
  if (!response.ok) {
    const body = await response.text()
    let details: unknown = body
    if (body) {
      try { details = JSON.parse(body) } catch { details = body }
    }
    throw new ApiError(`Request failed: ${response.status}`, response.status, details)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
