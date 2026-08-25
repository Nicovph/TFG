/**
 * PreferencesPanel.test.tsx verifies accessible preference controls and feedback.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_PREFERENCES } from '../data/preferences'
import { PreferencesPanel } from './PreferencesPanel'

describe('PreferencesPanel', () => {
  it('disables every control and omits retry while preferences are rate-limited', () => {
    render(
      <PreferencesPanel
        open
        preferences={DEFAULT_PREFERENCES}
        retryAfterSeconds={86_400}
        status="rate-limited"
        onPreferenceChange={vi.fn()}
        onRetry={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('1 día')
    expect(screen.queryByRole('button', { name: 'Recargar preferencias' })).toBeNull()
    for (const control of screen.getAllByRole('combobox')) {
      expect(control).toBeDisabled()
    }
  })

  it('offers recovery but keeps controls disabled after an uncertain save error', async () => {
    const user = userEvent.setup()
    const onRetry = vi.fn()
    render(
      <PreferencesPanel
        open
        preferences={DEFAULT_PREFERENCES}
        retryAfterSeconds={null}
        status="save-error"
        onPreferenceChange={vi.fn()}
        onRetry={onRetry}
      />,
    )

    const retryButton = screen.getByRole('button', { name: 'Recargar preferencias' })
    expect(screen.getByRole('combobox', { name: 'Tema de la aplicación' })).toBeDisabled()
    await user.click(retryButton)
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('reports a validated change from an enabled labeled selector', async () => {
    const user = userEvent.setup()
    const onPreferenceChange = vi.fn()
    render(
      <PreferencesPanel
        open
        preferences={DEFAULT_PREFERENCES}
        retryAfterSeconds={null}
        status="ready"
        onPreferenceChange={onPreferenceChange}
        onRetry={vi.fn()}
      />,
    )

    const theme = screen.getByRole('combobox', { name: 'Tema de la aplicación' })
    await user.selectOptions(theme, 'dark')

    expect(onPreferenceChange).toHaveBeenCalledWith('theme', 'dark')
  })
})
