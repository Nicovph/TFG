/**
 * InterpretationWorkspace.test.tsx verifies the accessible interpretation flow.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ComponentProps } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { Interpretation } from '../types'
import { InterpretationWorkspace } from './InterpretationWorkspace'

type WorkspaceProps = ComponentProps<typeof InterpretationWorkspace>

const request: WorkspaceProps['request'] = {
  targetMessage: 'Necesito ayuda para entender este mensaje.',
  previousContext: '',
  previousContextSpeaker: 'unknown',
  followingContext: '',
  followingContextSpeaker: 'unknown',
  externalProcessingAcknowledged: false,
}
const interpretation: Interpretation = {
  interpretation: 'La persona solicita ayuda de forma directa.',
  clearReformulation: 'Ayúdame a entender este mensaje.',
  needsMoreContext: false,
  contextNote: '',
  signals: [],
  visualConcepts: [],
  showContentWarning: false,
  visualSupport: null,
}

/**
 * Render the workspace with isolated callbacks and optional state overrides.
 *
 * Args:
 *   overrides: Properties that replace the representative ready state.
 *
 * Returns:
 *   The complete properties passed to the rendered workspace.
 */
function renderWorkspace(overrides: Partial<WorkspaceProps> = {}): WorkspaceProps {
  const props: WorkspaceProps = {
    canSubmit: true,
    contextExpanded: false,
    errorMessage: null,
    errorTitle: 'No se pudo interpretar el mensaje',
    interpretation: null,
    interpretationStatus: 'idle',
    logoSrc: '/test-logo.png',
    preferenceStatus: 'ready',
    remainingCharacters: 458,
    request,
    visualSupportEnabled: true,
    onAcknowledgmentChange: vi.fn(),
    onContextToggle: vi.fn(),
    onSpeakerChange: vi.fn(),
    onSubmit: vi.fn().mockResolvedValue(undefined),
    onTextChange: vi.fn(),
    onVisualSupportOpen: vi.fn(),
    ...overrides,
  }

  render(<InterpretationWorkspace {...props} />)
  return props
}

describe('InterpretationWorkspace', () => {
  it('requires explicit acknowledgment before the first external request', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace()

    await user.click(screen.getByRole('button', { name: 'ENVIAR' }))
    const dialog = screen.getByRole('dialog', { name: 'Procesamiento externo' })
    expect(dialog).toHaveAttribute('open')
    expect(props.onSubmit).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Continuar y enviar' }))
    expect(dialog).not.toHaveAttribute('open')
    expect(props.onAcknowledgmentChange).toHaveBeenCalledWith(true)
    expect(props.onSubmit).toHaveBeenCalledWith(true, true)
  })

  it('keeps interpretation available while preference updates are rate-limited', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace({
      preferenceStatus: 'rate-limited',
      request: { ...request, externalProcessingAcknowledged: true },
      visualSupportEnabled: false,
    })

    const submit = screen.getByRole('button', { name: 'ENVIAR' })
    expect(submit).toBeEnabled()
    expect(screen.queryByText(/preferencias antes de enviar/)).toBeNull()
    await user.click(submit)
    expect(props.onSubmit).toHaveBeenCalledWith(true, false)
  })

  it('exposes optional context with speaker controls only for present messages', async () => {
    const user = userEvent.setup()
    const props = renderWorkspace({
      contextExpanded: true,
      request: {
        ...request,
        previousContext: 'Este es el mensaje anterior.',
      },
    })

    const previousSpeakerSelector = screen.getByRole('combobox', {
      name: '¿Quién escribió el mensaje anterior?',
    })
    const followingSpeakerSelector = screen.getByRole('combobox', {
      name: '¿Quién escribió el mensaje posterior?',
    })
    expect(previousSpeakerSelector).toBeEnabled()
    expect(followingSpeakerSelector).toBeDisabled()
    await user.selectOptions(previousSpeakerSelector, 'different_from_target_author')
    expect(props.onSpeakerChange).toHaveBeenCalledWith(
      'previousContextSpeaker',
      'different_from_target_author',
    )

    await user.click(screen.getByRole('button', { name: 'Quitar y borrar contexto' }))
    expect(props.onContextToggle).toHaveBeenCalledOnce()
  })

  it('announces loading outside the busy result region', () => {
    renderWorkspace({ interpretationStatus: 'loading' })

    const resultRegion = screen.getByRole('region', {
      name: 'Resultado de la interpretación',
    })
    const loadingStatus = screen.getByRole('status')

    expect(resultRegion).toHaveAttribute('aria-busy', 'true')
    expect(loadingStatus).toHaveTextContent('Interpretando el mensaje…')
    expect(resultRegion).not.toContainElement(loadingStatus)
  })

  it('moves focus to a newly rendered interpretation', async () => {
    renderWorkspace({ interpretation, interpretationStatus: 'ready' })

    const heading = screen.getByRole('heading', { name: 'Interpretación' })
    await waitFor(() => expect(heading).toHaveFocus())
    expect(screen.getByText(interpretation.interpretation)).toBeVisible()
  })
})
