import { describe, expect, it } from 'vitest'
import router from './index'

describe('dashboard router', () => {
  it('redirects root to dashboard', async () => {
    await router.push('/')
    await router.isReady()
    expect(router.currentRoute.value.fullPath).toBe('/dashboard')
  })

  it('exposes the observability routes', () => {
    const names = router.getRoutes().map((route) => route.name)
    expect(names).toContain('dashboard')
    expect(names).toContain('agents')
    expect(names).toContain('runs')
    expect(names).toContain('run-detail')
    expect(names).toContain('tools')
    expect(names).toContain('evaluation')
    expect(names).toContain('usage')
  })
})