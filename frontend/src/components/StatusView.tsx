/**
 * StatusView.tsx renders accessible loading and recoverable error screens.
 */

import { BRAND_TAGLINE } from '../data/infoPages'
import { LoadingSpinner } from './LoadingSpinner'
import styles from './StatusView.module.css'

export interface StatusViewAction {
  label: string
  onClick: () => void
}

interface StatusViewProps {
  logoSrc: string
  message: string
  mode: 'loading' | 'error'
  primaryAction?: StatusViewAction
  secondaryAction?: StatusViewAction
  title: string
}

/**
 * Render a full-page status view with clear text and keyboard-accessible actions.
 *
 * Args:
 *   props: Visual mode, copy, logo, and optional actions for recovery.
 *
 * Returns:
 *   The status screen element.
 */
export function StatusView({
  logoSrc,
  message,
  mode,
  primaryAction,
  secondaryAction,
  title,
}: StatusViewProps) {
  const isLoading = mode === 'loading'

  return (
    <main className={styles.statusView}>
      <section className={styles.statusPanel}>
        <div className={styles.brandBlock}>
          <img className={styles.logo} src={logoSrc} width="92" height="92" alt="" />
          <p className={styles.brandName}>
            <span>TEA</span>slator
          </p>
          <p className={styles.brandTagline}>{BRAND_TAGLINE}</p>
        </div>

        <div className={isLoading ? styles.loadingVisual : styles.errorVisual} aria-hidden="true">
          {isLoading ? <LoadingSpinner variant="status" /> : <span>!</span>}
        </div>

        <div className={styles.copyBlock} role={isLoading ? 'status' : 'alert'}>
          <h1>{title}</h1>
          <p>{message}</p>
        </div>

        {primaryAction || secondaryAction ? (
          <div className={styles.actionGroup}>
            {primaryAction ? (
              <button className={styles.primaryAction} type="button" onClick={primaryAction.onClick}>
                {primaryAction.label}
              </button>
            ) : null}
            {secondaryAction ? (
              <button
                className={styles.secondaryAction}
                type="button"
                onClick={secondaryAction.onClick}
              >
                {secondaryAction.label}
              </button>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  )
}
