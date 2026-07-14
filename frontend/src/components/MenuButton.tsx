/**
 * MenuButton.tsx renders the shared accessible control for the main drawer.
 */

import type { Ref } from 'react'
import { MAIN_DRAWER_ID } from './Drawer'
import styles from './MenuButton.module.css'
import { Tooltip } from './Tooltip'

interface MenuButtonProps {
  buttonRef?: Ref<HTMLButtonElement>
  menuOpen: boolean
  onToggle: () => void
}

/**
 * Render the main drawer trigger with consistent semantics and styling.
 *
 * Args:
 *   props: Drawer state, toggle callback, and optional button reference.
 *
 * Returns:
 *   The tooltip-wrapped drawer trigger.
 */
export function MenuButton({ buttonRef, menuOpen, onToggle }: MenuButtonProps) {
  const controlLabel = menuOpen ? 'Cerrar menú' : 'Abrir menú'

  return (
    <Tooltip align="start" label={controlLabel}>
      <button
        className={styles.button}
        type="button"
        aria-label={controlLabel}
        aria-expanded={menuOpen}
        aria-controls={menuOpen ? MAIN_DRAWER_ID : undefined}
        aria-haspopup="dialog"
        onClick={onToggle}
        ref={buttonRef}
      >
        <span aria-hidden="true"></span>
      </button>
    </Tooltip>
  )
}
