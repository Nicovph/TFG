/**
 * formatRetryAfter.ts formats validated API retry delays for accessible,
 * plain-language interface messages.
 */

/**
 * Format a Retry-After duration using one easily understood unit.
 *
 * Args:
 *   seconds: Positive delay supplied by the internal Django API.
 *
 * Returns:
 *   A rounded duration in seconds, minutes, hours, or days.
 */
export function formatRetryAfter(seconds: number): string {
  if (seconds < 60) return `${seconds} ${seconds === 1 ? 'segundo' : 'segundos'}`

  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `${minutes} ${minutes === 1 ? 'minuto' : 'minutos'}`

  const hours = Math.ceil(minutes / 60)
  if (hours < 24) return `${hours} ${hours === 1 ? 'hora' : 'horas'}`

  const days = Math.ceil(hours / 24)
  return `${days} ${days === 1 ? 'día' : 'días'}`
}
