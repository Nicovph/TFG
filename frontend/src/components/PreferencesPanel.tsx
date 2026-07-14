/**
 * PreferencesPanel.tsx renders local preference controls using the same closed
 * option sets as the backend-facing preference model.
 */

import {
  PREFERENCE_GROUPS,
  parsePreferenceValue, // Validates the values of the preferences.
  type PreferenceChangeHandler,
  type PreferenceState,
} from '../data/preferences'
import styles from './PreferencesPanel.module.css'

export const SETTINGS_PANEL_ID = 'settings-panel'

interface PreferencesPanelProps {
  open: boolean
  preferences: PreferenceState
  onPreferenceChange: PreferenceChangeHandler
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
  onPreferenceChange,
}: PreferencesPanelProps) {
  if (!open) {
    return null
  }

  return (
    <section
      className={styles.preferencesPanel}
      id={SETTINGS_PANEL_ID}
      aria-label="Preferencias"
    >
      {PREFERENCE_GROUPS.map((group) => (
        /* // Creates a label for each selector. */
        <label
          className={styles.preferenceField}
          key={group.id}
          htmlFor={`preference-${group.id}`}
        >
          <span className={styles.preferenceLabel}>{group.label}</span>
          {/* // Coincides with the label's htmlFor for accessibility. */}
          <select
            id={`preference-${group.id}`}
            value={preferences[group.id]}
            onChange={(event) => {
              const nextValue = parsePreferenceValue(group.id, event.target.value)

              if (nextValue !== null) {
                // Only if the value is valid, call the change handler.
                onPreferenceChange(group.id, nextValue)
              }
            }}
          >
            {group.options.map((option) => (
              /* // option.value: Intern value. */
              <option value={option.value} key={option.value}>
                {/* // Visible text. */}
                {option.label}
              </option>
            ))}
          </select>
        </label>
      ))}
    </section>
  )
}
