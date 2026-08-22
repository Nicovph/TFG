/**
 * App.tsx coordinates the local TEAslator interface state and delegates each
 * view to focused components.
 */

import { useEffect, useRef, useState } from 'react'
import logoMark from './assets/Cerebro_logo_app.png'
import { AppHeader } from './components/AppHeader'
import { Drawer } from './components/Drawer'
import { HomeView } from './components/HomeView'
import { InfoView } from './components/InfoView'
import { InterpretationWorkspace } from './components/InterpretationWorkspace'
import { StatusView } from './components/StatusView'
import { VisualSupportDialog } from './components/VisualSupportDialog'
import { INFO_PAGES, isInfoView } from './data/infoPages'
import type { AppView } from './data/infoPages'
import { useAuthFlowError } from './hooks/useAuthFlowError'
import { useAuthSession } from './hooks/useAuthSession'
import { useApiHealth } from './hooks/useApiHealth'
import { useInterpretationWorkspace } from './hooks/useInterpretationWorkspace'
import { useUserPreferences } from './hooks/useUserPreferences'
import {
  readSessionStorage,
  removeSessionStorage,
  writeSessionStorage,
} from './utils/sessionStorage'

const VIEW_STORAGE_KEY = 'teaslator.currentView'
// Use to remember if an info page must return to home or main.
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
  const storedView = readSessionStorage(VIEW_STORAGE_KEY)
  return isAppView(storedView) ? storedView : 'home'
}

/**
 * Read the last return target for informational pages.
 *
 * Returns:
 *   The stored return target, or home when the stored value is invalid.
 */
function getStoredInfoReturnView(): 'home' | 'main' {
  const storedReturnView = readSessionStorage(INFO_RETURN_STORAGE_KEY)
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
  const [menuOpen, setMenuOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [accountOpen, setAccountOpen] = useState(false)
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
  const { authFlowError, beginAuthAttempt, clearAuthFlowState } =
    useAuthFlowError(authStatus)
  const {
    canSubmit,
    closeVisualSupport,
    contextExpanded,
    errorMessage,
    errorTitle,
    interpretation,
    interpretationStatus,
    openVisualSupport,
    remainingCharacters,
    request,
    requestInterpretation,
    resetInterpretationWorkspace,
    selectedPictogram,
    toggleContext,
    updateAcknowledgment,
    updateSpeaker,
    updateText,
  } = useInterpretationWorkspace()
  const {
    preferences,
    preferenceRetryAfterSeconds,
    preferenceStatus,
    resetPreferences,
    retryPreferences,
    updatePreference,
  } = useUserPreferences(authStatus)
  const { apiStatusText } = useApiHealth()

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
  const visualSupportEnabled = preferences.visualSupport === 'enabled'
  const preferencesUsable =
    preferenceStatus === 'ready' || preferenceStatus === 'rate-limited'

  /**
   * Updates the storage whenever the view changes.
   */
  useEffect(() => {
    writeSessionStorage(VIEW_STORAGE_KEY, currentView)
  }, [currentView])

  useEffect(() => {
    writeSessionStorage(INFO_RETURN_STORAGE_KEY, infoReturnView)
  }, [infoReturnView])

  /**
   * Applies the user's theme preference globally by setting the data-theme
   * attribute on the document root (<html> element). This enables theme-based
   * CSS selectors across all application views.
   */
  useEffect(() => {
    document.documentElement.dataset.theme = preferences.theme
  }, [preferences.theme])

  useEffect(() => {
    const pendingDestination = pendingInfoReturnFocusRef.current

    if (!pendingDestination || renderedView !== pendingDestination) {
      return
    }

    const focusTarget =
      pendingDestination === 'main' ? workspaceMenuButtonRef.current : homeMenuButtonRef.current

    if (focusTarget) {
      focusTarget.focus()
    }

    // Do not retain an impossible focus request if the destination has no target.
    pendingInfoReturnFocusRef.current = null
  }, [renderedView])

  /**
   * Remove transient content if Django explicitly resolves the session as absent.
   * A temporary session-check error deliberately preserves the visible workspace.
   */
  useEffect(() => {
    if (authStatus !== 'unauthenticated') {
      return
    }

    resetInterpretationWorkspace()
    resetPreferences()
  }, [authStatus, resetInterpretationWorkspace, resetPreferences])

  /**
   * Close overlays and popovers that should not survive navigation.
   * Prevents floating elements from persisting when switching views.
   *
   * Returns:
   *   Nothing.
   */
  const closeTransientPanels = () => {
    setMenuOpen(false)
    setSettingsOpen(false)
    setAccountOpen(false)
    closeVisualSupport()
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
   *
   * Returns:
   *   Nothing.
   */
  const handleGoogleEntry = () => {
    closeTransientPanels()
    beginAuthAttempt()
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
   *
   * Returns:
   *   Nothing.
   */
  const clearLocalSessionState = () => {
    closeTransientPanels()
    // Clear user-entered data before touching optional browser storage.
    resetInterpretationWorkspace()
    resetPreferences()
    setInfoReturnView('home')
    setCurrentView('home')
    clearAuthFlowState()
    removeSessionStorage(VIEW_STORAGE_KEY)
    removeSessionStorage(INFO_RETURN_STORAGE_KEY)
  }

  /**
   * Request backend logout and clear transient user-entered state on success.
   *
   * Returns:
   *   A promise that resolves after success or after exposing a recoverable error.
   */
  const handleLogout = async () => {
    try {
      await logout()
      clearLocalSessionState()
    } catch {
      // useAuthSession exposes logoutStatus === 'error' for accessible recovery UI.
    }
  }

  /**
   * Leave a recoverable authentication error and return to the start screen.
   */
  const handleReturnHomeFromAuthError = () => {
    clearLocalSessionState()
  }

  /**
   * Leave a recoverable logout error and keep the authenticated workspace visible.
   */
  const handleReturnToWorkspaceFromLogoutError = () => {
    clearLogoutError()
    closeTransientPanels()
  }

  if (authFlowError === 'rate-limited') {
    return (
      <StatusView
        logoSrc={logoMark}
        message="Se han realizado varios intentos de inicio de sesión seguidos. Espera aproximadamente un minuto antes de volver a intentarlo."
        mode="error"
        primaryAction={{ label: 'Volver al inicio', onClick: handleReturnHomeFromAuthError }}
        title="Espera antes de volver a intentarlo"
      />
    )
  }

  if (authFlowError === 'authentication-failed') {
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
              apiStatusText={apiStatusText}
              logoutStatus={logoutStatus}
              menuButtonRef={workspaceMenuButtonRef}
              menuOpen={menuOpen}
              preferences={preferences}
              preferenceRetryAfterSeconds={preferenceRetryAfterSeconds}
              preferenceStatus={preferenceStatus}
              settingsOpen={settingsOpen}
              onAccountToggle={handleAccountToggle}
              onClosePopovers={closePopovers}
              onLogout={handleLogout}
              onMenuToggle={handleMenuToggle}
              onNavigateWorkspace={() => handleNavigate('main')}
              onPreferenceChange={updatePreference}
              onPreferencesRetry={retryPreferences}
              onSettingsToggle={handleSettingsToggle}
            />
            {/* Block submission only while preferences are pending or uncertain. */}
            <InterpretationWorkspace
              canSubmit={canSubmit && preferencesUsable}
              contextExpanded={contextExpanded}
              errorMessage={errorMessage}
              errorTitle={errorTitle}
              interpretation={interpretation}
              interpretationStatus={interpretationStatus}
              logoSrc={logoMark}
              preferenceStatus={preferenceStatus}
              remainingCharacters={remainingCharacters}
              request={request}
              visualSupportEnabled={visualSupportEnabled}
              onAcknowledgmentChange={updateAcknowledgment}
              onContextToggle={toggleContext}
              onSpeakerChange={updateSpeaker}
              onSubmit={requestInterpretation}
              onTextChange={updateText}
              onVisualSupportOpen={openVisualSupport}
            />
          </main>
        ) : null}
      </div>

      <Drawer open={menuOpen} onClose={closeTransientPanels} onNavigate={handleNavigate} />

      {selectedPictogram ? (
        <VisualSupportDialog
          pictogram={selectedPictogram}
          onClose={closeVisualSupport}
        />
      ) : null}
    </>
  )
}

export default App
