/**
 * formatRetryAfter.test.ts verifies clear Retry-After units at each boundary.
 */

import { describe, expect, it } from 'vitest'
import { formatRetryAfter } from './formatRetryAfter'

describe('formatRetryAfter', () => {
  it.each([
    [1, '1 segundo'],
    [59, '59 segundos'],
    [60, '1 minuto'],
    [61, '2 minutos'],
    [3600, '1 hora'],
    [86400, '1 día'],
    [172800, '2 días'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatRetryAfter(seconds)).toBe(expected)
  })
})
