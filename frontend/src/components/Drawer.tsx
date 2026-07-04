/**
 * Drawer.tsx renders the modal lateral navigation drawer with keyboard focus
 * containment and Escape-to-close behavior.
 */

import { useEffect, useRef } from 'react'
import type { InfoView } from '../data/infoPages' // To restrict navigation to informational pages.
import styles from './Drawer.module.css'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export const MAIN_DRAWER_ID = 'main-drawer'

interface DrawerProps {
  open: boolean
  onClose: () => void
  onNavigate: (view: InfoView) => void
}

/**
 * Return visible focusable descendants for focus trapping.
 *
 * Args:
 *   container: The element that owns the modal focus scope.
 *
 * Returns:
 *   Focusable HTML elements inside the container.
 */
function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.offsetParent !== null,
  )
}

/**
 * Render the drawer when open and keep keyboard navigation inside it.
 *
 * Args:
 *   props: Drawer visibility, close action, and local navigation action.
 *
 * Returns:
 *   The drawer overlay or null when closed.
 */
export function Drawer({ open, onClose, onNavigate }: DrawerProps) {
  const panelRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) { // If the drawer is closed, it is not done anything.
      return undefined
    }

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeButtonRef.current?.focus()

    return () => {
      if (previousFocusRef.current?.isConnected) {
        previousFocusRef.current.focus()
      }
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return undefined
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }

      if (event.key !== 'Tab' || !panelRef.current) {
        return
      }

      const focusableElements = getFocusableElements(panelRef.current)
      const firstElement = focusableElements[0]
      const lastElement = focusableElements.at(-1)

      if (!firstElement || !lastElement) {
        event.preventDefault()
        return
      }

      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose, open])

  if (!open) { // This prevents the drawer from existing in the DOM unnecessarily.
    return null
  }

  return (
    <div className={styles.drawerLayer}>
      <button
        className={styles.drawerBackdrop}
        type="button"
        tabIndex={-1}
        aria-label="Cerrar menú"
        onClick={onClose}
      ></button>
      <aside
        id={MAIN_DRAWER_ID}
        className={styles.drawerPanel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
        ref={panelRef}
      >
        <div className={styles.drawerHeader}>
          <h2 className={styles.drawerBrand} id="drawer-title">
            <span>TEA</span>slator
          </h2>
          <button
            className={styles.closeButton}
            type="button"
            aria-label="Cerrar menú"
            onClick={onClose}
            ref={closeButtonRef}
          >
            <span aria-hidden="true"></span>
          </button>
        </div>
        <nav className={styles.drawerNav} aria-label="Menú principal">
          <button
            className={styles.primaryNavItem}
            type="button"
            onClick={() => onNavigate('about')}
          >
            Acerca del proyecto
          </button>
          <button type="button" onClick={() => onNavigate('privacy')}>
            Política de privacidad
          </button>
          <button type="button" onClick={() => onNavigate('terms')}>
            Condiciones de uso
          </button>
        </nav>
      </aside>
    </div>
  )
}
