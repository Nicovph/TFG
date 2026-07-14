/**
 * App.tsx coordinates the local TEAslator interface state and delegates each
 * view to focused components.
 */

import { useEffect, useRef, useState } from 'react'
import type { SubmitEvent } from 'react'
import logoMark from './assets/Cerebro_logo_app.png'
import { getMockInterpretation } from './api'
import { AppHeader } from './components/AppHeader'
import { Drawer } from './components/Drawer'
import { HomeView } from './components/HomeView'
import { InfoView } from './components/InfoView'
import { InterpretationWorkspace } from './components/InterpretationWorkspace'
import { StatusView } from './components/StatusView'
import { VisualSupportDialog } from './components/VisualSupportDialog'
import { INFO_PAGES, isInfoView } from './data/infoPages'
import type { AppView } from './data/infoPages'
import { DEFAULT_PREFERENCES } from './data/preferences'
import type { PreferenceChangeHandler, PreferenceState } from './data/preferences'
import { useAuthSession } from './hooks/useAuthSession'
import { useApiHealth } from './hooks/useApiHealth'
import type { MockInterpretation } from './types'

const MAX_MESSAGE_LENGTH = 500
const VIEW_STORAGE_KEY = 'teaslator.currentView'
// Use to remember if an info page must return to home or main.
const INFO_RETURN_STORAGE_KEY = 'teaslator.infoReturnView'
/** It serves to indicate that the user of the current tab voluntarily initiated
 * a Google authentication flow, allowing the marker to persist through the temporary
 * departure to Google and the return to the same tab, while preventing it from persisting
 * indefinitely.
 */
const AUTH_ATTEMPT_STORAGE_KEY = 'teaslator.authAttemptPending'
const AUTH_ERROR_FRAGMENT = '#auth-error'

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
 * Remove the generic authentication error marker (#auth-error) from the browser URL.
 * Prevents the user from seeing #auth-error in the address bar after viewing the message.
 */
function clearAuthErrorFragment(): void {
  /**
   * If the window type is undefined or the hash (string containing '#' follow by the fragment identifier of the location URL) is not #auth-error.
   */
  if (typeof window === 'undefined' || window.location.hash !== AUTH_ERROR_FRAGMENT) {
    return
  }

  /**
   * history.replaceState is an API to modify the current URL without reload the page and without adding a new entrance in the browser history.
   * null: The history status is not modified.
   * document.title: Mantain the page title.
   * The last argument rebuilds the URL without the hash.
   */
  window.history.replaceState(
    null,
    document.title,
    `${window.location.pathname}${window.location.search}`,
  )
}

/**
 * Check for an authentication error produced by a user-initiated flow.
 *
 * Returns:
 *   True only when the URL error marker and the local attempt marker are both present
 * (there was a recent error).
 * This prevents the error message from appearing when the user reloads the page or accesses a URL with #auth-error.
 */
function hasAuthFlowError(): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  /**
   * Only return True if there is an error in the URL and there was a pending authentication attempt.
   */
  return (
    window.location.hash === AUTH_ERROR_FRAGMENT &&
    window.sessionStorage.getItem(AUTH_ATTEMPT_STORAGE_KEY) === 'true'
  )
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
  /**
   * It keeps the message in React memory only, due to the use of the useState hook.
   */
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
  const [authFlowError, setAuthFlowError] = useState(hasAuthFlowError)
  // These references restore focus only after returning from an informational page.
  const homeMenuButtonRef = useRef<HTMLButtonElement>(null)
  const workspaceMenuButtonRef = useRef<HTMLButtonElement>(null)
  const pendingInfoReturnFocusRef = useRef<'home' | 'main' | null>(null)
  const {
    authStatus,
    clearLogoutError,
    logout,
    logoutStatus,
    retrySessionCheck,
    startGoogleLogin,
  } = useAuthSession()
  const { apiReady, apiStatusText } = useApiHealth()

  const remainingCharacters = MAX_MESSAGE_LENGTH - message.length
  const canSubmit = message.trim().length > 0 && interpretationStatus !== 'loading'
  const renderedView: AppView =
    authStatus === 'authenticated' && currentView === 'home'
      ? 'main'
      : authStatus !== 'authenticated' && currentView === 'main'
        ? 'home'
        : currentView

  /**
   * The user returns to the page stored in infoReturnView, unless they attempt to 
   * return to "home" from "main" or vice versa.
   */
  const resolvedInfoReturnView: 'home' | 'main' =
    authStatus === 'authenticated' && infoReturnView === 'home'
      ? 'main'
      : authStatus !== 'authenticated' && infoReturnView === 'main'
        ? 'home'
        : infoReturnView
  const infoReturnLabel =
    resolvedInfoReturnView === 'main'
      ? 'Volver al área de interpretación'
      : 'Volver a la página de inicio'
  const infoPage = isInfoView(renderedView) ? INFO_PAGES[renderedView] : null
  const showVisualSupport = preferences.visualSupport === 'enabled' && interpretation !== null

  /**
   * Updates the storage whenever the view changes.
   */
  useEffect(() => {
    window.sessionStorage.setItem(VIEW_STORAGE_KEY, currentView)
  }, [currentView])

  useEffect(() => {
    window.sessionStorage.setItem(INFO_RETURN_STORAGE_KEY, infoReturnView)
  }, [infoReturnView])

  useEffect(() => {
    const pendingDestination = pendingInfoReturnFocusRef.current

    if (!pendingDestination || renderedView !== pendingDestination) {
      return
    }

    const focusTarget =
      pendingDestination === 'main' ? workspaceMenuButtonRef.current : homeMenuButtonRef.current

    if (focusTarget) {
      focusTarget.focus()
      pendingInfoReturnFocusRef.current = null
    }
  }, [renderedView])

  useEffect(() => {
    if (window.location.hash !== AUTH_ERROR_FRAGMENT) {
      return
    }

    window.sessionStorage.removeItem(AUTH_ATTEMPT_STORAGE_KEY)
    clearAuthErrorFragment()
  }, [])

  /**
   * Prevents the mark from persisting after the check is resolved.
   */
  useEffect(() => {
    if (authStatus !== 'checking') {
      window.sessionStorage.removeItem(AUTH_ATTEMPT_STORAGE_KEY)
    }
  }, [authStatus])

  /**
   * Close overlays and popovers that should not survive navigation.
   * Prevents floating elements from persisting when switching views.
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

    if (nextView === 'main' && authStatus !== 'authenticated') {
      setInfoReturnView('home')
      setCurrentView('home')
      return
    }

    if (isInfoView(nextView) && !isInfoView(renderedView)) {
      setInfoReturnView(renderedView === 'main' ? 'main' : 'home')
    }

    setCurrentView(nextView)
  }

  /**
   * Return from an informational page and restore focus in the rendered destination.
   *
   * Args:
   *   None.
   *
   * Returns:
   *   Nothing.
   */
  const handleInfoReturn = () => {
    pendingInfoReturnFocusRef.current = resolvedInfoReturnView
    handleNavigate(resolvedInfoReturnView)
  }

  /**
   * Start the backend-managed Google authentication flow.
   */
  const handleGoogleEntry = () => {
    closeTransientPanels()
    setAuthFlowError(false)
    window.sessionStorage.setItem(AUTH_ATTEMPT_STORAGE_KEY, 'true')
    startGoogleLogin()
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
  const clearLocalSessionState = () => {
    closeTransientPanels()
    window.sessionStorage.removeItem(VIEW_STORAGE_KEY)
    window.sessionStorage.removeItem(INFO_RETURN_STORAGE_KEY)
    window.sessionStorage.removeItem(AUTH_ATTEMPT_STORAGE_KEY)
    setAuthFlowError(false)
    setMessage('')
    setInterpretation(null)
    setInterpretationStatus('idle')
    setPreferences(DEFAULT_PREFERENCES)
    setInfoReturnView('home')
    setCurrentView('home')
  }

  /**
   * Request backend logout and clear transient user-entered state on success.
   */
  const handleLogout = () => {
    logout()
      .then(() => {
        clearLocalSessionState()
      })
      .catch(() => {
        return undefined
      })
  }

  /**
   * Leave a recoverable authentication error and return to the start screen.
   */
  const handleReturnHomeFromAuthError = () => {
    setAuthFlowError(false)
    clearLocalSessionState()
  }

  /**
   * Leave a recoverable logout error and keep the authenticated workspace visible.
   */
  const handleReturnToWorkspaceFromLogoutError = () => {
    clearLogoutError()
    closeTransientPanels()
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

  if (authFlowError) {
    return (
      <StatusView
        logoSrc={logoMark}
        message="No se pudo completar el inicio de sesión. Vuelve a intentarlo más tarde."
        mode="error"
        primaryAction={{ label: 'Intentar de nuevo', onClick: handleGoogleEntry }}
        secondaryAction={{ label: 'Volver al inicio', onClick: handleReturnHomeFromAuthError }}
        title="No pudimos iniciar sesión"
      />
    )
  }

  if (authStatus === 'checking') {
    return (
      <StatusView
        logoSrc={logoMark}
        message="Estamos comprobando tu sesión de forma segura."
        mode="loading"
        title="Un momento"
      />
    )
  }

  if (authStatus === 'error') {
    return (
      <StatusView
        logoSrc={logoMark}
        message="No se pudo comprobar tu sesión. Inténtalo de nuevo."
        mode="error"
        primaryAction={{ label: 'Reintentar', onClick: retrySessionCheck }}
        title="No pudimos comprobar tu sesión"
      />
    )
  }

  if (logoutStatus === 'error') {
    return (
      <StatusView
        logoSrc={logoMark}
        message="No pudimos cerrar la sesión desde aquí. Puedes reintentarlo sin perder lo que ves en pantalla."
        mode="error"
        primaryAction={{ label: 'Reintentar cierre', onClick: handleLogout }}
        secondaryAction={{ label: 'Volver', onClick: handleReturnToWorkspaceFromLogoutError }}
        title="No se cerró la sesión"
      />
    )
  }

  return (
    <>
      {/* Keep every normal view in one inert subtree while the modal drawer is open. */}
      <div id="app-content" inert={menuOpen}>
        {renderedView === 'home' ? (
          <HomeView
            logoSrc={logoMark}
            menuButtonRef={homeMenuButtonRef}
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
            onReturn={handleInfoReturn}
            onMenuToggle={handleMenuToggle}
            returnLabel={infoReturnLabel}
          />
        ) : null}

        {renderedView === 'main' ? (
          <main>
            <AppHeader
              accountOpen={accountOpen}
              apiReady={apiReady}
              apiStatusText={apiStatusText}
              logoutStatus={logoutStatus}
              menuButtonRef={workspaceMenuButtonRef}
              menuOpen={menuOpen}
              preferences={preferences}
              settingsOpen={settingsOpen}
              onAccountToggle={handleAccountToggle}
              onClosePopovers={closePopovers}
              onLogout={handleLogout}
              onMenuToggle={handleMenuToggle}
              onNavigateWorkspace={() => handleNavigate('main')}
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
      </div>

      <Drawer open={menuOpen} onClose={closeTransientPanels} onNavigate={handleNavigate} />

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
