/**
 * Texto del TDR listo para leerse en pantalla.
 *
 * El backend ya limpia lo que lee (`dominio/documentos.py::limpiar_texto`), pero las lecturas y los
 * requisitos guardados antes de esa limpieza siguen en la base y se enseñan tal cual. Esto aplica
 * las mismas reglas de forma, las seguras, para que un TDR viejo tampoco se vea con «……………».
 * Solo es presentación: lo que se envía al servidor no pasa por aquí.
 */

export const POR_COMPLETAR = '[por completar]'

const MARCADOR = POR_COMPLETAR.replace(/[[\]]/g, '\\$&')
const SEGUIDOS = new RegExp(`${MARCADOR}(?:[\\s.,:;/-]*${MARCADOR})+`, 'g')

/** Una racha de puntos, elipsis o guiones bajos que pesa cuatro puntos o más es un hueco. */
function hueco(racha) {
  const peso = [...racha].reduce((suma, letra) => suma + (letra === '…' ? 3 : letra === ' ' ? 0 : 1), 0)
  return peso >= 4 ? ` ${POR_COMPLETAR} ` : racha
}

export function textoLegible(texto) {
  let plano = String(texto ?? '')
    .replace(/[ \t ]+/g, ' ')
    .trim()
  if (!plano) return ''
  plano = plano.replace(/[.…_](?: ?[.…_])*/g, hueco)
  plano = plano.replace(SEGUIDOS, POR_COMPLETAR)
  // «I T E M» → «ITEM»: cuatro o más mayúsculas sueltas. Con tres se arriesga a pegar «A Y B».
  plano = plano.replace(/(?<![\p{L}\d])((?:\p{Lu} ){3,}\p{Lu})(?![\p{L}\d])/gu, (todo) => todo.replace(/ /g, ''))
  plano = plano
    .replace(/[ \t]+/g, ' ')
    .replace(/ +([:;,)])/g, '$1')
    .replace(/\( +/g, '(')
    .replace(/\$ +(?=\[)/g, '$')
    .replace(SEGUIDOS, POR_COMPLETAR)
  return plano
    .split('\n')
    .map((linea) => linea.trim())
    .filter(Boolean)
    .join('\n')
}

/**
 * Trozos del texto para pintar los huecos aparte: `[{ texto, hueco }]`. Así «[por completar]» se ve
 * como un dato que falta y no como parte de la frase.
 */
export function trozosTdr(texto) {
  const limpio = textoLegible(texto)
  if (!limpio) return []
  return limpio
    .split(POR_COMPLETAR)
    .flatMap((parte, n) => (n === 0 ? [{ texto: parte, hueco: false }] : [{ texto: POR_COMPLETAR, hueco: true }, { texto: parte, hueco: false }]))
    .filter((trozo) => trozo.texto)
}
