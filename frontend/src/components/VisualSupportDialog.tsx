/**
 * VisualSupportDialog.tsx enlarges one validated ARASAAC pictogram in a native
 * modal dialog with browser-managed focus containment.
 */

import { useEffect, useId, useRef, useState } from 'react'
import type { AvailablePictogram } from '../types'
import styles from './VisualSupportDialog.module.css'

interface VisualSupportDialogProps {
  pictogram: AvailablePictogram
  onClose: () => void
}

/**
 * Render an enlarged pictogram and restore focus when it closes.
 *
 * Args:
 *   props: Validated pictogram and close callback.
 *
 * Returns:
 *   A native modal dialog containing the pictogram and its visible label.
 */
export function VisualSupportDialog({
  pictogram,
  onClose,
}: VisualSupportDialogProps) {
  // Keep the accessible name unique if more than one dialog is rendered.
  const titleId = useId()
  const dialogRef = useRef<HTMLDialogElement>(null)
  // Store the element that had focus before opening the modal, so it can be restored upon closing.
  const previousFocusRef = useRef<HTMLElement | null>(null)
  // A validated URL can still fail at delivery time; keep the dialog usable.
  const [imageFailed, setImageFailed] = useState(false)

  useEffect(() => {
    const dialog = dialogRef.current
    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    dialog?.showModal()

    // Cleanup function.
    return () => {
      if (dialog?.open) dialog.close()
      // If the element that had the focus is still mounted, focus is returned to it.
      if (previousFocusRef.current?.isConnected) previousFocusRef.current.focus()
    }
  }, [])

  return (
    <dialog
      className={styles.visualSupportDialog}
      ref={dialogRef}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className={styles.dialogContent}>
        <button type="button" autoFocus onClick={onClose}>
          Cerrar
        </button>
        {imageFailed ? (
          <p className={styles.imageFallback} role="status">
            El pictograma no se pudo cargar.
          </p>
        ) : (
          <img
            src={pictogram.imageUrl}
            width="300"
            height="300"
            alt=""
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
          />
        )}
        <h2 id={titleId}>{pictogram.label}</h2>
      </div>
    </dialog>
  )
}
