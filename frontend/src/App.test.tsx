/**
 * App.test.tsx verifies user-visible coordination across the frontend views.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { DEFAULT_PREFERENCES } from './data/preferences'
import { useApiHealth } from './hooks/useApiHealth'
import { useAuthFlowError } from './hooks/useAuthFlowError'
import { useAuthSession } from './hooks/useAuthSession'
import { useInterpretationWorkspace } from './hooks/useInterpretationWorkspace'
import { useUserPreferences } from './hooks/useUserPreferences'

vi.mock('./hooks/useApiHealth', () => ({ useApiHealth: vi.fn() }))
vi.mock('./hooks/useAuthFlowError', () => ({ useAuthFlowError: vi.fn() }))
vi.mock('./hooks/useAuthSession', () => ({ useAuthSession: vi.fn() }))
vi.mock('./hooks/useInterpretationWorkspace', () => ({
  useInterpretationWorkspace: vi.fn(),
}))
vi.mock('./hooks/useUserPreferences', () => ({ useUserPreferences: vi.fn() }))

const useApiHealthMock = vi.mocked(useApiHealth)
const useAuthFlowErrorMock = vi.mocked(useAuthFlowError)
const useAuthSessionMock = vi.mocked(useAuthSession)
const useInterpretationWorkspaceMock = vi.mocked(useInterpretationWorkspace)
const useUserPreferencesMock = vi.mocked(useUserPreferences)

let apiHealth: ReturnType<typeof useApiHealth>
let authFlow: ReturnType<typeof useAuthFlowError>
let authSession: ReturnType<typeof useAuthSession>
let interpretationWorkspace: ReturnType<typeof useInterpretationWorkspace>
let userPreferences: ReturnType<typeof useUserPreferences>

beforeEach(() => {
  window.sessionStorage.clear()
  apiHealth = {
    apiHealth: { status: 'ok', service: 'django' },
    apiStatusText: 'API conectada',
    healthError: false,
  }
  authFlow = {
    authFlowError: null,
    beginAuthAttempt: vi.fn(),
    clearAuthFlowState: vi.fn(),
  }
  authSession = {
    authStatus: 'unauthenticated',
    logoutStatus: 'idle',
    clearLogoutError: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    retrySessionCheck: vi.fn(),
    startGoogleLogin: vi.fn(),
  }
  interpretationWorkspace = {
    canSubmit: false,
    closeVisualSupport: vi.fn(),
    contextExpanded: false,
    errorMessage: null,
    errorTitle: 'No se pudo interpretar el mensaje',
    interpretation: null,
    interpretationStatus: 'idle',
    openVisualSupport: vi.fn(),
    remainingCharacters: 500,
    request: {
      targetMessage: '',
      previousContext: '',
      previousContextSpeaker: 'unknown',
      followingContext: '',
      followingContextSpeaker: 'unknown',
      externalProcessingAcknowledged: false,
    },
    requestInterpretation: vi.fn().mockResolvedValue(undefined),
    resetInterpretationWorkspace: vi.fn(),
    selectedPictogram: null,
    toggleContext: vi.fn(),
    updateAcknowledgment: vi.fn(),
    updateSpeaker: vi.fn(),
    updateText: vi.fn(),
  }
  userPreferences = {
    preferences: DEFAULT_PREFERENCES,
    preferenceRetryAfterSeconds: null,
    preferenceStatus: 'idle',
    resetPreferences: vi.fn(),
    retryPreferences: vi.fn(),
    updatePreference: vi.fn(),
  }

  useApiHealthMock.mockImplementation(() => apiHealth)
  useAuthFlowErrorMock.mockImplementation(() => authFlow)
  useAuthSessionMock.mockImplementation(() => authSession)
  useInterpretationWorkspaceMock.mockImplementation(
    () => interpretationWorkspace,
  )
  useUserPreferencesMock.mockImplementation(() => userPreferences)
})

afterEach(() => {
  document.documentElement.removeAttribute('data-theme')
  window.sessionStorage.clear()
  vi.clearAllMocks()
})

describe('App', () => {
  it('announces session checking as a non-interrupting status', () => {
    authSession = { ...authSession, authStatus: 'checking' }

    render(<App />)

    expect(screen.getByRole('status')).toHaveTextContent(
      'Estamos comprobando tu sesión de forma segura.',
    )
    expect(screen.getByRole('heading', { name: 'Un momento' })).toBeVisible()
  })

  it('shows a recoverable authentication rate-limit screen', async () => {
    const user = userEvent.setup()
    authFlow = { ...authFlow, authFlowError: 'rate-limited' }

    render(<App />)

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Espera aproximadamente un minuto',
    )
    vi.clearAllMocks()
    await user.click(screen.getByRole('button', { name: 'Volver al inicio' }))
    expect(authFlow.clearAuthFlowState).toHaveBeenCalledOnce()
    expect(interpretationWorkspace.resetInterpretationWorkspace).toHaveBeenCalledOnce()
    expect(userPreferences.resetPreferences).toHaveBeenCalledOnce()
  })

  it('navigates from home to an information page and restores the menu focus', async () => {
    const user = userEvent.setup()
    render(<App />)

    const menuButton = screen.getByRole('button', { name: 'Abrir menú' })
    expect(menuButton).toHaveAttribute('aria-expanded', 'false')
    await user.click(menuButton)
    expect(menuButton).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('dialog', { name: 'TEAslator' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Política de privacidad' }))
    const title = screen.getByRole('heading', { name: 'Política de privacidad' })
    await waitFor(() => expect(title).toHaveFocus())

    await user.click(
      screen.getByRole('button', { name: 'Volver a la página de inicio' }),
    )
    const restoredMenuButton = screen.getByRole('button', { name: 'Abrir menú' })
    await waitFor(() => expect(restoredMenuButton).toHaveFocus())

    await user.click(screen.getByRole('button', { name: 'Acceder con Google' }))
    expect(authFlow.beginAuthAttempt).toHaveBeenCalledOnce()
    expect(authSession.startGoogleLogin).toHaveBeenCalledOnce()
  })

  it('allows interpretation while preference changes are rate-limited', async () => {
    const user = userEvent.setup()
    authSession = { ...authSession, authStatus: 'authenticated' }
    userPreferences = {
      ...userPreferences,
      preferenceRetryAfterSeconds: 30,
      preferenceStatus: 'rate-limited',
    }
    interpretationWorkspace = {
      ...interpretationWorkspace,
      canSubmit: true,
      request: {
        ...interpretationWorkspace.request,
        targetMessage: 'Mensaje sintético para interpretar.',
        externalProcessingAcknowledged: true,
      },
    }

    render(<App />)

    const submit = screen.getByRole('button', { name: 'ENVIAR' })
    expect(submit).toBeEnabled()
    await user.click(submit)
    expect(interpretationWorkspace.requestInterpretation).toHaveBeenCalledWith(
      true,
      true,
    )
  })

  it('coordinates settings, account actions, and successful logout cleanup', async () => {
    const user = userEvent.setup()
    authSession = { ...authSession, authStatus: 'authenticated' }
    userPreferences = { ...userPreferences, preferenceStatus: 'ready' }

    const { rerender } = render(<App />)

    const settings = screen.getByRole('button', { name: 'Ajustes' })
    await user.click(settings)
    expect(settings).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('region', { name: 'Preferencias' })).toBeVisible()

    const account = screen.getByRole('button', { name: 'Cuenta Google' })
    await user.click(account)
    expect(settings).toHaveAttribute('aria-expanded', 'false')
    expect(account).toHaveAttribute('aria-expanded', 'true')
    await user.click(screen.getByRole('button', { name: 'Cerrar sesión' }))

    await waitFor(() => expect(authSession.logout).toHaveBeenCalledOnce())
    expect(interpretationWorkspace.resetInterpretationWorkspace).toHaveBeenCalledOnce()
    expect(userPreferences.resetPreferences).toHaveBeenCalledOnce()
    expect(authFlow.clearAuthFlowState).toHaveBeenCalledOnce()

    authSession = { ...authSession, authStatus: 'unauthenticated' }
    rerender(<App />)
    const googleEntry = screen.getByRole('button', { name: 'Acceder con Google' })
    await waitFor(() => expect(googleEntry).toHaveFocus())
  })
})
