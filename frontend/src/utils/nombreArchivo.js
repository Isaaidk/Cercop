/**
 * El nombre con el que se guarda un archivo bajado de la API.
 *
 * Dos piezas puras, separadas del cliente HTTP para poder probarlas sin navegador:
 *
 * - `nombreDesdeCabecera` lee `Content-Disposition`. Primero `filename*=` (RFC 5987, UTF-8): es la
 *   única forma en que llega un nombre con tildes o espacios —Starlette, con esos nombres, **solo**
 *   escribe esa—. Antes se leía únicamente `filename=`, y un anexo como «INFORME DE
 *   NECESIDAD.docx» se guardaba como `contrataciones.xlsx`, el nombre por defecto de la exportación.
 * - `conExtension` garantiza la extensión real a partir del tipo del archivo, por si el nombre llega
 *   de otro sitio (el de la ficha, que no trae extensión).
 */

const EXTENSIONES = {
  'application/pdf': '.pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
  'application/msword': '.doc',
  'application/vnd.ms-excel': '.xls',
  'application/vnd.ms-powerpoint': '.ppt',
  'application/vnd.oasis.opendocument.text': '.odt',
  'application/vnd.oasis.opendocument.spreadsheet': '.ods',
  'application/zip': '.zip',
  'application/vnd.rar': '.rar',
  'application/x-7z-compressed': '.7z',
  'application/rtf': '.rtf',
  'image/png': '.png',
  'image/jpeg': '.jpg',
  'image/gif': '.gif',
  'image/tiff': '.tif',
  'image/webp': '.webp',
}

/** «.pdf», «.docx»… para un tipo MIME, o cadena vacía si no se conoce. */
export function extensionDeTipo(tipo) {
  return EXTENSIONES[String(tipo || '').split(';')[0].trim().toLowerCase()] || ''
}

/** «PDF», «DOCX»… para mostrar junto al nombre, o cadena vacía. */
export function formatoDeTipo(tipo) {
  return extensionDeTipo(tipo).slice(1).toUpperCase()
}

/** El nombre que propone el servidor en `Content-Disposition`, o `porDefecto`. */
export function nombreDesdeCabecera(cabecera, porDefecto = '') {
  const texto = String(cabecera || '')
  const extendido = /filename\*\s*=\s*([\w-]+)'[^']*'([^;]+)/i.exec(texto)
  if (extendido) {
    try {
      const nombre = decodeURIComponent(extendido[2].trim().replace(/^"|"$/g, ''))
      if (nombre) return nombre
    } catch {
      // Codificación rota: se intenta con `filename=`.
    }
  }
  const simple = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(texto)
  const nombre = (simple?.[1] ?? simple?.[2] ?? '').trim()
  return nombre || porDefecto
}

/**
 * `nombre` con la extensión que corresponde a `tipo`, si le falta.
 *
 * Si ya termina en la extensión correcta no se toca; si el tipo no se conoce, tampoco (no se inventa
 * una extensión). Sin nombre, «documento».
 */
export function conExtension(nombre, tipo) {
  const base = String(nombre || '').trim() || 'documento'
  const extension = extensionDeTipo(tipo)
  if (!extension) return base
  const actual = (/\.[a-z0-9]{2,5}$/i.exec(base)?.[0] || '').toLowerCase()
  if (actual === extension || (actual === '.jpeg' && extension === '.jpg')) return base
  return `${base}${extension}`
}
