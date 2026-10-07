/**
 * Convierte el mapa del Ecuador en trazos que el navegador puede pintar.
 *
 * Se hace aquí y no con una biblioteca de mapas por una razón concreta: lo único que hace falta es
 * **pintar 24 polígonos y saber cuál se pulsa**. Traer una biblioteca de cartografía para eso añade
 * cientos de kilobytes, una hoja de estilos que hay que reescribir para adaptarla al tema y una
 * versión más que actualizar. Calcular los trazos cuesta unas decenas de líneas y el resultado se
 * comporta igual que cualquier otro elemento de la interfaz: se pinta con las variables de color del
 * panel y se anima con transiciones de CSS.
 *
 * El problema de Galápagos, y por qué hay dos proyecciones
 * -------------------------------------------------------
 * Las islas están a unos 1.000 km del continente. Si se encuadra el país entero en un mismo marco,
 * la escala la marca Galápagos: el continente queda reducido a una franja estrecha y el mapa deja de
 * servir para leer nada.
 *
 * Se resuelve como lo hacen los mapas oficiales del Ecuador: **el continente ocupa el marco y
 * Galápagos va en un recuadro aparte**, pegado a la costa y a la altura que le corresponde, con su
 * línea de puntos que indica que no está ahí. Es una convención que cualquiera del país reconoce al
 * instante, y evita la alternativa fácil —quitar Galápagos— que dejaría fuera a una provincia de
 * verdad.
 *
 * El recuadro estaba escrito y **no hacía nada de esto**, porque la isla no se reconocía como isla:
 * el GeoJSON la llama «Galápagos» —con tilde— y aquí se comparaba contra «Galapagos» a secas. La
 * comparación exacta fallaba en silencio, Galápagos entraba en el encuadre del continente con sus
 * noventa y dos grados de longitud, y el resultado era el peor de los dos mundos: la escala se
 * hundía a la mitad —el país entero cabía en una franja de doscientos píxeles a la derecha— y el
 * recuadro de puntos, colocado en una esquina fija, quedaba **vacío** en la otra punta. Ahora los
 * nombres se comparan **normalizados**, como en el resto del panel (`utils/provincias`), y el
 * recuadro se coloca a partir de la geometría: a la altura de las islas y pegado a la costa.
 */

import { normalizarNombre } from './provincias'

/**
 * La provincia que se dibuja aparte, en **forma normalizada**.
 *
 * Normalizada porque el nombre del mapa lleva tildes y el de la fuente no: comparar los dos textos
 * tal cual es exactamente lo que dejó a las islas dentro del encuadre del continente.
 */
const ISLAS = 'galapagos'

/** Tamaño máximo del recuadro de las islas y su aire interior, en píxeles. */
const ANCHO_ISLAS = 88
const ALTO_ISLAS = 96
const RELLENO_ISLAS = 6

/** Separación entre el recuadro y la costa, y aire mínimo hasta el borde del lienzo. */
const HUECO_ISLAS = 8
const AIRE_ISLAS = 6

/**
 * Carga el mapa y devuelve los trazos ya proyectados.
 *
 * El resultado se memoriza: el archivo se descarga una vez y las proyecciones se calculan una vez,
 * aunque se cambie el tamaño de la ventana o se vuelva a entrar al panel.
 */
let cache = null
let enCurso = null

export async function cargarMapa() {
  if (cache) return cache
  if (enCurso) return enCurso

  enCurso = (async () => {
    const respuesta = await fetch(`${import.meta.env.BASE_URL}data/ecuador-provincias.geojson`)
    if (!respuesta.ok) {
      throw new Error(`No se pudo cargar el mapa (${respuesta.status}).`)
    }
    const geojson = await respuesta.json()
    cache = proyectar(geojson)
    enCurso = null
    return cache
  })()

  return enCurso
}

/**
 * Proyecta el mapa completo: el continente en su marco y las islas en el suyo.
 *
 * Devuelve dos grupos porque se pintan en dos sitios distintos del mismo `svg`, y cada uno con su
 * propia escala. Mezclarlos en un solo grupo obligaría a pintarlos con la misma transformación, que
 * es justo lo que hay que evitar.
 */
export function proyectar(geojson, { ancho = 620, alto = 520 } = {}) {
  const features = (geojson.features || []).filter((f) => f.geometry)

  const continente = []
  const islas = []

  for (const feature of features) {
    const nombre = feature.properties?.shapeName || ''
    const destino = normalizarNombre(nombre) === ISLAS ? islas : continente
    destino.push({ nombre, geometria: feature.geometry })
  }

  // El encuadre del continente se calcula **solo con el continente**. Es el paso que evita que
  // Galápagos desplace el mapa y deje al país convertido en una línea.
  const marcoContinente = calcularMarco(continente)
  const marcoIslas = calcularMarco(islas)

  const margen = 12
  const altoUtil = alto - 40
  const proyeccionContinente = encajar(marcoContinente, ancho, altoUtil, margen)
  const proyeccionIslas = encajar(marcoIslas, ANCHO_ISLAS, ALTO_ISLAS, RELLENO_ISLAS)
  const recuadro = recuadroDeLasIslas(marcoContinente, marcoIslas, proyeccionContinente, {
    alto: altoUtil,
  })

  return {
    viewBox: `0 0 ${ancho} ${alto}`,
    provincias: [
      ...trazos(continente, proyeccionContinente, ancho, altoUtil),
      // Las islas se dibujan dentro de su recuadro: la proyección las encuadra en un marco propio y
      // el desplazamiento las lleva al hueco que el continente deja libre a su izquierda.
      ...trazos(islas, proyeccionIslas, ancho, altoUtil, { dx: recuadro.x, dy: recuadro.y }),
    ],
    // El recuadro de las islas se dibuja aparte, con línea de puntos, para que se entienda que ese
    // trozo del mapa no está a escala ni en su sitio.
    recuadroIslas: recuadro,
    ancho,
    alto,
  }
}

/**
 * Dónde y de qué tamaño va el recuadro de las islas.
 *
 * **Dónde:** pegado a la costa y a la altura de las islas, no en una esquina. El recuadro dice «esto
 * está al oeste, fuera del encuadre»; una esquina lejana dice «esto está en cualquier sitio», y es
 * lo que hacía que Galápagos pareciera un mapa aparte olvidado en un borde.
 *
 * La altura se mide **en la proyección del continente**: se toma la latitud del centro de las islas
 * y se pregunta en qué píxel cae. Así el recuadro queda frente a la costa que le toca —Galápagos
 * está a la altura del norte de Manabí— sin escribir ninguna coordenada a mano, y sigue
 * cuadrando si algún día cambia el archivo del mapa.
 *
 * **De qué tamaño:** del ancho que quede libre a la izquierda del continente. Ecuador es más alto
 * que ancho, así que el encuadre deja una banda de océano a la izquierda; el recuadro se recorta a
 * lo que quepa para que nunca se monte encima del país y las islas parezcan estar en la costa. El
 * tope es `ANCHO_ISLAS`, porque un recuadro más grande que el continente deja de ser un detalle y
 * pasa a ser el mapa.
 */
function recuadroDeLasIslas(marcoContinente, marcoIslas, proyeccion, { alto }) {
  const [xCosta] = proyeccion.aPunto(marcoContinente.minLng, marcoContinente.minLat)
  const latitud = (marcoIslas.minLat + marcoIslas.maxLat) / 2
  const [, yIslas] = proyeccion.aPunto(0, latitud)

  const ancho = Math.min(ANCHO_ISLAS, xCosta - HUECO_ISLAS - AIRE_ISLAS)
  const altoRecuadro = Math.round(ancho * (ALTO_ISLAS / ANCHO_ISLAS))

  return {
    x: Math.round(xCosta - HUECO_ISLAS - ancho),
    y: Math.round(
      Math.min(Math.max(yIslas - altoRecuadro / 2, AIRE_ISLAS), alto - altoRecuadro - AIRE_ISLAS),
    ),
    ancho,
    alto: altoRecuadro,
  }
}

/** Rectángulo que contiene todas las geometrías, en grados. */
function calcularMarco(entradas) {
  let minLng = Infinity
  let maxLng = -Infinity
  let minLat = Infinity
  let maxLat = -Infinity

  for (const { geometria } of entradas) {
    for (const anillo of anillos(geometria)) {
      for (const [lng, lat] of anillo) {
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) continue
        if (lng < minLng) minLng = lng
        if (lng > maxLng) maxLng = lng
        if (lat < minLat) minLat = lat
        if (lat > maxLat) maxLat = lat
      }
    }
  }

  if (!Number.isFinite(minLng)) return { minLng: -81, maxLng: -75, minLat: -5, maxLat: 1.5 }
  return { minLng, maxLng, minLat, maxLat }
}

/** Recorre los anillos de cualquier geometría (Polygon o MultiPolygon). */
function* anillos(geometria) {
  if (geometria.type === 'Polygon') {
    for (const anillo of geometria.coordinates) yield anillo
    return
  }
  if (geometria.type === 'MultiPolygon') {
    for (const poligono of geometria.coordinates) {
      for (const anillo of poligono) yield anillo
    }
  }
}

/**
 * Calcula la transformación de grados a píxeles conservando la proporción.
 *
 * Se usa una única escala para los dos ejes. Con dos escalas independientes el mapa se estiraría
 * hasta llenar el marco y las provincias quedarían deformadas: Pichincha, que es más ancha que alta,
 * parecería cuadrada. Se prefiere un poco de espacio libre a un mapa con las formas mal.
 */
function encajar(marco, ancho, alto, margen) {
  const anchoGrados = Math.max(marco.maxLng - marco.minLng, 1e-6)
  const altoGrados = Math.max(marco.maxLat - marco.minLat, 1e-6)

  const disponibleAncho = ancho - margen * 2
  const disponibleAlto = alto - margen * 2

  const escala = Math.min(disponibleAncho / anchoGrados, disponibleAlto / altoGrados)

  // Se centra el resultado en el marco sobrante, para que el mapa no quede pegado a una esquina.
  const desplazamientoX = margen + (disponibleAncho - anchoGrados * escala) / 2
  const desplazamientoY = margen + (disponibleAlto - altoGrados * escala) / 2

  return {
    // La latitud se invierte: en grados crece hacia el norte y en pantalla hacia abajo.
    aPunto: (lng, lat) => [
      desplazamientoX + (lng - marco.minLng) * escala,
      desplazamientoY + (marco.maxLat - lat) * escala,
    ],
  }
}

/**
 * Convierte una lista de provincias en trazos de `path` de SVG.
 *
 * Se redondea a un decimal: sin redondear, cada coordenada ocupa quince caracteres y el trazado
 * resultante pesa el triple sin que se aprecie ninguna diferencia en pantalla. Un decimal en un
 * lienzo de 620 píxeles es una décima de píxel.
 */
function trazos(entradas, proyeccion, ancho, alto, { dx = 0, dy = 0 } = {}) {
  return entradas.map(({ nombre, geometria }) => {
    const partes = []

    for (const anillo of anillos(geometria)) {
      let primero = true
      for (const [lng, lat] of anillo) {
        const [x, y] = proyeccion.aPunto(lng, lat)
        const px = (x + dx).toFixed(1)
        const py = (y + dy).toFixed(1)
        partes.push(`${primero ? 'M' : 'L'}${px},${py}`)
        primero = false
      }
      partes.push('Z')
    }

    return { nombre, d: partes.join(' ') }
  })
}
