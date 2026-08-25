/**
 * Tooltip.tsx provides visual hints for icon-only controls on pointer hover
 * and keyboard focus. Each control must provide its own accessible name.
 */

import { useEffect, useState } from 'react'
import type { FocusEvent, PointerEvent, ReactElement } from 'react'
import styles from './Tooltip.module.css'

interface TooltipProps {
  align?: 'start' | 'center' | 'end'
  children: ReactElement
  label: string
}

/**
 * Render a dismissible visual hint for one accessible interactive child.
 *
 * Args:
 *   props: Tooltip text, alignment, and the control that triggers it.
 *
 * Returns:
 *   The wrapped control and its tooltip content.
 */
export function Tooltip({ align = 'center', children, label }: TooltipProps) {
  const [focusVisible, setFocusVisible] = useState(false)
  const [hovered, setHovered] = useState(false)
  /**
   * Tracks whether the current tooltip interaction was dismissed with Escape.
   */
  const [dismissed, setDismissed] = useState(false)
  const visible = !dismissed && (focusVisible || hovered)

  /**
   * Dismiss visible hints before document-level overlays handle Escape.
   */
  useEffect(() => {
    if (!visible) {
      return undefined
    }

    /**
     * Dismiss the current visual hint without moving focus or pointer hover.
     *
     * Args:
     *   event: The native keyboard event dispatched by the browser.
     */
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') {
        return
      }

      // Capture prevents the same Escape from also closing a parent drawer or dialog.
      event.stopPropagation()
      setDismissed(true)
    }

    /**
     * Uses capture phase (`true`) so the tooltip can handle Escape
     * before parent overlays (e.g. Drawer) receive the event.
     * This creates the desired layered dismissal behavior.
     */
    window.addEventListener('keydown', handleEscape, true)
    return () => window.removeEventListener('keydown', handleEscape, true)
  }, [visible])

  /**
   * Clear keyboard visibility when focus leaves the wrapped control.
   *
   * Args:
   *   event: The focus event emitted by the wrapper.
   */
  const handleBlur = (event: FocusEvent<HTMLSpanElement>) => {
    const nextFocusedElement = event.relatedTarget

    if (
      !(nextFocusedElement instanceof Node) ||
      !event.currentTarget.contains(nextFocusedElement)
    ) {
      setFocusVisible(false)
    }
  }

  /**
   * Reveal the hint only when browser focus indication is appropriate.
   *
   * Args:
   *   event: The focus event emitted by the wrapper.
   */
  const handleFocus = (event: FocusEvent<HTMLSpanElement>) => {
    const focusedElement = event.target
    const focusShouldRevealTooltip =
      focusedElement instanceof Element && focusedElement.matches(':focus-visible')

    setDismissed(false)
    setFocusVisible(focusShouldRevealTooltip)
  }

  /**
   * Reveal the hint for hover-capable pointers without creating touch-only hover state.
   *
   * Args:
   *   event: The pointer event emitted when the pointer enters the wrapper.
   */
  const handlePointerEnter = (event: PointerEvent<HTMLSpanElement>) => {
    if (event.pointerType === 'touch') {
      return
    }

    setDismissed(false)
    setHovered(true)
  }

  /**
   * Clear pointer visibility after pointer activation, exit, or cancellation.
   */
  const handlePointerExit = () => {
    setHovered(false)
  }

  return (
    <span
      className={styles.tooltipAnchor}
      onBlurCapture={handleBlur}
      onFocusCapture={handleFocus}
      onPointerCancel={handlePointerExit}
      onPointerDownCapture={handlePointerExit}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerExit}
    >
      {children}
      {visible ? (
        <span className={`${styles.tooltip} ${styles[align]}`} aria-hidden="true">
          {label}
        </span>
      ) : null}
    </span>
  )
}
