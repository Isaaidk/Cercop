/**
 * Reglas de los términos que se escriben a mano: cuánto tienen que medir y con qué se comparan.
 *
 * Vive en un solo archivo porque lo usan sitios distintos —el almacén de filtros del panel lateral y
 * los campos de la pestaña de ofertas— y una regla duplicada se separa: el día que una de las dos
 * copias cambiara, la misma palabra se aceptaría en una pantalla y se rechazaría en la otra sin que
 * nada avisara.
 */

/**
 * Longitud mínima de un término de búsqueda.
 *
 * Tres letras es lo que exige el servidor (`LONGITUD_MINIMA_TERMINO` en el dominio) y lo que ya
 * exigían los otros campos: con menos no se busca, se adivina. La comprobación de aquí es para
 * explicarlo antes de pulsar; la que garantiza que no se cuele es la del servidor.
 *
 * Es **la única** declaración del mínimo en el panel. Estaba escrita cuatro veces —en el gestor de
 * palabras clave, en el de CPC, en la pestaña de ofertas y en el almacén de filtros— y cuatro copias
 * del mismo número son cuatro sitios donde cambiarlo y tres donde olvidarlo.
 */
export const LONGITUD_MINIMA_TERMINO = 3

/**
 * Separa una lista pegada por la persona en términos.
 *
 * Se aceptan comas, punto y coma y saltos de línea porque son los tres separadores que aparecen al
 * copiar de una hoja de cálculo, que es de donde sale casi siempre una lista de términos.
 *
 * Las palabras de menos de tres letras se descartan **y se cuentan**: el contador de la pantalla dice
 * cuántas se van a añadir antes de pulsar, y quien pega veinte términos merece saber que uno se
 * quedó fuera por corto en lugar de descubrirlo después contando fichas.
 *
 * Los repetidos se unifican sin distinguir mayúsculas —«Lavado» y «lavado» son el mismo filtro,
 * porque el servidor normaliza— y se conserva la primera grafía escrita, que es la que la persona
 * reconoce. Se resuelve aquí, en una sola función, para que el contador y el alta no puedan
 * discrepar: si cada una contara a su manera, el botón diría «Añadir 7» y añadiría 5.
 *
 * Vive aquí y no en cada gestor porque la usan el CPC, la descripción del producto y las palabras
 * clave: es la misma idea —pegar una lista— y tiene que comportarse igual en los tres sitios.
 */
export function terminosDeLista(texto, minimo = LONGITUD_MINIMA_TERMINO) {
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

/**
 * Clave con la que se comparan dos términos para no repetir: sin mayúsculas ni acentos.
 *
 * Es la misma reducción que aplica el servidor al normalizar los términos, así que «LAVADO»,
 * «Lavado» y «lavado» son el mismo filtro. Se hace también en el navegador para que las fichas no se
 * dupliquen en pantalla mientras el servidor responde.
 */
export function claveDeTermino(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
    .toLowerCase()
}
