/**
 * VisualSupport.tsx renders validated ARASAAC pictograms, attribution, and the
 * text-preserving visual fallback.
 */

import { useId, useRef, useState } from 'react'
import unavailableIllustration from '../assets/visual-support-unavailable.png'
import type { AvailablePictogram, VisualSupportResult } from '../types'
import styles from './VisualSupport.module.css'

interface VisualSupportProps {
  result: VisualSupportResult
  onOpen: (pictogram: AvailablePictogram) => void
}

/**
 * Render useful pictograms without turning missing concepts into empty cards.
 *
 * Args:
 *   props: Validated visual-support result and pictogram preview callback.
 *
 * Returns:
 *   Available pictograms, a complete fallback, or nothing when none were requested.
 */
export function VisualSupport({ result, onOpen }: VisualSupportProps) {
  // Keep the accessible name and focus target local to this component instance.
  const headingId = useId()
  const headingRef = useRef<HTMLHeadingElement>(null)
  // Save the concepts whose images could not be loaded in the browser.
  const [failedConcepts, setFailedConcepts] = useState<string[]>([])

  if (result.status === 'not_requested') return null

  const availablePictograms = result.items.filter(
    (item): item is AvailablePictogram => item.status === 'available',
  )
  // From the pictograms found by the backend, remove those whose image has already triggered an onError event.
  const visiblePictograms = availablePictograms.filter(
    (item) => !failedConcepts.includes(item.concept),
  )
  const allImagesFailed =
    availablePictograms.length > 0 && visiblePictograms.length === 0
  const showFallback = result.status === 'unavailable' || allImagesFailed
  const loadingFailureMessage =
    'Algunos pictogramas no se pudieron cargar. La interpretación de texto sigue disponible.'
  const message = allImagesFailed
    ? 'Los pictogramas no se pudieron cargar. La interpretación de texto sigue disponible.'
    : result.message

  return (
    <section className={styles.visualSupport} aria-labelledby={headingId}>
      <h3 ref={headingRef} id={headingId} tabIndex={-1}>
        {showFallback ? 'Apoyo visual no disponible' : 'Apoyo visual'}
      </h3>

      {showFallback ? (
        <div className={styles.fallback}>
          <img
            src={unavailableIllustration}
            width="180"
            height="180"
            alt=""
          />
          <p role={allImagesFailed ? 'status' : undefined}>{message}</p>
        </div>
      ) : (
        <>
          <ul className={styles.pictogramList}>
            {visiblePictograms.map((pictogram) => (
              <li key={pictogram.concept}>
                <button
                  type="button"
                  aria-haspopup="dialog"
                  aria-label={`Ampliar pictograma: ${pictogram.label}`}
                  onClick={() => onOpen(pictogram)}
                >
                  <img
                    src={pictogram.imageUrl}
                    width="300"
                    height="300"
                    alt=""
                    // Defer off-screen images.
                    loading="lazy"
                    decoding="async"
                    // It does not include the Referer header, so as not to communicate the URL
                    // from which the pictogram was loaded to the external server.
                    referrerPolicy="no-referrer"
                    onError={(event) => {
                      // Focus is on the button (parent); restore it after this item is removed.
                      const restoreFocus =
                        event.currentTarget.parentElement === document.activeElement
                      // onError can fire more than once for the same image; only append the concept
                      // if it is not already in the failed list, so React state stays deduplicated.
                      setFailedConcepts((current) =>
                        current.includes(pictogram.concept)
                          ? current
                          : [...current, pictogram.concept],
                      )
                      // Move focus to the section heading after the DOM updates.
                      // It only executes if the button that is about to disappear had the focus.
                      if (restoreFocus) {
                        // It postpones the operation until the browser's next render cycle, so that
                        // React has already had the chance to update the interface and remove the failed pictogram.
                        requestAnimationFrame(() => headingRef.current?.focus())
                      }
                    }}
                  />
                  <span>{pictogram.label}</span>
                </button>
              </li>
            ))}
          </ul>

          {message ? <p className={styles.message}>{message}</p> : null}
          {/* Do not repeat an equivalent partial-failure message from Django. */}
          {failedConcepts.length > 0 && message !== loadingFailureMessage ? (
            <p className={styles.message} role="status">
              {loadingFailureMessage}
            </p>
          ) : null}

          {result.attribution ? (
            <footer className={styles.attribution}>
              <p>{result.attribution.text}</p>
              <a
                href={result.attribution.termsUrl}
                // Tells the browser that the link should open in a new tab.
                target="_blank"
                // Block window.opener (handle the new tab gets to the original page) and omit Referer.
                rel="noopener noreferrer"
              >
                Condiciones de uso de ARASAAC (se abre en una pestaña nueva)
              </a>
            </footer>
          ) : null}
        </>
      )}
    </section>
  )
}
