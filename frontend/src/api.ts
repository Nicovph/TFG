/**
 * api.ts centralizes typed calls from React to the Django API. It keeps session
 * cookies in the browser and never stores OAuth/OIDC tokens.
 */

import type {
  PreferenceKey,
  PreferenceState,
} from './data/preferences'
import type {
  ApiHealth,
  Interpretation,
  InterpretationRequest,
  InterpretationSignalKind,
  SessionStatus,
} from './types'

// Keep this value synchronized with Django's effective CSRF_COOKIE_NAME setting,
// whose default is "csrftoken". Reading it from the static Vite frontend also
// requires CSRF_COOKIE_HTTPONLY and CSRF_USE_SESSIONS to remain false.
const CSRF_COOKIE_NAME = 'csrftoken'

// `as const` preserves each entry as a readonly string literal, allowing this
// tuple to be both the runtime allowlist and the compile-time type source.
const API_ERROR_CODES = [
  'authentication_unavailable',
  'invalid_interpretation_request',
  'invalid_json',
  'unsupported_media_type',
  'authentication_required',
  'permission_denied',
  'method_not_allowed',
  'not_acceptable',
  'interpretation_attempt_rate_limited',
  'duplicate_interpretation_request',
  'interpretation_rate_limited',
  'invalid_provider_response',
  'invalid_interpretation_response',
  'offensive_language_hidden',
  'interpretation_temporarily_unavailable',
  'interpretation_not_configured',
  'interpretation_provider_error',
] as const

// `typeof` obtains the tuple type and `[number]` derives the union of all its
// element types. This compile-time operation emits no JavaScript.
type ApiErrorCode = (typeof API_ERROR_CODES)[number]

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
 * The internal Error.message remains the stable technical code "api_request_failed".
 *
 */
export class ApiError extends Error {
  // `code` groups every API failure; `apiCode` preserves its validated cause.
  readonly code = 'api_request_failed' as const
  readonly apiCode: ApiErrorCode | null
  readonly publicMessage: string | null
  readonly retryAfterSeconds: number | null
  readonly status: number

  /**
   * Create an API error containing only validated safe response details.
   *
   * Args:
   *   status: The HTTP response status returned by the internal API.
   *   apiCode: Validated machine-readable code returned by Django.
   *   publicMessage: Length-bounded message returned by the same-origin API.
   *   retryAfterSeconds: Optional positive delay returned by Django.
   */
  constructor(
    status: number,
    apiCode: ApiErrorCode | null,
    publicMessage: string | null,
    retryAfterSeconds: number | null,
  ) {
    super('api_request_failed')
    this.name = 'ApiError'
    this.apiCode = apiCode
    this.publicMessage = publicMessage
    this.retryAfterSeconds = retryAfterSeconds
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
 * Parse the only safe details retained from a failed internal API response.
 *
 * Args:
 *   response: Non-successful same-origin response returned by Django.
 *
 * Returns:
 *   A closed API code, length-bounded public message, and optional retry delay.
 */
async function parseApiError(response: Response): Promise<ApiError> {
  let apiCode: ApiErrorCode | null = null
  let publicMessage: string | null = null

  try {
    const payload: unknown = await response.json()

    if (isRecord(payload)) {
      // find() retains a known literal code; any unknown server value becomes null.
      apiCode = API_ERROR_CODES.find((code) => code === payload.error) ?? null

      if (
        typeof payload.message === 'string' &&
        payload.message.length <= 300
      ) {
        publicMessage = payload.message
      }
    }
  } catch {
    // An invalid error body is discarded instead of exposing or retaining it.
  }

  const retryAfterHeader = response.headers.get('Retry-After')
  const parsedRetryAfter = retryAfterHeader ? Number(retryAfterHeader) : Number.NaN
  const retryAfterSeconds =
  // Accept only positive safe integers (exactly representable in IEEE-754 double precision).
    Number.isSafeInteger(parsedRetryAfter) && parsedRetryAfter > 0
      ? parsedRetryAfter
      : null

  return new ApiError(
    response.status,
    apiCode,
    publicMessage,
    retryAfterSeconds,
  )
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
    throw await parseApiError(response)
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
    // Keep the health contract closed so deployment metadata is not mistaken for API state.
    Object.keys(payload).length !== 2 ||
    payload.status !== 'ok' ||
    payload.service !== 'django'
  ) {
    throw new Error('invalid_api_health_payload')
  }

  return {
    status: payload.status,
    service: payload.service,
  }
}

const INTERPRETATION_SIGNAL_KINDS = [
  'possible_irony',
  'possible_ambiguity',
  'possible_indirect_language',
  'possible_offensive_language',
  'possible_aggression',
  'possible_cyberbullying',
  // Literal tuple + compile-time check that every value belongs to InterpretationSignalKind.
] as const satisfies readonly InterpretationSignalKind[]

/**
 * Parse and validate the closed pragmatic interpretation returned by Django.
 *
 * Args:
 *   payload: The JSON value returned by the protected interpretation endpoint.
 *
 * Returns:
 *   A camel-cased interpretation safe for React to render as text.
 *
 * Raises:
 *   Error: If the payload contains missing, extra, or invalid fields.
 */
function parseInterpretation(payload: unknown): Interpretation {
  if (
    !isRecord(payload) ||
    Object.keys(payload).length !== 8 ||
    payload.kind !== 'pragmatic_interpretation' ||
    typeof payload.interpretation !== 'string' ||
    typeof payload.clear_reformulation !== 'string' ||
    typeof payload.needs_more_context !== 'boolean' ||
    typeof payload.context_note !== 'string' ||
    !Array.isArray(payload.signals) ||
    !payload.signals.every(
      (signal) =>
        isRecord(signal) &&
        Object.keys(signal).length === 2 &&
        typeof signal.kind === 'string' &&
        INTERPRETATION_SIGNAL_KINDS.includes(
          signal.kind as InterpretationSignalKind,
        ) &&
        typeof signal.explanation === 'string',
    ) ||
    !isStringArray(payload.visual_concepts) ||
    typeof payload.show_content_warning !== 'boolean'
  ) {
    throw new Error('invalid_interpretation_payload')
  }

  return {
    kind: payload.kind,
    interpretation: payload.interpretation,
    clearReformulation: payload.clear_reformulation,
    needsMoreContext: payload.needs_more_context,
    contextNote: payload.context_note,
    signals: payload.signals as Interpretation['signals'],
    visualConcepts: payload.visual_concepts,
    showContentWarning: payload.show_content_warning,
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
 * Request one transient pragmatic interpretation from Django.
 *
 * Args:
 *   request: Bounded text, optional context, speaker relations, and notice state.
 *   signal: Optional abort signal used to cancel an obsolete request.
 *
 * Returns:
 *   The strictly validated interpretation returned by Django.
 */
export async function getInterpretation(
  request: InterpretationRequest,
  signal?: AbortSignal,
): Promise<Interpretation> {
  return parseInterpretation(
    await fetchJson('/api/interpretations/', {
      body: {
        target_message: request.targetMessage,
        previous_context: request.previousContext,
        previous_context_speaker: request.previousContextSpeaker,
        following_context: request.followingContext,
        following_context_speaker: request.followingContextSpeaker,
        external_processing_acknowledged:
          request.externalProcessingAcknowledged,
      },
      csrf: true,
      method: 'POST',
      signal,
    }),
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
