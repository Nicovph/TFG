/**
 * api.ts centralizes typed calls from React to the Django API. It keeps session
 * cookies in the browser and never stores OAuth/OIDC tokens.
 */

import type {
  PreferenceKey,
  PreferenceState,
} from './data/preferences'
import type { ApiHealth, MockInterpretation, SessionStatus } from './types'

// Keep this value synchronized with Django's effective CSRF_COOKIE_NAME setting,
// whose default is "csrftoken". Reading it from the static Vite frontend also
// requires CSRF_COOKIE_HTTPONLY and CSRF_USE_SESSIONS to remain false.
const CSRF_COOKIE_NAME = 'csrftoken'

interface ApiRequestOptions {
  /**
   * It is the HTTP body for preferences update.
   */
  body?: unknown
  /**
   * Indicate whether the request needs to include the CSRF token.
   */
  csrf?: boolean
  method?: 'GET' | 'PATCH' | 'POST'
  signal?: AbortSignal
}

/**
 * Represent a non-successful HTTP response without retaining response details.
 */
export class ApiError extends Error {
  readonly code = 'api_request_failed' as const
  readonly status: number

  /**
   * Create an API error containing only a safe code and HTTP status.
   *
   * Args:
   *   status: The HTTP response status returned by the internal API.
   */
  constructor(status: number) {
    super('api_request_failed')
    this.name = 'ApiError'
    this.status = status
  }
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
   * It is confirmed not to be an array because they are also of type 'object'.
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
   * document.cookie returns all cookies as a single string separated by ';' and split convert it into an array of parts.
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
         * If malformed cookie, the decoding failed.
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
  const token = readCookie(CSRF_COOKIE_NAME)

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
 *   ApiError: If the response status is unsuccessful.
 *   Error: If the response body is not valid JSON.
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

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }

  const response = await fetch(path, {
    /**
     * The browser must send cookies only when the request is from the same origin.
     */
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    headers,
    /**
     * If no method is provided, it uses GET.
     */
    method: options.method ?? 'GET',
    signal: options.signal,
  })

  if (!response.ok) {
    throw new ApiError(response.status)
  }

  try {
    /**
     * Converts the body of an HTTP response from JSON format to a JavaScript object.
     */
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
 * Parse and validate the minimized user preference payload.
 *
 * Args:
 *   payload: The JSON value returned by Django.
 *
 * Returns:
 *   The frontend preference representation.
 *
 * Raises:
 *   Error: If the payload contains missing, extra, or invalid fields.
 */
function parseUserPreferences(payload: unknown): PreferenceState {
  const expectedKeys = [
    'visual_support_enabled',
    'show_offensive_language',
    'show_content_warnings',
    'theme',
    'interpretation_detail',
  ] as const

  if (
    !isRecord(payload) ||
    Object.keys(payload).length !== expectedKeys.length ||
    !expectedKeys.every((key) => key in payload) ||
    typeof payload.visual_support_enabled !== 'boolean' ||
    typeof payload.show_offensive_language !== 'boolean' ||
    typeof payload.show_content_warnings !== 'boolean' ||
    (payload.theme !== 'light' && payload.theme !== 'dark' && payload.theme !== 'system') ||
    (payload.interpretation_detail !== 'brief' &&
      payload.interpretation_detail !== 'standard' &&
      payload.interpretation_detail !== 'detailed')
  ) {
    throw new Error('invalid_user_preferences_payload')
  }

  return {
    interpretationDetail: payload.interpretation_detail,
    visualSupport: payload.visual_support_enabled ? 'enabled' : 'disabled',
    offensiveLanguage: payload.show_offensive_language ? 'shown' : 'hidden',
    contentWarnings: payload.show_content_warnings ? 'shown' : 'hidden',
    theme: payload.theme,
  }
}

/**
 * For each key, define exactly which partial object will be sent to the backend.
 */
type PreferencePatchByKey = {
  interpretationDetail: {
    interpretation_detail: PreferenceState['interpretationDetail']
  }
  visualSupport: { visual_support_enabled: boolean }
  offensiveLanguage: { show_offensive_language: boolean }
  contentWarnings: { show_content_warnings: boolean }
  theme: { theme: PreferenceState['theme'] }
}

/**
 * A utility type representing any single-preference patch.
 */
type PreferencePatch = PreferencePatchByKey[PreferenceKey]

/**
 * A type that requires a serialization function for each preference key.
 */
type PreferenceSerializerMap = {
  [K in PreferenceKey]: (value: PreferenceState[K]) => PreferencePatchByKey[K]
}

/**
 * Serialize every supported UI preference into its one-field API patch.
 *
 * Each callback is contextually typed from the same preference key. Requiring
 * every key in the mapped type makes additions to PreferenceState fail to
 * compile until their serializer is implemented.
 */
const PREFERENCE_SERIALIZERS: PreferenceSerializerMap = {
  interpretationDetail: (value) => ({ interpretation_detail: value }),
  visualSupport: (value) => ({ visual_support_enabled: value === 'enabled' }),
  offensiveLanguage: (value) => ({ show_offensive_language: value === 'shown' }),
  contentWarnings: (value) => ({ show_content_warnings: value === 'shown' }),
  theme: (value) => ({ theme: value }),
}

/**
 * Convert one typed UI preference into the corresponding API field.
 *
 * Args:
 *   key: The preference selected by the user.
 *   value: The validated UI value for that preference.
 *
 * Returns:
 *   A one-field partial update payload using backend field names.
 */
function serializePreferenceChange<K extends PreferenceKey>(
  key: K,
  value: PreferenceState[K],
): PreferencePatch {
  return PREFERENCE_SERIALIZERS[key](value)
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
 * Args:
 *   signal: Optional abort signal used to cancel an obsolete request.
 *
 * Returns:
 *   A typed mock interpretation object.
 */
export async function getMockInterpretation(signal?: AbortSignal): Promise<MockInterpretation> {
  return parseMockInterpretation(
    await fetchJson('/api/interpretations/mock/', { signal }),
  )
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
 * Load the authenticated user's minimized preference set.
 *
 * Args:
 *   signal: Optional abort signal used to cancel obsolete requests.
 *
 * Returns:
 *   The validated frontend preference state.
 */
export async function getUserPreferences(signal?: AbortSignal): Promise<PreferenceState> {
  return parseUserPreferences(await fetchJson('/api/preferences/', { signal }))
}

/**
 * Persist one preference for the authenticated Django session.
 *
 * Args:
 *   key: The typed frontend preference key.
 *   value: The validated value selected by the user.
 *   signal: Optional abort signal used to cancel an obsolete update.
 *
 * Returns:
 *   The complete validated preference state returned by Django.
 */
export async function updateUserPreference<K extends PreferenceKey>(
  key: K,
  value: PreferenceState[K],
  signal?: AbortSignal,
): Promise<PreferenceState> {
  return parseUserPreferences(
    await fetchJson('/api/preferences/', {
      body: serializePreferenceChange(key, value),
      csrf: true,
      method: 'PATCH',
      signal,
    }),
  )
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
       * Include Django's CSRF token for this unsafe same-origin request.
       */
      csrf: true,
      method: 'POST',
    }),
  )
}
