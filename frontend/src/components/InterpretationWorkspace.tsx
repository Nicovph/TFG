/**
 * InterpretationWorkspace.tsx renders the message input, mocked interpretation
 * result, and visual support controls.
 */

import type { SubmitEventHandler } from 'react'
import { VISUAL_SUPPORT_DIALOG_ID } from './VisualSupportDialog'
import visuallyHiddenStyles from './VisuallyHidden.module.css'
import styles from './InterpretationWorkspace.module.css'
import type { MockInterpretation } from '../types'

interface InterpretationWorkspaceProps {
  canSubmit: boolean // If the send button should be enabled.
  interpretation: MockInterpretation | null
  interpretationStatus: 'idle' | 'loading' | 'ready' | 'error'
  logoSrc: string
  maxMessageLength: number
  message: string
  remainingCharacters: number
  showVisualSupport: boolean
  onVisualSupportOpen: (visualLabel: string) => void
  onMessageChange: (message: string) => void
  onSubmit: SubmitEventHandler<HTMLFormElement>
}

/**
 * Render the interpretation workspace and keep user text local to the browser.
 *
 * Args:
 *   props: Message state, mock result state, and interaction callbacks.
 *
 * Returns:
 *   The main interpretation workspace.
 */
export function InterpretationWorkspace({
  canSubmit,
  interpretation,
  interpretationStatus,
  logoSrc,
  maxMessageLength,
  message,
  remainingCharacters,
  showVisualSupport,
  onVisualSupportOpen,
  onMessageChange,
  onSubmit,
}: InterpretationWorkspaceProps) {
  return (
    <section className={styles.workspace} aria-labelledby="workspace-title">
      <img className={styles.workspaceMark} src={logoSrc} width="92" height="92" alt="" />
      {/* // Hidden title for screen readers. */}
      <h1 className={visuallyHiddenStyles.visuallyHidden} id="workspace-title">
        Interpretación de mensajes
      </h1>

      <form className={styles.messageForm} onSubmit={onSubmit}>
        <div className={styles.modeControls} aria-label="Modo de entrada">
          <button
            type="button"
            className={`${styles.modeButton} ${styles.active}`}
            aria-pressed="true"
          >
            <span aria-hidden="true" className={styles.textModeIcon}>
              A<sub>b</sub>
            </span>
            Texto
          </button>
        </div>

        <div className={styles.workGrid}>
          <div className={styles.inputPanel}>
            <label className={visuallyHiddenStyles.visuallyHidden} htmlFor="message-input">
              Texto a interpretar
            </label>
            {/* // Permits multi-line input for the message to be interpreted. */}
            <textarea
              id="message-input"
              value={message}
              maxLength={maxMessageLength}
              onChange={(event) => onMessageChange(event.target.value)}
              placeholder="Añadir texto aquí."
              rows={8}
            />
            {/* // Specifies the number of visible text lines. */}
            <span className={styles.characterCount} aria-live="polite">
              {remainingCharacters}
            </span>
          </div>

          {/* // section groups related content */}
          <section className={styles.resultPanel} aria-live="polite" aria-label="Interpretación">
            {interpretationStatus === 'loading' ? (
              <p>Interpretando.</p>
            ) : interpretationStatus === 'error' ? (
              <p>No se pudo obtener la respuesta simulada.</p>
            ) : interpretation ? (
              <div className={styles.resultContent}>
                <p>{interpretation.summary}</p>
                <ul>
                  {/* // .map converts each signal in a <li>. */}
                  {interpretation.signals.map((signal) => (
                    /* // key is required for React to track list items efficiently. */
                    <li key={signal}>{signal}</li>
                  ))}
                </ul>
                {showVisualSupport ? (
                  <div className={styles.conceptList} aria-label="Conceptos visuales">
                    {/* // .map converts each visual concept into a button. */}
                    {interpretation.visualConcepts.map((concept) => (
                      <button
                        type="button"
                        key={concept}
                        aria-controls={VISUAL_SUPPORT_DIALOG_ID}
                        aria-haspopup="dialog"
                        onClick={() => onVisualSupportOpen(concept)}
                      >
                        {concept}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (
              <p>Interpretación.</p>
            )}
          </section>
        </div>

        <button className={styles.submitButton} type="submit" disabled={!canSubmit}>
          ENVIAR
        </button>
      </form>
    </section>
  )
}
