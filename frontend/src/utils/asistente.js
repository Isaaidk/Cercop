/**
 * Piezas puras de la pantalla «Asistente»: formato del texto, fechas relativas, dinero, los chips del
 * resumen y la traducción de las pantallas que nombra el servidor a las pestañas reales del panel.
 *
 * Viven aquí, sin Vue, para poder probarlas con `node --test` (ver `tests/asistente.test.mjs`).
 *
 * El texto del asistente **nunca** se pinta con `v-html`. `segmentarTexto` lo parte en bloques y
 * trozos (`{ texto, negrita }`) que la plantilla pinta con interpolación normal, así que cualquier
 * `<script>` o etiqueta que llegue en el texto se ve como texto y no se ejecuta.
 */
import { usd } from './oportunidades.js'

export { usd }

/** Tope de caracteres de un mensaje; el mismo que valida el servidor. */
export const LIMITE_TEXTO = 2000

/** Desde cuántos caracteres se enseña el contador, para no distraer mientras se escribe poco. */
export const AVISO_LIMITE = 1800

const MS_DIA = 86_400_000

// ------------------------------------------------------------------------------------- texto

/**
 * Parte una línea en trozos normales y en negrita (`**así**`).
 *
 * Un `**` sin pareja se deja tal cual, como texto: mejor ver dos asteriscos que perder media frase.
 */
export function trozosDeLinea(linea) {
  const texto = String(linea ?? '')
  const trozos = []
  const patron = /\*\*(.+?)\*\*/g
  let desde = 0
  let encontrado
  while ((encontrado = patron.exec(texto)) !== null) {
    if (encontrado.index > desde) trozos.push({ texto: texto.slice(desde, encontrado.index), negrita: false })
    trozos.push({ texto: encontrado[1], negrita: true })
    desde = encontrado.index + encontrado[0].length
  }
  if (desde < texto.length) trozos.push({ texto: texto.slice(desde), negrita: false })
  return trozos
}

/**
 * Convierte el texto del asistente en bloques que la plantilla pinta sin `v-html`.
 *
 * - Las líneas que empiezan con «- » (o «• ») forman una lista.
 * - Las demás líneas seguidas forman un párrafo; cada salto de línea se respeta (`lineas`).
 * - Una línea en blanco separa párrafos.
 *
 * Devuelve `[{ tipo: 'parrafo', lineas: [[trozo]] } | { tipo: 'lista', elementos: [[trozo]] }]`.
 */
export function segmentarTexto(texto) {
  const lineas = String(texto ?? '')
    .replace(/\r\n?/g, '\n')
    .split('\n')
  const bloques = []
  let actual = null

  for (const cruda of lineas) {
    const linea = cruda.replace(/\s+$/, '')
    const vineta = /^\s*[-•]\s+(.*)$/.exec(linea)
    if (vineta) {
      if (actual?.tipo !== 'lista') {
        actual = { tipo: 'lista', elementos: [] }
        bloques.push(actual)
      }
      actual.elementos.push(trozosDeLinea(vineta[1]))
    } else if (!linea.trim()) {
      actual = null
    } else {
      if (actual?.tipo !== 'parrafo') {
        actual = { tipo: 'parrafo', lineas: [] }
        bloques.push(actual)
      }
      actual.lineas.push(trozosDeLinea(linea.trim()))
    }
  }
  return bloques
}

/** El texto del contador: vacío hasta acercarse al tope, después «1.850 / 2.000». */
export function textoContador(longitud, limite = LIMITE_TEXTO, aviso = AVISO_LIMITE) {
  const n = Number(longitud) || 0
  if (n < aviso) return ''
  const miles = (valor) => new Intl.NumberFormat('es-EC').format(valor)
  return `${miles(n)} / ${miles(limite)}`
}

/** Primer nombre para el saludo: «María José Pérez» → «María». */
export function primerNombre(nombre) {
  const limpio = String(nombre ?? '').trim()
  if (!limpio || limpio.includes('@')) return limpio.split('@')[0]
  return limpio.split(/\s+/)[0]
}

// ------------------------------------------------------------------------------------- fechas

function aFecha(valor) {
  if (!valor) return null
  const fecha = valor instanceof Date ? valor : new Date(valor)
  return Number.isNaN(fecha.getTime()) ? null : fecha
}

function inicioDelDia(fecha) {
  return new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate()).getTime()
}

const FECHA_CORTA = new Intl.DateTimeFormat('es-EC', { day: 'numeric', month: 'short', year: 'numeric' })
const FECHA_SIN_ANIO = new Intl.DateTimeFormat('es-EC', { day: 'numeric', month: 'short' })

/** «12 nov 2026»; sin el año si es el año en curso. Vacío si no hay fecha. */
export function fechaCorta(valor, ahora = new Date()) {
  const fecha = aFecha(valor)
  if (!fecha) return ''
  const formato = fecha.getFullYear() === aFecha(ahora).getFullYear() ? FECHA_SIN_ANIO : FECHA_CORTA
  return formato.format(fecha).replace('.', '')
}

/**
 * Cuándo se tocó una conversación, en palabras: «Hace un momento», «Hace 5 min», «Hace 3 h»,
 * «Ayer», «Hace 4 días» y, pasada la semana, la fecha.
 */
export function fechaRelativa(valor, ahora = new Date()) {
  const fecha = aFecha(valor)
  const referencia = aFecha(ahora)
  if (!fecha || !referencia) return ''
  const segundos = Math.round((referencia.getTime() - fecha.getTime()) / 1000)
  if (segundos < 60) return 'Hace un momento'
  const dias = Math.round((inicioDelDia(referencia) - inicioDelDia(fecha)) / MS_DIA)
  if (dias <= 0) {
    const minutos = Math.floor(segundos / 60)
    if (minutos < 60) return `Hace ${minutos} min`
    return `Hace ${Math.floor(minutos / 60)} h`
  }
  if (dias === 1) return 'Ayer'
  if (dias < 7) return `Hace ${dias} días`
  return fechaCorta(fecha, referencia)
}

/**
 * El cierre de una ínfima o proceso como insignia: `{ texto, clase }`.
 *
 * Las mismas reglas que `insigniaDePlazo`: rojo solo si cierra hoy o mañana, ámbar dentro de la
 * semana, gris el resto. Se cuentan días enteros hacia abajo.
 */
export function cierreDe(valor, ahora = new Date()) {
  const fecha = aFecha(valor)
  if (!fecha) return { texto: '', clase: '' }
  const dias = Math.floor((fecha.getTime() - aFecha(ahora).getTime()) / MS_DIA)
  if (dias < 0) return { texto: `Cerró el ${fechaCorta(fecha, ahora)}`, clase: '' }
  if (dias === 0) return { texto: 'Cierra hoy', clase: 'etiqueta--error' }
  if (dias === 1) return { texto: 'Cierra mañana', clase: 'etiqueta--error' }
  if (dias < 7) return { texto: `Cierra en ${dias} días`, clase: 'etiqueta--aviso' }
  if (dias < 31) return { texto: `Cierra en ${dias} días`, clase: '' }
  return { texto: `Cierra el ${fechaCorta(fecha, ahora)}`, clase: '' }
}

// ------------------------------------------------------------------------------------- textos

const MINUSCULAS = new Set(['de', 'del', 'la', 'las', 'los', 'y', 'el'])

/** «SANTO DOMINGO DE LOS TSACHILAS» → «Santo Domingo de los Tsachilas». */
export function nombrePropio(texto) {
  return String(texto ?? '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((palabra, indice) =>
      indice > 0 && MINUSCULAS.has(palabra) ? palabra : palabra.charAt(0).toUpperCase() + palabra.slice(1),
    )
    .join(' ')
}

/** «Cantón, Provincia», sin repetir si son iguales. */
export function lugarDe(fila) {
  const partes = [fila?.canton, fila?.provincia].filter(Boolean).map(nombrePropio)
  return [...new Set(partes)].join(', ')
}

/** Una lista (o un texto suelto) como «a, b y c». */
export function enumerar(valor) {
  const lista = (Array.isArray(valor) ? valor : valor ? [valor] : [])
    .map((item) => (item && typeof item === 'object' ? item.descripcion || item.codigo || item.nombre : item))
    .map((item) => String(item ?? '').trim())
    .filter(Boolean)
  if (lista.length <= 1) return lista[0] || ''
  return `${lista.slice(0, -1).join(', ')} y ${lista[lista.length - 1]}`
}

const ETAPAS = {
  borrador: 'Borrador',
  enviada: 'Enviada',
  ganada: 'Ganada',
  perdida: 'Perdida',
  descartada: 'Descartada',
}

/** El nombre de una etapa del CRM para leer: «enviada» → «Enviada». */
export function nombreEtapa(etapa) {
  const clave = String(etapa ?? '').trim()
  if (!clave) return ''
  return ETAPAS[clave] || clave.charAt(0).toUpperCase() + clave.slice(1).replace(/_/g, ' ')
}

/** La fila de una tarjeta, con la forma que espera `prepararOferta` del panel (`{ id, codigo, … }`). */
export function registroDeTarjeta(fila) {
  if (!fila) return null
  return {
    ...fila,
    id: fila.registro_id ?? fila.id ?? null,
    codigo: fila.codigo || '',
  }
}

// ------------------------------------------------------------------------------------- resumen

const CHIPS = [
  {
    clave: 'propuestas',
    uno: '1 ínfima para ti',
    varios: (n) => `${n} ínfimas para ti`,
    mensaje: 'Muéstrame las ínfimas que puedo ofertar',
  },
  {
    clave: 'alertas',
    uno: '1 alerta activa',
    varios: (n) => `${n} alertas activas`,
    mensaje: 'Muéstrame mis alertas',
  },
  {
    clave: 'ofertas_abiertas',
    uno: '1 oferta abierta',
    varios: (n) => `${n} ofertas abiertas`,
    mensaje: '¿Cómo van mis ofertas?',
  },
  {
    clave: 'por_cerrar',
    uno: '1 oferta por cerrar',
    varios: (n) => `${n} ofertas por cerrar`,
    mensaje: '¿Qué ofertas están por cerrar?',
  },
]

/**
 * Los chips del resumen: `[{ clave, texto, mensaje }]`, solo de lo que tiene número mayor que cero.
 * Un cero o un `null` (el servidor no lo pudo calcular) no se enseña: un chip «0 alertas» no invita
 * a nada.
 */
export function chipsDeResumen(resumen) {
  if (!resumen || typeof resumen !== 'object') return []
  return CHIPS.flatMap(({ clave, uno, varios, mensaje }) => {
    const n = Number(resumen[clave])
    if (resumen[clave] === null || resumen[clave] === undefined || !Number.isFinite(n) || n <= 0) return []
    const cifra = new Intl.NumberFormat('es-EC').format(n)
    return [{ clave, texto: n === 1 ? uno : varios(cifra), mensaje }]
  })
}

// ------------------------------------------------------------------------------------- pestañas

/**
 * Nombres que puede mandar el servidor → id real de la pestaña del panel.
 *
 * Los ids reales se dejan pasar tal cual. «alertas» vive en «Recomendadas» (el radar), «empresa» es
 * el perfil y «mis-ofertas» el CRM.
 */
const PESTANAS_DEL_ASISTENTE = {
  'mis-ofertas': 'misofertas',
  mis_ofertas: 'misofertas',
  alertas: 'radar',
  avisos: 'radar',
  recomendadas: 'radar',
  empresa: 'perfil',
  rup: 'perfil',
  procesos: 'ofertas',
  estadisticas: 'resumen',
  preparar: 'documentos',
  'preparar-oferta': 'documentos',
}

/**
 * El id de la pestaña real para lo que nombra el servidor, o `null` si no existe o no está entre las
 * `disponibles` (por rol): mejor no moverse que abrir una pantalla que el usuario no puede ver.
 */
export function pestanaDelAsistente(pestana, disponibles = null) {
  const clave = String(pestana ?? '').trim().toLowerCase()
  if (!clave) return null
  const real = PESTANAS_DEL_ASISTENTE[clave] || clave
  if (disponibles && !disponibles.includes(real)) return null
  return real
}

// ------------------------------------------------------------------------------------- vistas

/**
 * Qué vista del catálogo necesita una sugerencia o un chip para no acabar en «sin acceso».
 *
 * Es la misma regla que aplica el servidor (que ya filtra las sugerencias que manda): las ínfimas y
 * las propuestas salen de «Ínfimas cuantías»; precios, competidores e historial de contratos de un
 * RUC, de «Ofertas». Aquí se aplica a las sugerencias fijas del panel y a lo que ya estuviera
 * pintado cuando cambian las vistas.
 */
const VISTA_DE_SUGERENCIA = [
  { patron: /[íi]nfima|propuesta|recomi[ée]nd/i, vista: 'necesidades' },
  { patron: /precio|competid|historial de contratos/i, vista: 'ofertas' },
]

/**
 * ¿Se puede ofrecer esta sugerencia a quien tiene estas vistas vigentes?
 *
 * `vigentes` es la lista de códigos de vista vigentes, o `null` cuando no se sabe (aún no se cargó,
 * o es el dueño de la plataforma): entonces no se oculta nada y decide el servidor.
 */
export function sugerenciaVisible(texto, vigentes) {
  if (!Array.isArray(vigentes)) return true
  const regla = VISTA_DE_SUGERENCIA.find(({ patron }) => patron.test(String(texto ?? '')))
  return !regla || vigentes.includes(regla.vista)
}

/** Las sugerencias que no llevan a una vista oculta. */
export function sugerenciasVisibles(lista, vigentes) {
  return (Array.isArray(lista) ? lista : []).filter((texto) => sugerenciaVisible(texto, vigentes))
}
