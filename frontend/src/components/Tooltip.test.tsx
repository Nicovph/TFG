/**
 * Tooltip.test.tsx verifies dismissible keyboard and pointer hints.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Tooltip } from './Tooltip'

describe('Tooltip', () => {
  it('shows on keyboard focus and dismisses with Escape without moving focus', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Información adicional">
        <button type="button">Ayuda</button>
      </Tooltip>,
    )

    const button = screen.getByRole('button', { name: 'Ayuda' })
    await user.tab()
    expect(button).toHaveFocus()
    expect(screen.getByText('Información adicional')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByText('Información adicional')).toBeNull()
    expect(button).toHaveFocus()
  })

  it('hides on pointer activation and ignores touch hover', async () => {
    const user = userEvent.setup()
    render(
      <Tooltip label="Información adicional">
        <button type="button">Ayuda</button>
      </Tooltip>,
    )

    const button = screen.getByRole('button', { name: 'Ayuda' })
    await user.hover(button)
    expect(screen.getByText('Información adicional')).toBeInTheDocument()
    fireEvent.pointerDown(button, { pointerType: 'mouse' })
    expect(screen.queryByText('Información adicional')).toBeNull()
    await user.unhover(button)

    fireEvent.pointerEnter(button, { pointerType: 'touch' })
    expect(screen.queryByText('Información adicional')).toBeNull()
  })
})
