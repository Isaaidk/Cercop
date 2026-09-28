/**
 * El plazo para entregar la proforma: cuántos días quedan y de qué color se pinta.
 *
 * Vive aquí y no dentro de un componente porque lo usan dos —la tabla de registros y el listado que
 * aparece bajo el mapa— y porque el semáforo tiene que decir lo mismo en los dos sitios. Duplicado,
 * el día que se mueva un umbral uno de los dos se quedaría con el viejo y la misma contratación
 * saldría verde en una pantalla y amarilla en la otra.
 *
 * El plazo se **calcula**, nunca se guarda: no es un dato del registro sino una cuenta atrás, y
 * almacenarlo dejaría el número congelado el día que se ingirió. Se mide contra el reloj del
 * navegador a propósito: la pregunta es «cuánto tiempo tengo yo», y la respuesta depende de la hora
 * de quien pregunta, no de la del servidor.
 */

/** Los umbrales, en días. */
export const DIAS_VERDE = 7
export const DIAS_AMARILLO = 3

const MILISEGUNDOS_POR_DIA = 86_400_000

/**
 * Días que quedan para el límite, redondeados hacia abajo. `null` si no hay fecha o no se entiende.
 *
 * Se redondea hacia abajo para que el día del vencimiento sea `0` y no `1`: con redondeo normal,
 * una fecha a las ocho de la mañana de mañana saldría «1 día» cuando en realidad quedan horas.
 */
export function diasParaProforma(fechaLimite) {
  if (!fechaLimite) return null
  const limite = fechaLimite instanceof Date ? fechaLimite : new Date(fechaLimite)
  const instante = limite.getTime()
  if (Number.isNaN(instante)) return null
  return Math.floor((instante - Date.now()) / MILISEGUNDOS_POR_DIA)
}

/**
 * La clase de color del semáforo.
 *
 * Verde desde {DIAS_VERDE} días, amarillo por debajo, rojo por debajo de {DIAS_AMARILLO}. Los plazos
 * ya vencidos caen en el rojo, que es donde hay que mirar; se distinguen por el texto, no por el
 * color, para no confundir «quedan 2 días» con «se pasó hace 2 días».
 */
export function nivelDePlazo(dias) {
  if (dias === null || dias === undefined) return 'plazo--sin'
  if (dias < DIAS_AMARILLO) return 'plazo--rojo'
  if (dias < DIAS_VERDE) return 'plazo--amarillo'
  return 'plazo--verde'
}

/** El texto del plazo. «Vencida» en vez de un número negativo: un menos no se lee de un vistazo. */
export function textoDePlazo(dias) {
  if (dias === null || dias === undefined) return 'Sin fecha'
  if (dias < 0) return 'Vencida'
  if (dias === 0) return 'Hoy'
  if (dias === 1) return '1 día'
  return `${dias} días`
}
