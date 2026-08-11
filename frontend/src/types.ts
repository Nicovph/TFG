/**
 * types.ts defines shared frontend contracts returned by the Django API.
 */

export interface ApiHealth {
  status: 'ok'
  service: 'django'
}

export type ContextSpeakerRelation =
  | 'same_as_target_author'
  | 'different_from_target_author'
  | 'unknown'

export type InterpretationSignalKind =
  | 'possible_irony'
  | 'possible_ambiguity'
  | 'possible_indirect_language'
  | 'possible_offensive_language'
  | 'possible_aggression'
  | 'possible_cyberbullying'

export interface InterpretationRequest {
  targetMessage: string
  previousContext: string
  previousContextSpeaker: ContextSpeakerRelation
  followingContext: string
  followingContextSpeaker: ContextSpeakerRelation
  externalProcessingAcknowledged: boolean
}

export interface InterpretationSignal {
  kind: InterpretationSignalKind
  explanation: string
}

export interface Interpretation {
  kind: 'pragmatic_interpretation'
  interpretation: string
  clearReformulation: string
  needsMoreContext: boolean
  contextNote: string
  signals: InterpretationSignal[]
  visualConcepts: string[]
  showContentWarning: boolean
}

export interface SessionStatus {
  authenticated: boolean
}
