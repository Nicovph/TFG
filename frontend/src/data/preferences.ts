/**
 * preferences.ts mirrors the backend preference vocabulary with narrow
 * TypeScript unions instead of permissive string records.
 */

export type InterpretationDetail = 'brief' | 'standard' | 'detailed'
export type VisualSupport = 'enabled' | 'disabled'
export type OffensiveLanguage = 'hidden' | 'shown'
export type ContentWarnings = 'shown' | 'hidden'
export type ThemePreference = 'light' | 'dark' | 'system'

export interface PreferenceState {
  interpretationDetail: InterpretationDetail
  visualSupport: VisualSupport
  offensiveLanguage: OffensiveLanguage
  contentWarnings: ContentWarnings
  theme: ThemePreference
}

export type PreferenceKey = keyof PreferenceState // 'interpretationDetail' | 'visualSupport' | 'offensiveLanguage' | 'contentWarnings' | 'theme'
export type PreferenceChangeHandler = <K extends PreferenceKey>(
  key: K, // The preference field being changed.
  value: PreferenceState[K], // The new value for the preference field.
) => void

export interface PreferenceOption<K extends PreferenceKey = PreferenceKey> {
  value: PreferenceState[K]
  label: string
}

export interface PreferenceGroup<K extends PreferenceKey = PreferenceKey> {
  id: K
  label: string
  options: readonly PreferenceOption<K>[]
}

export const DEFAULT_PREFERENCES: PreferenceState = {
  interpretationDetail: 'standard',
  visualSupport: 'enabled',
  offensiveLanguage: 'hidden',
  contentWarnings: 'shown',
  theme: 'system',
}

type PreferenceGroups = readonly [
  PreferenceGroup<'interpretationDetail'>,
  PreferenceGroup<'visualSupport'>,
  PreferenceGroup<'offensiveLanguage'>,
  PreferenceGroup<'contentWarnings'>,
  PreferenceGroup<'theme'>,
]

export const PREFERENCE_GROUPS = [
  {
    id: 'interpretationDetail',
    label: 'Detalle de la interpretación',
    options: [
      { value: 'brief', label: 'Corta y directa' },
      { value: 'standard', label: 'Estándar' },
      { value: 'detailed', label: 'Detallada' },
    ],
  },
  {
    id: 'visualSupport',
    label: 'Nivel de apoyo visual',
    options: [
      { value: 'enabled', label: 'Mostrar pictogramas' },
      { value: 'disabled', label: 'No mostrar pictogramas' },
    ],
  },
  {
    id: 'offensiveLanguage',
    label: 'Ocultación / Revelación de lenguaje ofensivo',
    options: [
      { value: 'hidden', label: 'Ocultar lenguaje ofensivo' },
      { value: 'shown', label: 'Revelar lenguaje ofensivo' },
    ],
  },
  {
    id: 'contentWarnings',
    label: 'Mostrar / Ocultar advertencias',
    options: [
      { value: 'shown', label: 'Mostrar advertencias' },
      { value: 'hidden', label: 'Ocultar advertencias' },
    ],
  },
  {
    id: 'theme',
    label: 'Tema de la aplicación',
    options: [
      { value: 'light', label: 'Claro' },
      { value: 'dark', label: 'Oscuro' },
      { value: 'system', label: 'Usar el tema del sistema' },
    ],
  },
] as const satisfies PreferenceGroups // as const is used to treat the array values as contants
// satisfies validates the structure of the array.

/**
 * Parse a string coming from a select control into a typed preference value.
 *
 * Args:
 *   key: The preference field being changed (like 'interpretationDetail').
 *   value: The raw value read from the browser control (like 'standard').
 *
 * Returns:
 *   A typed preference value when the value belongs to the field; otherwise null.
 */
export function parsePreferenceValue<K extends PreferenceKey>(
  key: K,
  value: string,
): PreferenceState[K] | null {
  const group = PREFERENCE_GROUPS.find((candidate) => candidate.id === key)
  const option = group?.options.find((candidate) => candidate.value === value)

  if (!option) {
    return null
  }

  return option.value as PreferenceState[K]
}