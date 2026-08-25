/**
 * api.test.ts verifies the frontend boundary for same-origin Django responses.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getInterpretation,
  getUserPreferences,
  updateUserPreference,
} from './api'

const fetchMock = vi.fn<typeof fetch>()
const preferencePayload = {
  visual_support_enabled: true,
  show_offensive_language: false,
  show_content_warnings: true,
  theme: 'dark',
  interpretation_detail: 'standard',
}

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
})

afterEach(() => {
  document.cookie = 'csrftoken=; Max-Age=0; Path=/'
  vi.unstubAllGlobals()
})

describe('Django API boundary', () => {
  it('sends one CSRF-protected preference field and validates the response', async () => {
    document.cookie = 'csrftoken=test-token; Path=/'
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(preferencePayload), { status: 200 }),
    )

    await expect(updateUserPreference('theme', 'dark')).resolves.toEqual({
      interpretationDetail: 'standard',
      visualSupport: 'enabled',
      offensiveLanguage: 'hidden',
      contentWarnings: 'shown',
      theme: 'dark',
    })
    expect(fetchMock).toHaveBeenCalledWith('/api/preferences/', {
      credentials: 'same-origin',
      body: '{"theme":"dark"}',
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        'X-CSRFToken': 'test-token',
      },
      method: 'PATCH',
      signal: undefined,
    })
  })

  it('rejects unexpected fields in the closed preference response', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ ...preferencePayload, unexpected: 'discard-me' }),
        { status: 200 },
      ),
    )

    await expect(getUserPreferences()).rejects.toThrow(
      'invalid_user_preferences_payload',
    )
  })

  it('keeps only a valid positive Retry-After value from a 429 response', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'Too many requests.' }), {
        status: 429,
        headers: { 'Retry-After': '75' },
      }),
    )

    await expect(getUserPreferences()).rejects.toMatchObject({
      status: 429,
      apiCode: null,
      publicMessage: null,
      retryAfterSeconds: 75,
    })
  })

  it('retains valid text while replacing an invalid visual extension', async () => {
    document.cookie = 'csrftoken=test-token; Path=/'
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          interpretation: 'La frase expresa que llueve mucho.',
          clear_reformulation: 'Está lloviendo mucho.',
          needs_more_context: false,
          context_note: '',
          signals: [],
          visual_concepts: ['lluvia'],
          show_content_warning: false,
          visual_support: {
            status: 'complete',
            items: [
              {
                concept: 'lluvia',
                status: 'available',
                pictogram_id: 123,
                label: 'Lluvia',
                image_url: 'https://example.invalid/untrusted.png',
              },
            ],
            message: '',
            attribution: null,
          },
        }),
        { status: 200 },
      ),
    )

    const interpretation = await getInterpretation(
      {
        targetMessage: 'Está lloviendo a cántaros.',
        previousContext: '',
        previousContextSpeaker: 'unknown',
        followingContext: '',
        followingContextSpeaker: 'unknown',
        externalProcessingAcknowledged: true,
      },
      true,
    )

    expect(interpretation.interpretation).toBe('La frase expresa que llueve mucho.')
    expect(interpretation.visualSupport).toEqual({
      status: 'unavailable',
      items: [{ concept: 'lluvia', status: 'temporarily_unavailable' }],
      message: 'El apoyo visual no está disponible. La interpretación de texto sigue disponible.',
      attribution: null,
    })
  })
})
