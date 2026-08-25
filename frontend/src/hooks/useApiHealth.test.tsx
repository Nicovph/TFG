/**
 * useApiHealth.test.tsx verifies non-sensitive Django availability feedback.
 */

import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getApiHealth } from '../api'
import { useApiHealth } from './useApiHealth'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()

  return {
    ...actual,
    getApiHealth: vi.fn(),
  }
})

const getApiHealthMock = vi.mocked(getApiHealth)

beforeEach(() => getApiHealthMock.mockReset())

describe('useApiHealth', () => {
  it('announces a successful Django health check', async () => {
    getApiHealthMock.mockResolvedValueOnce({ status: 'ok', service: 'django' })
    const { result } = renderHook(useApiHealth)

    expect(result.current.apiStatusText).toBe('Comprobando API')
    await waitFor(() => expect(result.current.apiStatusText).toBe('API conectada'))
    expect(result.current.healthError).toBe(false)
  })

  it('announces an unavailable API without exposing the failure', async () => {
    getApiHealthMock.mockRejectedValueOnce(new Error('synthetic_network_failure'))
    const { result } = renderHook(useApiHealth)

    await waitFor(() => expect(result.current.apiStatusText).toBe('API no disponible'))
    expect(result.current.apiHealth).toBeNull()
    expect(result.current.healthError).toBe(true)
  })
})
