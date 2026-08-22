/**
 * useInterpretationWorkspace.ts owns transient interpretation input, results,
 * cancellation, and the selected ARASAAC pictogram dialog state.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getInterpretation } from '../api'
import type {
  AvailablePictogram,
  ContextSpeakerRelation,
  Interpretation,
  InterpretationRequest,
} from '../types'
import { formatRetryAfter } from '../utils/formatRetryAfter'

// This fixed product contract mirrors Django's combined input limit.
export const MAX_INTERPRETATION_INPUT_LENGTH = 500

// Construct the ECMA-402 segmenter once because every text edit uses it.
// Grapheme boundaries keep perceived characters such as ZWJ emoji sequences intact.
// undefined locale uses the user's default locale.
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, {
  granularity: 'grapheme',
})

export type InterpretationTextField =
  | 'targetMessage'
  | 'previousContext'
  | 'followingContext'
export type ContextSpeakerField =
  | 'previousContextSpeaker'
  | 'followingContextSpeaker'
type InterpretationStatus = 'idle' | 'loading' | 'ready' | 'error'

const EMPTY_REQUEST: InterpretationRequest = {
  targetMessage: '',
  previousContext: '',
  previousContextSpeaker: 'unknown',
  followingContext: '',
  followingContextSpeaker: 'unknown',
  externalProcessingAcknowledged: false,
}

interface InterpretationWorkspaceHookResult {
  canSubmit: boolean
  closeVisualSupport: () => void
  contextExpanded: boolean
  errorMessage: string | null
  errorTitle: string
  interpretation: Interpretation | null
  interpretationStatus: InterpretationStatus
  openVisualSupport: (pictogram: AvailablePictogram) => void
  remainingCharacters: number
  request: InterpretationRequest
  requestInterpretation: (
    externalProcessingAcknowledged: boolean,
    includeVisualSupport: boolean,
  ) => Promise<void>
  resetInterpretationWorkspace: () => void
  selectedPictogram: AvailablePictogram | null
  toggleContext: () => void
  updateAcknowledgment: (acknowledged: boolean) => void
  updateSpeaker: (
    field: ContextSpeakerField,
    relation: ContextSpeakerRelation,
  ) => void
  updateText: (field: InterpretationTextField, value: string) => void
}

/**
 * Count the shared character budget used by the target and both contexts.
 *
 * Args:
 *   request: Current transient interpretation request.
 *
 * Returns:
 *   The number of characters currently entered across all text fields.
 */
function getInputLength(request: InterpretationRequest): number {
  return (
    Array.from(request.targetMessage).length +
    Array.from(request.previousContext).length +
    Array.from(request.followingContext).length
  )
}

/**
 * Truncate text at a grapheme boundary without exceeding Django's code-point budget.
 *
 * Intl.Segmenter groups complete perceived characters, while Array.from(segment)
 * deliberately counts their Unicode code points to match Python's len() contract.
 *
 * Args:
 *   value: NFKC-normalized text to bound.
 *   maximumCodePoints: Remaining shared input capacity.
 *
 * Returns:
 *   The longest leading sequence of complete graphemes within the capacity.
 */
function truncateToCodePointLimit(
  value: string,
  maximumCodePoints: number,
): string {
  let result = ''
  let usedCodePoints = 0

  for (const { segment } of GRAPHEME_SEGMENTER.segment(value)) {
    const segmentCodePoints = Array.from(segment).length

    if (usedCodePoints + segmentCodePoints > maximumCodePoints) break

    result += segment
    usedCodePoints += segmentCodePoints
  }

  return result
}

/**
 * Convert an internal API failure into safe, actionable interface text.
 *
 * Args:
 *   error: Unknown failure raised while requesting an interpretation.
 *
 * Returns:
 *   A Spanish message without provider or implementation details.
 */
function getInterpretationErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const message =
      error.publicMessage ?? 'No se pudo completar la interpretación.'

    return error.retryAfterSeconds
      ? `${message} Espera aproximadamente ${formatRetryAfter(error.retryAfterSeconds)}.`
      : message
  }

  return 'No se pudo obtener una interpretación válida. Inténtalo de nuevo.'
}

/**
 * Keep user-entered text and the validated result only in React memory.
 *
 * Returns:
 *   Bounded request state, result state, and callbacks for the workspace.
 */
export function useInterpretationWorkspace(): InterpretationWorkspaceHookResult {
  const [request, setRequest] = useState<InterpretationRequest>(EMPTY_REQUEST)
  const [contextExpanded, setContextExpanded] = useState(false)
  const [interpretation, setInterpretation] = useState<Interpretation | null>(null)
  const [interpretationStatus, setInterpretationStatus] =
    useState<InterpretationStatus>('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [errorTitle, setErrorTitle] = useState('No se pudo interpretar el mensaje')
  const [selectedPictogram, setSelectedPictogram] =
    useState<AvailablePictogram | null>(null)
  const activeRequestRef = useRef<AbortController | null>(null)

  const remainingCharacters = Math.max(
    0,
    MAX_INTERPRETATION_INPUT_LENGTH - getInputLength(request),
  )
  const canSubmit =
    request.targetMessage.trim().length > 0 &&
    interpretationStatus !== 'loading'

  /** Cancel the active request and invalidate its asynchronous callbacks. */
  const cancelInterpretationRequest = useCallback(() => {
    activeRequestRef.current?.abort()
    activeRequestRef.current = null
  }, [])

  /** Remove output that no longer corresponds to the current request. */
  const discardResult = useCallback(() => {
    cancelInterpretationRequest()
    setInterpretation(null)
    setInterpretationStatus('idle')
    setErrorMessage(null)
    setSelectedPictogram(null)
  }, [cancelInterpretationRequest])

  // Register cancelInterpretationRequest as cleanup so any in-flight request
  // is aborted on unmount or when the cancel function identity changes.
  useEffect(() => cancelInterpretationRequest, [cancelInterpretationRequest])

  /**
   * Update one text field while enforcing the shared backend character limit.
   *
   * Args:
   *   field: Target, previous-context, or following-context property.
   *   value: Latest text received from the associated textarea.
   */
  const updateText = useCallback(
    (field: InterpretationTextField, value: string) => {
      discardResult()
      setRequest((current) => {
        // Match Django's canonical text before applying the shared character budget.
        const normalizedValue = value.replace(/\r\n?/g, '\n').normalize('NFKC')
        const fieldLimit =
          MAX_INTERPRETATION_INPUT_LENGTH -
          getInputLength(current) +
          // Add back this field’s current length so we can fully replace it
          // without double-counting against the shared limit.
          // Array.from counts Unicode code points (avoids splitting surrogate pairs).
          Array.from(current[field]).length
        const boundedValue = truncateToCodePointLimit(normalizedValue, fieldLimit)
        const next = { ...current, [field]: boundedValue }

        if (field === 'previousContext' && boundedValue.trim().length === 0) {
          next.previousContextSpeaker = 'unknown'
        } else if (
          field === 'followingContext' &&
          boundedValue.trim().length === 0
        ) {
          next.followingContextSpeaker = 'unknown'
        }

        return next
      })
    },
    [discardResult],
  )

  /**
   * Update one closed speaker relation and discard its obsolete result.
   *
   * Args:
   *   field: Previous or following speaker-relation property.
   *   relation: Relation to the author of the target message.
   */
  const updateSpeaker = useCallback(
    (field: ContextSpeakerField, relation: ContextSpeakerRelation) => {
      const context =
        field === 'previousContextSpeaker'
          ? request.previousContext
          : request.followingContext

      // The hook must not attach author metadata to an absent optional context.
      if (context.trim().length === 0) return

      discardResult()
      setRequest((current) => ({ ...current, [field]: relation }))
    },
    [discardResult, request.followingContext, request.previousContext],
  )

  /**
   * Update the transient acknowledgment required before external processing.
   *
   * Args:
   *   acknowledged: Whether the user has read the processing notice.
   */
  const updateAcknowledgment = useCallback(
    (acknowledged: boolean) => {
      setRequest((current) => ({
        ...current,
        externalProcessingAcknowledged: acknowledged,
      }))
    },
    [],
  )

  /** Show optional context or remove it explicitly with all of its data. */
  const toggleContext = useCallback(() => {
    if (contextExpanded) {
      discardResult()
      setRequest((current) => ({
        ...current,
        previousContext: '',
        previousContextSpeaker: 'unknown',
        followingContext: '',
        followingContextSpeaker: 'unknown',
      }))
    }

    setContextExpanded((current) => !current)
  }, [contextExpanded, discardResult])

  /**
   * Request the real backend interpretation after the transient notice is accepted.
   *
   * Args:
   *   externalProcessingAcknowledged: Whether the user confirmed the notice
   *     immediately before the first external request in this workspace.
   *   includeVisualSupport: Whether Django should resolve visual concepts in ARASAAC.
   */
  const requestInterpretation = useCallback(async (
    externalProcessingAcknowledged: boolean,
    includeVisualSupport: boolean,
  ) => {
    if (!canSubmit || !externalProcessingAcknowledged) return

    cancelInterpretationRequest()
    const controller = new AbortController()
    activeRequestRef.current = controller
    setInterpretation(null)
    setSelectedPictogram(null)
    setErrorMessage(null)
    setInterpretationStatus('loading')

    try {
      const payload = await getInterpretation(
        { ...request, externalProcessingAcknowledged },
        includeVisualSupport,
        controller.signal,
      )

      if (controller.signal.aborted || activeRequestRef.current !== controller) {
        return
      }

      setInterpretation(payload)
      setInterpretationStatus('ready')
    } catch (error: unknown) {
      if (controller.signal.aborted || activeRequestRef.current !== controller) {
        return
      }

      setErrorTitle(
        error instanceof ApiError && error.status === 429
          ? 'Espera antes de volver a intentarlo'
          : error instanceof ApiError && error.apiCode === 'offensive_language_hidden'
            ? 'No se pudo mostrar la interpretación'
            : 'No se pudo interpretar el mensaje',
      )
      setErrorMessage(getInterpretationErrorMessage(error))
      setInterpretationStatus('error')
    } finally {
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null
      }
    }
  }, [canSubmit, cancelInterpretationRequest, request])

  /** Clear all transient interpretation data after logout or session expiry. */
  const resetInterpretationWorkspace = useCallback(() => {
    cancelInterpretationRequest()
    setRequest(EMPTY_REQUEST)
    setContextExpanded(false)
    setInterpretation(null)
    setInterpretationStatus('idle')
    setErrorMessage(null)
    setSelectedPictogram(null)
  }, [cancelInterpretationRequest])

  /** Open the visual-support dialog for one validated ARASAAC pictogram. */
  const openVisualSupport = useCallback((pictogram: AvailablePictogram) => {
    setSelectedPictogram(pictogram)
  }, [])

  /** Close the enlarged pictogram dialog. */
  const closeVisualSupport = useCallback(() => {
    setSelectedPictogram(null)
  }, [])

  return {
    canSubmit,
    closeVisualSupport,
    contextExpanded,
    errorMessage,
    errorTitle,
    interpretation,
    interpretationStatus,
    openVisualSupport,
    remainingCharacters,
    request,
    requestInterpretation,
    resetInterpretationWorkspace,
    selectedPictogram,
    toggleContext,
    updateAcknowledgment,
    updateSpeaker,
    updateText,
  }
}
