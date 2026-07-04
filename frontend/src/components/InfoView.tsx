/**
 * InfoView.tsx renders static informational pages selected from the navigation
 * drawer.
 */

import { BRAND_TAGLINE } from '../data/infoPages'
import type { InfoPageContent } from '../data/infoPages'
import { MAIN_DRAWER_ID } from './Drawer'
import styles from './InfoView.module.css'

interface InfoViewProps {
  infoPage: InfoPageContent
  logoSrc: string
  menuOpen: boolean
  onMenuToggle: () => void
  onReturn: () => void
}

/**
 * Render an informational page with the required top-right brand block.
 *
 * Args:
 *   props: Page content, logo source, menu state, and menu action.
 *
 * Returns:
 *   The informational page view.
 */
export function InfoView({ infoPage, logoSrc, menuOpen, onMenuToggle, onReturn }: InfoViewProps) {
  return (
    <main className={styles.infoView}>
      <header className={styles.infoHeader}>
        <div className={styles.infoNavigation}>
          <button
            className={styles.menuButton}
            type="button"
            aria-label="Abrir menú"
            aria-expanded={menuOpen}
            aria-controls={MAIN_DRAWER_ID}
            aria-haspopup="dialog"
            onClick={onMenuToggle}
          >
            <span aria-hidden="true"></span>
          </button>
          <button
            className={styles.backButton}
            type="button"
            aria-label="Volver"
            onClick={onReturn}
          >
            <span aria-hidden="true"></span>
          </button>
        </div>
        <button
          className={styles.infoBrandButton}
          type="button"
          aria-label="Volver"
          onClick={onReturn}
        >
          <img src={logoSrc} width="74" height="74" alt="" />
          <span className={styles.brandName}>
            <span>TEA</span>slator
          </span>
          <span className={styles.infoBrandTagline}>{BRAND_TAGLINE}</span>
        </button>
      </header>

      <article className={styles.infoArticle}>
        <h1>{infoPage.title}</h1>
        {infoPage.paragraphs.map((paragraph) => (
          <p key={paragraph}>{paragraph}</p>
        ))}
      </article>
    </main>
  )
}
