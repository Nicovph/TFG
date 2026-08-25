/**
 * VisualSupportDialog.test.tsx verifies modal pictogram recovery and dismissal.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AvailablePictogram } from '../types'
import { VisualSupportDialog } from './VisualSupportDialog'

const pictogram: AvailablePictogram = {
  concept: 'lluvia',
  status: 'available',
  pictogramId: 123,
  label: 'Lluvia',
  imageUrl: 'https://static.arasaac.org/pictograms/123/123_300.png',
}

describe('VisualSupportDialog', () => {
  it('opens as a labeled modal and preserves a usable image failure state', () => {
    const onClose = vi.fn()
    render(<VisualSupportDialog pictogram={pictogram} onClose={onClose} />)

    const dialog = screen.getByRole('dialog', { name: 'Lluvia' })
    expect(dialog).toHaveAttribute('open')
    const image = dialog.querySelector('img')
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer')
    fireEvent.error(image!)
    expect(screen.getByRole('status')).toHaveTextContent(
      'El pictograma no se pudo cargar.',
    )
  })

  it('delegates button, cancel, and backdrop dismissal', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(<VisualSupportDialog pictogram={pictogram} onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: 'Lluvia' })

    await user.click(screen.getByRole('button', { name: 'Cerrar' }))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    expect(onClose).toHaveBeenCalledTimes(2)
    fireEvent.click(dialog)
    expect(onClose).toHaveBeenCalledTimes(3)
  })

  it('restores focus when the dialog is removed', () => {
    const onClose = vi.fn()
    const { rerender } = render(
      <>
        <button type="button">Abrir pictograma</button>
      </>,
    )
    const invoker = screen.getByRole('button', { name: 'Abrir pictograma' })
    invoker.focus()

    rerender(
      <>
        <button type="button">Abrir pictograma</button>
        <VisualSupportDialog pictogram={pictogram} onClose={onClose} />
      </>,
    )
    rerender(
      <>
        <button type="button">Abrir pictograma</button>
      </>,
    )

    expect(invoker).toHaveFocus()
  })
})
