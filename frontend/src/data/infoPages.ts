/**
 * infoPages.ts stores local informational page content and app-view routing
 * types used by the mock frontend flow.
 */

export type InfoView = 'about' | 'privacy' | 'terms'
export type AppView = 'home' | 'main' | InfoView

export interface InfoPageContent {
  title: string
  paragraphs: readonly string[]
}

export const BRAND_TAGLINE = 'COMUNICAR · COMPRENDER · CONECTAR'
export const ACCOUNT_LABEL = 'Cuenta Google'

export const INFO_PAGES: Record<InfoView, InfoPageContent> = {
  about: {
    title: 'Acerca del proyecto',
    paragraphs: [
      'TEAslator es una aplicación de apoyo para interpretar mensajes escritos y facilitar la comprensión de la intención comunicativa. Fue pensada para' +
      'ayudar a personas con Trastorno del Espectro Autista (TEA), por las dificultades que presenta este colectivo para interpretar mensajes que no sean' +
      'literales, directos o explícitos. A pesar de ello, la aplicación puede ser útil para cualquier persona que busque ayuda para interpretar mensajes' +
      'ambiguos, indirectos o irónicos, o para quienes acompañan a personas con TEA y desean ofrecer apoyo en la interpretación de mensajes.',
      'La interfaz está pensada para ser clara y directa, y se siguieron las mejores prácticas de accesibilidad, debido a que el público albo podría tener' +
      'dificultades para interactuar con la interfaz. Además, esta fue basada en la interfaz de Google Translator por dos motivos: primero, la relación' +
      'conceptual entre ambas aplicaciones, y segundo, la familiaridad que muchas personas tienen con la interfaz del traductor de Google, lo que facilita' +
      'el uso de la aplicación.',
    ],
  },
  privacy: {
    title: 'Política de privacidad',
    paragraphs: [
      'La aplicación está diseñada para minimizar los datos persistidos y evitar guardar mensajes, prompts, interpretaciones o respuestas completas del modelo.',
      'Las integraciones externas se gestionarán de tal forma que se minimice la exposición de datos personales y se cumpla con la normativa de privacidad' +
      'aplicable.',
    ],
  },
  terms: {
    title: 'Condiciones de uso',
    paragraphs: [
      'TEAslator ofrece una ayuda de interpretación y no sustituye el criterio personal, profesional o educativo de quienes acompañan a la persona usuaria' +
      'en caso de tratarse de alguien con necesidades especiales.',
      'Las respuestas generadas deben revisarse con contexto, especialmente cuando existan matices, ironía, lenguaje ofensivo o información sensible.',
    ],
  },
}

/**
 * Check whether an application view maps to an informational page.
 *
 * Args:
 *   view: The current local application view.
 *
 * Returns:
 *   True when the view is an informational page key.
 */
export function isInfoView(view: AppView): view is InfoView {
  return view === 'about' || view === 'privacy' || view === 'terms'
}