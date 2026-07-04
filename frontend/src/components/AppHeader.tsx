/**
 * AppHeader.tsx renders the authenticated workspace header and composes the
 * preferences and account popovers.
 */

import { AccountMenu } from './AccountMenu'
import { MAIN_DRAWER_ID } from './Drawer'
import styles from './AppHeader.module.css'
import { PreferencesPanel, SETTINGS_PANEL_ID } from './PreferencesPanel'
import settingsIcon from '../assets/engranaje_configuraciones.png'
import type { PreferenceChangeHandler, PreferenceState } from '../data/preferences'
// import type is used to import only the type definitions used in compile time for typing.

interface AppHeaderProps {
  accountOpen: boolean
  apiReady: boolean
  apiStatusText: string
  menuOpen: boolean // If the drawer is opened.
  preferences: PreferenceState
  settingsOpen: boolean
  onAccountToggle: () => void
  onClosePopovers: () => void
  onLogout: () => void
  onMenuToggle: () => void
  onNavigateHome: () => void
  onPreferenceChange: PreferenceChangeHandler
  onSettingsToggle: () => void
}

/**
 * Render the main app header with menu, brand, settings, and account controls.
 *
 * Args:
 *   props: Header state and callbacks managed by the root app component.
 *
 * Returns:
 *   The main workspace header.
 */
export function AppHeader({
  accountOpen,
  apiReady,
  apiStatusText,
  menuOpen,
  preferences,
  settingsOpen,
  onAccountToggle,
  onClosePopovers,
  onLogout,
  onMenuToggle,
  onNavigateHome,
  onPreferenceChange,
  onSettingsToggle,
}: AppHeaderProps) {
  return (
    <header className={styles.appHeader}>
      {settingsOpen || accountOpen ? (
        <button
          className={styles.popoverBackdrop}
          type="button"
          aria-label="Cerrar panel"
          onClick={onClosePopovers}
        ></button>
      ) : null}

      <div className={styles.headerBrandGroup}>
        <button
          className={styles.menuButton}
          type="button"
          aria-label="Abrir menú"
          aria-expanded={menuOpen}
          aria-controls={MAIN_DRAWER_ID}
          aria-haspopup="dialog"
          onClick={onMenuToggle}
        >
          <span aria-hidden="true"></span>
        </button>

        <button
          className={styles.brandButton}
          type="button"
          aria-label="Volver al inicio"
          onClick={onNavigateHome}
        >
          <span className={styles.brandName}>
            <span>TEA</span>slator
          </span>
        </button>
      </div>

      <div className={styles.headerActions}>
        {/* // Permits screen readers to announce changes in the API status text without an agresive interrumption. */}
        <span
          className={apiReady ? `${styles.apiStatus} ${styles.ready}` : styles.apiStatus}
          aria-live="polite"
        >
          {apiStatusText}
        </span>
        {/* // Preferences container. */}
        <div className={styles.settingsArea}>
          {/* // Indicates that the button controls a dialog popup. */}
          <button
            className={styles.settingsButton}
            type="button"
            aria-label="Ajustes"
            aria-expanded={settingsOpen}
            aria-controls={SETTINGS_PANEL_ID}
            aria-haspopup="dialog"
            onClick={onSettingsToggle}
          >
            <img className={styles.settingsIcon} src={settingsIcon} width="30" height="30" alt="" />
          </button>
          <PreferencesPanel
            open={settingsOpen}
            preferences={preferences}
            onPreferenceChange={onPreferenceChange}
          />
        </div>
        <AccountMenu open={accountOpen} onAccountToggle={onAccountToggle} onLogout={onLogout} />
      </div>
    </header>
  )
}
