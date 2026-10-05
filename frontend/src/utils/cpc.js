/**
 * El CPC de una contratación, tal y como lo devuelve la API.
 *
 * Va en su propio módulo y no dentro de la tabla porque el mismo resumen se lee en más de un sitio
 * —la columna de la tabla y, más adelante, la ficha del móvil—, y dos copias de la misma regla
 * acabarían mostrando cosas distintas del mismo dato.
 *
 * La regla que resume: se muestra el **código** y el **nombre estándar** del CPC, nunca la
 * descripción libre del producto. Es lo que hace útil este campo: `871410032 LAVADO Y ENGRASADO DE
 * AUTOMOTORES` dice de qué está clasificado el gasto, mientras que «Lavado, engrasado y pulverizado
 * de la Volqueta 5 kodiak chevrolet» es lo que escribió la entidad y no se puede comparar ni contar.
 *
 * Los códigos repetidos salen **una sola vez**: una necesidad con diecisiete líneas del mismo
 * servicio tiene un CPC, no diecisiete.
 */

/** Los ítems de una fila, descartando lo que no tenga código. */
export function itemsDe(fila) {
  const crudos = Array.isArray(fila?.items) ? fila.items : []
  return crudos.filter((item) => item && String(item.codigo || '').trim())
}

/** Longitud mínima de un término, la misma que exige el servidor. */
export const LONGITUD_MINIMA = 3

/**
 * Separa una lista pegada por el usuario en términos.
 *
 * Se aceptan comas, punto y coma y saltos de línea porque son los tres separadores que aparecen al
 * copiar de una hoja de cálculo, que es de donde sale casi siempre una lista de clasificaciones.
 *
 * Las palabras de menos de tres letras se descartan **y se cuentan**: el contador de la pantalla dice
 * cuántas se van a añadir antes de pulsar, y quien pega veinte términos merece saber que uno se
 * quedó fuera por corto en lugar de descubrirlo después contando chips.
 *
 * Los repetidos se unifican sin distinguir mayúsculas —«Lavado» y «lavado» son el mismo filtro,
 * porque el servidor normaliza— y se conserva la primera grafía escrita, que es la que la persona
 * reconoce. Se resuelve aquí, en una sola función, para que el contador y el alta no puedan
 * discrepar: si cada una contara a su manera, el botón diría «Añadir 7» y añadiría 5.
 */
export function terminosDeLista(texto, minimo = LONGITUD_MINIMA) {
  const partes = String(texto || '')
    .split(/[,;\n]/)
    .map((parte) => parte.trim())
    .filter(Boolean)

  const utiles = new Map()
  let cortas = 0
  for (const parte of partes) {
    if (parte.length < minimo) {
      cortas += 1
      continue
    }
    const clave = parte.toLowerCase()
    if (!utiles.has(clave)) utiles.set(clave, parte)
  }
  return { terminos: [...utiles.values()], cortas }
}

/** Códigos distintos y ordenados. */
export function codigosCpc(fila) {
  return [...new Set(itemsDe(fila).map((item) => String(item.codigo)))].sort()
}

/**
 * `871410032 LAVADO Y ENGRASADO DE AUTOMOTORES | 431510128 REPUESTOS PARA MOTOR DIESEL`.
 *
 * Vacío significa «todavía no se ha leído la ficha de esta necesidad», que es distinto de «no tiene
 * clasificación»: la ficha se lee por tandas y una contratación recién publicada puede tardar un
 * ciclo en tenerla.
 */
export function resumenCpc(fila) {
  const vistos = new Map()
  for (const item of itemsDe(fila)) {
    const clave = `${item.codigo}|${item.descripcion_cpc || ''}`
    if (!vistos.has(clave)) vistos.set(clave, item)
  }
  return [...vistos.values()]
    .map((item) => `${item.codigo} ${item.descripcion_cpc || ''}`.trim())
    .join(' | ')
}
