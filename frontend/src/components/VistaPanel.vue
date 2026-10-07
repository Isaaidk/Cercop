<script setup>
/**
 * El panel: barra superior, filtros a un lado y el contenido al otro.
 *
 * Aquí vive la única pieza de lógica que no es de presentación: **una sola recarga por cambio de
 * filtro**, retrasada unos milisegundos.
 *
 * Por qué retrasada
 * -----------------
 * Cambiar de fecha con el selector dispara un cambio por cada tecla y por cada flecha del calendario.
 * Sin el retraso, mover la fecha dos días lanzaría cuatro peticiones y las respuestas podrían llegar
 * desordenadas: la tabla mostraría el resultado de una fecha intermedia y parecería que el filtro no
 * responde. Con el retraso se envía una sola petición, la del estado final.
 *
 * Y una sola, no dos
 * ------------------
 * Cada recarga pide los registros **y** las gráficas juntas, en vez de dejar que cada tarjeta pida lo
 * suyo al detectar el cambio. Si cada una lo hiciera por su cuenta, el mismo cambio de filtro
 * provocaría cuatro peticiones casi simultáneas, que además competirían por el mismo servidor y
 * podrían pintar estados intermedios distintos en la tabla y en el gráfico.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import BarraSuperior from '@/components/BarraSuperior.vue'
import CambiarContrasena from '@/components/CambiarContrasena.vue'
import GestionUsuarios from '@/components/GestionUsuarios.vue'
import GraficaFuentes from '@/components/GraficaFuentes.vue'
import GraficaDistribucion from '@/components/GraficaDistribucion.vue'
import GraficaProvincias from '@/components/GraficaProvincias.vue'
import GraficaSerie from '@/components/GraficaSerie.vue'
import ListaProvincia from '@/components/ListaProvincia.vue'
import MapaEcuador from '@/components/MapaEcuador.vue'
import OfertasTab from '@/components/OfertasTab.vue'
import PanelEmpresas from '@/components/PanelEmpresas.vue'
import Paginacion from '@/components/Paginacion.vue'
import PanelFiltros from '@/components/PanelFiltros.vue'
import PlantillaExcel from '@/components/PlantillaExcel.vue'
import TablaRegistros from '@/components/TablaRegistros.vue'
import { usePresencia } from '@/composables/usePresencia'
import { useEsMovil } from '@/composables/useEsMovil'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { sesion } from '@/stores/sesion'
import { FAMILIAS } from '@/utils/familias'
import { haceCuanto, numero } from '@/utils/formato'

const props = defineProps({
  tema: { type: String, default: 'claro' },
})

const emit = defineEmits(['alternar-tema', 'cerrar-sesion'])

const presencia = usePresencia()

const panelCuentaAbierto = ref(false)
const filtrosAbiertos = ref(false)

// Con qué ancho se está mirando. Decide qué hace el botón de filtros: abrir el cajón en móvil o
// esconder la columna en escritorio.
const esMovil = useEsMovil()

// Dónde se recuerda si la columna de filtros está a la vista. La clave lleva prefijo porque
// `localStorage` es de todo el sitio, no de este componente.
const CLAVE_FILTROS_VISIBLES = 'panel:filtros-visibles'

/**
 * Si la columna de filtros está a la vista en escritorio.
 *
 * Se recuerda entre visitas: quien la esconde lo hace porque prefiere la tabla ancha, y volver a
 * esconderla en cada recarga sería deshacer su decisión cada vez que abre el panel. En móvil este
 * estado no se usa —ahí manda `filtrosAbiertos`, que es el cajón— y arranca en `true` para que el
 * panel se vea como siempre la primera vez.
 */
const filtrosVisibles = ref(leerFiltrosVisibles())

function leerFiltrosVisibles() {
  try {
    const guardado = localStorage.getItem(CLAVE_FILTROS_VISIBLES)
    return guardado === null ? true : guardado === '1'
  } catch {
    // Un navegador que no deja leer el almacén no puede impedir usar el panel: se muestra.
    return true
  }
}

function guardarFiltrosVisibles(visible) {
  try {
    localStorage.setItem(CLAVE_FILTROS_VISIBLES, visible ? '1' : '0')
  } catch {
    /* sin almacén, la preferencia vale solo para esta sesión */
  }
}

/**
 * El botón de filtros de la barra superior.
 *
 * Hace una cosa u otra según el ancho, y son distintas de verdad: en móvil abre y cierra el cajón
 * —que no se recuerda, porque tapar el contenido es una acción del momento— y en escritorio
 * esconde y muestra la columna, que sí se recuerda.
 */
function alternarFiltros() {
  if (esMovil.value) {
    filtrosAbiertos.value = !filtrosAbiertos.value
    return
  }
  filtrosVisibles.value = !filtrosVisibles.value
  guardarFiltrosVisibles(filtrosVisibles.value)
}
/**
 * Pestaña con la que se abre el panel.
 *
 * Es la primera, y no el resumen de gráficas. El panel se abre casi siempre para **mirar las
 * contrataciones** —qué ha salido, de qué entidad, por cuánto— y el resumen es lo que se consulta
 * después. Abrir en la primera pestaña también evita una rareza visible: con otra seleccionada, la
 * pestaña de más a la izquierda aparece apagada y parece que falta algo.
 */
const pestana = ref('infimas')
const cambiandoContrasena = ref(false)
const exito = ref('')

/** Pestañas del contenido. En móvil evitan apilar mapa, cuatro gráficas y una tabla. */
const PESTANAS_BASE = [
  // El listado de ínfimas cuantías va primero, y la pestaña **fija la familia**: aquí se ven ínfimas
  // y solo ínfimas. Tener la familia en la pestaña y no en un desplegable del lateral es lo que
  // permite que cada pestaña responda a una pregunta concreta: «qué necesidades de compra han salido»
  // frente a «qué procesos con oferta se han publicado».
  { id: 'infimas', etiqueta: 'Ínfimas cuantías', icono: '≡' },
  // El listado del portal de procesos, que consulta la fuente OCDS por su cuenta: por eso esta
  // pestaña no necesita que nadie le diga qué familia mostrar.
  { id: 'ofertas', etiqueta: 'Ofertas', icono: '▤' },
  // El mapa sí deja elegir familia, porque su pregunta es otra: «dónde». Ver el selector en el
  // propio panel, con la opción de las dos a la vez.
  { id: 'mapa', etiqueta: 'Mapa', icono: '▣' },
  { id: 'resumen', etiqueta: 'Resumen', icono: '◎' },
]

/**
 * Las pestañas que existen para quien está delante.
 *
 * La plantilla y los usuarios solo aparecen a un rol administrativo, y las empresas solo al dueño
 * del sistema. Se ocultan en lugar de mostrarlas y que fallen: un consultor que pulse «Usuarios» y
 * reciba un error de permisos entendería que el sistema está roto, no que él no tiene esa capacidad.
 * El servidor lo rechazaría igualmente —ahí está la barrera de verdad—, pero no hay motivo para
 * ofrecer a nadie un botón que solo puede llevarle a un rechazo.
 */
const PESTANAS = computed(() => {
  const deEmpresas = { id: 'empresas', etiqueta: 'Empresas', icono: '⌂' }
  if (!sesion.esAdministrativo.value) {
    // El dueño del sistema ve además el censo de empresas, que es la única pantalla que mira a
    // todas a la vez. Un administrador de negocio no la ve porque no hay nada suyo ahí.
    return sesion.esDePlataforma.value ? [...PESTANAS_BASE, deEmpresas] : PESTANAS_BASE
  }
  return [
    PESTANAS_BASE[0],
    PESTANAS_BASE[1],
    PESTANAS_BASE[2],
    // La plantilla decide cómo se ve **todo** lo que la empresa exporta, así que va junto a lo que
    // se exporta y antes del resumen, que es lo último que se consulta.
    { id: 'plantilla', etiqueta: 'Plantilla', icono: '⬓' },
    PESTANAS_BASE[3],
    { id: 'usuarios', etiqueta: 'Usuarios', icono: '⬢' },
    ...(sesion.estado.rol === 'super_admin' ? [deEmpresas] : []),
  ]
})

/**
 * Cambia de pestaña, fijando la familia cuando la pestaña la determina.
 *
 * Las dos pestañas de familia la fijan, incluso la de ofertas, que consulta la fuente por su cuenta:
 * si no lo hiciera, el estado general seguiría diciendo «ínfimas» mientras la pantalla muestra
 * ofertas, y al pasar al mapa el usuario vería una familia que no es la que acababa de mirar.
 *
 * Se hace aquí y no en un vigilante sobre `pestana` porque la familia tiene que cambiar **antes** de
 * que se recargue nada: el vigilante de los filtros ya se encarga de pedir los datos nuevos, y
 * fijarla después lanzaría una consulta con la familia vieja y otra con la nueva.
 */
function abrirPestana(id) {
  pestana.value = id
  if (id === 'infimas' || id === 'ofertas') filtros.elegirCategoria(id)
}

// Las etiquetas del selector de familia del mapa y del titular de la tabla salen de `utils/familias`:
// el mismo nombre en los dos sitios y en la pista de cada gráfica.
const TITULO_INFIMAS = 'Ínfimas cuantías'

/**
 * El título de la tabla del mapa.
 *
 * Dice qué familia se está mirando, y lo dice la misma pieza que filtra: si el título fuera fijo y
 * la familia cambiara, la tabla mostraría ofertas con un titular que habla de ínfimas. Es el tipo de
 * desajuste que nadie detecta porque cada mitad, por separado, parece correcta.
 */
const tituloDeLaFamilia = computed(() => {
  const elegida = FAMILIAS.find((opcion) => opcion.id === filtros.estado.categoria)
  return elegida && elegida.id ? elegida.etiqueta : 'Contrataciones'
})

/**
 * El reparto por tipo de procedimiento, ya traducido a lo que entiende la gráfica.
 *
 * La traducción se hace aquí y no en el componente para que el componente no sepa cómo se llama el
 * campo en la API: si algún día el agregado devuelve otra cosa, se cambia en un sitio.
 */
const porTipoDeProceso = computed(() =>
  (datos.estado.estadisticas.por_tipo_proceso || []).map((fila) => ({
    etiqueta: fila.tipo_proceso,
    total: fila.total,
  })),
)

/**
 * Qué gráficas del Resumen se enseñan.
 *
 * Se eligen porque no todas sirven siempre: con el filtro de CPC puesto, «Origen de los datos» dice
 * «todas de NCO» y no informa de nada, y quien mira el mapa todo el día no necesita la serie mensual.
 * Antes la única forma de quitar una de en medio era no abrir el Resumen.
 *
 * La elección se guarda en el navegador —como la del panel de filtros— y no en el servidor: es una
 * preferencia de quien mira, no una configuración de la empresa, y no tiene por qué viajar a la base.
 *
 * Quitar la última se impide en vez de dejar la pantalla vacía: una pantalla en blanco no explica
 * cómo volver, y el botón que la arregla estaría justo donde ya no se mira.
 */
const GRAFICAS = [
  { id: 'provincias', etiqueta: 'Provincias' },
  { id: 'serie', etiqueta: 'Publicaciones por mes' },
  { id: 'tipos', etiqueta: 'Tipo de procedimiento' },
  { id: 'fuentes', etiqueta: 'Origen de los datos' },
]

const CLAVE_GRAFICAS = 'panel:graficas-ocultas'
const TODAS = GRAFICAS.map((grafica) => grafica.id)

/**
 * Se guardan **las que se ocultan**, no las que se ven.
 *
 * Con la lista de visibles, añadir una gráfica nueva la dejaría invisible para todo el que ya tuviera
 * una elección guardada —y sin nada en pantalla que explicara por qué no aparece—. Guardando lo
 * oculto, la gráfica nueva se ve por defecto y la elección de quien ya había quitado otras se respeta.
 */
function leerOcultas() {
  try {
    const guardadas = JSON.parse(localStorage.getItem(CLAVE_GRAFICAS) || 'null')
    if (!Array.isArray(guardadas)) return []
    const validas = guardadas.filter((id) => TODAS.includes(id))
    // Una preferencia que las oculte todas se ignora: dejaría el Resumen vacío sin forma de volver.
    return validas.length < TODAS.length ? validas : []
  } catch {
    // Un valor ilegible —o un navegador sin almacenamiento— no puede dejar el Resumen sin gráficas.
    return []
  }
}

const graficasOcultas = ref(leerOcultas())

function verGrafica(id) {
  return !graficasOcultas.value.includes(id)
}

/** `true` si es la única que queda a la vista: quitarla dejaría el Resumen sin ninguna gráfica. */
function esLaUnica(id) {
  return verGrafica(id) && graficasOcultas.value.length === TODAS.length - 1
}

function alternarGrafica(id) {
  const ocultas = verGrafica(id)
    ? [...graficasOcultas.value, id]
    : graficasOcultas.value.filter((cual) => cual !== id)
  if (ocultas.length === TODAS.length) return
  graficasOcultas.value = ocultas
  try {
    localStorage.setItem(CLAVE_GRAFICAS, JSON.stringify(ocultas))
  } catch {
    /* sin almacenamiento, la elección dura lo que dure la pestaña */
  }
}

function alCambiarContrasena(resultado) {
  cambiandoContrasena.value = false
  exito.value = (resultado?.avisos || []).join(' ') || 'Tu contraseña ha cambiado.'
}

let temporizador = null

/**
 * Cada cuánto se pregunta si hay datos nuevos.
 *
 * Un minuto, y no menos: la pregunta cuesta una lectura de caché, pero cada panel abierto es una
 * petición HTTP más, y con cientos de paneles la diferencia entre un minuto y diez segundos es buena
 * parte del tráfico del API. Con un minuto, lo que escriba la ingesta aparece solo, sin que nadie
 * toque un filtro ni recargue la página.
 */
const MS_REVISION_NOVEDADES = 60_000
let revisorNovedades = null

/**
 * ¿Hay algo nuevo que enseñar?
 *
 * Se pregunta por la **versión de los datos**, no por los datos: un número que sale de la caché y no
 * toca la base. Cuando cambia, la recarga la hace el almacén con los filtros **aplicados**, así que lo
 * que alguien esté escribiendo en el borrador no se pierde y la página en la que está no se mueve.
 */
async function revisarNovedades() {
  // Con la pestaña de fondo no se pregunta: nadie está mirando la tabla, y el navegador ya frena los
  // temporizadores de fondo. Al volver se pregunta en el acto, así que no se pierde nada.
  if (document.hidden || datos.estado.cargando) return
  try {
    await datos.revisarNovedades()
  } catch {
    // No se avisa: la tabla se queda con lo que tenía y se reintenta en la vuelta siguiente. Un
    // «no se pudo comprobar si hay novedades» delante de una tabla correcta es ruido, no información.
  }
}

/** Al volver a la pestaña se pregunta enseguida, sin esperar al siguiente minuto. */
function alVolverALaPestana() {
  if (!document.hidden) revisarNovedades()
}

/**
 * Recarga con retraso. Se cancela el anterior en lugar de encolarlos: solo interesa el estado final
 * de los filtros, y ejecutar los intermedios gastaría peticiones en resultados que nadie verá.
 */
function recargar({ inmediato = false } = {}) {
  clearTimeout(temporizador)
  if (inmediato) {
    datos.cargar()
    return
  }
  temporizador = setTimeout(() => datos.cargar(), 280)
}

// `deep` porque los filtros son un objeto con una lista dentro: cambiar una palabra clave muta el
// arreglo y sin `deep` el vigilante no lo vería.
watch(
  () => filtros.parametros.value,
  () => recargar(),
  { deep: true },
)

onMounted(async () => {
  // La familia de la pestaña con la que se abre. Tiene que fijarse **aquí** y no solo al pulsar la
  // pestaña: como el panel arranca ya en «Ínfimas cuantías», sin esto la primera carga traería las
  // dos familias y la tabla estaría mostrando ofertas bajo un titular que dice ínfimas cuantías
  // hasta que alguien pulsara otra pestaña y volviera.
  filtros.elegirCategoria('infimas')

  // Las tres primeras peticiones van a la vez: son independientes y encadenarlas daría tres esperas
  // seguidas antes de que aparezca nada.
  await Promise.all([
    filtros.cargarPalabras(),
    filtros.cargarCpc(),
    datos.cargarCatalogos(),
  ])
  await datos.cargar()

  // A partir de aquí, la tabla se pone al día sola cuando la ingesta escribe. Sin esto, lo único que
  // la refrescaba era tocar un filtro: la ingesta podía cerrar dos ciclos y la pantalla seguía
  // enseñando lo de antes, incluso con la necesidad ya guardada y su CPC ya leído.
  revisorNovedades = setInterval(revisarNovedades, MS_REVISION_NOVEDADES)
  document.addEventListener('visibilitychange', alVolverALaPestana)
})

onBeforeUnmount(() => {
  clearTimeout(temporizador)
  clearInterval(revisorNovedades)
  document.removeEventListener('visibilitychange', alVolverALaPestana)
  // Aquí se avisaba al servidor del cierre de la ventana, y ese aviso revocaba la sesión. Se quitó
  // por dos motivos: al recargar la página no salta, pero **cualquier desmontaje del panel sí** —y
  // en desarrollo eso pasa en cada recarga en caliente—, así que la sesión se caía sola. Cerrar el
  // panel ya no cierra la sesión: la cierran el botón de salir, la expulsión por superar el tope y
  // la caducidad.
  datos.limpiar()
})

const aviso = computed(() => sesion.estado.error)

/** Permite ocultar el cartel de ejemplo sin recargar, aunque vuelve a aparecer al recargar. */
const ejemploOculto = ref(false)
const mostrarAvisoEjemplo = computed(() => datos.estado.usandoEjemplo && !ejemploOculto.value)

const ultimaActualizacion = computed(() =>
  datos.estado.generacion
    ? `Datos de la generación ${datos.estado.generacion}`
    : 'Sin ingesta registrada todavía',
)
</script>

<template>
  <div class="panel">
    <BarraSuperior
      :tema="props.tema"
      :nombre="sesion.estado.nombre"
      :email="sesion.estado.email"
      :admin="sesion.esAdministrativo.value"
      :presencia="sesion.esDePlataforma.value"
      :conectados="presencia.conectados.value"
      :total="presencia.total.value"
      :personas="presencia.personas.value"
      :alcance="presencia.alcance.value"
      :en-vivo="presencia.enVivo.value"
      :panel-abierto="panelCuentaAbierto"
      :filtros-abiertos="esMovil ? filtrosAbiertos : filtrosVisibles"
      :filtros-activos="filtros.hayFiltros.value"
      @alternar-tema="emit('alternar-tema')"
      @cerrar-sesion="emit('cerrar-sesion')"
      @alternar-panel="panelCuentaAbierto = !panelCuentaAbierto"
      @cambiar-contrasena="cambiandoContrasena = true"
      @alternar-filtros="alternarFiltros"
    />

    <p v-if="exito" class="panel__exito aparece" role="status">
      {{ exito }}
      <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Ocultar" @click="exito = ''">
        ✕
      </button>
    </p>

    <!-- Aviso de datos de ejemplo. No se puede cerrar de forma permanente a propósito: si se
         recordara la elección, alguien podría volver al panel semanas después, con datos reales ya
         cargados, y seguir con el cartel oculto sin darse cuenta de que ahora sí son reales. -->
    <Transition name="deslizar">
      <div v-if="mostrarAvisoEjemplo" class="aviso-ejemplo" role="status">
        <span class="aviso-ejemplo__icono" aria-hidden="true">⚗</span>
        <p>
          <strong>Estás viendo datos de ejemplo.</strong>
          No hay contrataciones ingestadas para estos filtros todavía, así que las cifras son
          inventadas para poder revisar el diseño. Aparecerán datos reales cuando el proceso de
          ingesta complete un ciclo.
        </p>
        <button
          type="button"
          class="boton boton--fantasma boton--pequeno"
          aria-label="Ocultar el aviso de datos de ejemplo"
          @click="ejemploOculto = true"
        >
          ✕
        </button>
      </div>
    </Transition>

    <p v-if="aviso" class="panel__aviso" role="alert">{{ aviso }}</p>

    <div class="panel__cuerpo" :class="{ 'panel__cuerpo--sin-filtros': !esMovil && !filtrosVisibles }">
      <!-- Filtros: columna fija en escritorio, cajón deslizante en móvil. -->
      <aside
        id="panel-filtros"
        class="panel__lateral superficie"
        :class="{ 'panel__lateral--abierto': filtrosAbiertos }"
      >
        <div class="panel__lateral-cabecera">
          <p class="panel__lateral-titulo">Filtros</p>
          <button
            type="button"
            class="boton boton--fantasma boton--icono panel__lateral-cerrar"
            aria-label="Cerrar los filtros"
            @click="filtrosAbiertos = false"
          >
            ✕
          </button>
        </div>
        <PanelFiltros />
      </aside>

      <!-- Velo que cierra el cajón al tocarlo. Solo se pinta cuando el cajón está abierto. -->
      <div
        v-if="filtrosAbiertos"
        class="panel__velo"
        aria-hidden="true"
        @click="filtrosAbiertos = false"
      />

      <main class="panel__principal">
        <nav class="pestanas" aria-label="Secciones del panel">
          <button
            v-for="opcion in PESTANAS"
            :key="opcion.id"
            type="button"
            class="pestanas__boton"
            :class="{ 'pestanas__boton--activa': pestana === opcion.id }"
            :aria-selected="pestana === opcion.id"
            role="tab"
            @click="abrirPestana(opcion.id)"
          >
            <span aria-hidden="true">{{ opcion.icono }}</span>
            {{ opcion.etiqueta }}
            <!--
              El número de cada pestaña es el de **su** familia, no el de la consulta en curso.

              Antes las dos leían `datos.estado.total`, que es el total de la última búsqueda: como
              abrir la pestaña de ofertas cambia la familia que se consulta, el número de las ínfimas
              pasaba a mostrar el de las ofertas sin que nada hubiera cambiado fuera de la pestaña.
              Los totales por familia vienen del servidor con los mismos filtros que la tabla, así
              que solo cambian al aplicar filtros o cuando la ingesta trae datos nuevos. Las pestañas
              que no son de una familia —mapa, resumen, plantilla— no llevan número y no lo llevaban.
            -->
            <span
              v-if="datos.estado.totalesPorCategoria[opcion.id]"
              class="pestanas__cuenta"
            >
              {{ numero(datos.estado.totalesPorCategoria[opcion.id]) }}
            </span>
          </button>
        </nav>

        <section v-show="pestana === 'resumen'" class="resumen">
          <!-- El selector de gráficas. Va aquí arriba y no escondido en un menú porque lo que
               decide es qué hay debajo; un ajuste que cambia la pantalla tiene que verse en la
               pantalla que cambia. -->
          <div class="selector superficie">
            <span class="selector__etiqueta">Gráficas</span>
            <div class="selector__botones" role="group" aria-label="Gráficas del resumen">
              <button
                v-for="grafica in GRAFICAS"
                :key="grafica.id"
                type="button"
                class="boton boton--pequeno"
                :class="verGrafica(grafica.id) ? 'boton--principal' : 'boton--secundario'"
                :aria-pressed="verGrafica(grafica.id)"
                :disabled="esLaUnica(grafica.id)"
                :title="
                  esLaUnica(grafica.id)
                    ? 'Al menos una gráfica tiene que quedar a la vista'
                    : ''
                "
                @click="alternarGrafica(grafica.id)"
              >
                <span aria-hidden="true">{{ verGrafica(grafica.id) ? '◉' : '○' }}</span>
                {{ grafica.etiqueta }}
              </button>
            </div>
          </div>

          <div class="rejilla">
            <!-- `v-show` y no `v-if`: la gráfica que se oculta y se vuelve a mostrar **no** se
                 reconstruye, y el envoltorio sabe redibujarla si nació sin tamaño. -->
            <GraficaProvincias v-show="verGrafica('provincias')" />
            <GraficaSerie v-show="verGrafica('serie')" />
            <GraficaDistribucion
              v-show="verGrafica('tipos')"
              titulo="Tipo de procedimiento"
              pista="subasta inversa, licitación, catálogo electrónico…"
              :filas="porTipoDeProceso"
            />
            <GraficaFuentes v-show="verGrafica('fuentes')" />
          </div>
        </section>

        <section v-show="pestana === 'mapa'" class="panel__pila">
          <!--
            El selector de familia, dentro del mapa.

            El mapa responde a «dónde», y esa pregunta se hace igual sobre las dos familias: «dónde
            se están comprando medicamentos» vale tanto para las necesidades de compra como para los
            procesos con oferta. Tenerlas juntas en una sola vista es lo que permite ver si las dos
            coinciden en la misma provincia.

            Se escribe en el filtro de verdad —el mismo que leen la tabla y las gráficas de debajo—
            y no en un estado propio del mapa. Si el mapa tuviera el suyo, el mapa y la tabla que
            tiene justo al lado podrían estar mostrando familias distintas y las cifras no cuadrarían
            sin que nada explicara por qué.
          -->
          <div class="selector superficie">
            <span class="selector__etiqueta">Familia</span>
            <div class="selector__botones" role="group" aria-label="Familia de contratación">
              <button
                v-for="opcion in FAMILIAS"
                :key="opcion.id || 'todas'"
                type="button"
                class="boton boton--pequeno"
                :class="
                  filtros.estado.categoria === opcion.id ? 'boton--principal' : 'boton--secundario'
                "
                :aria-pressed="filtros.estado.categoria === opcion.id"
                @click="filtros.elegirCategoria(opcion.id)"
              >
                {{ opcion.etiqueta }}
              </button>
            </div>
          </div>

          <div class="rejilla rejilla--mapa">
            <div class="tarjeta aparece">
              <header class="tarjeta__cabecera">
                <div>
                  <p class="tarjeta__titulo">Mapa de provincias</p>
                  <p class="tarjeta__pista">
                    Pulsa una provincia para sumarla al filtro y vuelve a pulsarla para quitarla.
                    Aplica los filtros para que la tabla y las gráficas la sigan.
                  </p>
                </div>
              </header>
              <div class="tarjeta__cuerpo">
                <MapaEcuador />
              </div>
            </div>
            <GraficaProvincias />
          </div>

          <ListaProvincia @ver-todos="abrirPestana('infimas')" />

          <!-- La misma tabla que la pestaña de ínfimas cuantías, con su detalle desplegable y su
               paginación. Es lo que responde a «ver todas las contrataciones de la región con los
               filtros aplicados» sin cambiar de pestaña: el listado propio que había aquí recortaba
               el objeto y la entidad, no dejaba abrir el detalle de una ínfima cuantía y no
               paginaba. -->
          <TablaRegistros :titulo="tituloDeLaFamilia">
            <template #paginacion>
              <Paginacion
                :pagina="filtros.estado.pagina"
                :paginas="datos.estado.paginas"
                :total="datos.estado.total"
                :tamano="filtros.estado.tamano"
                @cambiar="filtros.cambiarPagina"
              />
            </template>
          </TablaRegistros>
        </section>

        <!--
          El panel de empresas se pide solo al dueño de la plataforma, y se pide de verdad (`v-if`, no
          solo `v-show`): la pestaña no existe para los demás, así que con `v-show` el componente se
          montaba igual y disparaba en cada carga un petición que el servidor rechazaba con 403. El
          error no se veía —va dentro de una sección oculta—, pero era una petición inútil y un fallo
          en el registro del navegador que parecía un defecto del panel.
        -->
        <section v-if="sesion.esDePlataforma.value" v-show="pestana === 'empresas'">
          <PanelEmpresas />
        </section>

        <section v-show="pestana === 'infimas'">
          <TablaRegistros :titulo="TITULO_INFIMAS">
            <template #paginacion>
              <Paginacion
                :pagina="filtros.estado.pagina"
                :paginas="datos.estado.paginas"
                :total="datos.estado.total"
                :tamano="filtros.estado.tamano"
                @cambiar="filtros.cambiarPagina"
              />
            </template>
          </TablaRegistros>
        </section>

        <section v-show="pestana === 'ofertas'">
          <OfertasTab />
        </section>

        <section v-show="pestana === 'plantilla'">
          <PlantillaExcel />
        </section>

        <section v-show="pestana === 'usuarios'" class="tarjeta aparece">
          <div class="tarjeta__cuerpo">
            <GestionUsuarios />
          </div>
        </section>

        <footer class="panel__pie">
          <span>{{ ultimaActualizacion }}</span>
          <span v-if="datos.estado.desdeCache">· respuesta servida desde la memoria intermedia</span>
          <span v-if="presencia.enVivo.value">· presencia en vivo</span>
          <span v-else-if="presencia.error.value" :title="presencia.error.value">
            · presencia sin conexión
          </span>
        </footer>
      </main>
    </div>

    <CambiarContrasena
      v-if="cambiandoContrasena"
      @cerrar="cambiandoContrasena = false"
      @cambiada="alCambiarContrasena"
    />

    <!-- Botón flotante para abrir los filtros en móvil: la barra superior ya tiene el suyo, pero
         queda lejos del pulgar cuando la lista es larga. -->
    <button
      type="button"
      class="panel__flotante"
      :aria-label="filtros.hayFiltros.value ? 'Abrir los filtros (hay filtros activos)' : 'Abrir los filtros'"
      @click="filtrosAbiertos = true"
    >
      <span aria-hidden="true">⚙</span>
      <span v-if="filtros.hayFiltros.value" class="panel__flotante-marca" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.panel {
  min-height: 100vh;
  padding-bottom: var(--e-6);
}

.panel__cuerpo {
  display: grid;
  grid-template-columns: 340px minmax(0, 1fr);
  gap: var(--e-4);
  align-items: start;
  padding: var(--e-5);
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

/*
 * La columna de filtros. Tres decisiones que se ven juntas:
 *
 * - **340 px y no 300.** Los tres campos de texto —palabras clave, CPC y descripción— llevan su
 *   explicación al lado, y en 300 px cada ayuda ocupaba cinco líneas y el botón de aplicar quedaba a
 *   dos pantallas de la fecha que se acababa de escribir. Con 40 px más, la mitad de las ayudas
 *   caben en una línea menos.
 * - **Relleno de un paso menos.** `--e-5` (24 px) por cada lado se comía 48 de los 300: el contenido
 *   real eran 252 px. Con `--e-4` y la columna más ancha, el texto dispone de 308.
 * - **`overflow-x: hidden`, y no es cosmético.** Con `overflow-y: auto` el navegador convierte el otro
 *   eje en `auto` por su cuenta, así que **cualquier** contenido un píxel más ancho que la columna
 *   hacía aparecer una barra horizontal. Pasaba con los dos botones de alta del CPC, que no cabían.
 *   Se arregla en su sitio —que envuelvan—, y esto lo deja cerrado para el siguiente control ancho
 *   que se añada: lo que no quepa se recorta en el borde, en lugar de arrastrar la columna.
 */
.panel__lateral {
  position: sticky;
  top: calc(var(--altura-cabecera) + var(--e-4));
  padding: var(--e-4);
  max-height: calc(100vh - var(--altura-cabecera) - var(--e-6));
  overflow-y: auto;
  overflow-x: hidden;
}

.panel__lateral-cabecera {
  display: none;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--e-3);
}

/*
 * La columna de filtros escondida.
 *
 * La clase solo se pone en escritorio —en móvil manda el cajón, y allí el estado es otro— así que
 * no hace falta acotarla con una consulta de medios. La cabecera del panel y las gráficas se
 * reparten todo el ancho: es lo que se buscaba al esconderla.
 */
.panel__cuerpo--sin-filtros {
  grid-template-columns: minmax(0, 1fr);
}

.panel__cuerpo--sin-filtros .panel__lateral {
  display: none;
}

.panel__lateral-titulo {
  font-weight: 700;
  font-size: var(--t-md);
}

.panel__principal {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
  min-width: 0;
}

.rejilla {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--e-5);
  align-items: start;
  animation: aparecer var(--normal) var(--curva-entrada) both;
}

.rejilla--mapa {
  grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr);
}

/* Las barras de selección —la familia del mapa y las gráficas del resumen—. Van en su propia barra y
   no dentro de una tarjeta porque mandan sobre **todo** lo que hay debajo: metida dentro del mapa,
   parecería que la familia solo cambia el mapa. */
.selector {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
}

.selector__etiqueta {
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--texto-tenue);
}

.selector__botones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

/* El mapa arriba y, debajo, las contrataciones de la provincia elegida. Van en la misma pestaña
   porque mirar el mapa y tener que cambiar de pestaña para ver qué hay es un ida y vuelta. */
.panel__pila {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

/* El resumen: la barra de gráficas y la rejilla de abajo. */
.resumen {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.pestanas {
  display: flex;
  gap: var(--e-1);
  padding: var(--e-1);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  border: 1px solid var(--borde);
  align-self: flex-start;
  max-width: 100%;
  overflow-x: auto;
}

.pestanas__boton {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.4rem 0.9rem;
  border: 0;
  border-radius: var(--r-1);
  background: transparent;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--texto-tenue);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--rapido) var(--curva), color var(--rapido) var(--curva);
}

.pestanas__boton:hover {
  color: var(--texto);
}

.pestanas__boton--activa {
  background: var(--superficie);
  color: var(--texto);
  box-shadow: var(--sombra-1);
}

.pestanas__cuenta {
  padding: 0 0.35rem;
  border-radius: var(--r-redondo);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  font-size: 0.7rem;
  font-weight: 700;
}

.panel__aviso {
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

/* Confirmación de una acción que salió bien. Se puede cerrar, pero no desaparece sola: los avisos que
   se van solos son los que nadie lee cuando llega justo en el momento en que uno mira a otro sitio. */
.panel__exito {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--ok);
  background: var(--ok-suave);
  color: var(--ok);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.aviso-ejemplo {
  display: flex;
  align-items: flex-start;
  gap: var(--e-3);
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px dashed var(--aviso);
  background: var(--aviso-suave);
  color: var(--aviso);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.aviso-ejemplo__icono {
  font-size: var(--t-md);
  line-height: 1.2;
}

.aviso-ejemplo p {
  flex: 1;
}

.panel__pie {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.panel__velo {
  display: none;
}

.panel__flotante {
  display: none;
  position: fixed;
  right: var(--e-4);
  bottom: var(--e-4);
  z-index: 40;
  width: 52px;
  height: 52px;
  border: 0;
  border-radius: 50%;
  background: var(--acento);
  color: #fff;
  font-size: 1.3rem;
  box-shadow: var(--sombra-2);
  cursor: pointer;
}

.panel__flotante-marca {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ok);
  border: 2px solid var(--acento);
}

/* Transición del cartel de datos de ejemplo. Se declara aquí porque las clases de `<Transition>`
   tienen que existir en algún sitio y este es el único componente que usa ese nombre. */
.deslizar-enter-active,
.deslizar-leave-active {
  transition: opacity var(--normal) var(--curva), transform var(--normal) var(--curva);
}

.deslizar-enter-from,
.deslizar-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (max-width: 1023px) {
  .panel__cuerpo {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--e-4);
    gap: 0;
  }

  /* El panel de filtros pasa a ser un cajón. Se saca del flujo con `position: fixed` en lugar de
     apilarlo encima del contenido: apilado, cambiar un filtro obligaría a desplazarse hasta arriba
     para ver el efecto, y el efecto es justo lo que se quiere comprobar. */
  .panel__lateral {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 50;
    width: min(340px, 88vw);
    max-height: none;
    border-radius: 0;
    border: 0;
    border-right: 1px solid var(--borde);
    transform: translateX(-102%);
    transition: transform var(--normal) var(--curva);
    overflow-y: auto;
  }

  .panel__lateral--abierto {
    transform: translateX(0);
    box-shadow: var(--sombra-3);
  }

  .panel__lateral-cabecera {
    display: flex;
  }

  .panel__velo {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 45;
    background: rgb(0 0 0 / 35%);
    animation: aparecer var(--rapido) var(--curva) both;
  }

  .panel__flotante {
    display: grid;
    place-items: center;
  }

  .rejilla,
  .rejilla--mapa {
    grid-template-columns: minmax(0, 1fr);
  }

  .aviso-ejemplo,
  .panel__aviso {
    margin-left: var(--e-4);
    margin-right: var(--e-4);
  }
}

@media (min-width: 1024px) {
  .panel__flotante {
    display: none;
  }
}
</style>
