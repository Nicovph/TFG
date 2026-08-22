/**
 * useUserPreferences.ts synchronizes the authenticated user's preferences with
 * Django while keeping optimistic UI changes recoverable.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getUserPreferences, updateUserPreference } from '../api'
import {
  DEFAULT_PREFERENCES,
  type PreferenceChangeHandler,
  type PreferenceState,
} from '../data/preferences'
import type { AuthStatus } from './useAuthSession'

export type PreferenceRequestStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'saving'
  | 'load-error'
  | 'save-error'
  | 'rate-limited'

interface UserPreferencesHookResult {
  preferences: PreferenceState
  preferenceRetryAfterSeconds: number | null
  preferenceStatus: PreferenceRequestStatus
  resetPreferences: () => void
  retryPreferences: () => void
  updatePreference: PreferenceChangeHandler
}

/**
 * Load and update preferences owned by the current authenticated session.
 *
 * Args:
 *   authStatus: The current Django session state exposed by the auth hook.
 *
 * Returns:
 *   Preference state, request status, and recoverable update callbacks.
 */
export function useUserPreferences(authStatus: AuthStatus): UserPreferencesHookResult {
  const [preferences, setPreferences] = useState<PreferenceState>(DEFAULT_PREFERENCES)
  const [preferenceStatus, setPreferenceStatus] =
    useState<PreferenceRequestStatus>('idle')
  const [preferenceRetryAfterSeconds, setPreferenceRetryAfterSeconds] =
    useState<number | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const activeRequestRef = useRef<AbortController | null>(null)

  // Re-enable confirmed local preferences when Django's retry window expires.
  useEffect(() => {
    // Nothing to schedule unless we are currently rate-limited.
    if (preferenceStatus !== 'rate-limited' || preferenceRetryAfterSeconds === null) {
      return
    }

    // Resume normal preference updates after Retry-After seconds.
    const timeoutId = window.setTimeout(() => {
      setPreferenceRetryAfterSeconds(null)
      setPreferenceStatus('ready')
    }, preferenceRetryAfterSeconds * 1000)

    // Clear the timer on unmount or dependency change.
    return () => window.clearTimeout(timeoutId)
  }, [preferenceRetryAfterSeconds, preferenceStatus])

  useEffect(() => {
    activeRequestRef.current?.abort()

    if (authStatus !== 'authenticated') {
      activeRequestRef.current = null
      return
    }

    const controller = new AbortController()
    activeRequestRef.current = controller

    getUserPreferences(controller.signal)
      .then((loadedPreferences) => {
        if (controller.signal.aborted) {
          return
        }

        setPreferences(loadedPreferences)
        setPreferenceRetryAfterSeconds(null)
        setPreferenceStatus('ready')
      })
      .catch(() => {
        if (controller.signal.aborted) {
          return
        }

        setPreferenceStatus('load-error')
      })
      .finally(() => {
        if (activeRequestRef.current === controller) {
          activeRequestRef.current = null
        }
      })

    return () => controller.abort()
  }, [authStatus, loadAttempt])

  /**
   * Retry loading the authoritative preference state from Django.
   *
   * Returns:
   *   Nothing.
   */
  const retryPreferences = useCallback(() => {
    if (preferenceStatus === 'rate-limited') return

    setPreferenceRetryAfterSeconds(null)
    setPreferenceStatus('loading')
    setLoadAttempt((currentAttempt) => currentAttempt + 1)
  }, [preferenceStatus])

  /**
   * Remove the previous session's preference values from local React state.
   *
   * Returns:
   *   Nothing.
   */
  const resetPreferences = useCallback(() => {
    activeRequestRef.current?.abort()
    activeRequestRef.current = null
    setPreferences(DEFAULT_PREFERENCES)
    setPreferenceRetryAfterSeconds(null)
    setPreferenceStatus('idle')
  }, [])

  /**
   * Apply one local change immediately and reconcile it with Django.
   *
   * Args:
   *   key: The typed preference field selected by the user.
   *   value: The validated option selected for that field.
   *
   * Returns:
   *   Nothing.
   */
  const updatePreference: PreferenceChangeHandler = useCallback(
    (key, value) => {
      if (authStatus !== 'authenticated' || preferenceStatus !== 'ready') {
        return
      }

      const previousPreferences = preferences
      /**
       * Create new preferences object by copying the previous state and
       * overriding the specific key with the new value.
       * This immutable pattern prevents accidental mutation of state.
       */
      const nextPreferences = {
        ...previousPreferences,
        [key]: value,
      }
      const controller = new AbortController()

      activeRequestRef.current?.abort()
      activeRequestRef.current = controller
      setPreferences(nextPreferences)
      setPreferenceRetryAfterSeconds(null)
      setPreferenceStatus('saving')

      updateUserPreference(key, value, controller.signal)
        .then((savedPreferences) => {
          if (controller.signal.aborted) {
            return
          }

          setPreferences(savedPreferences)
          setPreferenceStatus('ready')
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            return
          }

          setPreferences(previousPreferences)
          const rateLimited = error instanceof ApiError && error.status === 429
          setPreferenceRetryAfterSeconds(
            // The fallback prevents an indefinite lock if an intermediary drops Retry-After.
            rateLimited ? (error.retryAfterSeconds ?? 60) : null,
          )
          setPreferenceStatus(rateLimited ? 'rate-limited' : 'save-error')
        })
        .finally(() => {
          if (activeRequestRef.current === controller) {
            activeRequestRef.current = null
          }
        })
    },
    [authStatus, preferences, preferenceStatus],
  )

  return {
    preferences: authStatus === 'authenticated' ? preferences : DEFAULT_PREFERENCES,
    preferenceRetryAfterSeconds,
    preferenceStatus:
      authStatus === 'authenticated'
        ? preferenceStatus === 'idle'
          ? 'loading'
          : preferenceStatus
        : 'idle',
    resetPreferences,
    retryPreferences,
    updatePreference,
  }
}
