/**
 * HomeView.tsx renders the initial unauthenticated landing screen described by
 * the wireframes.
 */

import { BRAND_TAGLINE } from '../data/infoPages'
import { MAIN_DRAWER_ID } from './Drawer'
import styles from './HomeView.module.css'

interface HomeViewProps {
  logoSrc: string
  menuOpen: boolean
  onGoogleEntry: () => void
  onMenuToggle: () => void
}

/**
 * Render the start screen with the brand mark and Google entry action.
 *
 * Args:
 *   props: Logo source, menu state, and click handlers.
 *
 * Returns:
 *   The home view element.
 */
export function HomeView({ logoSrc, menuOpen, onGoogleEntry, onMenuToggle }: HomeViewProps) {
  return (
    <main className={styles.homeView}>
      <header className={styles.homeHeader}>
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
      </header>

      <section className={styles.homeContent} aria-labelledby="home-title">
        <img className={styles.homeLogo} src={logoSrc} width="170" height="170" alt="" />
        <h1 className={styles.homeTitle} id="home-title">
          <span>TEA</span>slator
        </h1>
        <p className={styles.brandTagline}>{BRAND_TAGLINE}</p>
        <button className={styles.googleButton} type="button" onClick={onGoogleEntry}>
          ENTRAR CON GOOGLE
        </button>
      </section>
    </main>
  )
}