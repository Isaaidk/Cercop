/**
 * Formato de números, fechas y textos para mostrar.
 *
 * Todo lo que se enseña pasa por aquí para que el panel hable de una sola manera: si una cifra
 * aparece con separador de miles en un sitio y sin él en otro, el lector duda de si son la misma
 * cosa. Se usa la configuración regional de Ecuador, que es donde está el usuario.
 */

const LOCALE = 'es-EC'

const ENTERO = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 })
const DECIMAL = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const FECHA_CORTA = new Intl.DateTimeFormat(LOCALE, { day: '2-digit', month: 'short', year: 'numeric' })
const FECHA_LARGA = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})
const MES_CORTO = new Intl.DateTimeFormat(LOCALE, { month: 'short', year: '2-digit' })

/** Entero con separador de miles. Un valor ausente se muestra como raya, no como cero. */
export function numero(valor) {
  if (valor === null || valor === undefined || Number.isNaN(Number(valor))) return '—'
  return ENTERO.format(Number(valor))
}

export function decimal(valor) {
  if (valor === null || valor === undefined || Number.isNaN(Number(valor))) return '—'
  return DECIMAL.format(Number(valor))
}

/**
 * Cifra abreviada para ejes y tarjetas: 1,2 mil · 3,4 M.
 *
 * Se usa en los ejes de las gráficas porque un eje con «12.480» cinco veces ocupa más que el propio
 * gráfico en una pantalla de móvil.
 */
export function abreviado(valor) {
  const n = Number(valor) || 0
  if (Math.abs(n) >= 1_000_000) return `${DECIMAL.format(n / 1_000_000)} M`
  if (Math.abs(n) >= 10_000) return `${ENTERO.format(Math.round(n / 1000))} mil`
  if (Math.abs(n) >= 1000) return `${DECIMAL.format(n / 1000)} mil`
  return ENTERO.format(n)
}

/**
 * Convierte a fecha lo que devuelve la API.
 *
 * La API entrega textos ISO. Se parsean una sola vez aquí: hacerlo en cada componente daría lugar a
 * tratamientos distintos de la misma fecha —y a un `NaN` en pantalla el día que un campo llegue
 * vacío—.
 */
export function aFecha(valor) {
  if (!valor) return null
  const fecha = valor instanceof Date ? valor : new Date(valor)
  return Number.isNaN(fecha.getTime()) ? null : fecha
}

export function fechaCorta(valor) {
  const fecha = aFecha(valor)
  return fecha ? FECHA_CORTA.format(fecha) : '—'
}

export function fechaLarga(valor) {
  const fecha = aFecha(valor)
  return fecha ? FECHA_LARGA.format(fecha) : '—'
}

export function mesCorto(valor) {
  const fecha = aFecha(valor)
  return fecha ? MES_CORTO.format(fecha).replace('.', '') : '—'
}

/**
 * «hace 5 minutos», «hace 3 días».
 *
 * Se calcula a mano y no con `Intl.RelativeTimeFormat` porque hace falta el paso intermedio —elegir
 * la unidad— y el resultado de `RelativeTimeFormat` en español («hace 5 minutos») es exactamente lo
 * que devuelve esta función, sin la fase de adivinar la unidad a partir de las opciones.
 */
export function haceCuanto(valor) {
  const fecha = aFecha(valor)
  if (!fecha) return 'nunca'

  const segundos = Math.round((Date.now() - fecha.getTime()) / 1000)
  if (segundos < 0) return 'dentro de un momento'
  if (segundos < 60) return 'hace unos segundos'

  const minutos = Math.round(segundos / 60)
  if (minutos < 60) return `hace ${minutos} ${minutos === 1 ? 'minuto' : 'minutos'}`

  const horas = Math.round(minutos / 60)
  if (horas < 24) return `hace ${horas} ${horas === 1 ? 'hora' : 'horas'}`

  const dias = Math.round(horas / 24)
  if (dias < 30) return `hace ${dias} ${dias === 1 ? 'día' : 'días'}`

  const meses = Math.round(dias / 30)
  if (meses < 12) return `hace ${meses} ${meses === 1 ? 'mes' : 'meses'}`

  const anios = Math.round(meses / 12)
  return `hace ${anios} ${anios === 1 ? 'año' : 'años'}`
}

/**
 * Quita las etiquetas HTML de un valor de la fuente.
 *
 * La fuente publica algunos campos con marcado dentro —el estado viene como `<a ...>En Curso</a>` y
 * el contacto como un párrafo con `<br/>`—. Se limpia aquí y no se pinta con `v-html`: insertar
 * marcado que viene de fuera es la vía habitual de un ataque de guion incrustado, y este panel
 * muestra datos de terceros que no controlamos.
 */
export function sinEtiquetas(valor) {
  if (valor === null || valor === undefined) return ''
  const texto = String(valor)
  if (!texto.includes('<')) return texto

  const documento = new DOMParser().parseFromString(texto, 'text/html')
  return (documento.body.textContent || '').replace(/\s+/g, ' ').trim()
}

/** Acorta un texto largo sin cortar una palabra por la mitad. */
export function recortar(texto, limite = 120) {
  const limpio = String(texto || '').trim()
  if (limpio.length <= limite) return limpio
  const corte = limpio.slice(0, limite)
  const ultimoEspacio = corte.lastIndexOf(' ')
  return `${corte.slice(0, ultimoEspacio > 40 ? ultimoEspacio : limite)}…`
}
