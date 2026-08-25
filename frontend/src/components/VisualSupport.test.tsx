/**
 * VisualSupport.test.tsx verifies safe and accessible pictogram presentation.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { AvailablePictogram, VisualSupportResult } from '../types'
import { VisualSupport } from './VisualSupport'

const pictogram: AvailablePictogram = {
  concept: 'lluvia',
  status: 'available',
  pictogramId: 123,
  label: 'Lluvia',
  imageUrl: 'https://static.arasaac.org/pictograms/123/123_300.png',
}
const availableResult: VisualSupportResult = {
  status: 'complete',
  items: [pictogram],
  message: '',
  attribution: {
    text: 'Autor pictogramas: Sergio Palao. Procedencia: ARASAAC.',
    termsUrl: 'https://arasaac.org/terms-of-use',
  },
}

describe('VisualSupport', () => {
  it('opens an available pictogram from its accessible button', async () => {
    const user = userEvent.setup()
    const onOpen = vi.fn()
    render(<VisualSupport result={availableResult} onOpen={onOpen} />)

    const openButton = screen.getByRole('button', {
      name: 'Ampliar pictograma: Lluvia',
    })
    const image = openButton.querySelector('img')
    expect(image).toHaveAttribute('referrerpolicy', 'no-referrer')
    expect(screen.getByRole('link', { name: /Condiciones de uso/ })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    await user.click(openButton)
    expect(onOpen).toHaveBeenCalledWith(pictogram)
  })

  it('preserves the text workflow when visual support is unavailable', () => {
    const unavailableResult: VisualSupportResult = {
      status: 'unavailable',
      items: [{ concept: 'lluvia', status: 'temporarily_unavailable' }],
      message: 'El apoyo visual no está disponible. La interpretación de texto sigue disponible.',
      attribution: null,
    }

    render(<VisualSupport result={unavailableResult} onOpen={vi.fn()} />)

    expect(
      screen.getByRole('heading', { name: 'Apoyo visual no disponible' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/La interpretación de texto sigue disponible/)).toBeVisible()
  })
})
