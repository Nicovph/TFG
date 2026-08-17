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
  ArasaacAttribution,
  AvailablePictogram,
  Interpretation,
  InterpretationRequest,
  InterpretationSignalKind,
  MissingPictogram,
  SessionStatus,
  VisualSupportResult,
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
 * Check whether an object contains exactly one closed set of keys.
 *
 * Args:
 *   value: Object returned by the same-origin API.
 *   expectedKeys: Complete list of permitted keys.
 *
 * Returns:
 *   True when no key is missing or unexpected; otherwise false.
 */
function hasExactKeys(
  value: Record<string, unknown>,
  expectedKeys: readonly string[],
): boolean {
  return (
    Object.keys(value).length === expectedKeys.length &&
    expectedKeys.every((key) => Object.hasOwn(value, key))
  )
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

const ARASAAC_ATTRIBUTION_TEXT =
  'Autor pictogramas: Sergio Palao. Procedencia: ARASAAC (https://arasaac.org). Licencia: CC (BY-NC-SA). Propiedad: Gobierno de Aragón (España).'
const ARASAAC_TERMS_URL = 'https://arasaac.org/terms-of-use' as const
// Keep the runtime allowlist exhaustive with the public status union.
const VISUAL_SUPPORT_STATUSES = {
  not_requested: true,
  complete: true,
  partial: true,
  unavailable: true,
} satisfies Record<VisualSupportResult['status'], true>

/**
 * Check one normalized string against a closed character budget.
 *
 * Args:
 *   value: Untrusted value returned by Django.
 *   minimum: Smallest accepted string length.
 *   maximum: Largest accepted string length.
 *
 * Returns:
 *   True when the value is a trimmed string inside the limits; otherwise false.
 */
function isBoundedTrimmedString(
  value: unknown,
  minimum: number,
  maximum: number,
): value is string {
  return (
    typeof value === 'string' &&
    value.length >= minimum &&
    value.length <= maximum &&
    value.trim() === value
  )
}

/**
 * Parse one discriminated visual-support item returned by Django.
 *
 * Args:
 *   value: Untrusted available or missing pictogram payload.
 *
 * Returns:
 *   A closed camel-cased pictogram item.
 *
 * Raises:
 *   Error: If the item, identifier, label, or image URL is invalid.
 */
function parseVisualSupportItem(
  value: unknown,
): AvailablePictogram | MissingPictogram {
  if (!isRecord(value) || !isBoundedTrimmedString(value.concept, 1, 64)) {
    throw new Error('invalid_visual_support_payload')
  }

  if (value.status === 'available') {
    if (
      !hasExactKeys(value, [
        'concept',
        'status',
        'pictogram_id',
        'label',
        'image_url',
      ]) ||
      !Number.isSafeInteger(value.pictogram_id) ||
      (value.pictogram_id as number) <= 0 ||
      !isBoundedTrimmedString(value.label, 1, 96) ||
      typeof value.image_url !== 'string'
    ) {
      throw new Error('invalid_visual_support_payload')
    }

    const pictogramId = value.pictogram_id as number
    const imageRoot =
      `https://static.arasaac.org/pictograms/${pictogramId}/${pictogramId}`
    if (
      value.image_url !== `${imageRoot}_300.png` &&
      value.image_url !== `${imageRoot}_plural_300.png`
    ) {
      throw new Error('invalid_visual_support_payload')
    }

    return {
      concept: value.concept,
      status: value.status,
      pictogramId,
      label: value.label,
      imageUrl: value.image_url,
    }
  }

  if (
    (value.status === 'not_found' ||
      value.status === 'temporarily_unavailable') &&
    hasExactKeys(value, ['concept', 'status'])
  ) {
    return { concept: value.concept, status: value.status }
  }

  throw new Error('invalid_visual_support_payload')
}

/**
 * Parse the fixed ARASAAC credit attached to displayed pictograms.
 *
 * Args:
 *   value: Untrusted attribution payload returned by Django.
 *
 * Returns:
 *   The closed camel-cased attribution.
 *
 * Raises:
 *   Error: If the attribution differs from the backend contract.
 */
function parseArasaacAttribution(value: unknown): ArasaacAttribution {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['text', 'terms_url']) ||
    value.text !== ARASAAC_ATTRIBUTION_TEXT ||
    value.terms_url !== ARASAAC_TERMS_URL
  ) {
    throw new Error('invalid_visual_support_payload')
  }

  return { text: value.text, termsUrl: value.terms_url }
}

/**
 * Parse and cross-check the complete visual-support extension.
 *
 * Args:
 *   value: Untrusted extension returned by the interpretation endpoint.
 *   expectedConcepts: Validated concepts that each item must preserve in order.
 *
 * Returns:
 *   A coherent camel-cased result safe for the visual-support components.
 *
 * Raises:
 *   Error: If fields, item tags, summary, message, or attribution disagree.
 */
function parseVisualSupport(
  value: unknown,
  expectedConcepts: readonly string[],
): VisualSupportResult {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ['status', 'items', 'message', 'attribution']) ||
    typeof value.status !== 'string' ||
    !Object.hasOwn(VISUAL_SUPPORT_STATUSES, value.status) ||
    !Array.isArray(value.items) ||
    value.items.length > 10 ||
    !isBoundedTrimmedString(value.message, 0, 140)
  ) {
    throw new Error('invalid_visual_support_payload')
  }

  const items = value.items.map((item) => parseVisualSupportItem(item))
  const availableCount = items.filter((item) => item.status === 'available').length
  const expectedStatus =
    items.length === 0
      ? 'not_requested'
      : availableCount === items.length
        ? 'complete'
        : availableCount > 0
          ? 'partial'
          : 'unavailable'
  const attribution =
    value.attribution === null
      ? null
      : parseArasaacAttribution(value.attribution)
  const requiresMessage =
    expectedStatus === 'partial' || expectedStatus === 'unavailable'

  if (
    items.length !== expectedConcepts.length ||
    items.some((item, index) => item.concept !== expectedConcepts[index]) ||
    value.status !== expectedStatus ||
    Boolean(value.message) !== requiresMessage ||
    Boolean(attribution) !== (availableCount > 0)
  ) {
    throw new Error('invalid_visual_support_payload')
  }

  return {
    status: expectedStatus,
    items,
    message: value.message,
    attribution,
  }
}

/**
 * Parse and validate the closed pragmatic interpretation returned by Django.
 *
 * Args:
 *   payload: The JSON value returned by the protected interpretation endpoint.
 *   includeVisualSupport: Whether the requested contract requires ARASAAC data.
 *
 * Returns:
 *   A camel-cased interpretation safe for React to render as text.
 *
 * Raises:
 *   Error: If the payload contains missing, extra, or invalid fields.
 */
function parseInterpretation(
  payload: unknown,
  includeVisualSupport: boolean,
): Interpretation {
  const expectedKeys = [
    'kind',
    'interpretation',
    'clear_reformulation',
    'needs_more_context',
    'context_note',
    'signals',
    'visual_concepts',
    'show_content_warning',
  ]

  if (
    !isRecord(payload) ||
    // Only the requested visual extension may be absent; base fields stay closed.
    !(
      hasExactKeys(payload, expectedKeys) ||
      (includeVisualSupport &&
        hasExactKeys(payload, [...expectedKeys, 'visual_support']))
    ) ||
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
    !Array.isArray(payload.visual_concepts) ||
    payload.visual_concepts.length > 10 ||
    !payload.visual_concepts.every((concept) =>
      isBoundedTrimmedString(concept, 1, 64),
    ) ||
    typeof payload.show_content_warning !== 'boolean'
  ) {
    throw new Error('invalid_interpretation_payload')
  }

  const visualConcepts = payload.visual_concepts as string[]
  let visualSupport: VisualSupportResult | null = null

  if (includeVisualSupport) {
    try {
      visualSupport = parseVisualSupport(
        payload.visual_support,
        visualConcepts,
      )
    } catch {
      // Discard an untrusted visual extension without losing valid text output.
      const items: MissingPictogram[] = visualConcepts.map((concept) => ({
        concept,
        status: 'temporarily_unavailable',
      }))
      visualSupport = {
        status: items.length > 0 ? 'unavailable' : 'not_requested',
        items,
        message: items.length > 0
          ? 'El apoyo visual no está disponible. La interpretación de texto sigue disponible.'
          : '',
        attribution: null,
      }
    }
  }

  return {
    kind: payload.kind,
    interpretation: payload.interpretation,
    clearReformulation: payload.clear_reformulation,
    needsMoreContext: payload.needs_more_context,
    contextNote: payload.context_note,
    signals: payload.signals as Interpretation['signals'],
    visualConcepts,
    showContentWarning: payload.show_content_warning,
    visualSupport,
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
 *   includeVisualSupport: Whether Django must resolve validated concepts in ARASAAC.
 *   signal: Optional abort signal used to cancel an obsolete request.
 *
 * Returns:
 *   The strictly validated interpretation returned by Django.
 */
export async function getInterpretation(
  request: InterpretationRequest,
  includeVisualSupport: boolean,
  signal?: AbortSignal,
): Promise<Interpretation> {
  const path = includeVisualSupport
    ? '/api/interpretations/?include=visual_support'
    : '/api/interpretations/'

  return parseInterpretation(
    await fetchJson(path, {
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
    includeVisualSupport,
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
