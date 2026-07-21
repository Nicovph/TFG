/**
 * useApiHealth.ts centralizes the initial React-Django connectivity check.
 */

import { useEffect, useMemo, useState } from 'react' // useMemo is used to memoize the status text.
import { getApiHealth } from '../api'
import type { ApiHealth } from '../types'

interface ApiHealthHookResult {
  apiHealth: ApiHealth | null
  apiStatusText: string
  healthError: boolean
}

/**
 * Load non-sensitive health metadata and expose display-ready status state.
 *
 * Returns:
 *   API health data, status copy, and an error flag.
 */
export function useApiHealth(): ApiHealthHookResult {
  const [apiHealth, setApiHealth] = useState<ApiHealth | null>(null)
  const [healthError, setHealthError] = useState(false)

  useEffect(() => {
    const controller = new AbortController() // AbortController is used to cancel the fetch request if the component unmounts before the request completes.

    getApiHealth(controller.signal)
      .then((payload) => { // If the request is successful, update the state with the API health data and reset the error flag.
        setApiHealth(payload)
        setHealthError(false)
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return
        }

        setHealthError(true)
      })

    return () => controller.abort()
  }, [])

  const apiStatusText = useMemo(() => {
    if (apiHealth?.status === 'ok') {
      return 'API conectada'
    }

    if (healthError) {
      return 'API no disponible'
    }

    return 'Comprobando API'
  }, [apiHealth?.status, healthError]) // The useMemo hook is used to memoize the status text, so it only recalculates when apiHealth.status or healthError changes.

  return {
    apiHealth,
    apiStatusText,
    healthError,
  }
}
