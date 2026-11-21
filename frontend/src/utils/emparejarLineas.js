/**
 * Qué ítem pedido por la entidad corresponde a cada línea de la proforma.
 *
 * Sirve para avisar «la entidad pide 3, aquí hay 20». Antes se emparejaba solo por CPC, y en una
 * ínfima de ferretería todos los ítems comparten el mismo (621650011: BROCHA 4", FLEXÓMETRO 5 MTS…):
 * cada línea caía en el primer ítem y casi todas salían con un aviso falso.
 *
 * El orden de confianza:
 *  1. la referencia que guarda la línea cuando se llenó desde los ítems (`item_ref`);
 *  2. el CPC, solo si ningún otro ítem lo comparte;
 *  3. el CPC (o todos los ítems, si la línea no tiene CPC) más el parecido de la descripción,
 *     con un ganador claro.
 * Sin una coincidencia segura devuelve `null`: mejor no avisar que avisar mal.
 */

const UMBRAL = 0.6
const MARGEN = 0.15

/** «BROCHA 4"» → «brocha 4»: sin tildes, sin signos, en minúsculas. */
export function normalizarTexto(texto) {
  return String(texto ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9ñ]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** La primera línea de la descripción: debajo van las especificaciones que se copiaron del TDR. */
function primeraLinea(texto) {
  return String(texto ?? '').split('\n').find((linea) => linea.trim()) || ''
}

function palabras(texto) {
  return new Set(normalizarTexto(texto).split(' ').filter(Boolean))
}

/**
 * Parecido entre la descripción de una línea y la de un ítem, de 0 a 1. Cuenta el solapamiento de
 * palabras (Dice) y, si la persona añadió detalle («BROCHA 4" MARCA WILSON»), que todas las palabras
 * del ítem sigan en la línea.
 */
export function parecido(descripcionLinea, descripcionItem) {
  const linea = palabras(primeraLinea(descripcionLinea))
  const item = palabras(primeraLinea(descripcionItem))
  if (!linea.size || !item.size) return 0
  let comunes = 0
  for (const palabra of item) if (linea.has(palabra)) comunes += 1
  const dice = (2 * comunes) / (linea.size + item.size)
  const contenido = item.size >= 2 ? (comunes / item.size) * 0.9 : 0
  return Math.max(dice, contenido)
}

/** La referencia estable de un ítem pedido: su número en la ficha o, si no lo trae, su posición. */
export function referenciaDeItem(item, posicion) {
  const numero = item?.numero
  return numero !== undefined && numero !== null && String(numero).trim() !== ''
    ? `n:${String(numero).trim()}`
    : `p:${posicion}`
}

/** El ítem pedido que corresponde a `linea`, o `null` si no hay uno seguro. */
export function emparejarLinea(linea, pedidos) {
  const items = Array.isArray(pedidos) ? pedidos : []
  if (!linea || !items.length) return null

  if (linea.item_ref) {
    const propio = items.find((item, posicion) => referenciaDeItem(item, posicion) === linea.item_ref)
    if (propio) return propio
  }

  const cpc = String(linea.cpc ?? '').trim()
  const mismoCpc = cpc ? items.filter((item) => String(item?.cpc ?? '').trim() === cpc) : []
  if (mismoCpc.length === 1) return mismoCpc[0]

  // Varios ítems con el CPC de la línea: decide la descripción. Sin CPC, se busca entre todos.
  const candidatos = mismoCpc.length ? mismoCpc : cpc ? [] : items
  if (!candidatos.length) return null
  const puntuados = candidatos
    .map((item) => ({ item, puntos: parecido(linea.descripcion, item?.descripcion) }))
    .sort((a, b) => b.puntos - a.puntos)
  const [mejor, segundo] = puntuados
  if (mejor.puntos < UMBRAL) return null
  if (segundo && mejor.puntos - segundo.puntos < MARGEN) return null
  return mejor.item
}

/** La cantidad pedida contra la escrita: el aviso solo sale con un emparejamiento seguro. */
export function cantidadDistinta(linea, pedidos) {
  const pedido = emparejarLinea(linea, pedidos)
  const pedida = Number(pedido?.cantidad)
  const escrita = Number(linea?.cantidad)
  if (!pedido || !(pedida > 0) || !(escrita > 0)) return null
  return Math.abs(pedida - escrita) > 1e-9 ? { pedido, pedida, escrita } : null
}
