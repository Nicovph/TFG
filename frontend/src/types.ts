/**
 * types.ts defines shared frontend contracts returned by the Django API.
 */

export interface ApiHealth {
  status: 'ok'
  service: 'django'
  apiVersion: string
  features: string[]
}

export interface MockInterpretation {
  kind: 'mock_interpretation'
  summary: string
  tone: string
  signals: string[]
  visualConcepts: string[]
}
