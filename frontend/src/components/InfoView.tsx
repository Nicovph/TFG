/**
 * InfoView.tsx renders static informational pages selected from the navigation
 * drawer.
 */

import { useEffect, useRef } from 'react'
import { BRAND_TAGLINE } from '../data/infoPages'
import type { InfoPageContent } from '../data/infoPages'
import { MenuButton } from './MenuButton'
import { Tooltip } from './Tooltip'
import styles from './InfoView.module.css'

interface InfoViewProps {
  infoPage: InfoPageContent
  logoSrc: string
  menuOpen: boolean
  onMenuToggle: () => void
  onReturn: () => void
  returnLabel: string
}

/**
 * Render an informational page with the required top-right brand block.
 *
 * Args:
 *   props: Page content, logo source, menu state, return label, and navigation actions.
 *
 * Returns:
 *   The informational page view.
 */
export function InfoView({
  infoPage,
  logoSrc,
  menuOpen,
  onMenuToggle,
  onReturn,
  returnLabel,
}: InfoViewProps) {
  const titleRef = useRef<HTMLHeadingElement>(null)

  /**
   * Move focus to the heading after the informational page changes.
   */
  useEffect(() => {
    if (infoPage.title.length === 0) {
      return
    }

    // Move focus to the new page heading when navigation removes the drawer invoker.
    titleRef.current?.focus()
  }, [infoPage.title])
  const brandReturnLabel = `TEAslator, ${BRAND_TAGLINE}. ${returnLabel}`

  return (
    <main className={styles.infoView}>
      <header className={styles.infoHeader}>
        <nav className={styles.infoNavigation} aria-label="Página informativa">
          <MenuButton menuOpen={menuOpen} onToggle={onMenuToggle} />
          <Tooltip align="start" label={returnLabel}>
            <button
              className={styles.backButton}
              type="button"
              aria-label={returnLabel}
              onClick={onReturn}
            >
              <span aria-hidden="true"></span>
            </button>
          </Tooltip>
        </nav>
        <button
          className={styles.infoBrandButton}
          type="button"
          aria-label={brandReturnLabel}
          onClick={onReturn}
        >
          <img src={logoSrc} width="74" height="74" alt="" />
          <span className={styles.brandName}>
            <span>TEA</span>slator
          </span>
          <span className={styles.infoBrandTagline}>{BRAND_TAGLINE}</span>
        </button>
      </header>

      {/**
       * Allows receiving programmatic focus (.focus()) without including the
       * element in the natural Tab navigation.
       */}
      <article className={styles.infoArticle}>
        <h1 ref={titleRef} tabIndex={-1}>
          {infoPage.title}
        </h1>
        {infoPage.paragraphs.map((paragraph, index) => (
          <p key={`${infoPage.title}-${index}`}>{paragraph}</p>
        ))}
      </article>
    </main>
  )
}
