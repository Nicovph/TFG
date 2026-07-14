/**
 * api.ts centralizes typed calls from React to the Django API. It keeps session
 * cookies in the browser and never stores OAuth/OIDC tokens.
 */

import type { ApiHealth, MockInterpretation, SessionStatus } from './types'

interface ApiRequestOptions {
  /**
   * Indicate whether the request needs to include the CSRF token.
   */
  csrf?: boolean
  method?: 'GET' | 'POST'
  signal?: AbortSignal
}

/**
 * Check whether a value is a plain object record.
 *
 * Args:
 *   value: The value returned by JSON parsing.
 *
 * Returns:
 *   True when the value is an object record (an 
 *   object with string keys and unknown values); otherwise false.
 */
function isRecord(value: unknown): value is Record<string, unknown> {
  /**
   * It is confirmed not to be an array because it is also of type 'object'.
   */
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Check whether a value is an array of strings.
 *
 * Args:
 *   value: The value returned by JSON parsing.
 *
 * Returns:
 *   True when every array item is a string; otherwise false.
 */
function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

/**
 * Read a named cookie value using the browser cookie API.
 *
 * Args:
 *   name: The cookie name to look up.
 *
 * Returns:
 *   The decoded cookie value, or null when it is absent.
 */
function readCookie(name: string): string | null {
  const cookiePrefix = `${name}=`
  /**
   * document.cookie returns all cookie as a single string seprated by ';' and split convert it into an array of parts.
   */
  const cookieParts = document.cookie.split(';')

  for (const cookiePart of cookieParts) {
    const trimmedCookie = cookiePart.trim()

    if (trimmedCookie.startsWith(cookiePrefix)) {
      try {
        /**
         * decodeURIComponent decodes special characters (%20, %2F, etc.) that can be in the cookie value.
         * slice extracts the value after the '='.
         */
        return decodeURIComponent(trimmedCookie.slice(cookiePrefix.length))
        /**
         * If malformed cookie, the decodification failed.
         */
      } catch {
        return null
      }
    }
  }

  return null
}

/**
 * Read Django's CSRF cookie for unsafe same-origin requests.
 *
 * Returns:
 *   The CSRF token value emitted by Django.
 *
 * Raises:
 *   Error: If the CSRF cookie is unavailable.
 */
function getCsrfToken(): string {
  const token = readCookie('csrftoken')

  if (!token) {
    throw new Error('csrf_token_missing')
  }

  return token
}

/**
 * Fetch JSON from an internal API endpoint with safe defaults.
 *
 * Args:
 *   path: The relative API path.
 *   options: HTTP method, CSRF, and abort settings.
 *
 * Returns:
 *   The parsed JSON payload as an unknown value.
 *
 * Raises:
 *   DOMException: If reading the response is cancelled through AbortController.
 *   Error: If the response status is unsuccessful or its body is not valid JSON.
 */
async function fetchJson(path: string, options: ApiRequestOptions = {}): Promise<unknown> {
  /**
   * Declares that the client expects a JSON response.
   */
  const headers: Record<string, string> = {
    Accept: 'application/json',
  }

  if (options.csrf) {
    headers['X-CSRFToken'] = getCsrfToken()
  }

  const response = await fetch(path, {
    /**
     * The browser must send cookies only when the request is from the same origin.
     */
    credentials: 'same-origin',
    headers,
    /**
     * If no method is provided, it uses GET.
     */
    method: options.method ?? 'GET',
    signal: options.signal,
  })

  if (!response.ok) {
    throw new Error('api_request_failed')
  }

  try {
    return await response.json()
  } catch (error: unknown) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error
    }

    /**
     * The { cause: error } option stores the original error as the cause, which is very helpful when debugging.
     */
    throw new Error('invalid_json_response', { cause: error })
  }
}

/**
 * Parse and validate the API health payload.
 *
 * Args:
 *   payload: The JSON value returned by Django.
 *
 * Returns:
 *   A typed API health object.
 *
 * Raises:
 *   Error: If the payload shape is not the expected contract.
 */
function parseApiHealth(payload: unknown): ApiHealth {
  if (
    !isRecord(payload) ||
    payload.status !== 'ok' ||
    payload.service !== 'django' ||
    typeof payload.api_version !== 'string' ||
    !isStringArray(payload.features)
  ) {
    throw new Error('invalid_api_health_payload')
  }

  return {
    status: payload.status,
    service: payload.service,
    apiVersion: payload.api_version,
    features: payload.features,
  }
}

/**
 * Parse and validate the mock interpretation payload.
 *
 * Args:
 *   payload: The JSON value returned by Django.
 *
 * Returns:
 *   A typed mock interpretation object.
 *
 * Raises:
 *   Error: If the payload shape is not the expected contract.
 */
function parseMockInterpretation(payload: unknown): MockInterpretation {
  if (
    !isRecord(payload) ||
    payload.kind !== 'mock_interpretation' ||
    typeof payload.summary !== 'string' ||
    typeof payload.tone !== 'string' ||
    !isStringArray(payload.signals) ||
    !isStringArray(payload.visual_concepts)
  ) {
    throw new Error('invalid_mock_interpretation_payload')
  }

  return {
    kind: payload.kind,
    summary: payload.summary,
    tone: payload.tone,
    signals: payload.signals,
    visualConcepts: payload.visual_concepts,
  }
}

/**
 * Parse and validate the minimized session status payload.
 *
 * Args:
 *   payload: The JSON value returned by Django.
 *
 * Returns:
 *   A typed session status object.
 *
 * Raises:
 *   Error: If the payload shape is not the expected contract.
 */
function parseSessionStatus(payload: unknown): SessionStatus {
  if (!isRecord(payload) || typeof payload.authenticated !== 'boolean') {
    throw new Error('invalid_session_status_payload')
  }

  return {
    authenticated: payload.authenticated,
  }
}

/**
 * Load non-sensitive health metadata from Django.
 *
 * Args:
 *   signal: Optional abort signal used to cancel obsolete requests.
 *
 * Returns:
 *   A typed API health object.
 */
export async function getApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  return parseApiHealth(await fetchJson('/api/health/', { signal }))
}

/**
 * Load a fixed simulated interpretation from Django.
 *
 * Returns:
 *   A typed mock interpretation object.
 */
export async function getMockInterpretation(): Promise<MockInterpretation> {
  return parseMockInterpretation(await fetchJson('/api/interpretations/mock/'))
}

/**
 * Load the minimized Django session status for the current browser.
 *
 * Args:
 *   signal: Optional abort signal used to cancel obsolete requests.
 *
 * Returns:
 *   Whether the browser has an authenticated Django session.
 */
/**
 * export makes the function public so it can be used from other files.
 */
export async function getSessionStatus(signal?: AbortSignal): Promise<SessionStatus> {
  /**
   * Checks if the browser has a valid Django session.
   */
  return parseSessionStatus(await fetchJson('/api/auth/session/', { signal }))
}

/**
 * End the current Django session through a CSRF-protected POST.
 *
 * Returns:
 *   The minimized post-logout session status returned by Django.
 */
export async function logoutSession(): Promise<SessionStatus> {
  return parseSessionStatus(
    await fetchJson('/api/auth/logout/', {
      /**
       * csrf demonstrates that the POST originates from the legitimate application.
       */
      csrf: true,
      method: 'POST',
    }),
  )
}
