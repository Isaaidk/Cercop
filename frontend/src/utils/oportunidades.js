/**
 * Piezas compartidas del área «Oportunidades para ti»: radar, alertas y mercado.
 *
 * Viven aquí, sin depender de Vue ni del API, por dos razones: las usan tres componentes que tienen
 * que contar lo mismo con las mismas palabras —si la alerta se resume de una forma al crearla y de
 * otra en la lista, el usuario duda de si es la misma—, y así se pueden probar con `node --test`.
 */
import { codigoDeProvincia, nombreDeProvincia } from './provincias.js'

const USD = new Intl.NumberFormat('es-EC', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})
const USD_CENTAVOS = new Intl.NumberFormat('es-EC', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/**
 * Monto en dólares con el formato de Ecuador. Un valor ausente o cero se muestra como raya: en estas
 * fuentes un cero casi siempre es «no publicado», y enseñar «$0» haría creer que algo fue gratis.
 * Los centavos solo aparecen en montos pequeños, donde sí cambian la lectura.
 */
export function usd(valor) {
  const n = Number(valor)
  if (valor === null || valor === undefined || valor === '' || !Number.isFinite(n) || n === 0) {
    return '—'
  }
  return Math.abs(n) < 1000 ? USD_CENTAVOS.format(n) : USD.format(n)
}

/** «a», «a o b», «a, b o c». */
export function unirConO(lista) {
  const partes = lista.filter(Boolean)
  if (partes.length <= 1) return partes[0] || ''
  return `${partes.slice(0, -1).join(', ')} o ${partes[partes.length - 1]}`
}

/** ¿Es un código CPC? El backend lo decide igual: cualquier dígito lo convierte en código. */
export function esCpc(texto) {
  return /\d/.test(String(texto || ''))
}

const CUANDO = {
  inmediata: 'al instante',
  diaria: 'en un resumen diario',
  semanal: 'en un resumen semanal',
}

function rangoEnPalabras(min, max) {
  const hayMin = min !== '' && min !== null && min !== undefined && Number(min) > 0
  const hayMax = max !== '' && max !== null && max !== undefined && Number(max) > 0
  if (hayMin && hayMax) return `entre ${usd(min)} y ${usd(max)}`
  if (hayMax) return `de hasta ${usd(max)}`
  if (hayMin) return `desde ${usd(min)}`
  return ''
}

/**
 * La alerta contada en una frase. Es lo que hace entendible el constructor: en vez de revisar cuatro
 * campos, quien la arma lee «Te avisaremos… cuando aparezca un proceso sobre “impresoras”, en
 * Pichincha, de hasta $7.000» y sabe si eso es lo que quería.
 *
 * Devuelve cadena vacía si la alerta todavía no dice qué buscar: sin palabras ni CPC no hay alerta.
 */
export function resumirAlerta(alerta = {}) {
  const palabras = (alerta.palabras || []).map((p) => `«${p}»`)
  const cpc = alerta.cpc || []
  const partes = []
  if (palabras.length) partes.push(`sobre ${unirConO(palabras)}`)
  if (cpc.length) partes.push(`${cpc.length === 1 ? 'del CPC' : 'de los CPC'} ${unirConO(cpc)}`)
  if (!partes.length) return ''

  const provincia = alerta.provincia ? nombreDeProvincia(alerta.provincia) || alerta.provincia : ''
  const canton = String(alerta.canton || '').trim()
  let donde = 'en todo el país'
  if (provincia && canton) donde = `en ${canton} (${provincia})`
  else if (provincia) donde = `en ${provincia}`

  const cuanto = rangoEnPalabras(alerta.presupuesto_min, alerta.presupuesto_max)
  const cuando = CUANDO[alerta.frecuencia] || CUANDO.diaria
  return `Te avisaremos ${cuando} cuando aparezca un proceso ${partes.join(' o ')}, ${donde}${
    cuanto ? `, ${cuanto}` : ''
  }.`
}

/**
 * Lo que el perfil comercial dice que vende la empresa, en el formato que usan las tres pantallas.
 *
 * Sigue la misma regla que el radar del backend (`criterios_desde_perfil`): los CPC salen de las
 * claves vigiladas con dígitos, de los productos y de la experiencia; las palabras, de las palabras
 * del perfil, de los nombres de productos y de las claves sin dígitos. Así, lo que aquí falta es
 * exactamente lo que le falta al radar para recomendar.
 */
export function perfilComercial(perfil, claves) {
  const p = perfil || {}
  const cpc = new Set()
  const palabras = new Set()
  const productos = new Set()
  const provincias = new Set()

  for (const clave of claves || []) {
    const texto = String(typeof clave === 'string' ? clave : clave?.texto || '').trim()
    if (!texto) continue
    if (esCpc(texto)) cpc.add(texto)
    else palabras.add(texto)
  }
  for (const fila of p.palabras || []) if (fila?.texto) palabras.add(String(fila.texto).trim())
  for (const fila of p.ofertas || []) {
    if (fila?.nombre) productos.add(String(fila.nombre).trim())
    if (fila?.cpc) cpc.add(String(fila.cpc).trim())
  }
  for (const fila of p.experiencia || []) if (fila?.cpc) cpc.add(String(fila.cpc).trim())
  for (const fila of p.cobertura || []) {
    if (fila?.provincia) provincias.add(codigoDeProvincia(fila.provincia) || fila.provincia)
  }

  const listaCpc = [...cpc].filter(Boolean)
  const listaPalabras = [...palabras].filter((x) => x && x.length <= 60)
  const listaProductos = [...productos].filter((x) => x && x.length <= 60)
  return {
    cpc: listaCpc,
    palabras: listaPalabras,
    productos: listaProductos,
    provincias: [...provincias],
    vacio: !listaCpc.length && !listaPalabras.length && !listaProductos.length,
  }
}
