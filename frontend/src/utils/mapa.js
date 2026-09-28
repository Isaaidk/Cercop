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
 * Galápagos va en un recuadro aparte**, con su propio encuadre y su línea de puntos que indica que
 * no está ahí. Es una convención que cualquiera del país reconoce al instante, y evita la
 * alternativa fácil —quitar Galápagos— que dejaría fuera a una provincia de verdad.
 */

/** Provincias que no entran en el encuadre principal porque se dibujan aparte. */
const ISLAS = 'Galapagos'

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
    const destino = nombre === ISLAS ? islas : continente
    destino.push({ nombre, geometria: feature.geometry })
  }

  // El encuadre del continente se calcula **solo con el continente**. Es el paso que evita que
  // Galápagos desplace el mapa y deje al país convertido en una línea.
  const marcoContinente = calcularMarco(continente)
  const marcoIslas = calcularMarco(islas)

  const margen = 12
  const proyeccionContinente = encajar(marcoContinente, ancho, alto - 40, margen)
  const proyeccionIslas = encajar(marcoIslas, 108, 74, 6)

  return {
    viewBox: `0 0 ${ancho} ${alto}`,
    provincias: [
      ...trazos(continente, proyeccionContinente, ancho, alto - 40),
      // Las islas se desplazan a la esquina inferior izquierda, que es donde queda libre en el
      // encuadre del continente: Ecuador se extiende hacia el norte y el este.
      ...trazos(islas, proyeccionIslas, ancho, alto - 40, { dx: 8, dy: (alto - 40) - 82 }),
    ],
    // El recuadro de las islas se dibuja aparte, con línea de puntos, para que se entienda que ese
    // trozo del mapa no está a escala ni en su sitio.
    recuadroIslas: { x: 8, y: alto - 40 - 82, ancho: 108, alto: 74 },
    ancho,
    alto,
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
