/**
 * AccountMenu.tsx renders the mock account control and logout action shown in
 * the authenticated workspace header.
 */

import { ACCOUNT_LABEL } from '../data/infoPages'
import styles from './AccountMenu.module.css'

const ACCOUNT_MENU_BUTTON_ID = 'account-menu-button'
const ACCOUNT_MENU_ID = 'account-menu-popup'

interface AccountMenuProps {
  open: boolean
  onAccountToggle: () => void/* function to open and close the account panel */
  onLogout: () => void
}

/**
 * Render the account pill and the logout popover.
 *
 * Args:
 *   props: Visibility flag and account action callbacks.
 *
 * Returns:
 *   The account menu controls.
 */
export function AccountMenu({ open, onAccountToggle, onLogout }: AccountMenuProps) {
  return ( /* Here begins the JSX that renders the account menu. */
    <div className={styles.accountArea}>
      <button
        id={ACCOUNT_MENU_BUTTON_ID}
        className={styles.userPill}
        type="button" /* Avoids default form submission. */
        aria-expanded={open} /* Informs assistive technologies if the associated menu is expanded.*/
        aria-haspopup="menu" // Indicates that the button controls a menu popup.
        aria-controls={ACCOUNT_MENU_ID} // Associates the button with the menu popup for accessibility.
        onClick={onAccountToggle}
      >
        {ACCOUNT_LABEL}
      </button>
      {open ? ( // Conditional render, only showing the menu when `open` is true.
        <div
          id={ACCOUNT_MENU_ID}
          className={styles.accountPanel}
          role="menu"
          aria-labelledby={ACCOUNT_MENU_BUTTON_ID}
        >
          <button type="button" role="menuitem" onClick={onLogout}>
            Cerrar Sesión
          </button>
        </div>
      ) : null}
    </div>
  )
}
