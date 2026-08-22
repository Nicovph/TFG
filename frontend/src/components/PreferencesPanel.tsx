/**
 * PreferencesPanel.tsx renders authenticated preference controls backed by
 * the validated Django preference API.
 */

import {
  PREFERENCE_GROUPS,
  parsePreferenceValue, // Validates the values of the preferences.
  type PreferenceChangeHandler,
  type PreferenceState,
} from '../data/preferences'
import type { PreferenceRequestStatus } from '../hooks/useUserPreferences'
import { formatRetryAfter } from '../utils/formatRetryAfter'
import styles from './PreferencesPanel.module.css'

export const SETTINGS_PANEL_ID = 'settings-panel'

interface PreferencesPanelProps {
  open: boolean
  preferences: PreferenceState
  retryAfterSeconds: number | null
  status: PreferenceRequestStatus
  onPreferenceChange: PreferenceChangeHandler
  onRetry: () => void
}

/**
 * Render typed select controls for user preferences.
 *
 * Args:
 *   props: Visibility flag, current preferences, and typed change callback.
 *
 * Returns:
 *   The preferences panel or null when closed.
 */
export function PreferencesPanel({
  open,
  preferences,
  retryAfterSeconds,
  status,
  onPreferenceChange,
  onRetry,
}: PreferencesPanelProps) {
  if (!open) {
    return null
  }

  const controlsDisabled = status !== 'ready'
  const retryMessage = retryAfterSeconds
    ? `Espera aproximadamente ${formatRetryAfter(retryAfterSeconds)} antes de volver a cambiarlas.`
    : 'Espera antes de volver a cambiarlas.'
  const statusMessage =
    status === 'loading'
      ? 'Cargando preferencias…'
      : status === 'saving'
        ? 'Guardando cambios…'
        : status === 'load-error'
          ? 'No se pudieron cargar tus preferencias.'
          : status === 'rate-limited'
            ? `Has alcanzado temporalmente el límite de cambios de preferencias. ${retryMessage} Se ha restaurado el valor anterior.`
            : status === 'save-error'
              ? 'No se pudo confirmar si el cambio se guardó. Se ha restaurado el valor anterior en la pantalla.'
              : null
  const hasError =
    status === 'load-error' || status === 'save-error' || status === 'rate-limited'
  const canRetry = status === 'load-error' || status === 'save-error'

  return (
    <section
      className={styles.preferencesPanel}
      id={SETTINGS_PANEL_ID}
      aria-label="Preferencias"
    >
      {PREFERENCE_GROUPS.map((group) => (
        /* Creates a label for each selector. */
        <label
          className={styles.preferenceField}
          key={group.id}
          htmlFor={`preference-${group.id}`}
        >
          <span className={styles.preferenceLabel}>{group.label}</span>
          {/* Coincides with the label's htmlFor for accessibility. */}
          <select
            disabled={controlsDisabled}
            id={`preference-${group.id}`}
            value={preferences[group.id]}
            onChange={(event) => {
              const nextValue = parsePreferenceValue(group.id, event.target.value)

              if (nextValue !== null) {
                {/* Only if the value is valid, call the change handler. */}
                onPreferenceChange(group.id, nextValue)
              }
            }}
          >
            {group.options.map((option) => (
              /* // option.value: Internal value. */
              <option value={option.value} key={option.value}>
                {/* // Visible text. */}
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ))}
      {statusMessage ? (
        <div className={hasError ? styles.errorStatus : styles.requestStatus}>
          <span role={hasError ? 'alert' : 'status'}>{statusMessage}</span>
          {canRetry ? (
            <button className={styles.retryButton} type="button" onClick={onRetry}>
              Recargar preferencias
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
