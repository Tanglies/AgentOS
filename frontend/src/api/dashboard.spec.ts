import { beforeEach, describe, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

describe('dashboard api', () => {
  it('uses demo data when VITE_DEMO_MODE is true', async () => {
    vi.stubEnv('VITE_DEMO_MODE', 'true')
    const { getOverview } = await import('./dashboard')
    const overview = await getOverview()
    expect(overview.total_runs).toBeGreaterThan(0)
    expect(overview.active_agents).toBe(6)
  })

  it('reads a non-json error body exactly once', async () => {
    vi.stubEnv('VITE_DEMO_MODE', 'false')
    const fetchMock = vi.fn().mockResolvedValue(new Response('Unauthorized', { status: 401 }))
    vi.stubGlobal('fetch', fetchMock)
    const { apiRequest } = await import('./client')
    await expect(apiRequest('/private')).rejects.toMatchObject({ status: 401, details: 'Unauthorized' })
  })

  it('sends auth header through the shared api client', async () => {
    vi.stubEnv('VITE_DEMO_MODE', 'false')
    window.localStorage.setItem('agentos-api-key', 'sk-test')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetchMock)
    const { apiRequest } = await import('./client')
    await apiRequest('/health')
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/health', expect.objectContaining({ headers: expect.objectContaining({ 'X-API-Key': 'sk-test' }) }))
  })
})