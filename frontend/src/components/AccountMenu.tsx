/**
 * AccountMenu.tsx renders the minimized account control and logout action
 * shown in the authenticated workspace header.
 */

import { ACCOUNT_LABEL } from '../data/infoPages'
import type { LogoutStatus } from '../hooks/useAuthSession'
import { LoadingSpinner } from './LoadingSpinner'
import styles from './AccountMenu.module.css'

const ACCOUNT_PANEL_ID = 'account-panel'

interface AccountMenuProps {
  logoutStatus: LogoutStatus
  open: boolean
  onAccountToggle: () => void
  onLogout: () => void
}

/**
 * Render the account pill and the logout popover.
 *
 * Args:
 *   props: Visibility flag and account action callbacks.
 *
 * Returns:
 *   The account disclosure controls.
 */
export function AccountMenu({ logoutStatus, open, onAccountToggle, onLogout }: AccountMenuProps) {
  const logoutInProgress = logoutStatus === 'loading'

  return (
    <div className={styles.accountArea}>
      <button
        className={styles.userPill}
        type="button"
        aria-expanded={open}
        aria-controls={open ? ACCOUNT_PANEL_ID : undefined}
        onClick={onAccountToggle}
      >
        {ACCOUNT_LABEL}
      </button>
      {open ? (
        <div id={ACCOUNT_PANEL_ID} className={styles.accountPanel}>
          <button type="button" onClick={onLogout} disabled={logoutInProgress}>
            {logoutInProgress ? (
              <LoadingSpinner variant="compact" />
            ) : null}
            {logoutInProgress ? 'Cerrando sesión' : 'Cerrar sesión'}
          </button>
        </div>
      ) : null}
    </div>
  )
}
