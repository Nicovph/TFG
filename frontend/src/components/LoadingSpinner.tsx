/**
 * LoadingSpinner.tsx renders decorative progress feedback with explicit visual variants.
 */

import styles from './LoadingSpinner.module.css'

interface LoadingSpinnerProps {
  variant: 'compact' | 'status'
}

/**
 * Render a decorative loading spinner.
 *
 * Args:
 *   props: Visual variant selected by the consuming component.
 *
 * Returns:
 *   A spinner hidden from assistive technologies.
 */
export function LoadingSpinner({ variant }: LoadingSpinnerProps) {
  return <span className={`${styles.spinner} ${styles[variant]}`} aria-hidden="true"></span>
}
