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
