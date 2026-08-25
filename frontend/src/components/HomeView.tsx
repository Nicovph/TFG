/**
 * HomeView.tsx renders the initial unauthenticated landing screen described by
 * the wireframes.
 */

import type { Ref } from 'react'
import { BRAND_TAGLINE } from '../data/infoPages'
import googleLogo from '../assets/google-g-logo.png'
import { MenuButton } from './MenuButton'
import styles from './HomeView.module.css'

interface HomeViewProps {
  googleEntryButtonRef: Ref<HTMLButtonElement>
  logoSrc: string
  menuButtonRef: Ref<HTMLButtonElement>
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
export function HomeView({
  googleEntryButtonRef,
  logoSrc,
  menuButtonRef,
  menuOpen,
  onGoogleEntry,
  onMenuToggle,
}: HomeViewProps) {
  return (
    <main className={styles.homeView}>
      <header className={styles.homeHeader}>
        <MenuButton buttonRef={menuButtonRef} menuOpen={menuOpen} onToggle={onMenuToggle} />
      </header>

      <section className={styles.homeContent} aria-labelledby="home-title">
        <img className={styles.homeLogo} src={logoSrc} width="170" height="170" alt="" />
        <h1 className={styles.homeTitle} id="home-title">
          <span>TEA</span>slator
        </h1>
        <p className={styles.brandTagline}>{BRAND_TAGLINE}</p>
        <button
          className={styles.googleButton}
          type="button"
          onClick={onGoogleEntry}
          ref={googleEntryButtonRef}
        >
          <img
            className={styles.googleLogo}
            src={googleLogo}
            width="20"
            height="20"
            alt=""
          />
          <span>Acceder con Google</span>
        </button>
      </section>
    </main>
  )
}
