/**
 * App.tsx coordinates the local TEAslator interface state and delegates each
 * view to focused components.
 */

import { useEffect, useState } from 'react'
import type { SubmitEvent } from 'react'
import logoMark from './assets/Cerebro_logo_app.png'
import { getMockInterpretation } from './api'
import { AppHeader } from './components/AppHeader'
import { Drawer } from './components/Drawer'
import { HomeView } from './components/HomeView'
import { InfoView } from './components/InfoView'
import { InterpretationWorkspace } from './components/InterpretationWorkspace'
import { VisualSupportDialog } from './components/VisualSupportDialog'
import { INFO_PAGES, isInfoView } from './data/infoPages'
import type { AppView } from './data/infoPages'
import { DEFAULT_PREFERENCES } from './data/preferences'
import type { PreferenceChangeHandler, PreferenceState } from './data/preferences'
import { useApiHealth } from './hooks/useApiHealth'
import type { MockInterpretation } from './types'

const MAX_MESSAGE_LENGTH = 500
const VIEW_STORAGE_KEY = 'teaslator.currentView'
const INFO_RETURN_STORAGE_KEY = 'teaslator.infoReturnView'

/**
 * Check whether a stored string matches a valid application view.
 *
 * Args:
 *   view: The value read from browser session storage.
 *
 * Returns:
 *   True when the value is a supported app view.
 */
function isAppView(view: string | null): view is AppView {
  return (
    view === 'home' ||
    view === 'main' ||
    view === 'about' ||
    view === 'privacy' ||
    view === 'terms'
  )
}

/**
 * Read the last local view without storing user text or interpretation data.
 *
 * Returns:
 *   The last stored view, or home when no valid view has been stored.
 */
function getStoredView(): AppView {
  if (typeof window === 'undefined') {
    return 'home'
  }

  const storedView = window.sessionStorage.getItem(VIEW_STORAGE_KEY)
  return isAppView(storedView) ? storedView : 'home'
}

/**
 * Read the last return target for informational pages.
 *
 * Returns:
 *   The stored return target, or home when the stored value is invalid.
 */
function getStoredInfoReturnView(): 'home' | 'main' {
  if (typeof window === 'undefined') {
    return 'home'
  }

  const storedReturnView = window.sessionStorage.getItem(INFO_RETURN_STORAGE_KEY)
  return storedReturnView === 'main' ? 'main' : 'home'
}

/**
 * Render the TEAslator single-page interface and keep transient UI state local.
 *
 * Returns:
 *   The React application element.
 */
function App() {
  // const [estado, setEstado] = useState(valorInicial);
  const [currentView, setCurrentView] = useState<AppView>(() => getStoredView())
  const [infoReturnView, setInfoReturnView] = useState<'home' | 'main'>(() =>
    getStoredInfoReturnView(),
  )
  const [message, setMessage] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
  const [preferences, setPreferences] = useState<PreferenceState>(DEFAULT_PREFERENCES)
  const [selectedVisualLabel, setSelectedVisualLabel] = useState<string | null>(null)
  const [interpretation, setInterpretation] = useState<MockInterpretation | null>(null)
  const [interpretationStatus, setInterpretationStatus] = useState<
    'idle' | 'loading' | 'ready' | 'error'
  >('idle')
  const { apiReady, apiStatusText } = useApiHealth()

  const remainingCharacters = MAX_MESSAGE_LENGTH - message.length
  const canSubmit = message.trim().length > 0 && interpretationStatus !== 'loading'
  const infoPage = isInfoView(currentView) ? INFO_PAGES[currentView] : null
  const showVisualSupport = preferences.visualSupport === 'enabled' && interpretation !== null

  useEffect(() => {
    window.sessionStorage.setItem(VIEW_STORAGE_KEY, currentView)
  }, [currentView])

  useEffect(() => {
    window.sessionStorage.setItem(INFO_RETURN_STORAGE_KEY, infoReturnView)
  }, [infoReturnView])

  /**
   * Close overlays and popovers that should not survive navigation.
   */
  const closeTransientPanels = () => {
    setMenuOpen(false)
    setSettingsOpen(false)
    setAccountOpen(false)
    setSelectedVisualLabel(null)
  }

  /**
   * Navigate between local app views.
   *
   * Args:
   *   nextView: The next view selected by the user.
   */
  const handleNavigate = (nextView: AppView) => {
    closeTransientPanels()

    if (isInfoView(nextView) && !isInfoView(currentView)) {
      setInfoReturnView(currentView === 'main' ? 'main' : 'home')
    }

    setCurrentView(nextView)
  }

  /**
   * Enter the main workspace after the placeholder Google sign-in action.
   */
  const handleGoogleEntry = () => {
    closeTransientPanels()
    setInfoReturnView('main')
    setCurrentView('main')
  }

  /**
   * Toggle the lateral navigation drawer.
   */
  const handleMenuToggle = () => {
    setMenuOpen((current) => !current) // Toggle the menu open state.
    setSettingsOpen(false) // Close the settings popover if it was open.
    setAccountOpen(false) // Close the account popover if it was open.
  }

  /**
   * Toggle the user preferences popover.
   */
  const handleSettingsToggle = () => {
    setSettingsOpen((current) => !current)
    setAccountOpen(false)
  }

  /**
   * Toggle the account action popover.
   */
  const handleAccountToggle = () => {
    setAccountOpen((current) => !current)
    setSettingsOpen(false)
  }

  /**
   * Close header popovers.
   */
  const closePopovers = () => {
    setSettingsOpen(false)
    setAccountOpen(false)
  }

  /**
   * Return to the start screen and clear transient user-entered state.
   */
  const handleLogout = () => {
    closeTransientPanels()
    window.sessionStorage.removeItem(VIEW_STORAGE_KEY)
    window.sessionStorage.removeItem(INFO_RETURN_STORAGE_KEY)
    setMessage('')
    setInterpretation(null)
    setInterpretationStatus('idle')
    setInfoReturnView('home')
    setCurrentView('home')
  }

  /**
   * Update a typed local preference value.
   *
   * Args:
   *   key: The preference field being changed.
   *   value: The validated value for that field.
   */
  const handlePreferenceChange: PreferenceChangeHandler = (key, value) => {
    setPreferences((current) => ({
      ...current, // Spread the current preferences to retain unchanged values.
      [key]: value, // Update the specific preference field with the new value.
    }))
  }

  /**
   * Update the message and clear stale interpretation output when input is empty.
   *
   * Args:
   *   nextMessage: The latest text entered by the user.
   */
  const handleMessageChange = (nextMessage: string) => {
    setMessage(nextMessage)

    if (nextMessage.trim().length === 0) {
      setInterpretation(null)
      setInterpretationStatus('idle')
      setSelectedVisualLabel(null)
    }
  }

  /**
   * Submit the local form and request a fixed mock result without sending text.
   *
   * Args:
   *   event: The form submission event.
   */
  const handleSubmit = (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault()

    if (!canSubmit) {
      return
    }

    setInterpretationStatus('loading')

    getMockInterpretation()
      .then((payload) => { // Promise.then(callback). It allows asynchronous code to be executed sequentially.
        setInterpretation(payload)
        setInterpretationStatus('ready')
      })
      .catch(() => {
        setInterpretationStatus('error')
      })
  }

  return (
    <>
      <Drawer open={menuOpen} onClose={closeTransientPanels} onNavigate={handleNavigate} />

      {currentView === 'home' ? (
        <HomeView
          logoSrc={logoMark}
          menuOpen={menuOpen}
          onGoogleEntry={handleGoogleEntry}
          onMenuToggle={handleMenuToggle}
        />
      ) : null}

      {infoPage ? (
        <InfoView
          infoPage={infoPage}
          logoSrc={logoMark}
          menuOpen={menuOpen}
          onReturn={() => handleNavigate(infoReturnView)}
          onMenuToggle={handleMenuToggle}
        />
      ) : null}

      {currentView === 'main' ? (
        <main>
          <AppHeader
            accountOpen={accountOpen}
            apiReady={apiReady}
            apiStatusText={apiStatusText}
            menuOpen={menuOpen}
            preferences={preferences}
            settingsOpen={settingsOpen}
            onAccountToggle={handleAccountToggle}
            onClosePopovers={closePopovers}
            onLogout={handleLogout}
            onMenuToggle={handleMenuToggle}
            onNavigateHome={() => handleNavigate('main')}
            onPreferenceChange={handlePreferenceChange}
            onSettingsToggle={handleSettingsToggle}
          />
          <InterpretationWorkspace
            canSubmit={canSubmit}
            interpretation={interpretation}
            interpretationStatus={interpretationStatus}
            logoSrc={logoMark}
            maxMessageLength={MAX_MESSAGE_LENGTH}
            message={message}
            remainingCharacters={remainingCharacters}
            showVisualSupport={showVisualSupport}
            onVisualSupportOpen={setSelectedVisualLabel}
            onMessageChange={handleMessageChange}
            onSubmit={handleSubmit}
          />
        </main>
      ) : null}

      {selectedVisualLabel ? (
        <VisualSupportDialog
          visualLabel={selectedVisualLabel}
          logoSrc={logoMark}
          onClose={() => setSelectedVisualLabel(null)}
        />
      ) : null}
    </>
  )
}

export default App
