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
import { terminosDeLista } from '@/utils/cpc'

/** Longitud mínima de una palabra clave, la misma que exige el servidor. */
const LONGITUD_MINIMA = 3

const estado = reactive({
  /** Todas las palabras clave del negocio, con su estado de ingesta. */
  palabras: [],
  /** Las que están activas como filtro. Puede haber varias a la vez. */
  seleccionadas: [],

  /**
   * Las palabras con las que se busca en el **CPC**, no en el texto de la convocatoria.
   *
   * Es un filtro distinto del de palabras clave y por eso vive aparte. La búsqueda de palabras
   * clave mira el objeto de compra, que es texto libre escrito por la entidad: pedir «lavado»
   * devuelve desde un servicio de lavado de vehículos hasta una capacitación sobre prevención de
   * lavado de activos. El CPC es la clasificación normalizada del Estado, así que buscar ahí
   * encuentra **lo que está clasificado así** y deja fuera lo que solo lo menciona de pasada.
   *
   * No se elige de un catálogo cerrado: se escribe. Los códigos se pueden teclear tal cual —
   * `871410032`— porque la búsqueda también cubre el código.
   */
  cpc: [],

  /**
   * Las provincias elegidas en el mapa. **Es una lista**, no un valor suelto.
   *
   * Comparar la misma búsqueda en tres provincias es un uso real —«¿dónde se está comprando esto?»—,
   * y con un valor único habría que hacer tres consultas y sumar los resultados a mano. La API acepta
   * el parámetro repetido, así que la lista viaja en una sola petición.
   */
  provincias: [],
  canton: null,
  estadoRegistro: null,
  /**
   * El NIC de una ínfima cuantía: el «NIC-1768120280001-2022-00003» que la ficha publica como
   * código de la necesidad. Es el mismo criterio `codigo` que ya usaba el listado de ofertas, pero
   * aquí se llama por su nombre de negocio, que es como lo nombra quien tiene la ficha delante.
   *
   * Se escribe y no se elige: nadie recuerda el código entero, así que el servidor compara por
   * **fragmento** —los últimos dígitos, el año— y no por igualdad.
   */
  codigo: null,
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

  /**
   * La familia de contratación que se está mirando: `'infimas'`, `'ofertas'` o `null` (todas).
   *
   * **No es un criterio del borrador sino de la vista**, y por eso vive aquí abajo con la paginación
   * y el orden, no con los filtros. La fija la pestaña —«Ínfimas cuantías» pone `infimas`, el mapa
   * deja elegir— y se aplica al instante, sin pasar por el botón de aplicar: nadie espera pulsar
   * «aplicar» después de cambiar de pestaña, igual que nadie lo espera al pasar de página.
   *
   * Tampoco cuenta en «cuántos filtros hay puestos». No se lo ha pedido el usuario a un control: es
   * dónde está mirando. Contarlo haría que el botón de limpiar dijera que hay un filtro activo sin
   * que el usuario hubiera filtrado nada, y limpiarlo no cambiaría lo que ve.
   */
  categoria: null,

  pagina: 1,
  tamano: 25,

  cargandoPalabras: false,
  errorPalabras: '',

  /**
   * Carga y error de la lista de CPC. Van aparte de los de las palabras clave porque son dos
   * peticiones distintas y un fallo en una no puede dejar la otra sin estado que enseñar.
   */
  cargandoCpc: false,
  errorCpcLista: '',
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
  'cpc',
  'modo',
  'provincias',
  'canton',
  'estadoRegistro',
  'codigo',
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

/**
 * Pone **en vigor** la lista de CPC que hay en el borrador.
 *
 * La lista de CPC no es un catálogo donde elegir: es la vigilancia que el equipo decidió, y quien la
 * cambia espera verla funcionando. Por eso sus cuatro mutaciones la aplican al instante, igual que
 * `cargarCpc` la aplica al abrir el panel.
 *
 * Antes se quedaba en el borrador y había que pulsar «Aplicar». El síntoma era el peor posible: la
 * lista se guardaba de verdad —el servidor la devolvía y su chip aparecía en pantalla— y la tabla
 * seguía enseñando lo mismo, así que lo que se lee es «el filtro no hace nada» o incluso «no me deja
 * agregar la lista». La vuelta a la página uno es la misma que hace `aplicar()`: si el filtro nuevo
 * deja el resultado en dos páginas y se está mirando la siete, seguir en la siete dice «no hay
 * resultados» y parece que el filtro no encontró nada.
 */
function aplicarClavesCpc() {
  aplicados.cpc = [...estado.cpc]
  estado.pagina = 1
}

export const filtros = {
  estado,

  /** Los criterios en vigor, para leerlos sin depender del borrador. */
  aplicados,

  /** Hay algún criterio en vigor: es lo que explica lo que se está viendo. */
  hayFiltros: computed(
    () =>
      aplicados.seleccionadas.length > 0 ||
      aplicados.cpc.length > 0 ||
      aplicados.provincias.length > 0 ||
      Boolean(aplicados.estadoRegistro) ||
      Boolean(aplicados.codigo) ||
      Boolean(aplicados.fuente) ||
      Boolean(aplicados.desde) ||
      Boolean(aplicados.hasta) ||
      aplicados.soloNuevos ||
      aplicados.soloConPlazo,
  ),

  /** Cuántos criterios están en vigor, para el rótulo del botón de limpiar. */
  cuantos: computed(() => {
    let total = aplicados.seleccionadas.length > 1 ? 1 : aplicados.seleccionadas.length
    if (aplicados.cpc.length) total += 1
    if (aplicados.provincias.length) total += 1
    if (aplicados.estadoRegistro) total += 1
    if (aplicados.codigo) total += 1
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
      cpc: aplicados.cpc,
      modo: aplicados.modo,
      orden: estado.orden,
      pagina: estado.pagina,
      tamano: estado.tamano,
      provincia: aplicados.provincias.map(nombreParaApi),
      // La familia viaja como criterio de la vista, no del borrador.
      categoria: estado.categoria,
      estado: aplicados.estadoRegistro,
      // Vacío se envía como `null` para que el cliente omita el parámetro: `?codigo=` sería «código
      // vacío» y no devolvería nada, mientras que no enviarlo es «sin filtro por código». Es el
      // mismo cuidado que con `termino` y `cpc`.
      codigo: (aplicados.codigo || '').trim() || null,
      fuente: aplicados.fuente,
      desde: aplicados.desde,
      hasta: aplicados.hasta,
      solo_nuevos: aplicados.soloNuevos ? true : null,
      solo_con_plazo: aplicados.soloConPlazo ? true : null,
    }

    if (!aplicados.seleccionadas.length) salida.termino = null
    // Mismo motivo que con los términos: `?cpc=` en blanco es «CPC vacío» y no devuelve nada,
    // mientras que no enviar el parámetro es «sin filtro por CPC».
    if (!aplicados.cpc.length) salida.cpc = null
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

  // --- Búsqueda por CPC ----------------------------------------------------

  /**
   * Trae la lista de términos de CPC guardada por el negocio.
   *
   * Se **aplica de inmediato**, a diferencia de las palabras clave, que se cargan para poder
   * marcarlas. La razón es que esta lista no es un catálogo donde elegir: es la vigilancia que el
   * equipo decidió, y quien abre el panel espera verla funcionando. Los términos siguen pudiéndose
   * quitar de uno en uno con su ficha.
   */
  async cargarCpc() {
    estado.cargandoCpc = true
    estado.errorCpcLista = ''
    try {
      const datos = await api.listarCpc()
      const claves = (datos.claves || []).map((clave) => String(clave))
      estado.cpc = [...claves]
      aplicados.cpc = [...claves]
      return claves
    } catch (error) {
      estado.errorCpcLista = error.message
      return []
    } finally {
      estado.cargandoCpc = false
    }
  },

  /**
   * Añade un término a la búsqueda por CPC, sin repetirlo, y lo guarda.
   *
   * Se guarda **primero** en el servidor y solo después en la pantalla: al revés, un fallo de red
   * dejaría la ficha puesta en una lista que no existe, y al recargar desaparecería sin explicación.
   *
   * La comparación para no repetir ignora mayúsculas y acentos —«LAVADO», «Lavado» y «lavado» son el
   * mismo filtro—, que es la misma regla que aplica el servidor al comparar.
   */
  async agregarCpc(texto) {
    const limpio = String(texto || '').trim()
    if (limpio.length < LONGITUD_MINIMA) return { agregado: false, motivo: 'corta' }

    const clave = normalizarClave(limpio)
    if (estado.cpc.some((termino) => normalizarClave(termino) === clave)) {
      return { agregado: false, motivo: 'repetida' }
    }

    const datos = await api.agregarUnCpc(limpio)
    // El servidor decide: si dice que ya estaba, no se añade nada. Es la respuesta autoritativa, y
    // creer a la pantalla antes que al servidor dejaría dos listas distintas.
    if (!datos.agregadas) return { agregado: false, motivo: 'repetida' }

    estado.cpc.push(limpio)
    aplicarClavesCpc()
    return { agregado: true, motivo: '' }
  },

  quitarCpc(texto) {
    const indice = estado.cpc.indexOf(texto)
    if (indice !== -1) estado.cpc.splice(indice, 1)
    aplicarClavesCpc()
    // El borrado viaja sin esperar a la respuesta: la ficha ya no está en la pantalla, y si el
    // servidor falla se dice en el aviso sin devolverla a una lista de la que la persona la acaba
    // de sacar. Al recargar manda el servidor.
    return api.quitarCpc(texto).catch(() =>
      Promise.reject(new Error('No se pudo quitar el término de la lista guardada.')),
    )
  },

  async limpiarCpc() {
    await api.vaciarCpc()
    estado.cpc = []
    aplicarClavesCpc()
  },

  /**
   * Añade una lista pegada de términos de CPC: el mismo gesto que con las palabras clave.
   *
   * Se guarda en el servidor, como el alta individual, y **no** dispara ingesta: un término de CPC
   * solo acota lo que ya está descargado, así que no hay catálogo global, ni cola, ni espera de un
   * ciclo. La petición es una sola para toda la lista.
   *
   * Devuelve lo que hizo —añadidas, repetidas y descartadas por cortas— porque el aviso de la
   * pantalla tiene que poder decir por qué el resultado no coincide con lo que se pegó.
   */
  async agregarVariasCpc(texto) {
    const { terminos, cortas } = terminosDeLista(texto)
    if (!terminos.length) return { agregadas: [], repetidas: 0, cortas }

    // Una sola petición para toda la lista, igual que las palabras clave: veinte altas encadenadas
    // contra una base remota se irían a más de un minuto de espera.
    const datos = await api.agregarCpc(terminos)
    const agregadas = (datos.claves || []).map((clave) => String(clave))

    for (const termino of agregadas) {
      const clave = normalizarClave(termino)
      if (!estado.cpc.some((guardado) => normalizarClave(guardado) === clave)) {
        estado.cpc.push(termino)
      }
    }
    // El número de descartadas por cortas es el **nuestro**: los términos ya se filtraron antes de
    // enviarlos, así que preguntárselo al servidor daría cero y el aviso perdería el dato.
    aplicarClavesCpc()
    return { agregadas, repetidas: datos.repetidas || 0, cortas }
  },

  // --- Provincia -----------------------------------------------------------

  /**
   * Un clic simple: el filtro pasa a ser **solo** esa provincia.
   *
   * Es el gesto que se espera de un mapa: señalar dónde quieres mirar. Volver a pulsar la que ya
   * está sola la quita, que es como se deshace el filtro sin buscar un botón.
   */
  elegirProvincia(codigo) {
    const yaEsLaUnica = estado.provincias.length === 1 && estado.provincias[0] === codigo
    estado.provincias = yaEsLaUnica ? [] : [codigo]
    estado.canton = null
  },

  /**
   * Doble clic (o Ctrl/Mayús con el teclado): suma o quita esa provincia de la selección.
   *
   * Es la forma de comparar varias a la vez sin perder las que ya estaban.
   */
  alternarProvincia(codigo) {
    const indice = estado.provincias.indexOf(codigo)
    if (indice === -1) estado.provincias.push(codigo)
    else estado.provincias.splice(indice, 1)
    estado.canton = null
  },

  elegirCanton(canton) {
    estado.canton = estado.canton === canton ? null : canton
  },

  limpiarProvincia() {
    estado.provincias = []
    estado.canton = null
  },

  // --- Familia de contratación ---------------------------------------------

  /**
   * Cambia la familia que se está mirando y vuelve a la primera página.
   *
   * Volver a la página uno no es un detalle: si se está en la siete de un listado que la familia
   * nueva deja en dos páginas, seguir en la siete da «no hay resultados» y parece que esa familia no
   * tiene contrataciones.
   *
   * Se aplica al instante, sin pasar por el borrador, por la misma razón que la paginación: es
   * navegación dentro de lo que ya está filtrado, no un criterio nuevo que revisar.
   *
   * **Elegir familia descarta la fuente concreta**, y al revés. Son dos formas de decir lo mismo
   * —cada familia son sus fuentes— y mantenerlas a la vez deja al usuario pidiendo «ínfimas del
   * OCDS», que no existe: el servidor lo rechaza con toda la razón y el panel mostraría un error
   * delante de alguien que solo estaba mirando una pestaña. El que habla último manda; el otro se
   * limpia para que no queden diciendo cosas distintas.
   */
  elegirCategoria(categoria) {
    estado.categoria = categoria || null
    estado.pagina = 1
    if (estado.categoria) {
      estado.fuente = null
      aplicados.fuente = null
    }
  },

  /**
   * Fija la fuente concreta del borrador. Elegirla descarta la familia.
   *
   * Se limpia también **lo aplicado**, no solo el borrador: la familia viaja al servidor en el
   * momento en que se elige la pestaña, así que dejarla puesta en lo aplicado mantendría la consulta
   * contradictoria hasta que alguien pulsara «aplicar», que es justo lo que se quiere evitar.
   */
  elegirFuente(fuente) {
    estado.fuente = fuente || null
    if (estado.fuente) estado.categoria = null
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
    estado.cpc = []
    estado.provincias = []
    estado.canton = null
    estado.estadoRegistro = null
    estado.codigo = null
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

/**
 * Clave con la que se comparan dos términos para no repetir: sin mayúsculas ni acentos.
 *
 * Es la misma reducción que aplica el servidor (`normalizar_termino`): «LAVADO», «Lavado» y «lavado»
 * son el mismo filtro, porque la búsqueda los reduce al mismo término. Se hace también aquí para que
 * la ficha no se duplique en pantalla mientras el servidor responde, y para no depender de que la
 * respuesta llegue para saber si algo estaba repetido.
 */
function normalizarClave(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
    .toLowerCase()
}
