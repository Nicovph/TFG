/**
 * AppHeader.tsx renders the authenticated workspace header and composes the
 * preferences and account popovers.
 */

import type { Ref } from 'react'
import { AccountMenu } from './AccountMenu'
import styles from './AppHeader.module.css'
import { MenuButton } from './MenuButton'
import { PreferencesPanel, SETTINGS_PANEL_ID } from './PreferencesPanel'
import { Tooltip } from './Tooltip'
import visuallyHiddenStyles from './VisuallyHidden.module.css'
import settingsIcon from '../assets/engranaje_configuraciones.png'
import type { PreferenceChangeHandler, PreferenceState } from '../data/preferences'
import type { LogoutStatus } from '../hooks/useAuthSession'
import type { PreferenceRequestStatus } from '../hooks/useUserPreferences'

interface AppHeaderProps {
  accountOpen: boolean
  apiStatusText: string
  logoutStatus: LogoutStatus
  menuButtonRef: Ref<HTMLButtonElement>
  /**
   * Whether the modal navigation drawer is open.
   */
  menuOpen: boolean
  preferences: PreferenceState
  preferenceRetryAfterSeconds: number | null
  preferenceStatus: PreferenceRequestStatus
  settingsOpen: boolean
  onAccountToggle: () => void
  onClosePopovers: () => void
  onLogout: () => void
  onMenuToggle: () => void
  onNavigateWorkspace: () => void
  onPreferenceChange: PreferenceChangeHandler
  onPreferencesRetry: () => void
  onSettingsToggle: () => void
}

/**
 * Render the main app header with menu, brand, settings and account controls.
 *
 * Args:
 *   props: Header state and callbacks managed by the root app component.
 *
 * Returns:
 *   The main workspace header.
 */
export function AppHeader({
  accountOpen,
  apiStatusText,
  logoutStatus,
  menuButtonRef,
  menuOpen,
  preferences,
  preferenceRetryAfterSeconds,
  preferenceStatus,
  settingsOpen,
  onAccountToggle,
  onClosePopovers,
  onLogout,
  onMenuToggle,
  onNavigateWorkspace,
  onPreferenceChange,
  onPreferencesRetry,
  onSettingsToggle,
}: AppHeaderProps) {
  return (
    <header className={styles.appHeader}>
      {settingsOpen || accountOpen ? (
        <button
          className={styles.popoverBackdrop}
          type="button"
          tabIndex={-1}
          aria-label="Cerrar panel"
          onClick={onClosePopovers}
        ></button>
      ) : null}

      <div className={styles.headerBrandGroup}>
        <MenuButton buttonRef={menuButtonRef} menuOpen={menuOpen} onToggle={onMenuToggle} />

        <button
          className={styles.brandButton}
          type="button"
          aria-label="TEAslator: volver al área principal"
          onClick={onNavigateWorkspace}
        >
          <span className={styles.brandName}>
            <span>TEA</span>slator
          </span>
        </button>
      </div>

      <div className={styles.headerActions}>
        {/**
         * The status role announces API availability changes without interrupting the user.
        */}
        <span className={visuallyHiddenStyles.visuallyHidden} role="status">
          {apiStatusText}
        </span>
        {/**
         * Preferences container.
         */}
        <div className={styles.settingsArea}>
          {/** The settings button controls a non-modal disclosure panel. */}
          <Tooltip align="end" label="Ajustes">
            <button
              className={styles.settingsButton}
              type="button"
              aria-label="Ajustes"
              aria-expanded={settingsOpen}
              aria-controls={settingsOpen ? SETTINGS_PANEL_ID : undefined}
              onClick={onSettingsToggle}
            >
              <img
                className={styles.settingsIcon}
                src={settingsIcon}
                width="30"
                height="30"
                alt=""
              />
            </button>
          </Tooltip>
          <PreferencesPanel
            open={settingsOpen}
            preferences={preferences}
            retryAfterSeconds={preferenceRetryAfterSeconds}
            status={preferenceStatus}
            onPreferenceChange={onPreferenceChange}
            onRetry={onPreferencesRetry}
          />
        </div>
        <AccountMenu
          logoutStatus={logoutStatus}
          open={accountOpen}
          onAccountToggle={onAccountToggle}
          onLogout={onLogout}
        />
      </div>
    </header>
  )
}
