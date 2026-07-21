/**
 * useInterpretationWorkspace.ts owns transient message and mock interpretation
 * state, including cancellation of requests that no longer match the input.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { getMockInterpretation } from '../api'
import type { MockInterpretation } from '../types'

export const MAX_MESSAGE_LENGTH = 500

type InterpretationStatus = 'idle' | 'loading' | 'ready' | 'error'

interface InterpretationWorkspaceHookResult {
  canSubmit: boolean
  closeVisualSupport: () => void
  interpretation: MockInterpretation | null
  interpretationStatus: InterpretationStatus
  message: string
  openVisualSupport: (visualLabel: string) => void
  remainingCharacters: number
  requestInterpretation: () => Promise<void>
  resetInterpretationWorkspace: () => void
  selectedVisualLabel: string | null
  updateMessage: (nextMessage: string) => void
}

/**
 * Keep user-entered text and its current mock result only in React memory.
 *
 * Returns:
 *   Bounded message state, current interpretation state, visual-dialog state,
 *   and callbacks that invalidate obsolete asynchronous work.
 */
export function useInterpretationWorkspace(): InterpretationWorkspaceHookResult {
  /**
   * User text remains in component memory and is never written to browser
   * storage by this hook.
   */
  const [message, setMessage] = useState('')
  const [interpretation, setInterpretation] = useState<MockInterpretation | null>(null)
  const [interpretationStatus, setInterpretationStatus] =
    useState<InterpretationStatus>('idle')
  const [selectedVisualLabel, setSelectedVisualLabel] = useState<string | null>(null)
  const activeRequestRef = useRef<AbortController | null>(null)

  const remainingCharacters = Math.max(0, MAX_MESSAGE_LENGTH - message.length)
  const canSubmit = message.trim().length > 0 && interpretationStatus !== 'loading'

  /**
   * Cancel the active interpretation request and invalidate its callbacks.
   *
   * Returns:
   *   Nothing.
   */
  const cancelInterpretationRequest = useCallback(() => {
    activeRequestRef.current?.abort()
    activeRequestRef.current = null
  }, [])

  useEffect(() => {
    return () => {
      cancelInterpretationRequest()
    }
  }, [cancelInterpretationRequest])

  /**
   * Update bounded input and discard any result associated with older text.
   *
   * Args:
   *   nextMessage: The latest text received from the input component.
   *
   * Returns:
   *   Nothing.
   */
  const updateMessage = useCallback(
    (nextMessage: string) => {
      cancelInterpretationRequest()
      // Returns the entire string if it is less than the maximum size allowed, otherwise truncates it.
      setMessage(nextMessage.slice(0, MAX_MESSAGE_LENGTH))
      setInterpretation(null)
      setInterpretationStatus('idle')
      setSelectedVisualLabel(null)
    },
    [cancelInterpretationRequest],
  )

  /**
   * Request the fixed backend mock and ignore any response invalidated later.
   *
   * Returns:
   *   A promise that resolves after the current request has settled.
   */
  const requestInterpretation = useCallback(async () => {
    if (message.trim().length === 0 || interpretationStatus === 'loading') {
      return
    }

    cancelInterpretationRequest()
    const controller = new AbortController()
    activeRequestRef.current = controller

    // Loading never coexists with a result or visual selection from older text.
    setInterpretation(null)
    setSelectedVisualLabel(null)
    setInterpretationStatus('loading')

    try {
      const payload = await getMockInterpretation(controller.signal)

      /**
       * Check if the current request was aborted or if there is already a newer request.
       */
      if (controller.signal.aborted || activeRequestRef.current !== controller) {
        return
      }

      setInterpretation(payload)
      setInterpretationStatus('ready')
    } catch {
      /**
       * It only flags an error if the current request was not cancelled.
       */
      if (controller.signal.aborted || activeRequestRef.current !== controller) {
        return
      }

      setInterpretationStatus('error')
    } finally {
      if (activeRequestRef.current === controller) {
        activeRequestRef.current = null
      }
    }
  }, [cancelInterpretationRequest, interpretationStatus, message])

  /**
   * Clear all transient interpretation data after logout or session expiry.
   *
   * Returns:
   *   Nothing.
   */
  const resetInterpretationWorkspace = useCallback(() => {
    cancelInterpretationRequest()
    setMessage('')
    setInterpretation(null)
    setInterpretationStatus('idle')
    setSelectedVisualLabel(null)
  }, [cancelInterpretationRequest])

  /**
   * Open visual support for a concept in the current interpretation.
   *
   * Args:
   *   visualLabel: The concept label associated with the dialog.
   *
   * Returns:
   *   Nothing.
   */
  const openVisualSupport = useCallback((visualLabel: string) => {
    setSelectedVisualLabel(visualLabel)
  }, [])

  /**
   * Close the current visual-support dialog.
   *
   * Returns:
   *   Nothing.
   */
  const closeVisualSupport = useCallback(() => {
    setSelectedVisualLabel(null)
  }, [])

  return {
    canSubmit,
    closeVisualSupport,
    interpretation,
    interpretationStatus,
    message,
    openVisualSupport,
    remainingCharacters,
    requestInterpretation,
    resetInterpretationWorkspace,
    selectedVisualLabel,
    updateMessage,
  }
}
