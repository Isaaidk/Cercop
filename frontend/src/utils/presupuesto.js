/**
 * Cuánto del presupuesto de la entidad usa la proforma, mientras se escribe.
 *
 * La regla manda en el backend (`dominio/presupuesto.py::comparar_con_presupuesto`), que rechaza
 * guardar una proforma que lo supere. Aquí se repite solo para avisar antes de pulsar «Generar»:
 *
 * - si el presupuesto dice que incluye IVA, se compara el TOTAL; si dice que no, o no dice nada, el
 *   SUBTOTAL (el presupuesto referencial se publica, por regla, sin IVA);
 * - supera si pasa del presupuesto en más de medio centavo → no se puede generar;
 * - aviso si usa menos del 50 %, o si una línea con varias unidades pasa sola del presupuesto
 *   aunque su precio unitario quepa (casi siempre, el total escrito como unitario).
 */

export const USO_MINIMO = 0.5
const TOLERANCIA = 0.005

/** El presupuesto que dio la lectura del proceso, o null si no hay uno creíble. */
export function presupuestoValido(presupuesto) {
  const valor = Number(presupuesto?.valor)
  return Number.isFinite(valor) && valor > 0 ? { ...presupuesto, valor } : null
}

/**
 * @param {{subtotal: number, total: number}} totales
 * @param {Array<{cantidad: any, precio_unitario: any}>} lineas
 * @param {{valor: number, incluye_iva?: boolean|null}|null} presupuesto
 */
export function usoDelPresupuesto(totales, lineas, presupuesto) {
  const valido = presupuestoValido(presupuesto)
  if (!valido) return null
  const conIva = valido.incluye_iva === true
  const comparado = Number(conIva ? totales.total : totales.subtotal) || 0
  const porcentaje = (comparado / valido.valor) * 100
  const supera = comparado > valido.valor + TOLERANCIA
  const avisos = []
  if (!supera && comparado > 0 && comparado < valido.valor * USO_MINIMO) {
    avisos.push(
      `Usas solo el ${Math.round(porcentaje)} % del presupuesto. Revisa que no falte un ítem ni un cero en algún precio.`,
    )
  }
  ;(lineas || []).forEach((linea, posicion) => {
    const cantidad = Number(linea.cantidad) || 0
    const precio = linea.precio_unitario === '' ? 0 : Number(linea.precio_unitario) || 0
    if (cantidad > 1 && precio > 0 && precio <= valido.valor && precio * cantidad > valido.valor) {
      avisos.push(
        `La línea ${posicion + 1} pasa sola del presupuesto. ¿Escribiste el total de la línea como precio unitario?`,
      )
    }
  })
  return {
    comparado,
    base: conIva ? 'con IVA' : 'sin IVA',
    porcentaje,
    // La barra no pasa del 100 %: lo que sobra se dice con palabras, no con una barra desbordada.
    ancho: Math.max(0, Math.min(100, porcentaje)),
    supera,
    exceso: supera ? comparado - valido.valor : 0,
    restante: supera ? 0 : valido.valor - comparado,
    avisos,
  }
}
