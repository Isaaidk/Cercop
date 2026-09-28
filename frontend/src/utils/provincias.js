/**
 * Las 24 provincias del Ecuador y la correspondencia con los datos de la fuente.
 *
 * El problema que resuelve este archivo
 * -------------------------------------
 * La fuente oficial publica la ubicación como un solo texto con las dos cosas pegadas:
 * `"PICHINCHA - QUITO"`. Para filtrar por un cantón concreto eso sirve; para pintar un mapa donde se
 * pulsa *Pichincha* y aparecen **todas** sus contrataciones, no. Hay que separar la provincia del
 * cantón, y hacerlo bien: hay provincias cuyo nombre lleva espacios («LOS RIOS», «SANTO DOMINGO DE
 * LOS TSACHILAS») y cantones cuyo nombre lleva guiones, así que cortar por el primer guion y
 * recortar los espacios es lo único que funciona de forma general.
 *
 * Por qué la lista canónica está escrita a mano
 * --------------------------------------------
 * Podría deducirse de los datos, y sería un error: el mapa tiene que mostrar las 24 provincias
 * aunque todavía no haya contrataciones en tres de ellas. Si la lista saliera de los datos, un mapa
 * incompleto parecería un mapa completo y nadie sabría que falta información. Las que no tengan
 * datos se pintan igual, en gris, y eso es información.
 *
 * La lista de aquí es la del Ecuador continental e insular, con la grafía oficial. Los nombres del
 * mapa (GeoJSON) y los de la fuente (SERCOP) se comparan **normalizados** —sin tildes, sin
 * mayúsculas y sin puntuación— para que «Manabi», «MANABÍ» y «MANABI» sean lo mismo.
 */

/** Las 24 provincias, con el nombre como se muestra y el código usado por el mapa. */
export const PROVINCIAS = [
  { codigo: 'Azuay', nombre: 'Azuay' },
  { codigo: 'Bolivar', nombre: 'Bolívar' },
  { codigo: 'Canar', nombre: 'Cañar' },
  { codigo: 'Carchi', nombre: 'Carchi' },
  { codigo: 'Chimborazo', nombre: 'Chimborazo' },
  { codigo: 'Cotopaxi', nombre: 'Cotopaxi' },
  { codigo: 'El Oro', nombre: 'El Oro' },
  { codigo: 'Esmeraldas', nombre: 'Esmeraldas' },
  { codigo: 'Galapagos', nombre: 'Galápagos' },
  { codigo: 'Guayas', nombre: 'Guayas' },
  { codigo: 'Imbabura', nombre: 'Imbabura' },
  { codigo: 'Loja', nombre: 'Loja' },
  { codigo: 'Los Rios', nombre: 'Los Ríos' },
  { codigo: 'Manabi', nombre: 'Manabí' },
  { codigo: 'Morona Santiago', nombre: 'Morona Santiago' },
  { codigo: 'Napo', nombre: 'Napo' },
  { codigo: 'Orellana', nombre: 'Orellana' },
  { codigo: 'Pastaza', nombre: 'Pastaza' },
  { codigo: 'Pichincha', nombre: 'Pichincha' },
  { codigo: 'Santa Elena', nombre: 'Santa Elena' },
  { codigo: 'Santo Domingo de los Tsachilas', nombre: 'Santo Domingo de los Tsáchilas' },
  { codigo: 'Sucumbios', nombre: 'Sucumbíos' },
  { codigo: 'Tungurahua', nombre: 'Tungurahua' },
  { codigo: 'Zamora Chinchipe', nombre: 'Zamora Chinchipe' },
]

/**
 * Nombres alternativos que aparecen en los datos y que no coinciden con el nombre oficial.
 *
 * Existe porque la fuente no es constante: publica «MANABI» donde la provincia es «Manabí», y usa
 * «STO DGO DE LOS TSACHILAS» o «SANTO DOMINGO» para la misma provincia. Sin esta tabla, esas
 * contrataciones no aparecerían en el mapa y el total por provincia sería menor que el real, sin
 * ningún aviso.
 *
 * Se comparan en forma normalizada: minúsculas, sin tildes y sin puntuación.
 */
const ALIAS = {
  manabi: 'Manabi',
  sto: 'Santo Domingo de los Tsachilas',
  'sto dgo': 'Santo Domingo de los Tsachilas',
  'sto dgo de los tsachilas': 'Santo Domingo de los Tsachilas',
  'santo domingo': 'Santo Domingo de los Tsachilas',
  'santo domingo de los tsachilas': 'Santo Domingo de los Tsachilas',
  'los rios': 'Los Rios',
  'el oro': 'El Oro',
  galapagos: 'Galapagos',
  bolivar: 'Bolivar',
  canar: 'Canar',
  sucumbios: 'Sucumbios',
  orellana: 'Orellana',
  'zamora chinchipe': 'Zamora Chinchipe',
  'morona santiago': 'Morona Santiago',
  'santa elena': 'Santa Elena',
}

/**
 * Normaliza un nombre para poder compararlo.
 *
 * Se quitan tildes y todo lo que no sea letra o espacio. No se traduce ni se abrevian palabras: eso
 * convertiría «San» en «Santo» y equipararía provincias que no son la misma. Lo que no coincida se
 * queda fuera y se informa aparte, en lugar de asignarse a la provincia «más parecida»: un dato mal
 * ubicado en el mapa es peor que un dato ausente.
 */
export function normalizarNombre(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Índice de nombre normalizado → código de provincia, construido una sola vez. */
const INDICE = (() => {
  const mapa = new Map()
  for (const provincia of PROVINCIAS) {
    mapa.set(normalizarNombre(provincia.nombre), provincia.codigo)
    mapa.set(normalizarNombre(provincia.codigo), provincia.codigo)
  }
  for (const [alias, codigo] of Object.entries(ALIAS)) {
    mapa.set(normalizarNombre(alias), codigo)
  }
  return mapa
})()

/** El nombre presentable de una provincia a partir de su código. */
export function nombreDeProvincia(codigo) {
  return PROVINCIAS.find((provincia) => provincia.codigo === codigo)?.nombre || codigo
}

/**
 * Separa «PROVINCIA - CANTÓN» en sus dos partes.
 *
 * Se corta por el **primer** guion porque el cantón puede llevar más («PICHINCHA - SAN MIGUEL DE
 * LOS BANCOS» no, pero «GUAYAS - EL TRIUNFO - 2» sí aparece). Lo que va antes del primer guion es
 * siempre la provincia.
 */
export function separarProvincia(valor) {
  const texto = String(valor || '').trim()
  if (!texto) return { provincia: '', canton: '' }

  const corte = texto.indexOf('-')
  if (corte === -1) return { provincia: texto.trim(), canton: '' }

  return {
    provincia: texto.slice(0, corte).trim(),
    canton: texto.slice(corte + 1).trim(),
  }
}

/**
 * Traduce el nombre de una provincia de la fuente a su código, o `null` si no es una provincia.
 *
 * Devolver `null` es deliberado y ocurre más de lo que parece: la fuente publica valores como
 * `"NO DELIMITADO"` o `"EN EL EXTERIOR"` en el campo de la provincia. Asignarlos a una provincia
 * real inflaría su conteo; contarlos aparte y decirlo es lo honesto.
 */
export function codigoDeProvincia(nombre) {
  return INDICE.get(normalizarNombre(nombre)) || null
}

/**
 * Agrupa un listado «provincia - cantón» de la API en totales por provincia.
 *
 * Devuelve las 24 provincias siempre, con cero si no tienen datos, más una lista `sinUbicar` con lo
 * que no se pudo asociar a ninguna. Las dos partes viajan juntas a propósito: quien pinte el mapa
 * tiene que poder decir «y 42 contrataciones sin provincia identificada» en lugar de que la suma no
 * cuadre sin explicación.
 */
export function agruparPorProvincia(filas) {
  const totales = new Map(PROVINCIAS.map((provincia) => [provincia.codigo, 0]))
  const cantones = new Map(PROVINCIAS.map((provincia) => [provincia.codigo, []]))
  const sinUbicar = []
  let total = 0

  for (const fila of filas || []) {
    const cuantos = Number(fila.total ?? fila.cantidad ?? 0)
    total += cuantos

    const { provincia, canton } = separarProvincia(fila.provincia)
    const codigo = codigoDeProvincia(provincia)

    if (!codigo) {
      sinUbicar.push({ valor: fila.provincia, total: cuantos })
      continue
    }

    totales.set(codigo, (totales.get(codigo) || 0) + cuantos)
    if (canton) cantones.get(codigo).push({ canton, total: cuantos })
  }

  return {
    total,
    porProvincia: PROVINCIAS.map(({ codigo, nombre }) => ({
      codigo,
      nombre,
      total: totales.get(codigo) || 0,
      cantones: cantones.get(codigo).sort((a, b) => b.total - a.total),
    })).sort((a, b) => b.total - a.total),
    sinUbicar: sinUbicar.sort((a, b) => b.total - a.total),
  }
}
