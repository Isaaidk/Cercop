/**
 * Estado de los datos que se muestran: la tabla, las gráficas y el mapa.
 *
 * Por qué hay datos de ejemplo, y por qué están tan acotados
 * ---------------------------------------------------------
 * Un histórico recién creado está vacío: los términos se encolan y el `worker` los trae en el
 * siguiente ciclo, que puede tardar. Sin nada que mostrar, la interfaz no se puede **revisar**: no
 * se sabe si una gráfica está bien, si el mapa responde o si los colores se distinguen.
 *
 * Los datos de ejemplo existen solo para eso, y están sujetos a tres límites para que no puedan
 * confundirse con datos reales:
 *
 * 1. **Nunca sustituyen a datos reales.** Solo rellenan cuando la API respondió con cero
 *    resultados. Si hay una sola contratación, no se genera nada.
 * 2. **Se anuncian.** Mientras haya datos de ejemplo en pantalla, el panel muestra un rótulo que lo
 *    dice; sin él, la primera impresión sería creer que el sistema ya trajo información.
 * 3. **Están apagados por defecto.** Se encienden con `VITE_DATOS_DEMO=1`, y solo para revisar el
 *    diseño sin base de datos. Cuando se activaban solos al ver un cero, un filtro sin resultados
 *    llenaba el mapa de cifras inventadas.
 */

import { computed, reactive } from 'vue'

import { api } from '@/api/endpoints'
import { agruparPorProvincia } from '@/utils/provincias'
import { datosDeEjemplo } from '@/utils/datosDemo'
import { filtros } from '@/stores/filtros'

/**
 * Los datos de ejemplo están **apagados por defecto** desde que hay datos reales.
 *
 * Nacieron para poder revisar el diseño de un histórico vacío, y entonces se activaban solos cuando
 * la API devolvía cero. El problema es que «cero» también es una respuesta legítima y frecuente: basta
 * con marcar una palabra clave sin resultados para que el mapa y las gráficas se rellenen con cifras
 * inventadas. El usuario ve un reparto por provincia que **no corresponde a sus filtros** y no tiene
 * forma de saber que es falso salvo leyendo el cartel.
 *
 * Se encienden de forma explícita con `VITE_DATOS_DEMO=1`, que es lo que hace falta para revisar el
 * diseño sin base de datos. Un cero honesto —«no hay contrataciones con estos filtros»— es mejor
 * información que un gráfico bonito que miente.
 */
const DEMO_ACTIVO = import.meta.env.VITE_DATOS_DEMO === '1'

/**
 * A qué familia pertenece cada fuente, solo para los totales de las pestañas.
 *
 * La tabla de verdad está en el servidor —`FUENTES_POR_CATEGORIA` del dominio— y la respuesta trae
 * los totales ya calculados en `por_categoria`. Este mapa existe únicamente como respaldo para los
 * datos de ejemplo, que se arman en el navegador y no pasan por la API; si algún día discrepan, el
 * que manda es el servidor.
 */
const FAMILIA_DE_FUENTE = { NCO: 'infimas', OCDS: 'ofertas' }

/** Los totales por familia, en cero. Se usa como valor inicial y al vaciar el estado. */
function totalesEnCero() {
  return { infimas: 0, ofertas: 0 }
}

/**
 * Traduce la respuesta de las gráficas a los totales que llevan las pestañas.
 *
 * El número de cada pestaña tiene que ser **el de su propia familia**, y el del servidor llega ya
 * calculado con los mismos filtros que la tabla pero sin la familia puesta: por eso abrir la pestaña
 * de ofertas ya no cambia el número que se lee junto a las ínfimas. El respaldo por `por_fuente`
 * solo hace falta con los datos de ejemplo.
 */
function totalesDeCategoria(respuesta) {
  const totales = totalesEnCero()
  const porCategoria = respuesta?.por_categoria
  if (Array.isArray(porCategoria) && porCategoria.length) {
    for (const fila of porCategoria) {
      if (fila.categoria in totales) totales[fila.categoria] = fila.total || 0
    }
    return totales
  }
  for (const fila of respuesta?.por_fuente || []) {
    const familia = FAMILIA_DE_FUENTE[fila.fuente]
    if (familia) totales[familia] += fila.total || 0
  }
  return totales
}

const estado = reactive({
  registros: [],
  total: 0,
  paginas: 0,
  hayAnterior: false,
  haySiguiente: false,
  desdeCache: false,
  generacion: 0,

  estadisticas: { por_fuente: [], serie_mensual: [], por_provincia: [] },
  /**
   * El total de **cada** familia, con los mismos filtros que la tabla.
   *
   * No se usa `total` para el número de las pestañas: ese es el total de la consulta en curso y
   * cambia al cambiar de pestaña, porque la pestaña fija la familia. Un solo contador compartido
   * hacía que el número de las ínfimas se convirtiera en el de las ofertas al abrir esa pestaña.
   */
  totalesPorCategoria: totalesEnCero(),
  catalogos: { fuente: [], provincia: [], estado: [] },
  resumenProvincias: { total: 0, porProvincia: [], sinUbicar: [] },

  cargando: false,
  cargandoGraficas: false,
  error: '',
  /** Se enciende cuando lo que se ve viene del conjunto de ejemplo. */
  usandoEjemplo: false,
})

export const datos = {
  estado,

  /** El reparto por provincia ya traducido a las 24 provincias del mapa. */
  provincias: computed(() => estado.resumenProvincias),

  /** El total de las gráficas, que puede no coincidir con el de la tabla: la tabla está paginada. */
  totalFiltrado: computed(() => estado.resumenProvincias.total),

  async cargar({ conGraficas = true } = {}) {
    estado.cargando = true
    estado.error = ''

    try {
      // `.value` no es opcional: `filtros.parametros` es un `computed`, y pasarlo entero hacía que el
      // cliente HTTP serializara las tripas del objeto reactivo (`fn`, `_value`, `deps`, `__v_isRef`…)
      // como parámetros de consulta. Ningún filtro —palabra clave, provincia, fechas— llegaba al
      // servidor: la tabla devolvía siempre lo mismo y los controles parecían no hacer nada.
      const respuesta = await api.buscar(filtros.parametros.value)
      aplicarPagina(respuesta)

      if (conGraficas) await this.cargarGraficas()
    } catch (error) {
      estado.error = error.message
      estado.registros = []
      estado.total = 0
      estado.paginas = 0
      // Los contadores de las pestañas no pueden quedarse con las cifras de unos filtros que no se
      // han podido evaluar: el panel ya avisa del fallo y un número viejo al lado lo contradiría.
      estado.totalesPorCategoria = totalesEnCero()
    } finally {
      estado.cargando = false
    }
  },

  /**
   * Descarga el Excel con todos los resultados de los filtros activos.
   *
   * Se quitan `pagina` y `tamano` de los criterios aunque el servidor los ignore: el archivo no está
   * paginado, y mandarlos daría a entender que la exportación depende de la página que se mira.
   *
   * No toca el estado de la tabla. Exportar no es consultar: lo que hay en pantalla tiene que seguir
   * igual después de descargar el archivo.
   *
   * Devuelve el nombre propuesto y el número de filas, para que quien llama pueda avisar. De guardar
   * el archivo se encarga la interfaz, que es la única que puede tocar el navegador.
   *
   * `categoria` decide qué se lleva el archivo: `null` (lo normal) trae todo y el servidor reparte
   * una hoja por categoría; `'infimas'` u `'ofertas'` restringe la consulta a esa y genera una sola
   * hoja. No es una opción de presentación: cambia las filas que se piden, y por eso viaja con los
   * criterios y entra en la clave de caché.
   */
  async exportar(categoria = null) {
    const criterios = { ...filtros.parametros.value }
    delete criterios.pagina
    delete criterios.tamano
    // La familia se decide en el botón que se pulsa, no en la pestaña. Con la pestaña diciendo
    // «ínfimas» y los criterios arrastrándola, el botón de «todo» habría descargado solo las
    // ínfimas: un archivo que no coincide con lo que su etiqueta promete, y sin ningún aviso.
    delete criterios.categoria
    if (categoria) criterios.categoria = categoria
    return api.exportarRegistros(criterios)
  },

  async cargarGraficas() {
    estado.cargandoGraficas = true
    try {
      const respuesta = await api.estadisticas(filtros.parametros.value)
      const agrupado = agruparPorProvincia(respuesta.por_provincia || [])

      // Si la API no trajo nada y el ejemplo está permitido, se rellena para poder revisar el
      // diseño. La condición es «no hay ningún dato real», no «hay pocos»: mezclar los dos en la
      // misma gráfica daría un total que no significa nada.
      if (!respuesta.por_fuente?.length && !agrupado.total && DEMO_ACTIVO) {
        const ejemplo = datosDeEjemplo(filtros.estado.seleccionadas)
        estado.estadisticas = ejemplo.estadisticas
        estado.resumenProvincias = ejemplo.resumenProvincias
        estado.totalesPorCategoria = totalesDeCategoria(ejemplo.estadisticas)
        estado.usandoEjemplo = true
        return
      }

      estado.estadisticas = {
        por_fuente: respuesta.por_fuente || [],
        serie_mensual: respuesta.serie_mensual || [],
        por_provincia: respuesta.por_provincia || [],
      }
      estado.totalesPorCategoria = totalesDeCategoria(respuesta)
      estado.resumenProvincias = agrupado
      estado.usandoEjemplo = false
    } catch (error) {
      // Un fallo en las gráficas no puede tumbar la tabla, que ya se cargó. Se avisa y se sigue.
      estado.estadisticas = { por_fuente: [], serie_mensual: [], por_provincia: [] }
      estado.resumenProvincias = { total: 0, porProvincia: [], sinUbicar: [] }
      estado.totalesPorCategoria = totalesEnCero()
      if (!estado.error) estado.error = error.message
    } finally {
      estado.cargandoGraficas = false
    }
  },

  async cargarCatalogos() {
    try {
      const respuesta = await api.catalogos()
      estado.catalogos = {
        fuente: respuesta.fuente || [],
        provincia: respuesta.provincia || [],
        estado: respuesta.estado || [],
      }
    } catch {
      // Los catálogos solo rellenan desplegables; sin ellos el panel sigue siendo utilizable.
      estado.catalogos = { fuente: [], provincia: [], estado: [] }
    }
  },

  /**
   * Recarga si la ingesta escribió algo desde la última lectura.
   *
   * Se pregunta por la **versión**, no por los datos: la respuesta es un número que sale de la caché,
   * cuesta una lectura y no toca la base de datos. Comparar ese número con la generación de la última
   * respuesta es lo que distingue «hay algo nuevo» de «vuelve a pedir lo mismo», y es lo que permite
   * mirarlo cada minuto en lugar de recargar la tabla a ciegas.
   *
   * Que los dos números coincidan cuando el caché está apagado no es un problema: en ese caso la
   * versión es siempre cero y no se recarga nunca de más. Y si la comprobación falla, se reintenta en
   * la vuelta siguiente mientras la pantalla se queda con lo que ya tenía.
   *
   * Devuelve `true` solo si llegó a recargar.
   */
  async revisarNovedades() {
    if (estado.cargando) return false
    const { generacion } = await api.versionDatos()
    if (Number(generacion) === Number(estado.generacion)) return false
    await this.cargar()
    return true
  },

  limpiar() {
    estado.registros = []
    estado.total = 0
    estado.paginas = 0
    estado.estadisticas = { por_fuente: [], serie_mensual: [], por_provincia: [] }
    estado.resumenProvincias = { total: 0, porProvincia: [], sinUbicar: [] }
    estado.totalesPorCategoria = totalesEnCero()
    estado.usandoEjemplo = false
  },
}

function aplicarPagina(respuesta) {
  estado.registros = respuesta.elementos || []
  estado.total = respuesta.total || 0
  estado.paginas = respuesta.paginas || 0
  estado.hayAnterior = Boolean(respuesta.hay_anterior)
  estado.haySiguiente = Boolean(respuesta.hay_siguiente)
  estado.desdeCache = Boolean(respuesta.desde_cache)
  estado.generacion = respuesta.generacion || 0
}
