/**
 * useAuthSession.ts manages the frontend view of Django session state without
 * storing profile claims or OAuth/OIDC artifacts.
 */

import { useCallback, useEffect, useState } from 'react'
import { getSessionStatus, logoutSession } from '../api'

export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated' | 'error'
export type LogoutStatus = 'idle' | 'loading' | 'error'

interface AuthSessionHookResult {
  authStatus: AuthStatus
  logoutStatus: LogoutStatus
  clearLogoutError: () => void
  logout: () => Promise<void>
  retrySessionCheck: () => void
  startGoogleLogin: () => void
}

/**
 * Load and update the browser session state exposed by Django.
 *
 * Returns:
 *   Authentication state, logout state, and session action callbacks.
 */
export function useAuthSession(): AuthSessionHookResult {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('checking')
  const [logoutStatus, setLogoutStatus] = useState<LogoutStatus>('idle')
  const [sessionCheckAttempt, setSessionCheckAttempt] = useState(0)

  /**
   * Verification of the session. The AbortController allows the fetch request to be cancelled 
   * if the component unmounts or if a new check is initiated (preventing race conditions).
   * The dependency sessionCheckAttempt allows the reexecution of the verification when 
   * retrySessionCheck is called.
   */
  useEffect(() => {
    const controller = new AbortController()

    getSessionStatus(controller.signal)
      .then((sessionStatus) => {
        setAuthStatus(sessionStatus.authenticated ? 'authenticated' : 'unauthenticated')
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }

        setAuthStatus('error')
      })

    return () => controller.abort()
  }, [sessionCheckAttempt])

  /**
   * Retry the session check while preserving cancellation of obsolete requests.
   *
   * Returns:
   *   Nothing.
   */
  const retrySessionCheck = useCallback(() => {
    setAuthStatus('checking')
    setSessionCheckAttempt((currentAttempt) => currentAttempt + 1)
  }, [])

  const startGoogleLogin = useCallback(() => {
    setAuthStatus('checking')
    window.location.assign('/api/auth/google/start/')
  }, [])

  const clearLogoutError = useCallback(() => {
    setLogoutStatus('idle')
  }, [])

  const logout = useCallback(async () => {
    setLogoutStatus('loading')

    try {
      const sessionStatus = await logoutSession()

      if (sessionStatus.authenticated) {
        throw new Error('logout_failed')
      }

      setAuthStatus('unauthenticated')
      setLogoutStatus('idle')
    } catch (error: unknown) {
      setLogoutStatus('error')
      throw error
    }
  }, [])

  return {
    authStatus,
    logoutStatus,
    clearLogoutError,
    logout,
    retrySessionCheck,
    startGoogleLogin,
  }
}
