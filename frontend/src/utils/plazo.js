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
const MILISEGUNDOS_POR_HORA = 3_600_000
const MILISEGUNDOS_POR_MINUTO = 60_000

/** Desfase de Ecuador continental (America/Guayaquil): UTC−5 todo el año, sin horario de verano. */
const DESFASE_ECUADOR = '-05:00'
const SOLO_FECHA = /^\d{4}-\d{2}-\d{2}$/
const FECHA_HORA_SIN_ZONA = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

/**
 * El instante (milisegundos) de una fecha de la fuente, leída **en hora de Ecuador**.
 *
 * El portal publica las horas sin zona («2026-11-23T17:00:00»): son horas de Ecuador. Leídas con
 * `new Date()` quedarían en la zona del navegador, y quien mira desde otro huso vería el plazo
 * corrido. Una fecha sin hora es el día entero: el límite cierra al final del día (`finDelDia`), la
 * publicación cuenta desde el principio. `null` si no hay fecha o no se entiende.
 */
export function instanteEcuador(valor, { finDelDia = false } = {}) {
  if (valor === null || valor === undefined || valor === '') return null
  if (valor instanceof Date) return Number.isNaN(valor.getTime()) ? null : valor.getTime()
  let texto = String(valor).trim()
  if (SOLO_FECHA.test(texto)) texto = `${texto}T${finDelDia ? '23:59:59' : '00:00:00'}${DESFASE_ECUADOR}`
  else if (FECHA_HORA_SIN_ZONA.test(texto)) texto = `${texto.replace(' ', 'T')}${DESFASE_ECUADOR}`
  const instante = new Date(texto).getTime()
  return Number.isNaN(instante) ? null : instante
}

/**
 * Días que quedan para el límite, redondeados hacia abajo. `null` si no hay fecha o no se entiende.
 *
 * Se redondea hacia abajo para que el día del vencimiento sea `0` y no `1`: con redondeo normal,
 * una fecha a las ocho de la mañana de mañana saldría «1 día» cuando en realidad quedan horas.
 */
export function diasParaProforma(fechaLimite, ahora = Date.now()) {
  const instante = instanteEcuador(fechaLimite, { finDelDia: true })
  if (instante === null) return null
  return Math.floor((instante - ahora) / MILISEGUNDOS_POR_DIA)
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

/**
 * La insignia del plazo para las ínfimas cuantías: texto y clase de `.etiqueta`.
 *
 * Es más discreta que el semáforo de `nivelDePlazo`, y a propósito: el cliente pidió quitar los
 * colores fuertes del listado de ínfimas. El rojo queda **solo** para lo que cierra hoy o mañana,
 * que es lo único que exige actuar ya; el ámbar, para lo que cierra esta semana; el resto va en gris.
 * El texto dice siempre lo mismo que el color, así que nadie depende de distinguir los tonos.
 */
export function insigniaDePlazo(dias) {
  if (dias === null || dias === undefined) return { texto: 'Sin fecha', clase: '' }
  if (dias < 0) return { texto: 'Cerrada', clase: '' }
  if (dias === 0) return { texto: 'Cierra hoy', clase: 'etiqueta--error' }
  if (dias === 1) return { texto: 'Cierra mañana', clase: 'etiqueta--error' }
  if (dias < DIAS_VERDE) return { texto: `${dias} días`, clase: 'etiqueta--aviso' }
  return { texto: `${dias} días`, clase: '' }
}

/**
 * Cuánto falta, dicho para leerlo de un vistazo: «4 días y 3 horas», «5 horas», «20 minutos».
 *
 * Con más de un día se omiten los minutos; con menos de una hora solo quedan los minutos. Nunca
 * «0 minutos»: lo que queda por debajo del minuto se dice «menos de un minuto».
 */
export function textoRestante(milisegundos) {
  if (milisegundos === null || milisegundos === undefined || milisegundos <= 0) return ''
  const dias = Math.floor(milisegundos / MILISEGUNDOS_POR_DIA)
  const horas = Math.floor((milisegundos % MILISEGUNDOS_POR_DIA) / MILISEGUNDOS_POR_HORA)
  const minutos = Math.floor((milisegundos % MILISEGUNDOS_POR_HORA) / MILISEGUNDOS_POR_MINUTO)
  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`
  if (dias > 0) {
    return horas > 0 ? `${plural(dias, 'día', 'días')} y ${plural(horas, 'hora', 'horas')}` : plural(dias, 'día', 'días')
  }
  if (horas > 0) {
    return minutos > 0 ? `${plural(horas, 'hora', 'horas')} y ${plural(minutos, 'minuto', 'minutos')}` : plural(horas, 'hora', 'horas')
  }
  return minutos > 0 ? plural(minutos, 'minuto', 'minutos') : 'menos de un minuto'
}

/** Umbrales de la barra de tiempo, en porcentaje del plazo ya transcurrido. */
export const AVANCE_ATENCION = 50
export const AVANCE_URGENTE = 85

/**
 * La barra de tiempo del plazo: qué parte del tiempo entre la publicación y el límite ya pasó.
 *
 * Devuelve `null` si no hay fecha límite (no hay nada que medir). Si falta la publicación, o es
 * posterior al límite, no se puede calcular el porcentaje (`porcentaje: null`) pero sí lo que
 * queda. El nivel junta las dos medidas —lo que queda y lo que ya se gastó— para que una ínfima de
 * tres días a la que le quedan dos no salga en rojo, y una que cierra hoy nunca salga en verde:
 *
 * - `cerrado`: el límite ya pasó.
 * - `urgente`: cierra hoy o mañana (menos de 48 horas) o se gastó el 85 % del plazo.
 * - `atencion`: quedan menos de {DIAS_AMARILLO} días o se gastó la mitad.
 * - `holgado`: el resto.
 */
export function avanceDelPlazo(publicacion, limite, ahora = Date.now()) {
  const fin = instanteEcuador(limite, { finDelDia: true })
  if (fin === null) return null
  const inicio = instanteEcuador(publicacion)
  const restante = fin - ahora
  const medible = inicio !== null && fin > inicio
  const porcentaje = medible
    ? Math.round(Math.min(1, Math.max(0, (ahora - inicio) / (fin - inicio))) * 100)
    : null

  let nivel
  if (restante <= 0) nivel = 'cerrado'
  else if (restante < 2 * MILISEGUNDOS_POR_DIA || (porcentaje ?? 0) >= AVANCE_URGENTE) nivel = 'urgente'
  else if (restante < DIAS_AMARILLO * MILISEGUNDOS_POR_DIA || (porcentaje ?? 0) >= AVANCE_ATENCION) nivel = 'atencion'
  else nivel = 'holgado'

  return {
    porcentaje: restante <= 0 && medible ? 100 : porcentaje,
    nivel,
    cerrado: restante <= 0,
    restanteMs: Math.max(0, restante),
    texto: restante <= 0 ? 'Plazo cerrado' : `Quedan ${textoRestante(restante)}`,
    inicio,
    fin,
  }
}
