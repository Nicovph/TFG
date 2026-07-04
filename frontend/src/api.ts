/**
 * api.ts centralizes typed calls from React to the Django API. Is the
 * save HTTP client.
 */

import type { ApiHealth, MockInterpretation } from './types'

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
 * Fetch JSON from an internal API endpoint with safe defaults.
 *
 * Args:
 *   path: The relative API path.
 *   signal: Optional abort signal used to cancel obsolete requests.
 *
 * Returns:
 *   The parsed JSON payload as an unknown value.
 *
 * Raises:
 *   Error: If the response status is not successful.
 */
async function fetchJson(path: string, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json', // Expects JSON responses from Django.
    },
    signal,
  })

  if (!response.ok) {
    throw new Error('api_request_failed')
  }

  return response.json()
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
 * Load non-sensitive health metadata from Django.
 *
 * Args:
 *   signal: Optional abort signal used to cancel obsolete requests.
 *
 * Returns:
 *   A typed API health object.
 */
export async function getApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  return parseApiHealth(await fetchJson('/api/health/', signal))
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
