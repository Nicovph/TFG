/**
 * useAuthFlowError.ts manages the non-sensitive, tab-scoped marker used to
 * distinguish backend authentication statuses from arbitrary URL hashes.
 */

import { useCallback, useEffect, useState } from 'react'
import type { AuthStatus } from './useAuthSession'
import {
  readSessionStorage,
  removeSessionStorage,
  writeSessionStorage,
} from '../utils/sessionStorage'

/**
 * This marker records only that the current tab initiated authentication. OAuth
 * state, nonce, PKCE values, codes, and tokens remain exclusively in Django.
 */
const AUTH_ATTEMPT_STORAGE_KEY = 'teaslator.authAttemptPending'
const AUTH_ERROR_FRAGMENT = '#auth-error'
const AUTH_RATE_LIMITED_FRAGMENT = '#auth-rate-limited'

type AuthFlowError = 'authentication-failed' | 'rate-limited' | null

interface AuthFlowErrorHookResult {
  authFlowError: AuthFlowError
  beginAuthAttempt: () => void
  clearAuthFlowState: () => void
}

/**
 * Check for an authentication error produced by a user-initiated flow.
 *
 * Returns:
 *   The recognized error kind only when both its URL fragment and the
 *   current-tab attempt marker are present; otherwise null.
 */
function readAuthFlowError(): AuthFlowError {
  if (typeof window === 'undefined') {
    return null
  }

  if (readSessionStorage(AUTH_ATTEMPT_STORAGE_KEY) !== 'true') {
    return null
  }

  if (window.location.hash === AUTH_ERROR_FRAGMENT) return 'authentication-failed'
  if (window.location.hash === AUTH_RATE_LIMITED_FRAGMENT) return 'rate-limited'

  return null
}

/**
 * Remove a recognized authentication status fragment without reloading the page.
 *
 * Returns:
 *   Nothing. URL cleanup is optional and failures leave the interface usable.
 */
function clearAuthErrorFragment(): void {
  if (
    typeof window === 'undefined' ||
    (window.location.hash !== AUTH_ERROR_FRAGMENT &&
      window.location.hash !== AUTH_RATE_LIMITED_FRAGMENT)
  ) {
    return
  }

  try {
    /**
     * replaceState changes the current URL without adding a history entry. The
     * existing state is preserved for present or future client-side routing.
     * '' is the page title, ignored by most browsers.
     * Reconstructs the URL, keeping only the path and query string while deliberately 
     * removing the hash.
     */
    window.history.replaceState(
      window.history.state,
      '',
      `${window.location.pathname}${window.location.search}`,
    )
  } catch {
    // Removing the display-only fragment must never block authentication recovery.
  }
}

/**
 * Manage the recoverable Google-login error state for the current browser tab.
 *
 * Args:
 *   authStatus: The current Django session state.
 *
 * Returns:
 *   The visible error kind and callbacks to begin or clear an auth attempt.
 */
export function useAuthFlowError(authStatus: AuthStatus): AuthFlowErrorHookResult {
  // The initializer only reads state; fragment and marker consumption happens in an effect.
  const [authFlowError, setAuthFlowError] = useState(readAuthFlowError)

  useEffect(() => {
    if (
      typeof window === 'undefined' ||
      (window.location.hash !== AUTH_ERROR_FRAGMENT &&
        window.location.hash !== AUTH_RATE_LIMITED_FRAGMENT)
    ) {
      return
    }

    removeSessionStorage(AUTH_ATTEMPT_STORAGE_KEY)
    clearAuthErrorFragment()
  }, [])

  useEffect(() => {
    if (authStatus !== 'checking') {
      // A resolved session check ends the short-lived attempt-marker lifecycle.
      removeSessionStorage(AUTH_ATTEMPT_STORAGE_KEY)
    }
  }, [authStatus])

  /**
   * Mark a voluntary login attempt without allowing storage failure to block it.
   * Memoizes the auth initiation handler to maintain referential stability.
   * Prevents unnecessary re-renders in child components that receive this function 
   * as a prop.
   *
   * Returns:
   *   Nothing.
   */
  const beginAuthAttempt = useCallback(() => {
    setAuthFlowError(null)
    writeSessionStorage(AUTH_ATTEMPT_STORAGE_KEY, 'true')
  }, [])

  /**
   * Clear local authentication-flow state after recovery or logout.
   *
   * Returns:
   *   Nothing.
   */
  const clearAuthFlowState = useCallback(() => {
    setAuthFlowError(null)
    removeSessionStorage(AUTH_ATTEMPT_STORAGE_KEY)
  }, [])

  return {
    authFlowError,
    beginAuthAttempt,
    clearAuthFlowState,
  }
}
