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

const estado = reactive({
  registros: [],
  total: 0,
  paginas: 0,
  hayAnterior: false,
  haySiguiente: false,
  desdeCache: false,
  generacion: 0,

  estadisticas: { por_fuente: [], serie_mensual: [], por_provincia: [] },
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
   */
  async exportar() {
    const criterios = { ...filtros.parametros.value }
    delete criterios.pagina
    delete criterios.tamano
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
        estado.usandoEjemplo = true
        return
      }

      estado.estadisticas = {
        por_fuente: respuesta.por_fuente || [],
        serie_mensual: respuesta.serie_mensual || [],
        por_provincia: respuesta.por_provincia || [],
      }
      estado.resumenProvincias = agrupado
      estado.usandoEjemplo = false
    } catch (error) {
      // Un fallo en las gráficas no puede tumbar la tabla, que ya se cargó. Se avisa y se sigue.
      estado.estadisticas = { por_fuente: [], serie_mensual: [], por_provincia: [] }
      estado.resumenProvincias = { total: 0, porProvincia: [], sinUbicar: [] }
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

  limpiar() {
    estado.registros = []
    estado.total = 0
    estado.paginas = 0
    estado.estadisticas = { por_fuente: [], serie_mensual: [], por_provincia: [] }
    estado.resumenProvincias = { total: 0, porProvincia: [], sinUbicar: [] }
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
