/**
 * useInterpretationWorkspace.test.tsx verifies transient interpretation outcomes.
 */

import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getInterpretation } from '../api'
import type { Interpretation } from '../types'
import { useInterpretationWorkspace } from './useInterpretationWorkspace'

vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()

  return {
    ...actual,
    getInterpretation: vi.fn(),
  }
})

const getInterpretationMock = vi.mocked(getInterpretation)
const validInterpretation: Interpretation = {
  interpretation: 'La persona está muy cansada de esa situación.',
  clearReformulation: 'Estoy harto de que Javier cambie de tema.',
  needsMoreContext: false,
  contextNote: '',
  signals: [],
  visualConcepts: [],
  showContentWarning: false,
  visualSupport: null,
}

beforeEach(() => getInterpretationMock.mockReset())

describe('useInterpretationWorkspace', () => {
  it('stores a validated interpretation returned by Django', async () => {
    getInterpretationMock.mockResolvedValueOnce(validInterpretation)
    const { result } = renderHook(useInterpretationWorkspace)

    act(() => result.current.updateText('targetMessage', 'Estoy muy cansado.'))
    await act(() => result.current.requestInterpretation(true, true))

    expect(result.current.interpretationStatus).toBe('ready')
    expect(result.current.interpretation).toEqual(validInterpretation)
    expect(getInterpretationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        targetMessage: 'Estoy muy cansado.',
        externalProcessingAcknowledged: true,
      }),
      true,
      expect.any(AbortSignal),
    )
  })

  it('describes a 429 as a temporary wait with its Retry-After value', async () => {
    getInterpretationMock.mockRejectedValueOnce(
      new ApiError(
        429,
        'interpretation_rate_limited',
        'Has alcanzado temporalmente el límite de interpretaciones.',
        60,
      ),
    )
    const { result } = renderHook(useInterpretationWorkspace)

    act(() => result.current.updateText('targetMessage', 'Interpreta este mensaje.'))
    await act(() => result.current.requestInterpretation(true, false))

    expect(result.current.interpretationStatus).toBe('error')
    expect(result.current.errorTitle).toBe('Espera antes de volver a intentarlo')
    expect(result.current.errorMessage).toContain('1 minuto')
  })
})
