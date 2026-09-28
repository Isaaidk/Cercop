/**
 * Los filtros activos: palabras clave, provincia, fechas y orden.
 *
 * Es el estado del que depende **todo** lo que se ve en el panel: la tabla, las gráficas y el mapa
 * salen de aquí. Por eso los filtros viven en un almacén y no en un componente: si cada pestaña
 * guardara los suyos, cambiar de pestaña perdería la búsqueda y el usuario tendría que volver a
 * escribirla.
 *
 * La decisión importante: **la selección de provincia vive aparte de los filtros de texto.**
 * Podría parecer un filtro más y no lo es. Al pulsar una provincia en el mapa se busca por ella
 * *y* por las palabras clave a la vez, así que la provincia no puede sustituir al texto ni al revés.
 * Manteniéndola separada, el usuario puede ver «obras viales en Pichincha», quitar la provincia y
 * seguir con las mismas palabras sin rehacer nada.
 */

import { computed, reactive } from 'vue'

import { api } from '@/api/endpoints'

/** Longitud mínima de una palabra clave, la misma que exige el servidor. */
const LONGITUD_MINIMA = 3

const estado = reactive({
  /** Todas las palabras clave del negocio, con su estado de ingesta. */
  palabras: [],
  /** Las que están activas como filtro. Puede haber varias a la vez. */
  seleccionadas: [],

  provincia: null,
  canton: null,
  estadoRegistro: null,
  /**
   * La fuente de datos: `NCO` (necesidades de contratación) u `OCDS` (contrataciones publicadas).
   *
   * Estaba en el panel de filtros antes de existir aquí, y el desplegable no hacía nada: cambiaba un
   * valor que no se guardaba en ningún sitio ni viajaba a la API. Se declara junto al resto de
   * criterios para que no pueda volver a pasar: si un control escribe un filtro, el filtro tiene que
   * estar aquí.
   */
  fuente: null,
  desde: null,
  hasta: null,
  /**
   * `cualquiera` suma los resultados de cada palabra; `todas` exige que aparezcan todas.
   *
   * El valor por defecto es `cualquiera`, y no es una preferencia: quien suscribe palabras clave
   * suscribe **lo que quiere vigilar**, y vigilar no es una intersección. Con «todas», marcar dos
   * palabras que por separado devuelven 7 y 31 filas devuelve **cero** —porque ninguna contratación
   * menciona las dos a la vez— y el panel dice «no hay contrataciones» justo cuando más filtros se
   * han puesto. Sumar es lo que se espera al marcar varias casillas; acotar sigue disponible en el
   * botón «Todas».
   */
  modo: 'cualquiera',
  orden: 'recientes',
  soloNuevos: false,
  /** Deja fuera lo que ya no admite entrega de proformas. */
  soloConPlazo: false,

  pagina: 1,
  tamano: 25,

  cargandoPalabras: false,
  errorPalabras: '',
})

/**
 * Los criterios **ya aplicados**: son los únicos que consultan la API.
 *
 * `estado` es el borrador —lo que hay escrito en los controles— y `aplicados` es la fotografía de ese
 * borrador en el momento en que se pulsó «Aplicar filtros». La separación existe porque el panel se
 * recargaba en cada gesto: mover una fecha, marcar una casilla o pulsar una palabra clave lanzaban una
 * consulta, y con veinte palabras clave eso son veinte recargas seguidas. Las gráficas y el mapa se
 * rehacían en cada una, y la sensación era la de una pantalla que no deja leer nada.
 *
 * Con el borrador, tocar un control no consulta nada: solo marca que hay algo pendiente. La consulta
 * —y con ella el redibujado— ocurre una vez, cuando se pide.
 *
 * La paginación y el orden **no** pasan por aquí. Son navegación, no criterios: nadie espera pulsar
 * «siguiente» y que no ocurra nada hasta aplicarlo.
 */
const CAMPOS_DE_CRITERIO = [
  'seleccionadas',
  'modo',
  'provincia',
  'canton',
  'estadoRegistro',
  'fuente',
  'desde',
  'hasta',
  'soloNuevos',
  'soloConPlazo',
]

/**
 * Copia los criterios de un borrador.
 *
 * Los arreglos se copian en profundidad **a propósito**: `seleccionadas` es una lista, y guardarla por
 * referencia haría que el borrador y lo aplicado fueran el mismo objeto, con lo que marcar una palabra
 * clave cambiaría también lo que está en vigor y el botón de aplicar no tendría nada que hacer.
 */
function criteriosDe(origen) {
  const copia = {}
  for (const campo of CAMPOS_DE_CRITERIO) {
    const valor = origen[campo]
    copia[campo] = Array.isArray(valor) ? [...valor] : valor
  }
  return copia
}

const aplicados = reactive(criteriosDe(estado))

export const filtros = {
  estado,

  /** Los criterios en vigor, para leerlos sin depender del borrador. */
  aplicados,

  /** Hay algún criterio en vigor: es lo que explica lo que se está viendo. */
  hayFiltros: computed(
    () =>
      aplicados.seleccionadas.length > 0 ||
      Boolean(aplicados.provincia) ||
      Boolean(aplicados.estadoRegistro) ||
      Boolean(aplicados.fuente) ||
      Boolean(aplicados.desde) ||
      Boolean(aplicados.hasta) ||
      aplicados.soloNuevos ||
      aplicados.soloConPlazo,
  ),

  /** Cuántos criterios están en vigor, para el rótulo del botón de limpiar. */
  cuantos: computed(() => {
    let total = aplicados.seleccionadas.length > 1 ? 1 : aplicados.seleccionadas.length
    if (aplicados.provincia) total += 1
    if (aplicados.estadoRegistro) total += 1
    if (aplicados.fuente) total += 1
    if (aplicados.desde || aplicados.hasta) total += 1
    if (aplicados.soloNuevos) total += 1
    if (aplicados.soloConPlazo) total += 1
    return total
  }),

  /**
   * Cuántos criterios han cambiado desde la última vez que se aplicaron.
   *
   * Es lo que decide si el botón de aplicar hace algo, y el número que se le enseña al usuario. Sin
   * él, un botón que a veces no responde parece roto; con él, «Aplicar 3 filtros» explica por qué está
   * encendido y cuánto queda pendiente.
   */
  pendientes: computed(() => {
    let total = 0
    for (const campo of CAMPOS_DE_CRITERIO) {
      const actual = estado[campo]
      const vigente = aplicados[campo]
      const cambiado = Array.isArray(actual)
        ? actual.length !== vigente.length || actual.some((valor, i) => valor !== vigente[i])
        : actual !== vigente
      if (cambiado) total += 1
    }
    return total
  }),

  hayCambiosSinAplicar: computed(() => filtros.pendientes.value > 0),

  /**
   * Fija los criterios del borrador y vuelve a la primera página.
   *
   * Volver a la página uno no es un detalle: si se está en la siete de un resultado que el filtro
   * nuevo deja en dos páginas, seguir en la siete da «no hay resultados» y parece que el filtro no
   * encontró nada.
   */
  aplicar() {
    Object.assign(aplicados, criteriosDe(estado))
    estado.pagina = 1
  },

  /**
   * Traduce los criterios **en vigor** a los parámetros que entiende la API.
   *
   * Los campos vacíos se omiten en lugar de enviarse en blanco. No es lo mismo: `?provincia=` es un
   * filtro que pide «provincia vacía» y no devuelve nada, mientras que no enviar el parámetro es
   * «sin filtro por provincia». Con la búsqueda de texto pasa lo mismo y sería el fallo más difícil
   * de ver, porque la pantalla se quedaría en blanco sin ningún error.
   */
  parametros: computed(() => {
    const salida = {
      termino: aplicados.seleccionadas,
      modo: aplicados.modo,
      orden: estado.orden,
      pagina: estado.pagina,
      tamano: estado.tamano,
      provincia: aplicados.provincia ? nombreParaApi(aplicados.provincia) : null,
      estado: aplicados.estadoRegistro,
      fuente: aplicados.fuente,
      desde: aplicados.desde,
      hasta: aplicados.hasta,
      solo_nuevos: aplicados.soloNuevos ? true : null,
      solo_con_plazo: aplicados.soloConPlazo ? true : null,
    }

    if (!aplicados.seleccionadas.length) salida.termino = null
    return salida
  }),

  // --- Palabras clave ------------------------------------------------------

  async cargarPalabras() {
    estado.cargandoPalabras = true
    estado.errorPalabras = ''
    try {
      const datos = await api.listarTerminos()
      estado.palabras = datos.terminos || []
      // Si una palabra seleccionada ya no existe —otra persona del negocio la quitó—, se descarta la
      // selección. Mantenerla haría que la búsqueda no devolviera nada y el filtro no la mostraría
      // entre las opciones: el usuario vería «no hay resultados» sin poder saber por qué.
      const vigentes = new Set(estado.palabras.map((p) => p.texto))
      estado.seleccionadas = estado.seleccionadas.filter((texto) => vigentes.has(texto))
      // La selección **aplicada** se poda igual. Si solo se podara el borrador, un término retirado
      // por otro miembro del negocio seguiría viajando a la API y la búsqueda devolvería cero sin que
      // nada en pantalla lo explicara.
      aplicados.seleccionadas = aplicados.seleccionadas.filter((texto) => vigentes.has(texto))
      return estado.palabras
    } catch (error) {
      estado.errorPalabras = error.message
      return []
    } finally {
      estado.cargandoPalabras = false
    }
  },

  async agregarPalabra(texto) {
    const limpio = String(texto || '').trim()
    if (!limpio) return null

    const resultado = await api.agregarTermino(limpio)
    await this.cargarPalabras()
    // La palabra recién agregada se deja seleccionada: quien la escribe es porque quiere buscar por
    // ella. Obligarle a pulsarla otra vez después de haberla escrito es un paso de más.
    if (!estado.seleccionadas.includes(resultado.termino)) {
      estado.seleccionadas.push(resultado.termino)
    }
    return resultado
  },

  /**
   * Agrega varias palabras clave de una vez, a partir de un texto separado por comas.
   *
   * Va en **una sola petición**. Hacerlo una por una serían treinta y cinco peticiones encadenadas y,
   * como cada una tarda en abrir su conexión con la base, la espera se iría a más de un minuto: el
   * usuario creería que se ha colgado. El servidor las crea todas en una transacción.
   *
   * Se acepta también punto y coma y salto de línea como separador porque es lo que sale al copiar de
   * una hoja de cálculo, y se descartan las que queden demasiado cortas sin abortar el resto: perder
   * treinta y cuatro buenas porque una tenía dos letras sería un mal trueque.
   */
  async agregarPalabras(texto) {
    const partes = String(texto || '')
      .split(/[,;\n]/)
      .map((parte) => parte.trim())
      .filter(Boolean)

    const unicas = [...new Set(partes.map((parte) => parte.toLowerCase()))]
    const validas = unicas.filter((parte) => parte.length >= LONGITUD_MINIMA)
    if (!validas.length) return { terminos: [], descartadas: unicas.length }

    const resultado = await api.agregarTerminos(validas)
    await this.cargarPalabras()

    for (const termino of resultado.terminos || []) {
      if (!estado.seleccionadas.includes(termino)) estado.seleccionadas.push(termino)
    }
    return { ...resultado, descartadas: unicas.length - validas.length }
  },

  alternarPalabra(texto) {
    const indice = estado.seleccionadas.indexOf(texto)
    if (indice === -1) estado.seleccionadas.push(texto)
    else estado.seleccionadas.splice(indice, 1)
  },

  quitarPalabra(texto) {
    const indice = estado.seleccionadas.indexOf(texto)
    if (indice !== -1) estado.seleccionadas.splice(indice, 1)
  },

  seleccionarTodas() {
    estado.seleccionadas = estado.palabras.map((p) => p.texto)
  },

  limpiarPalabras() {
    estado.seleccionadas = []
  },

  // --- Provincia -----------------------------------------------------------

  /** Pulsar la provincia ya seleccionada la quita: es como se deshace el filtro desde el mapa. */
  alternarProvincia(codigo) {
    estado.provincia = estado.provincia === codigo ? null : codigo
    estado.canton = null
  },

  elegirCanton(canton) {
    estado.canton = estado.canton === canton ? null : canton
  },

  limpiarProvincia() {
    estado.provincia = null
    estado.canton = null
  },

  // --- Resto ---------------------------------------------------------------

  cambiarPagina(pagina) {
    estado.pagina = Math.max(1, pagina)
  },

  cambiarTamano(tamano) {
    estado.tamano = tamano
    estado.pagina = 1
  },

  /**
   * Escribe varios criterios en el borrador de una vez.
   *
   * **No toca la página**, y eso es deliberado. La página se aplica al instante y viaja en los
   * parámetros, así que reiniciarla aquí lanzaría una consulta con los criterios **viejos** y la
   * página nueva: exactamente la recarga que se quiere evitar. El reinicio ocurre en `aplicar()`, que
   * es donde los criterios y la página cambian juntos.
   */
  actualizar(cambios) {
    Object.assign(estado, cambios)
  },

  /**
   * Limpia el borrador **y los criterios en vigor**.
   *
   * Dejarlo solo en el borrador sería peor que no ofrecer el botón: la tabla seguiría filtrada por lo
   * anterior y el usuario vería los controles vacíos, sin manera de entender de dónde sale lo que
   * está viendo.
   */
  limpiarTodo() {
    estado.seleccionadas = []
    estado.provincia = null
    estado.canton = null
    estado.estadoRegistro = null
    estado.fuente = null
    estado.desde = null
    estado.hasta = null
    estado.soloNuevos = false
    estado.soloConPlazo = false
    Object.assign(aplicados, criteriosDe(estado))
    estado.pagina = 1
  },
}

/**
 * Convierte el código interno de una provincia en el nombre que espera la API.
 *
 * La API filtra por provincia comparando con la parte de antes del guion de `"PROVINCIA - CANTÓN"`,
 * así que lo que hay que enviar es el nombre en mayúsculas tal y como lo publica la fuente. El
 * servidor recorta y compara sin distinguir mayúsculas por su parte, de modo que una diferencia de
 * grafía no rompe la búsqueda; aun así se envía en mayúsculas porque es la forma del dato original y
 * hace que el filtro sea evidente al mirar la URL o los registros del servidor.
 */
function nombreParaApi(codigo) {
  return String(codigo).toUpperCase()
}
