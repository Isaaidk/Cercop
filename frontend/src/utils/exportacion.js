/**
 * Hasta dónde llega una descarga en Excel.
 *
 * Espeja `dominio/exportacion.py` del servidor: la descarga cubre como mucho los últimos **tres
 * meses** de fecha de publicación, porque es la única operación que lee el histórico entero sin
 * paginar. El servidor lo comprueba por su cuenta —esconder el botón no es un control— y esta es la
 * copia que evita ofrecer un botón condenado a un rechazo.
 *
 * Se cuenta en meses de **calendario** y en el día de Ecuador, igual que el servidor: contar 90 días
 * dejaría fuera o dentro un día distinto según el mes, y usar el día del navegador haría que el
 * límite cambiara según dónde esté la persona. Si las dos cuentas no coincidieran, el panel dejaría
 * pulsar un botón que el servidor rechaza.
 */

import { diaDeHoy } from '@/utils/fecha'

/** Meses de histórico que cubre una descarga. */
export const MESES_EXPORTABLES = 3

/**
 * Suma (o resta) meses de calendario a una fecha `AAAA-MM-DD`, ajustando el día al último del mes
 * de destino: tres meses atrás desde el 31 de mayo no es un 31 de febrero.
 */
function desplazarMeses(iso, meses) {
  const [anio, mes, dia] = iso.split('-').map(Number)
  const indice = mes - 1 + meses
  const anioDestino = anio + Math.floor(indice / 12)
  const mesDestino = (indice % 12 + 1 + 12) % 12 || 12
  // Día 0 del mes siguiente es el último día del mes pedido.
  const ultimoDia = new Date(Date.UTC(anioDestino, mesDestino, 0)).getUTCDate()
  const diaFinal = Math.min(dia, ultimoDia)
  const dosDigitos = (valor) => String(valor).padStart(2, '0')
  return `${anioDestino}-${dosDigitos(mesDestino)}-${dosDigitos(diaFinal)}`
}

/** La fecha de publicación más antigua que se puede descargar, como `AAAA-MM-DD`. */
export function inicioExportable() {
  return desplazarMeses(diaDeHoy(), -MESES_EXPORTABLES)
}

/**
 * ¿Cabe esta descarga en la ventana?
 *
 * Sin fecha inicial la respuesta es **no**, y no es un descuido: sin `desde` la consulta abarcaría
 * el histórico entero, que es justo lo que la ventana evita. El servidor lo rechaza igual, así que
 * aquí se dice antes de pulsar en lugar de después.
 */
export function descargaEnVentana(desde) {
  const limite = inicioExportable()
  return Boolean(desde) && String(desde) >= limite
}

/** El límite en el formato que se lee en una frase: `6 de julio de 2026`. */
export function limiteLegible(iso = inicioExportable()) {
  const [anio, mes, dia] = iso.split('-').map(Number)
  const meses = [
    'enero',
    'febrero',
    'marzo',
    'abril',
    'mayo',
    'junio',
    'julio',
    'agosto',
    'septiembre',
    'octubre',
    'noviembre',
    'diciembre',
  ]
  return `${dia} de ${meses[mes - 1]} de ${anio}`
}
