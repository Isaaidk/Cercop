<script setup>
/**
 * El panel: barra superior, menú lateral a la izquierda, filtros donde aplican y el contenido.
 *
 * La navegación vive en `MenuLateral` (rediseño 2026-11, ver `docs/35-guia-de-diseno-del-panel.md`):
 * sustituyó a la fila de pastillas de áreas y a las pestañas de encima del contenido. Los ids de las
 * pantallas, los permisos por rol, el montaje perezoso y los cierres por plazo siguen aquí, igual que
 * antes; el menú solo los pinta.
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
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import BarraSuperior from '@/components/BarraSuperior.vue'
import IconoPanel from '@/components/IconoPanel.vue'
import MenuLateral from '@/components/MenuLateral.vue'
const InicioPanel = defineAsyncComponent(() => import('@/components/InicioPanel.vue'))
const AsistentePanel = defineAsyncComponent(() => import('@/components/AsistentePanel.vue'))
import CambiarContrasena from '@/components/CambiarContrasena.vue'
const GestionUsuarios = defineAsyncComponent(() => import('@/components/GestionUsuarios.vue'))
const PerfilEmpresa = defineAsyncComponent(() => import('@/components/PerfilEmpresa.vue'))
const Documentos = defineAsyncComponent(() => import('@/components/Documentos.vue'))
const Mercado = defineAsyncComponent(() => import('@/components/Mercado.vue'))
const RadarOportunidades = defineAsyncComponent(() => import('@/components/RadarOportunidades.vue'))
const PropuestasParaTi = defineAsyncComponent(() => import('@/components/PropuestasParaTi.vue'))
import GraficaFuentes from '@/components/GraficaFuentes.vue'
import GraficaDistribucion from '@/components/GraficaDistribucion.vue'
import GraficaProvincias from '@/components/GraficaProvincias.vue'
import GraficaSerie from '@/components/GraficaSerie.vue'
import ListaProvincia from '@/components/ListaProvincia.vue'
import MapaEcuador from '@/components/MapaEcuador.vue'
const OfertasTab = defineAsyncComponent(() => import('@/components/OfertasTab.vue'))
const PanelEmpresas = defineAsyncComponent(() => import('@/components/PanelEmpresas.vue'))
const ComprasIa = defineAsyncComponent(() => import('@/components/ComprasIa.vue'))
import Paginacion from '@/components/Paginacion.vue'
import PanelFiltros from '@/components/PanelFiltros.vue'
const MisOfertas = defineAsyncComponent(() => import('@/components/MisOfertas.vue'))
const PlantillaExcel = defineAsyncComponent(() => import('@/components/PlantillaExcel.vue'))
import TablaRegistros from '@/components/TablaRegistros.vue'
import { usePresencia } from '@/composables/usePresencia'
import { useEsMovil } from '@/composables/useEsMovil'
import { api } from '@/api/endpoints'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { sesion } from '@/stores/sesion'
import { FAMILIAS } from '@/utils/familias'
import { fechaCorta, haceCuanto } from '@/utils/formato'
import { pestanaDelAsistente } from '@/utils/asistente'

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

// ------------------------------------------------------------------------------- menú lateral

/** Cajón del menú en móvil. No se recuerda: como el de filtros, tapar el contenido es del momento. */
const menuAbierto = ref(false)

const CLAVE_MENU_PLEGADO = 'panel:menu-plegado'

/**
 * Si el menú está plegado a solo iconos en escritorio.
 *
 * Se recuerda entre visitas por el mismo motivo que la columna de filtros: quien lo pliega quiere
 * más ancho para la tabla, y desplegárselo en cada recarga sería deshacer su decisión.
 */
const menuPlegado = ref(leerMenuPlegado())

function leerMenuPlegado() {
  try {
    return localStorage.getItem(CLAVE_MENU_PLEGADO) === '1'
  } catch {
    // Sin almacén se arranca desplegado: es la forma en que el menú se explica solo.
    return false
  }
}

/** El botón del menú de la barra: en móvil abre o cierra el cajón; en escritorio pliega la columna. */
function alternarMenu() {
  if (esMovil.value) {
    menuAbierto.value = !menuAbierto.value
    return
  }
  alternarPlegado()
}

function alternarPlegado() {
  menuPlegado.value = !menuPlegado.value
  try {
    localStorage.setItem(CLAVE_MENU_PLEGADO, menuPlegado.value ? '1' : '0')
  } catch {
    /* sin almacén, la preferencia vale solo para esta sesión */
  }
}

// Al cruzar el ancho de móvil los cajones dejan de existir; se cierran para no reaparecer abiertos.
watch(esMovil, () => {
  menuAbierto.value = false
  filtrosAbiertos.value = false
})
/**
 * Pestaña con la que se abre el panel: el **Asistente** (desde 2026-11).
 *
 * Se abre en el chat porque es la forma más directa de pedir algo —«¿qué ínfimas hay para mí?»—
 * sin saber dónde está cada pantalla, que era lo que más costaba a quien usa poco el ordenador. Lo
 * que sigue explica por qué antes se abría en la lista de ínfimas, que sigue siendo la primera
 * pantalla de datos:
 *
 * Es la primera, y no el resumen de gráficas. El panel se abre casi siempre para **mirar las
 * contrataciones** —qué ha salido, de qué entidad, por cuánto— y el resumen es lo que se consulta
 * después. Abrir en la primera pestaña también evita una rareza visible: con otra seleccionada, la
 * pestaña de más a la izquierda aparece apagada y parece que falta algo.
 */
const pestana = ref('asistente')

/**
 * Pestañas que ya se abrieron alguna vez. Cada pestaña se monta **la primera vez que se abre** y
 * después se queda montada (con `v-show`) para no perder lo escrito. Antes se montaban todas al
 * entrar, y cada inicio de sesión disparaba a la vez el radar, el mercado, el perfil y los
 * documentos aunque nadie fuera a mirarlos: con cientos de personas entrando, era trabajo del
 * servidor tirado. Su código, además, se baja aparte (`defineAsyncComponent`).
 */
const visitadas = reactive(new Set(['infimas']))
watch(pestana, (id) => visitadas.add(id), { immediate: true })
const visitada = (id) => visitadas.has(id)
const pedidoOferta = ref({ codigo: '', marca: 0 })
const cambiandoContrasena = ref(false)
const exito = ref('')

/**
 * Las pantallas del panel, con su nombre en el menú y la frase de una línea que dice para qué sirven.
 *
 * Los ids son los de siempre —otros componentes y la lógica de plazos los usan— aunque el nombre que
 * se lee haya cambiado: «Ofertas» pasó a «Procesos con oferta», «Radar» a «Recomendadas»… El id es
 * el contrato; la etiqueta, la presentación.
 */
const PANTALLAS = {
  asistente: {
    etiqueta: 'Asistente',
    pista: 'Pregunta lo que necesites: ínfimas, procesos, alertas o tu proforma.',
  },
  inicio: { etiqueta: 'Inicio', pista: 'Lo que tienes hoy: ínfimas, cierres próximos y avisos.' },
  // El listado de ínfimas cuantías **fija la familia**: aquí se ven ínfimas y solo ínfimas. Tener la
  // familia en la pantalla y no en un desplegable del lateral es lo que permite que cada una
  // responda a una pregunta concreta: «qué necesidades de compra han salido».
  infimas: {
    etiqueta: 'Ínfimas cuantías',
    pista: 'Compras pequeñas publicadas por las entidades. Abre una para ver la ficha y llenar el TDR.',
  },
  // El listado del portal de procesos, que consulta la fuente OCDS por su cuenta.
  ofertas: {
    etiqueta: 'Procesos con oferta',
    pista: 'Subastas, licitaciones y demás procesos publicados en el portal.',
  },
  // El mapa sí deja elegir familia, porque su pregunta es otra: «dónde».
  mapa: { etiqueta: 'Mapa', pista: 'Dónde se está comprando. Pulsa una provincia para filtrar.' },
  resumen: { etiqueta: 'Estadísticas', pista: 'Gráficas de lo publicado con los filtros puestos.' },
  // Todas las ínfimas abiertas que la empresa puede ofertar según su perfil. Va antes que el radar
  // porque responde a la pregunta más directa: «¿a qué puedo aplicar hoy?».
  propuestas: {
    etiqueta: 'Propuestas para ti',
    pista: 'Ínfimas abiertas que tu empresa puede ofertar, según tus CPC, ubicación y presupuesto.',
  },
  radar: {
    etiqueta: 'Recomendadas',
    pista: 'Procesos que encajan con tu empresa, tus alertas y sus avisos.',
  },
  mercado: {
    etiqueta: 'Precios y competencia',
    pista: 'Cuánto se adjudicó y a quién, para poner tu precio.',
  },
  documentos: { etiqueta: 'Preparar oferta', pista: 'Del TDR a la proforma firmada, paso a paso.' },
  // El CRM de las proformas hechas: tablero por etapa, calendario de cierres y tasa de éxito.
  misofertas: {
    etiqueta: 'Mis ofertas',
    pista: 'El seguimiento de tus proformas: etapas, cierres y resultados.',
  },
  perfil: { etiqueta: 'Perfil y RUP', pista: 'Los datos de tu empresa que se autollenan en cada oferta.' },
  plantilla: { etiqueta: 'Plantilla de Excel', pista: 'Qué columnas lleva lo que tu empresa descarga.' },
  usuarios: { etiqueta: 'Usuarios', pista: 'Quién de tu equipo entra al panel y con qué permisos.' },
  empresas: { etiqueta: 'Empresas', pista: 'Las empresas de la plataforma y sus plazos de acceso.' },
}

const PESTANAS_BASE = [
  'asistente',
  'inicio',
  'infimas',
  'ofertas',
  'mapa',
  'resumen',
  'propuestas',
  'radar',
  'mercado',
  'documentos',
  'misofertas',
]

/**
 * Las pantallas que existen para quien está delante.
 *
 * La plantilla, los usuarios y el perfil solo aparecen a un rol administrativo, y las empresas solo
 * al dueño del sistema. Se ocultan en lugar de mostrarlas y que fallen: un consultor que pulse
 * «Usuarios» y reciba un error de permisos entendería que el sistema está roto, no que él no tiene
 * esa capacidad. El servidor lo rechazaría igualmente —ahí está la barrera de verdad—, pero no hay
 * motivo para ofrecer a nadie un botón que solo puede llevarle a un rechazo.
 */
const PESTANAS = computed(() => {
  let ids
  if (!sesion.esAdministrativo.value) {
    // El dueño del sistema ve además el censo de empresas, que es la única pantalla que mira a
    // todas a la vez. Un administrador de negocio no la ve porque no hay nada suyo ahí.
    ids = sesion.esDePlataforma.value ? [...PESTANAS_BASE, 'empresas'] : PESTANAS_BASE
  } else {
    ids = [
      ...PESTANAS_BASE,
      'perfil',
      'plantilla',
      'usuarios',
      ...(sesion.estado.rol === 'super_admin' ? ['empresas'] : []),
    ]
  }
  // Las pantallas de una vista que el superadministrador ocultó (o cuyo plazo venció) **no salen
  // en el menú**: ofrecer un botón que solo lleva a «sin acceso» invita a pulsarlo. El servidor
  // sigue negando los datos en cada petición; esto solo evita enseñarlo.
  return ids.filter((id) => !pestanaCerrada(id)).map((id) => ({ id, ...PANTALLAS[id] }))
})

/**
 * Las pantallas agrupadas por la tarea del proveedor, en el orden de la guía de diseño. Una lista de
 * doce botones obliga a leerlos todos; cinco áreas con su frase dejan elegir primero qué se quiere
 * hacer.
 */
const AREAS = [
  // El asistente va arriba del todo: es la pantalla con la que se abre el panel.
  { id: 'asistente', etiqueta: 'Asistente', pista: '', pestanas: ['asistente'] },
  { id: 'inicio', etiqueta: 'Inicio', pista: '', pestanas: ['inicio'] },
  {
    id: 'buscar',
    etiqueta: 'Buscar oportunidades',
    pista: 'Qué compras públicas han salido',
    pestanas: ['infimas', 'ofertas', 'mapa', 'resumen'],
  },
  {
    id: 'parati',
    etiqueta: 'Oportunidades para ti',
    pista: 'Lo que encaja con tu empresa',
    pestanas: ['propuestas', 'radar', 'mercado'],
  },
  {
    id: 'ofertar',
    etiqueta: 'Ofertar',
    pista: 'Prepara la proforma y síguela',
    pestanas: ['documentos', 'misofertas'],
  },
  {
    id: 'empresa',
    etiqueta: 'Mi empresa',
    pista: 'Tus datos, tu equipo y tu Excel',
    pestanas: ['perfil', 'plantilla', 'usuarios', 'empresas'],
  },
]

const areasVisibles = computed(() => {
  const porId = Object.fromEntries(PESTANAS.value.map((opcion) => [opcion.id, opcion]))
  return AREAS.map((area) => ({
    ...area,
    opciones: area.pestanas.map((id) => porId[id]).filter(Boolean),
  })).filter((area) => area.opciones.length)
})

/** El área de la pantalla abierta, para la miga de la barra superior. Inicio no lleva área. */
const areaActiva = computed(() => {
  const area = AREAS.find((candidata) => candidata.pestanas.includes(pestana.value))
  return area && !['inicio', 'asistente'].includes(area.id) ? area.etiqueta : ''
})

const pantallaActual = computed(() => PANTALLAS[pestana.value] || { etiqueta: '', pista: '' })

// Pantallas que traen su propia cabecera, con más que un título (pestañas, contadores, acciones).
// En ellas el título del panel sobra: saldría el mismo nombre dos veces, uno encima del otro.
const CON_CABECERA_PROPIA = new Set(['asistente', 'propuestas', 'radar', 'mercado', 'documentos', 'misofertas'])

/** El motivo del cierre para el menú: vacío si la pantalla está abierta. */
function motivoCierre(id) {
  return pestanaCerrada(id) ? textoCierre(id) : ''
}

/**
 * Qué vista del catálogo hace falta para cada pestaña de datos.
 *
 * El mapa y el resumen leen agregados de `/v1/estadisticas`, que el servidor guarda con la vista de
 * gráficas. Las pestañas que no están aquí (plantilla, usuarios, empresas) dependen del rol.
 */
const VISTA_DE_PESTANA = {
  infimas: 'necesidades',
  // Las propuestas son ínfimas: sin la vista de necesidades, el servidor las negaría.
  propuestas: 'necesidades',
  ofertas: 'ofertas',
  mapa: 'graficas',
  resumen: 'graficas',
}

function vistaPropia(codigo) {
  return sesion.estado.vistas.find((fila) => fila.vista === codigo) || null
}

/**
 * ¿Está cerrada la pestaña por un plazo vencido o sin conceder?
 *
 * Mientras no se sepa —o para el dueño de la plataforma, que se concede los plazos a sí mismo— no se
 * cierra nada: el servidor sigue comprobando el plazo en cada petición de datos.
 */
function usarBusqueda(parametros) {
  filtros.cargarCriterios(parametros)
  pestana.value = parametros?.categoria === 'ofertas' ? 'ofertas' : 'infimas'
}

/**
 * Pestañas que valen con **cualquier** vista de datos: el radar y «Precios y competencia» leen las
 * fuentes que la persona tenga (ínfimas, ofertas o las dos). Sin ninguna, el servidor las niega.
 */
const VISTAS_DE_DATOS_DE_PESTANA = {
  radar: ['necesidades', 'ofertas'],
  mercado: ['necesidades', 'ofertas'],
}

function pestanaCerrada(id) {
  if (!sesion.estado.vistasCargadas || sesion.esDePlataforma.value) return false
  const alguna = VISTAS_DE_DATOS_DE_PESTANA[id]
  if (alguna) return !alguna.some((codigo) => vistaPropia(codigo)?.vigente)
  const codigo = VISTA_DE_PESTANA[id]
  if (!codigo) return false
  return !vistaPropia(codigo)?.vigente
}

function textoCierre(id) {
  const fila = vistaPropia(VISTA_DE_PESTANA[id])
  if (fila?.vence_en) {
    return `Tu acceso a «${fila.etiqueta}» venció el ${fechaCorta(fila.vence_en)}. Pide al administrador de la plataforma que lo renueve.`
  }
  return `Tu cuenta no tiene acceso a «${fila?.etiqueta || 'esta sección'}». Pide al administrador de la plataforma que te lo conceda.`
}

/**
 * Días que le quedan en la plataforma, el menor de las secciones que aún tiene.
 *
 * Es un solo número y no uno por pestaña: la cuenta se suspende cuando se acaba el plazo, y lo que
 * la persona necesita saber es cuánto falta para eso.
 */
const diasDePlataforma = computed(() => {
  if (sesion.esDePlataforma.value || !sesion.estado.vistasCargadas) return null
  const vigentes = sesion.estado.vistas.filter((fila) => fila.vigente)
  if (!vigentes.length) return null
  return Math.min(...vigentes.map((fila) => fila.dias_restantes ?? 0))
})

const avisoPlazo = computed(() => {
  const dias = diasDePlataforma.value
  if (dias === null) return ''
  const vence = venceDePlataforma.value ? ` Vence el ${fechaCorta(venceDePlataforma.value)}.` : ''
  if (dias <= 0) return `Te queda menos de un día en la plataforma.${vence}`
  if (dias === 1) return `Te queda 1 día en la plataforma.${vence}`
  return `Te quedan ${dias} días en la plataforma.${vence}`
})

const venceDePlataforma = computed(() => {
  if (sesion.esDePlataforma.value) return null
  const fechas = sesion.estado.vistas
    .filter((fila) => fila.vigente && fila.vence_en)
    .map((fila) => fila.vence_en)
  if (!fechas.length) return null
  return fechas.sort()[0]
})

const MS_REVISION_VISTAS = 5 * 60_000
let revisorVistas = null

/** Si la pestaña abierta se cerró, se pasa a la primera que siga abierta. */
function ajustarPestana() {
  if (!pestanaCerrada(pestana.value)) return
  const abierta = PESTANAS.value.find((opcion) => !pestanaCerrada(opcion.id))
  if (abierta) abrirPestana(abierta.id)
}

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
function prepararOferta(fila) {
  const codigo = String(fila?.codigo || '').trim()
  if (!codigo) return
  pedidoOferta.value = { codigo, marca: Date.now() }
  abrirPestana('documentos')
}

/**
 * El asistente pide abrir una pantalla por su nombre («alertas», «mis-ofertas», «empresa»…). Se
 * traduce al id real y solo se abre si existe para este rol; si no, no se mueve nada.
 */
function irDesdeAsistente(nombre) {
  const id = pestanaDelAsistente(
    nombre,
    PESTANAS.value.map((opcion) => opcion.id),
  )
  if (id) abrirPestana(id)
}

function abrirPestana(id) {
  pestana.value = id
  if (id === 'infimas' || id === 'ofertas') filtros.elegirCategoria(id)
}

/**
 * ¿Se pinta la columna de filtros del panel?
 *
 * Solo en las vistas que leen esos filtros. Documentos, mercado, perfil y usuarios tienen su propio
 * formulario, y la columna les quitaba un tercio del ancho sin cambiar nada de lo que muestran.
 *
 * Con la pestaña de **ofertas** abierta, tampoco. Sus filtros son los de la pestaña —entidad, tipo,
 * código, estado, fechas— y se aplican con su propio botón; la columna lateral es la de las ínfimas
 * cuantías (el NIC, el estado de la contratación, la fuente) y dejarla a la vista con la pestaña de
 * ofertas delante mezclaba dos juegos de filtros homónimos: se veían los dos «estado de la
 * contratación» y el «código» a la vez, con valores distintos y sin que se supiera cuál manda.
 *
 * Se oculta solo la columna **de este panel**; el botón de la barra que la abre o la cierra también
 * desaparece con ella, porque un botón que no hace nada se lee como un fallo.
 */
const CON_FILTROS = new Set(['infimas', 'mapa', 'resumen'])
const sinFiltrosDelPanel = computed(() => !CON_FILTROS.has(pestana.value))

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

async function pedirMasTiempo() {
  try {
    const resultado = await api.pedirMasTiempo()
    exito.value = resultado?.aviso || 'Tu pedido de más tiempo ya quedó anotado.'
  } catch (fallo) {
    exito.value = ''
    sesion.estado.error = fallo.message
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
    sesion.refrescarVistas(),
  ])
  ajustarPestana()
  await datos.cargar()

  revisorVistas = setInterval(async () => {
    if (document.hidden) return
    await sesion.refrescarVistas()
    ajustarPestana()
  }, MS_REVISION_VISTAS)

  // A partir de aquí, la tabla se pone al día sola cuando la ingesta escribe. Sin esto, lo único que
  // la refrescaba era tocar un filtro: la ingesta podía cerrar dos ciclos y la pantalla seguía
  // enseñando lo de antes, incluso con la necesidad ya guardada y su CPC ya leído.
  revisorNovedades = setInterval(revisarNovedades, MS_REVISION_NOVEDADES)
  document.addEventListener('visibilitychange', alVolverALaPestana)
})

onBeforeUnmount(() => {
  clearTimeout(temporizador)
  clearInterval(revisorNovedades)
  clearInterval(revisorVistas)
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
  <div
    class="panel"
    :class="{ 'panel--menu-plegado': menuPlegado && !esMovil, 'panel--asistente': pestana === 'asistente' }"
  >
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
      :titulo="pantallaActual.etiqueta"
      :area="areaActiva"
      :menu-abierto="esMovil ? menuAbierto : !menuPlegado"
      :filtros-abiertos="esMovil ? filtrosAbiertos : filtrosVisibles"
      :filtros-activos="filtros.hayFiltros.value"
      :con-filtros="!sinFiltrosDelPanel"
      :dias-restantes="diasDePlataforma"
      :texto-plazo="avisoPlazo"
      @pedir-tiempo="pedirMasTiempo"
      @alternar-tema="emit('alternar-tema')"
      @cerrar-sesion="emit('cerrar-sesion')"
      @alternar-panel="panelCuentaAbierto = !panelCuentaAbierto"
      @cambiar-contrasena="cambiandoContrasena = true"
      @alternar-filtros="alternarFiltros"
      @alternar-menu="alternarMenu"
    />

    <div class="panel__marco">
      <MenuLateral
        :areas="areasVisibles"
        :activa="pestana"
        :plegado="menuPlegado"
        :abierto="menuAbierto"
        :es-movil="esMovil"
        :cuentas="datos.estado.totalesPorCategoria"
        :motivo-cierre="motivoCierre"
        @elegir="abrirPestana"
        @alternar-plegado="alternarPlegado"
        @cerrar="menuAbierto = false"
      />

      <div class="panel__area">
        <p v-if="exito" class="panel__exito aparece" role="status">
          {{ exito }}
          <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Ocultar" @click="exito = ''">
            ✕
          </button>
        </p>

        <!-- Aviso de datos de ejemplo. No se puede cerrar de forma permanente a propósito: si se
             recordara la elección, alguien podría volver al panel semanas después, con datos reales
             ya cargados, y seguir con el cartel oculto sin darse cuenta de que ahora sí son reales. -->
        <Transition name="deslizar">
          <div v-if="mostrarAvisoEjemplo" class="aviso-ejemplo" role="status">
            <span class="etiqueta etiqueta--aviso">Ejemplo</span>
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

        <div
          class="panel__cuerpo"
          :class="{
            'panel__cuerpo--sin-filtros': sinFiltrosDelPanel || (!esMovil && !filtrosVisibles),
          }"
        >
          <!-- Filtros: columna fija en escritorio, cajón deslizante en móvil. -->
          <aside
            v-if="!sinFiltrosDelPanel"
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
            v-if="filtrosAbiertos && !sinFiltrosDelPanel"
            class="panel__velo"
            aria-hidden="true"
            @click="filtrosAbiertos = false"
          />

          <main class="panel__principal">
            <!-- Título de la pantalla y la frase que dice para qué sirve: una línea, no un párrafo. -->
            <header v-if="!CON_CABECERA_PROPIA.has(pestana)" class="pantalla">
              <h1 class="pantalla__titulo">{{ pantallaActual.etiqueta }}</h1>
              <p v-if="pantallaActual.pista" class="pantalla__pista">{{ pantallaActual.pista }}</p>
            </header>

            <!-- El plazo ya está en la barra de arriba. Solo se vuelve un aviso aparte cuando queda poco. -->
            <p v-if="avisoPlazo && (diasDePlataforma ?? 99) <= 30" class="panel__vencimiento" role="status">
              <span class="etiqueta etiqueta--aviso">Plazo</span>
              <span class="panel__vencimiento-texto">{{ avisoPlazo }}</span>
              <button type="button" class="boton boton--secundario boton--pequeno" @click="pedirMasTiempo">
                Pedir más tiempo
              </button>
            </p>

            <section v-if="pestanaCerrada(pestana)" class="panel__cerrada superficie" role="status">
              <span class="panel__cerrada-icono" aria-hidden="true">🔒</span>
              <p>{{ textoCierre(pestana) }}</p>
            </section>

            <!-- El chat ocupa el alto que queda: los mensajes se desplazan y el campo de escribir
                 se queda siempre a la vista. -->
            <section v-if="visitada('asistente')" v-show="pestana === 'asistente'" class="panel__asistente">
              <AsistentePanel
                :activa="pestana === 'asistente'"
                @preparar="prepararOferta"
                @ir="irDesdeAsistente"
              />
            </section>

            <section v-if="visitada('inicio')" v-show="pestana === 'inicio'">
              <InicioPanel :activa="pestana === 'inicio'" @ir="abrirPestana" />
            </section>

            <!-- `v-show` y no `v-if`: al renovar el plazo las gráficas vuelven sin reconstruirse. -->
            <section v-show="pestana === 'resumen' && !pestanaCerrada('resumen')" class="resumen">
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

            <section v-show="pestana === 'mapa' && !pestanaCerrada('mapa')" class="panel__pila">
              <!--
                El selector de familia, dentro del mapa.

                El mapa responde a «dónde», y esa pregunta se hace igual sobre las dos familias:
                «dónde se están comprando medicamentos» vale tanto para las necesidades de compra
                como para los procesos con oferta. Tenerlas juntas en una sola vista es lo que permite
                ver si las dos coinciden en la misma provincia.

                Se escribe en el filtro de verdad —el mismo que leen la tabla y las gráficas de
                debajo— y no en un estado propio del mapa. Si el mapa tuviera el suyo, el mapa y la
                tabla que tiene justo al lado podrían estar mostrando familias distintas y las cifras
                no cuadrarían sin que nada explicara por qué.
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

              <!-- La misma tabla que la pantalla de ínfimas cuantías, con su detalle desplegable y su
                   paginación. Es lo que responde a «ver todas las contrataciones de la región con los
                   filtros aplicados» sin cambiar de pantalla. -->
              <TablaRegistros :titulo="tituloDeLaFamilia" @preparar="prepararOferta">
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
              El panel de empresas se pide solo al dueño de la plataforma, y se pide de verdad (`v-if`,
              no solo `v-show`): la pantalla no existe para los demás, así que con `v-show` el
              componente se montaba igual y disparaba en cada carga un petición que el servidor
              rechazaba con 403.
            -->
            <section v-if="sesion.esDePlataforma.value && visitada('empresas')" v-show="pestana === 'empresas'">
              <PanelEmpresas />
              <ComprasIa />
            </section>

            <section v-show="pestana === 'infimas' && !pestanaCerrada('infimas')">
              <TablaRegistros :titulo="TITULO_INFIMAS" @preparar="prepararOferta">
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

            <section v-if="visitada('ofertas')" v-show="pestana === 'ofertas' && !pestanaCerrada('ofertas')">
              <OfertasTab @preparar="prepararOferta" />
            </section>

            <section v-if="visitada('plantilla')" v-show="pestana === 'plantilla'">
              <PlantillaExcel />
            </section>

            <!-- Solo se monta para quien administra: la lista de usuarios es una petición que a los
                 demás roles el servidor les niega (403), y montarla oculta solo producía ese error. -->
            <section
              v-if="sesion.esAdministrativo.value && visitada('usuarios')"
              v-show="pestana === 'usuarios'"
              class="tarjeta aparece"
            >
              <div class="tarjeta__cuerpo">
                <GestionUsuarios />
              </div>
            </section>

            <section v-if="visitada('perfil')" v-show="pestana === 'perfil'" class="tarjeta aparece">
              <div class="tarjeta__cuerpo">
                <PerfilEmpresa />
              </div>
            </section>

            <section
              v-if="visitada('propuestas')"
              v-show="pestana === 'propuestas' && !pestanaCerrada('propuestas')"
              class="tarjeta aparece"
            >
              <div class="tarjeta__cuerpo">
                <!-- `ir-perfil` solo se escucha si el rol tiene la pestaña de perfil: así la pantalla
                     sabe que no hay botón que ofrecer y dice en texto dónde está. -->
                <PropuestasParaTi
                  @preparar="prepararOferta"
                  v-on="PESTANAS.some((opcion) => opcion.id === 'perfil') ? { irPerfil: () => abrirPestana('perfil') } : {}"
                />
              </div>
            </section>

            <section v-if="visitada('radar')" v-show="pestana === 'radar' && !pestanaCerrada('radar')" class="tarjeta aparece">
              <div class="tarjeta__cuerpo">
                <RadarOportunidades
                  @usar-busqueda="usarBusqueda"
                  @preparar="prepararOferta"
                  @ir-perfil="PESTANAS.some((opcion) => opcion.id === 'perfil') && abrirPestana('perfil')"
                />
              </div>
            </section>

            <section v-if="visitada('mercado')" v-show="pestana === 'mercado' && !pestanaCerrada('mercado')" class="tarjeta aparece">
              <div class="tarjeta__cuerpo">
                <Mercado />
              </div>
            </section>

            <section v-if="visitada('documentos')" v-show="pestana === 'documentos'" class="tarjeta aparece">
              <div class="tarjeta__cuerpo">
                <Documentos
                  :codigo-inicial="pedidoOferta.codigo"
                  :marca="pedidoOferta.marca"
                  @perfil="abrirPestana('perfil')"
                />
              </div>
            </section>

            <section v-if="visitada('misofertas')" v-show="pestana === 'misofertas'" class="tarjeta aparece">
              <div class="tarjeta__cuerpo">
                <MisOfertas @preparar="prepararOferta" />
              </div>
            </section>

            <footer v-show="pestana !== 'asistente'" class="panel__pie">
              <span>{{ ultimaActualizacion }}</span>
              <span v-if="datos.estado.desdeCache">· respuesta servida desde la memoria intermedia</span>
              <span v-if="presencia.enVivo.value">· presencia en vivo</span>
              <span v-else-if="presencia.error.value" :title="presencia.error.value">
                · presencia sin conexión
              </span>
              <!-- Aviso de derechos y textos legales. Se abren en otra pestaña para no sacar a nadie
                   del panel a mitad de trabajo. -->
              <div class="panel__legal">
                <span>© {{ new Date().getFullYear() }} CercoApp. Todos los derechos reservados.</span>
                <span>
                  Prohibida la reproducción, copia o distribución total o parcial de este sitio, su
                  contenido, diseño y marca sin autorización escrita.
                </span>
                <span class="panel__legal-enlaces">
                  <a href="/terminos" target="_blank" rel="noopener">Términos y condiciones</a>
                  ·
                  <a href="/privacidad" target="_blank" rel="noopener">Política de privacidad</a>
                </span>
              </div>
            </footer>
          </main>
        </div>
      </div>
    </div>

    <CambiarContrasena
      v-if="cambiandoContrasena"
      @cerrar="cambiandoContrasena = false"
      @cambiada="alCambiarContrasena"
    />

    <!-- Botón flotante para abrir los filtros en móvil: la barra superior ya tiene el suyo, pero
         queda lejos del pulgar cuando la lista es larga. Solo donde hay filtros que abrir. -->
    <button
      v-if="!sinFiltrosDelPanel"
      type="button"
      class="panel__flotante"
      :aria-label="filtros.hayFiltros.value ? 'Abrir los filtros (hay filtros activos)' : 'Abrir los filtros'"
      @click="filtrosAbiertos = true"
    >
      <IconoPanel nombre="filtros" :tamano="20" />
      <span v-if="filtros.hayFiltros.value" class="panel__flotante-marca" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.panel {
  min-height: 100vh;
}

/*
 * El armazón: menú a la izquierda y el área de trabajo a la derecha. El ancho del menú es una
 * variable para que plegarlo sea cambiar un número y no reescribir la rejilla.
 */
.panel__marco {
  --ancho-menu: 248px;
  display: grid;
  grid-template-columns: var(--ancho-menu) minmax(0, 1fr);
  align-items: start;
}

.panel--menu-plegado .panel__marco {
  --ancho-menu: 64px;
}

.panel__area {
  min-width: 0;
  padding-bottom: var(--e-6);
}

/*
 * El asistente necesita un alto fijo —la ventana menos la barra y el margen de arriba— para que
 * desplacen los mensajes y no la página, y el campo de escribir quede siempre abajo a la vista.
 */
.panel--asistente .panel__area {
  padding-bottom: var(--e-4);
}

.panel__asistente {
  --margen-asistente: calc(var(--e-5) + var(--e-4));
  height: calc(100vh - var(--altura-cabecera) - var(--margen-asistente));
  height: calc(100dvh - var(--altura-cabecera) - var(--margen-asistente));
  min-height: 420px;
}

/* Cabecera de cada pantalla: título y una línea de para qué sirve. */
.pantalla {
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
}

.pantalla__titulo {
  font-size: var(--t-xl);
}

.pantalla__pista {
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.panel__cuerpo {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: var(--e-5);
  align-items: start;
  padding: var(--e-5) var(--e-5) 0;
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

/* Avisos en base neutra: el color va solo en la insignia pequeña, no en el bloque entero. */
.panel__vencimiento {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
  background: var(--superficie);
  color: var(--texto-suave);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.panel__vencimiento-texto {
  flex: 1;
  min-width: 12rem;
}

.panel__cerrada {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  padding: var(--e-5);
  border-radius: var(--r-2);
  color: var(--texto-suave);
  font-size: var(--t-md);
  line-height: 1.5;
}

.panel__cerrada-icono {
  font-size: var(--t-lg);
}

.panel__aviso {
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
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
  border: 1px solid var(--borde);
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
  border: 1px dashed var(--borde-fuerte);
  background: var(--superficie);
  color: var(--texto-suave);
  font-size: var(--t-sm);
  line-height: 1.5;
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

.panel__legal {
  flex-basis: 100%;
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1) var(--e-3);
  margin-top: var(--e-2);
  padding-top: var(--e-2);
  border-top: 1px solid var(--borde);
  line-height: 1.5;
}

.panel__legal-enlaces a {
  color: var(--texto-suave);
}

.panel__legal-enlaces a:hover,
.panel__legal-enlaces a:focus-visible {
  color: var(--acento);
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
  background: var(--superficie);
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
  /* En móvil y tableta el menú es un cajón fuera del flujo: el contenido usa todo el ancho. */
  .panel__marco {
    grid-template-columns: minmax(0, 1fr);
  }

  .panel__cuerpo {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--e-4) var(--e-4) 0;
    gap: 0;
  }

  /* El panel de filtros pasa a ser un cajón. Se saca del flujo con `position: fixed` en lugar de
     apilarlo encima del contenido: apilado, cambiar un filtro obligaría a desplazarse hasta arriba
     para ver el efecto, y el efecto es justo lo que se quiere comprobar. */
  .panel__lateral {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 50;
    width: min(340px, 88vw);
    max-height: none;
    border-radius: 0;
    border: 0;
    border-left: 1px solid var(--borde);
    /* Entra por la derecha: el menú entra por la izquierda y así no se confunden los dos cajones. */
    transform: translateX(102%);
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

  .panel__asistente {
    --margen-asistente: calc(var(--e-4) * 2);
  }
}

@media (min-width: 1024px) {
  .panel__flotante {
    display: none;
  }
}

@media (max-width: 639px) {
  .panel__cuerpo {
    padding: var(--e-3) var(--e-3) 0;
  }

  .panel--asistente .panel__area {
    padding-bottom: var(--e-3);
  }

  .panel__asistente {
    --margen-asistente: calc(var(--e-3) * 2);
  }

  .aviso-ejemplo,
  .panel__aviso,
  .panel__exito {
    margin-left: var(--e-3);
    margin-right: var(--e-3);
  }

  .pantalla__titulo {
    font-size: var(--t-lg);
  }
}
</style>
