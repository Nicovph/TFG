/**
 * VisualSupportDialog.tsx renders a modal dialog preview with focus trapping,
 * Escape handling, and a visible close button. It currently identifies a
 * visual concept and will display its ARASAAC pictogram in the next iteration.
 */

import { useEffect, useRef } from 'react' // React hooks for managing side effects and references to DOM elements.
import styles from './VisualSupportDialog.module.css'

// Focusable elements selector for keyboard navigation within the modal dialog.
// not is used to exclude elements that are not focusable.
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export const VISUAL_SUPPORT_DIALOG_ID = 'visual-support-dialog'

interface VisualSupportDialogProps {
  visualLabel: string // The name of the concept to be displayed in the dialog.
  logoSrc: string // The source URL for the logo image displayed in the dialog.
  onClose: () => void
}

/**
 * Return visible focusable descendants for the modal focus trap.
 *
 * Args:
 *   container: The dialog element that owns focus while open.
 *
 * Returns:
 *   Focusable HTML elements inside the dialog.
 */
function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.offsetParent !== null,
  )
}

/**
 * Render a modal concept preview and restore focus when it closes.
 *
 * Args:
 *   props: The selected concept, logo image source, and close callback.
 *
 * Returns:
 *   The modal concept dialog.
 */
export function VisualSupportDialog({ visualLabel, logoSrc, onClose }: VisualSupportDialogProps) {
  const dialogRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const previousFocusRef = useRef<HTMLElement | null>(null)

  useEffect(() => { // When the dialog opens.
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    closeButtonRef.current?.focus()

    return () => {
      if (previousFocusRef.current?.isConnected) { // If the previous focused element is still in the DOM.
        previousFocusRef.current.focus()
      }
    }
  }, [])

  useEffect(() => { // Implements the focus trap of the modal dialog.
    const handleKeyDown = (event: KeyboardEvent) => { // This function handles keyboard events.
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }

      if (event.key !== 'Tab' || !dialogRef.current) {
        return
      }

      const focusableElements = getFocusableElements(dialogRef.current)
      const firstElement = focusableElements[0]
      const lastElement = focusableElements.at(-1)

      if (!firstElement || !lastElement) { // If there are no focusable elements, do nothing.
        event.preventDefault()
        return
      }

      // If Shift+Tab is pressed and the first focusable element is active, move focus to the last.
      if (event.shiftKey && document.activeElement === firstElement) {
        event.preventDefault()
        lastElement.focus()
        //If Tab is pressed and the last focusable element is active, move focus to the first.
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    /* // The overlay that covers a part of the page when the dialog is open. */
    <div className={styles.visualSupportOverlay}>
      <button
        className={styles.visualSupportBackdrop}
        type="button"
        tabIndex={-1}
        aria-label="Cerrar diálogo"
        onClick={onClose}
      ></button>
      {/* // Associates the dialog with the title element for accessibility. */}
      <section
        id={VISUAL_SUPPORT_DIALOG_ID}
        className={styles.visualSupportDialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="visual-support-title"
        ref={dialogRef}
      >
        <button
          className={styles.closeButton}
          type="button"
          onClick={onClose}
          ref={closeButtonRef}
        >
          Cerrar
        </button>
        <img src={logoSrc} width="128" height="128" alt="" />
        {/* // The title of the dialog, which is associated with the dialog for accessibility. */}
        <h2 id="visual-support-title">{visualLabel}</h2>
      </section>
    </div>
  )
}
