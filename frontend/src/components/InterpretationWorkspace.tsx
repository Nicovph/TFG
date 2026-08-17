/**
 * InterpretationWorkspace.tsx renders the transient interpretation form,
 * validated result, and optional ARASAAC visual support.
 */

import { useEffect, useRef } from 'react'
import type {
  AvailablePictogram,
  ContextSpeakerRelation,
  Interpretation,
  InterpretationRequest,
  InterpretationSignalKind,
} from '../types'
import type {
  ContextSpeakerField,
  InterpretationTextField,
} from '../hooks/useInterpretationWorkspace'
import type { PreferenceRequestStatus } from '../hooks/useUserPreferences'
import { VisualSupport } from './VisualSupport'
import visuallyHiddenStyles from './VisuallyHidden.module.css'
import styles from './InterpretationWorkspace.module.css'

const SIGNAL_LABELS: Record<InterpretationSignalKind, string> = {
  possible_irony: 'Posible ironía',
  possible_ambiguity: 'Posible ambigüedad',
  possible_indirect_language: 'Posible lenguaje indirecto',
  possible_offensive_language: 'Posible lenguaje ofensivo',
  possible_aggression: 'Posible agresión',
  possible_cyberbullying: 'Posible ciberacoso',
}

const SPEAKER_OPTIONS = [
  { value: 'unknown', label: 'No lo sé' },
  {
    value: 'same_as_target_author',
    label: 'La misma persona',
  },
  { value: 'different_from_target_author', label: 'Otra persona' },
] as const satisfies readonly {
  value: ContextSpeakerRelation
  label: string
}[]

const CONTEXT_FIELDS = [
  {
    id: 'previous-context',
    label: 'Contexto anterior',
    placeholder: 'Mensaje anterior (opcional).',
    speakerField: 'previousContextSpeaker',
    textField: 'previousContext',
  },
  {
    id: 'following-context',
    label: 'Contexto posterior',
    placeholder: 'Mensaje posterior (opcional).',
    speakerField: 'followingContextSpeaker',
    textField: 'followingContext',
  },
] as const satisfies readonly {
  id: string
  label: string
  placeholder: string
  speakerField: ContextSpeakerField
  // // Exclude 'targetMessage' — only previousContext and followingContext are allowed here.
  textField: Exclude<InterpretationTextField, 'targetMessage'>
}[]

interface InterpretationWorkspaceProps {
  canSubmit: boolean
  contextExpanded: boolean
  errorMessage: string | null
  errorTitle: string
  interpretation: Interpretation | null
  interpretationStatus: 'idle' | 'loading' | 'ready' | 'error'
  logoSrc: string
  preferenceStatus: PreferenceRequestStatus
  remainingCharacters: number
  request: InterpretationRequest
  visualSupportEnabled: boolean
  onAcknowledgmentChange: (acknowledged: boolean) => void
  onContextToggle: () => void
  onSpeakerChange: (
    field: ContextSpeakerField,
    relation: ContextSpeakerRelation,
  ) => void
  onSubmit: (
    externalProcessingAcknowledged: boolean,
    includeVisualSupport: boolean,
  ) => Promise<void>
  onTextChange: (field: InterpretationTextField, value: string) => void
  onVisualSupportOpen: (pictogram: AvailablePictogram) => void
}

/**
 * Parse a select value against the closed speaker-relation vocabulary.
 *
 * Args:
 *   value: Raw value returned by the browser control.
 *
 * Returns:
 *   A supported relation, or null when the value is unexpected.
 */
function parseSpeakerRelation(value: string): ContextSpeakerRelation | null {
  return SPEAKER_OPTIONS.some((option) => option.value === value)
    ? (value as ContextSpeakerRelation)
    : null
}

/**
 * Render the interpretation workspace without persisting user or LLM content.
 *
 * Args:
 *   props: Transient request, result, state, and interaction callbacks.
 *
 * Returns:
 *   The accessible pragmatic interpretation form and result surface.
 */
export function InterpretationWorkspace({
  canSubmit,
  contextExpanded,
  errorMessage,
  errorTitle,
  interpretation,
  interpretationStatus,
  logoSrc,
  preferenceStatus,
  remainingCharacters,
  request,
  visualSupportEnabled,
  onAcknowledgmentChange,
  onContextToggle,
  onSpeakerChange,
  onSubmit,
  onTextChange,
  onVisualSupportOpen,
}: InterpretationWorkspaceProps) {
  const processingDialogRef = useRef<HTMLDialogElement>(null)
  const resultHeadingRef = useRef<HTMLHeadingElement>(null)
  const preferenceBlockingMessage =
    preferenceStatus === 'ready'
      ? null
      : preferenceStatus === 'load-error' || preferenceStatus === 'save-error'
        ? 'Revisa las preferencias en Ajustes antes de enviar.'
        : 'Espera a que se confirmen las preferencias antes de enviar.'

  // Move focus once to the new result so keyboard and screen-reader users do
  // not need to search for content added after the asynchronous request.
  // Optional chaining (?.) safely no-ops if the ref is still null (element not yet mounted).
  useEffect(() => {
    if (interpretationStatus === 'ready') resultHeadingRef.current?.focus()
  }, [interpretationStatus])

  return (
    <section className={styles.workspace} aria-labelledby="workspace-title">
      <img className={styles.workspaceMark} src={logoSrc} width="92" height="92" alt="" />
      <h1 className={visuallyHiddenStyles.visuallyHidden} id="workspace-title">
        Interpretación de mensajes
      </h1>

      <form
        className={styles.messageForm}
        onSubmit={(event) => {
          event.preventDefault()
          if (!canSubmit) return

          if (!request.externalProcessingAcknowledged) {
            processingDialogRef.current?.showModal()
            return
          }

          void onSubmit(true, visualSupportEnabled)
        }}
      >
        <div className={styles.modeControls} aria-label="Modo de entrada">
          <span className={`${styles.modeButton} ${styles.active}`}>
            <span aria-hidden="true" className={styles.textModeIcon}>
              A<sub>b</sub>
            </span>
            Texto
          </span>
        </div>

        <div className={styles.workGrid}>
          <div className={styles.inputColumn}>
            <div className={styles.inputPanel}>
              <label
                className={visuallyHiddenStyles.visuallyHidden}
                htmlFor="target-message"
              >
                Mensaje a interpretar
              </label>
              {/*
                Accessible required textarea:
                - aria-describedby links the character-count helper for screen readers.
                - rows sets the initial visible height.
              */}
              <textarea
                id="target-message"
                value={request.targetMessage}
                aria-describedby="input-character-count"
                onChange={(event) => onTextChange('targetMessage', event.target.value)}
                placeholder="Escribe el mensaje concreto que quieres interpretar."
                rows={6}
                required
              />
            </div>

            <div className={styles.inputActions}>
              <button
                className={styles.contextToggle}
                type="button"
                aria-expanded={contextExpanded}
                aria-controls="optional-context"
                onClick={onContextToggle}
              >
                {contextExpanded ? 'Quitar y borrar contexto' : 'Añadir contexto'}
              </button>
              <p className={styles.characterCount} id="input-character-count">
                {/* Explicit space between the count and the pluralized label */}
                {remainingCharacters}{' '}
                {remainingCharacters === 1
                  ? 'carácter disponible'
                  : 'caracteres disponibles'}
              </p>
            </div>

            {contextExpanded ? (
              <fieldset className={styles.contextFields} id="optional-context">
                {/* Label for screen readers to announce when the user enters the fieldset. */}
                <legend>Contexto opcional</legend>
                <p id="context-help">
                  Cada contexto debe contener un solo mensaje. Indica quién lo
                  escribió en relación con la persona del mensaje a interpretar.
                </p>
                {CONTEXT_FIELDS.map((context) => {
                  const value = request[context.textField]
                  
                  {/* `key={context.id}` is mandatory in React when rendering a list. */}
                  {/* aria-describedby is used so that screen readers read the explanation with the ID 
                    "context-help" when the user focuses on any of the context fields. */}
                  return (
                    <div className={styles.contextField} key={context.id}>
                      <label htmlFor={context.id}>{context.label}</label>
                      <textarea
                        id={context.id}
                        value={value}
                        aria-describedby="context-help input-character-count"
                        onChange={(event) =>
                          onTextChange(context.textField, event.target.value)
                        }
                        placeholder={context.placeholder}
                        rows={3}
                      />
                      <label htmlFor={`${context.id}-speaker`}>
                        ¿Quién escribió este mensaje?
                      </label>
                      <select
                        id={`${context.id}-speaker`}
                        value={request[context.speakerField]}
                        disabled={value.trim().length === 0}
                        onChange={(event) => {
                          const relation = parseSpeakerRelation(event.target.value)
                          if (relation) onSpeakerChange(context.speakerField, relation)
                        }}
                      >
                        {SPEAKER_OPTIONS.map((option) => (
                          <option value={option.value} key={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )
                })}
              </fieldset>
            ) : null}

          </div>

          <section
            className={styles.resultPanel}
            aria-label="Resultado de la interpretación"
            aria-busy={interpretationStatus === 'loading'}
          >
            {interpretationStatus === 'loading' ? (
              <p role="status">Interpretando el mensaje…</p>
            ) : interpretationStatus === 'error' ? (
              <div role="alert">
                <h2>{errorTitle}</h2>
                <p>{errorMessage}</p>
              </div>
            ) : interpretation ? (
              <div className={styles.resultContent}>
                {interpretation.showContentWarning ? (
                  <p className={styles.contentWarning} role="status">
                    <span aria-hidden="true">⚠️</span>
                    <span>
                      Este mensaje podría contener lenguaje ofensivo o una
                      interacción negativa.
                    </span>
                    <span aria-hidden="true">⚠️</span>
                  </p>
                ) : null}

                <section>
                  <h2 ref={resultHeadingRef} tabIndex={-1}>
                    Interpretación
                  </h2>
                  <p>{interpretation.interpretation}</p>
                </section>

                <section>
                  <h3>Posible forma directa de decirlo</h3>
                  <p>{interpretation.clearReformulation}</p>
                </section>

                {interpretation.needsMoreContext ? (
                  <section>
                    <h3>Contexto adicional necesario</h3>
                    <p>{interpretation.contextNote}</p>
                  </section>
                ) : null}

                {interpretation.signals.length > 0 ? (
                  <section>
                    <h3>Señales posibles</h3>
                    <ul>
                      {interpretation.signals.map((signal) => (
                        <li key={signal.kind}>
                          <strong>{SIGNAL_LABELS[signal.kind]}:</strong>{' '}
                          {signal.explanation}
                        </li>
                      ))}
                    </ul>
                  </section>
                ) : null}

                {visualSupportEnabled && interpretation.visualSupport ? (
                  <VisualSupport
                    result={interpretation.visualSupport}
                    onOpen={onVisualSupportOpen}
                  />
                ) : null}
              </div>
            ) : (
              <p>La interpretación aparecerá aquí.</p>
            )}
          </section>
        </div>

        {preferenceBlockingMessage ? (
          <p className={styles.submissionStatus} role="status">
            {preferenceBlockingMessage}
          </p>
        ) : null}
        <button className={styles.submitButton} type="submit" disabled={!canSubmit}>
          {interpretationStatus === 'loading' ? 'INTERPRETANDO…' : 'ENVIAR'}
        </button>
      </form>

      <dialog
        className={styles.processingDialog}
        ref={processingDialogRef}
        aria-labelledby="external-processing-title"
        aria-describedby="external-processing-notice"
      >
        <h2 id="external-processing-title">Procesamiento externo</h2>
        <p id="external-processing-notice">
          Antes del envío, la aplicación intentará reducir identificadores
          comunes del mensaje y los contextos. El texto resultante se enviará al
          asistente virtual para generar la interpretación. Esta reducción no 
          puede detectar todos los datos personales. La aplicación no almacenará 
          estos textos ni la respuesta. Si el apoyo visual está activado, se
          enviarán a ARASAAC únicamente conceptos visuales simples derivados de la
          interpretación para intentar obtener pictogramas relacionados. No se enviarán
          el mensaje introducido ni los contextos.
        </p>
        <div className={styles.processingActions}>
          <button
            className={styles.cancelProcessingButton}
            type="button"
            autoFocus
            onClick={() => processingDialogRef.current?.close()}
          >
            Cancelar
          </button>
          <button
            className={styles.confirmProcessingButton}
            type="button"
            onClick={() => {
              processingDialogRef.current?.close()
              onAcknowledgmentChange(true)
              void onSubmit(true, visualSupportEnabled)
            }}
          >
            Continuar y enviar
          </button>
        </div>
      </dialog>
    </section>
  )
}
