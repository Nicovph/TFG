/**
 * useUserPreferences.test.tsx verifies recoverable preference synchronization.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getUserPreferences, updateUserPreference } from '../api'
import { DEFAULT_PREFERENCES } from '../data/preferences'
import { useUserPreferences } from './useUserPreferences'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()

  return {
    ...actual,
    getUserPreferences: vi.fn(),
    updateUserPreference: vi.fn(),
  }
})

const getUserPreferencesMock = vi.mocked(getUserPreferences)
const updateUserPreferenceMock = vi.mocked(updateUserPreference)
const loadedPreferences = { ...DEFAULT_PREFERENCES, theme: 'light' as const }

beforeEach(() => {
  getUserPreferencesMock.mockReset()
  updateUserPreferenceMock.mockReset()
})

afterEach(() => vi.useRealTimers())

describe('useUserPreferences', () => {
  it('loads preferences and reconciles an optimistic update with Django', async () => {
    const savedPreferences = { ...loadedPreferences, theme: 'dark' as const }
    getUserPreferencesMock.mockResolvedValueOnce(loadedPreferences)
    updateUserPreferenceMock.mockResolvedValueOnce(savedPreferences)
    const { result } = renderHook(() => useUserPreferences('authenticated'))

    await waitFor(() => expect(result.current.preferenceStatus).toBe('ready'))
    act(() => result.current.updatePreference('theme', 'dark'))
    expect(result.current.preferences.theme).toBe('dark')
    expect(result.current.preferenceStatus).toBe('saving')
    await waitFor(() => expect(result.current.preferenceStatus).toBe('ready'))

    expect(result.current.preferences).toEqual(savedPreferences)
    expect(updateUserPreferenceMock).toHaveBeenCalledWith(
      'theme',
      'dark',
      expect.any(AbortSignal),
    )
  })

  it('preserves the rate-limit state until Retry-After expires', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    getUserPreferencesMock.mockResolvedValueOnce(loadedPreferences)
    updateUserPreferenceMock.mockRejectedValueOnce(
      new ApiError(429, null, null, 2),
    )
    const { result } = renderHook(() => useUserPreferences('authenticated'))

    await waitFor(() => expect(result.current.preferenceStatus).toBe('ready'))
    act(() => result.current.updatePreference('theme', 'dark'))
    await waitFor(() => expect(result.current.preferenceStatus).toBe('rate-limited'))

    expect(result.current.preferences).toEqual(loadedPreferences)
    expect(result.current.preferenceRetryAfterSeconds).toBe(2)
    act(() => result.current.retryPreferences())
    expect(getUserPreferencesMock).toHaveBeenCalledTimes(1)

    act(() => vi.advanceTimersByTime(2_000))
    expect(result.current.preferenceStatus).toBe('ready')
    expect(result.current.preferenceRetryAfterSeconds).toBeNull()
  })
})
