/**
 * useAuthSession.test.tsx verifies recoverable Django session state transitions.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getSessionStatus, logoutSession } from '../api'
import { useAuthSession } from './useAuthSession'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()

  return {
    ...actual,
    getSessionStatus: vi.fn(),
    logoutSession: vi.fn(),
  }
})

const getSessionStatusMock = vi.mocked(getSessionStatus)
const logoutSessionMock = vi.mocked(logoutSession)

beforeEach(() => {
  getSessionStatusMock.mockReset()
  logoutSessionMock.mockReset()
})

describe('useAuthSession', () => {
  it('recovers from a failed session check when the user retries', async () => {
    getSessionStatusMock
      .mockRejectedValueOnce(new Error('network_failure'))
      .mockResolvedValueOnce({ authenticated: false })
    const { result } = renderHook(useAuthSession)

    await waitFor(() => expect(result.current.authStatus).toBe('error'))
    act(() => result.current.retrySessionCheck())
    expect(result.current.authStatus).toBe('checking')
    await waitFor(() => expect(result.current.authStatus).toBe('unauthenticated'))
  })

  it('exposes an unauthenticated session only after Django confirms logout', async () => {
    getSessionStatusMock.mockResolvedValueOnce({ authenticated: true })
    logoutSessionMock.mockResolvedValueOnce({ authenticated: false })
    const { result } = renderHook(useAuthSession)

    await waitFor(() => expect(result.current.authStatus).toBe('authenticated'))
    await act(() => result.current.logout())

    expect(result.current.authStatus).toBe('unauthenticated')
    expect(result.current.logoutStatus).toBe('idle')
  })
})
