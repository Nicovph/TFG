/**
 * infoPages.ts stores local informational page content and app-view routing
 * types used by the local frontend flow.
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
      'TEAslator es una aplicación de apoyo para interpretar mensajes escritos y facilitar' +
      ' la comprensión de la intención comunicativa. Fue concebida inicialmente para mensajes ' +
      ' publicados en redes sociales, donde son frecuentes la ironía, los dobles sentidos, las' +
      ' indirectas y otras formas de comunicación no literal. También puede emplearse con frases' +
      ' procedentes de conversaciones por chat, mensajes entre familiares o amistades, comunicaciones' + 
      ' académicas o intercambios laborales.',
      'La aplicación está pensada especialmente para ayudar a personas con Trastorno del Espectro' +
      ' Autista (TEA), que pueden encontrar dificultades al interpretar mensajes no literales. Su' +
      ' objetivo es ayudar a identificar posibles significados implícitos y mostrar una posible' +
      ' forma directa de expresarlos, incorporando apoyo visual cuando esté habilitado.',
      'Aun así, puede resultar útil para cualquier persona que busque ayuda con mensajes ambiguos, indirectos' +
      ' o irónicos, así como para quienes acompañan a personas con TEA y desean ofrecerles apoyo en su interpretación.',
      'La interpretación puede depender del tono, de la relación entre las personas o de lo ocurrido antes o después.' +
      'Por ello, TEAslator indica cuándo necesita más información en lugar de presentar una intención incierta como' +
      ' segura. Se puede añadir un mensaje anterior y otro posterior como contexto e indicar si cada uno pertenece a la' +
      ' misma persona que escribió el mensaje a interpretar, a otra persona o si no se sabe.',
      'La interfaz está diseñada para ser clara, directa y accesible, teniendo en cuenta las necesidades de su público' +
      ' objetivo. Su diseño se inspira en el Traductor de Google por la relación conceptual entre ambas aplicaciones y' +
      ' por la familiaridad que muchas personas tienen con esa interfaz.',
    ],
  },
  privacy: {
    title: 'Política de privacidad',
    paragraphs: [
      'La aplicación está diseñada para minimizar los datos persistidos y evitar guardar mensajes, prompts, interpretaciones' +
      ' o respuestas completas del modelo.',
      'Las integraciones externas se gestionan desde el backend. Antes de enviar contenido al asistente virtual, este reduce' +
      ' identificadores habituales, aunque esta medida no puede detectar todos los datos personales ni garantizar el' +
      ' anonimato. La aplicación informa de este procesamiento externo antes de solicitar una interpretación.',
    ],
  },
  terms: {
    title: 'Condiciones de uso',
    paragraphs: [
      'TEAslator ofrece una ayuda de interpretación y no sustituye el criterio personal, profesional o educativo de quienes' +
      ' acompañan a la persona usuaria en caso de tratarse de alguien con necesidades especiales.',
      'Las respuestas generadas deben revisarse con contexto, especialmente cuando existan matices, ironía, lenguaje ofensivo' +
      ' o información sensible.',
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
