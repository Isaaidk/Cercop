/**
 * Fechas del calendario ecuatoriano.
 *
 * El panel cuenta los días como los cuenta el backend: en hora de Ecuador. Usar el día del
 * navegador daría un resultado distinto según dónde esté la persona —y una necesidad publicada a
 * las 20:00 en Quito pertenece al día 30, no al 31—, así que la fecha se calcula siempre en la zona
 * del negocio y no en la de quien mira.
 *
 * El backend guarda los instantes en UTC, pero el filtro de fechas interpreta `desde` y `hasta`
 * como días naturales de Ecuador (`inicio_del_dia` / `fin_del_dia` del dominio). Las dos partes
 * tienen que hablar del mismo día o el atajo «hoy» volvería a dejar fuera lo de esta tarde.
 */

const ZONA_NEGOCIO = 'America/Guayaquil'

/**
 * El día de hoy como `AAAA-MM-DD`, en Ecuador: el formato que aceptan los campos de fecha.
 *
 * Se arma a partir de las partes y no del texto ya formateado para que el resultado sea el mismo en
 * cualquier navegador: con `format()` la fecha saldría con las barras del idioma de la persona y no
 * llegaría al `input type="date"` ni a la API.
 */
export function diaDeHoy() {
  const partes = new Intl.DateTimeFormat('en-CA', {
    timeZone: ZONA_NEGOCIO,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())

  const valor = (tipo) => partes.find((parte) => parte.type === tipo)?.value || ''
  return `${valor('year')}-${valor('month')}-${valor('day')}`
}
