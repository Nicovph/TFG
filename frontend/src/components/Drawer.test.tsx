/**
 * Drawer.test.tsx verifies modal navigation and keyboard focus management.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Drawer } from './Drawer'

afterEach(() => vi.restoreAllMocks())

describe('Drawer', () => {
  it('contains keyboard focus, closes with Escape, and restores the invoker', async () => {
    vi.spyOn(HTMLElement.prototype, 'offsetParent', 'get').mockReturnValue(
      document.body,
    )
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onNavigate = vi.fn()
    const { rerender } = render(
      <>
        <button type="button">Abrir navegación</button>
        <Drawer open={false} onClose={onClose} onNavigate={onNavigate} />
      </>,
    )
    const invoker = screen.getByRole('button', { name: 'Abrir navegación' })
    invoker.focus()

    rerender(
      <>
        <button type="button">Abrir navegación</button>
        <Drawer open onClose={onClose} onNavigate={onNavigate} />
      </>,
    )
    const closeButtons = screen.getAllByRole('button', { name: 'Cerrar menú' })
    const closeButton = closeButtons.find((button) => button.tabIndex === 0)
    expect(closeButton).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Condiciones de uso' })).toHaveFocus()
    await user.tab()
    expect(closeButton).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(onClose).not.toHaveBeenCalled()
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()

    rerender(
      <>
        <button type="button">Abrir navegación</button>
        <Drawer open={false} onClose={onClose} onNavigate={onNavigate} />
      </>,
    )
    expect(invoker).toHaveFocus()
  })

  it('delegates navigation and backdrop dismissal', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    const onNavigate = vi.fn()
    render(<Drawer open onClose={onClose} onNavigate={onNavigate} />)

    await user.click(screen.getByRole('button', { name: 'Política de privacidad' }))
    expect(onNavigate).toHaveBeenCalledWith('privacy')

    const backdrop = screen
      .getAllByRole('button', { name: 'Cerrar menú' })
      .find((button) => button.tabIndex === -1)
    expect(backdrop).toBeDefined()
    await user.click(backdrop!)
    expect(onClose).toHaveBeenCalledOnce()
  })
})
