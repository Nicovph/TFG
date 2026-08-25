/**
 * useAuthFlowError.test.tsx verifies trusted authentication error navigation state.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthFlowError } from './useAuthFlowError'

afterEach(() => {
  window.history.replaceState(null, '', '/')
  window.sessionStorage.clear()
  vi.restoreAllMocks()
})

describe('useAuthFlowError', () => {
  it('accepts and consumes a rate-limit fragment from a started login flow', async () => {
    const attempt = renderHook(() => useAuthFlowError('checking'))

    act(() => attempt.result.current.beginAuthAttempt())
    attempt.unmount()
    window.history.replaceState(null, '', '/#auth-rate-limited')

    const { result } = renderHook(() => useAuthFlowError('checking'))

    expect(result.current.authFlowError).toBe('rate-limited')
    await waitFor(() => expect(window.location.hash).toBe(''))
  })

  it('ignores an auth fragment when session storage is unavailable', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Storage unavailable', 'SecurityError')
    })
    window.history.replaceState(null, '', '/#auth-error')

    const { result } = renderHook(() => useAuthFlowError('checking'))

    expect(result.current.authFlowError).toBeNull()
    await waitFor(() => expect(window.location.hash).toBe(''))
  })
})
