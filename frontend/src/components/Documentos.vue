<script setup>
/**
 * «Preparar oferta»: un asistente de cuatro pasos (leer el TDR, marcar requisitos, armar la proforma
 * y descargarla). Cada paso tiene una acción principal y la misma barra «Atrás / Siguiente».
 *
 * Todo lo que ya se sabe (perfil de la empresa, ficha del proceso, datos de la entidad, lo que el
 * TDR trae con etiqueta) llega escrito y marcado «autollenado · revisa»: la persona solo escribe
 * sus precios y lo que falte. Los precios nunca se proponen. El resumen no completa apartados que
 * el archivo no titula.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { esperarVisible, siguientePausa } from '@/utils/sondeo'
import TextoTdr from '@/components/TextoTdr.vue'
import { guardarArchivo as guardarEnDisco } from '@/utils/descargas'
import { armarProformaPdf } from '@/utils/proformaPdf'
import { decimal } from '@/utils/formato'
import { esImagen, textoDeArchivo } from '@/utils/ocr'
import { presupuestoValido, usoDelPresupuesto } from '@/utils/presupuesto'
import { textoLegible } from '@/utils/textoTdr'
import { tituloLibre, tituloRepetido } from '@/utils/titulos'

// Cada paso dice en una línea qué se hace en él; es lo que se lee bajo el título del paso.
const PASOS = [
  {
    id: 'proceso',
    etiqueta: 'Lee el TDR',
    resultado: 'Ves qué pide la entidad',
    ayuda: 'Escribe el código del proceso: bajamos el TDR del portal y te lo resumimos.',
  },
  {
    id: 'requisitos',
    etiqueta: 'Requisitos',
    resultado: 'Marcas lo que cumples',
    ayuda: 'Marca lo que ya cumples y lo que no aplica. Las respuestas se escriben en el paso 3.',
  },
  {
    id: 'documento',
    etiqueta: 'Tu proforma',
    resultado: 'Escribes tus precios',
    ayuda: 'Ya llenamos lo que sabemos. Revisa lo marcado «autollenado» y escribe tus precios.',
  },
  {
    id: 'entrega',
    etiqueta: 'Descarga',
    resultado: 'PDF o Word',
    ayuda: 'Revisa la vista previa y descárgala. Queda guardada en «Mis ofertas».',
  },
]

const TIPOS = [
  {
    id: 'proforma',
    etiqueta: 'Proforma',
    pista: 'Para una ínfima cuantía. Escribes cada producto y su precio.',
  },
  {
    id: 'cotizacion',
    etiqueta: 'Cotización',
    pista: 'Usa el catálogo de tu empresa. El precio lo confirmas tú.',
  },
  {
    id: 'ficha',
    etiqueta: 'Ficha técnica',
    pista: 'Marca, modelo y características de un producto. No lleva precios.',
  },
]

const NOMBRES_SECCION = {
  especificaciones: 'Especificaciones técnicas',
  cpc: 'Código CPC',
  cantidad: 'Cantidad',
  contacto: 'Contacto',
  objeto: 'Objeto de contratación',
  antecedentes: 'Antecedentes',
  alcance: 'Alcance',
  actividades: 'Actividades',
  entregables: 'Entregables',
  plazos: 'Plazos',
  presupuesto: 'Presupuesto',
  requisitos_tecnicos: 'Requisitos técnicos',
  condiciones: 'Condiciones de participación',
  contexto_anexos: 'Texto de todos los anexos (lo usa la IA para armar la proforma)',
}

const EJEMPLOS = [
  '¿Qué solicita este TDR?',
  '¿Cuál es el plazo de entrega?',
  '¿Qué requisitos pide el TDR?',
  '¿Cuál es la forma de pago?',
  '¿Qué requisitos me faltan?',
  '¿Qué oportunidades nuevas tengo?',
]

const props = defineProps({
  codigoInicial: { type: String, default: '' },
  marca: { type: Number, default: 0 },
})
const emit = defineEmits(['perfil'])

const CONDICIONES = [
  { id: 'plazo_ejecucion', etiqueta: 'Plazo de ejecución', pista: 'Ej. 120 días' },
  { id: 'plazo_entrega', etiqueta: 'Plazo de entrega', pista: 'Ej. 5 días calendario desde la orden' },
  { id: 'lugar_entrega', etiqueta: 'Lugar de entrega', pista: 'Ej. Bodega de la entidad' },
  { id: 'forma_pago', etiqueta: 'Forma de pago', pista: 'Ej. Contra entrega, previa factura' },
  { id: 'garantia', etiqueta: 'Garantía', pista: 'Ej. 12 meses por defectos de fábrica' },
  { id: 'validez', etiqueta: 'Vigencia de la oferta', pista: 'Mínimo 45 días desde la emisión' },
]
// Las que una entidad exige siempre en una proforma de ínfima cuantía.
const CONDICIONES_SERCOP = ['plazo_entrega', 'lugar_entrega', 'forma_pago', 'validez']

const paso = ref('proceso')
const tipo = ref('proforma')
const reviso = ref(false)
const error = ref('')
const aviso = ref('')
const ocupado = ref(false)
const lectura = ref(null)
const resumen = ref(null)
const codigo = ref('')
const requisitos = ref([])
const ofertas = ref([])
const documento = ref(null)
const contraste = ref(null)
const conversacion = ref([])
const pregunta = ref('')
const archivo = ref(null)
const trayendo = ref(false)
const tituloEmpresa = ref('')
const creditos = ref(null)
const generando = ref('')
const borrador = ref(null)
const verCompras = ref(false)
const pensando = ref(false)
const firmando = ref(false)
const firma = reactive({ archivo: null, clave: '', lugar: '' })
const verificacion = ref(null)

/**
 * Qué campos llenó el sistema y no la persona. Se enseñan con «autollenado · revisa»: el dato sale
 * del perfil, de la ficha o del TDR, y un TDR real a veces lo trae pegado a una cláusula entera.
 */
const autollenado = reactive(new Set())
function marcarAuto(clave, valor) {
  if (String(valor ?? '').trim()) autollenado.add(clave)
}
const esAuto = (clave, valor) => autollenado.has(clave) && Boolean(String(valor ?? '').trim())

const lineaVacia = () => ({
  descripcion: '',
  cantidad: 1,
  unidad: '',
  precio_unitario: '',
  cpc: '',
  cpc_nombre: '',
})

const proforma = reactive({
  // El título de la proforma: lo que se lee en el PDF y en «Mis ofertas». Se sugiere a partir de la
  // ínfima (objeto y código) y se puede cambiar; vacío vuelve a la sugerencia.
  titulo: '',
  entidad: '',
  objeto: '',
  contacto: '',
  // El formulario del SOCE pide un valor unitario ofertado y un total, sin IVA aparte: por defecto 0.
  impuesto_porcentaje: 0,
  lineas: [lineaVacia()],
})
const extras = reactive({
  empresa: {},
  carta: '',
  // Bloque «Entidad» y número de la proforma, como en el formulario del SOCE.
  entidad: { ruc: '', direccion: '', telefono: '' },
  numero: '',
  necesidad: '',
  // El Formulario de Perfil de Integridad (Anexo I, Res. R.E-SERCOP-2026-0005) viaja con la oferta.
  integridad: true,
  condiciones: Object.fromEntries(CONDICIONES.map((item) => [item.id, ''])),
  experiencia: '',
  personal: '',
  equipo: '',
  cumplimiento: [],
})
const ficha = reactive({
  nombre: '',
  marca: '',
  modelo: '',
  pais_origen: '',
  anio_fabricacion: '',
  cpc: '',
  garantia: '',
  contacto: '',
  especificaciones: [],
})
const preciosCatalogo = reactive({})
const cantidadesCatalogo = reactive({})
const soloPendientes = ref(false)

const tieneTexto = (valor) => Boolean(String(valor || '').trim())

const respuestas = computed(() => {
  const filas = extras.cumplimiento.filter((fila) => tieneTexto(fila.requisito))
  const hechas = filas.filter((fila) => tieneTexto(fila.como_cumple)).length
  return { total: filas.length, hechas, porcentaje: filas.length ? Math.round((hechas / filas.length) * 100) : 0 }
})

const especificado = computed(() => {
  const filas = ficha.especificaciones.filter((fila) => tieneTexto(fila.requerido) || tieneTexto(fila.ofertado))
  const hechas = filas.filter((fila) => tieneTexto(fila.ofertado)).length
  return { total: filas.length, hechas }
})

/** Lo que una entidad revisa antes de aceptar el documento. Cada punto dice qué falta. */
const revision = computed(() => {
  if (tipo.value === 'ficha') {
    return [
      { id: 'entidad', etiqueta: 'Entidad y objeto', ok: tieneTexto(proforma.entidad) && tieneTexto(proforma.objeto) },
      { id: 'bien', etiqueta: 'Producto, marca y modelo', ok: tieneTexto(ficha.nombre) && tieneTexto(ficha.marca) && tieneTexto(ficha.modelo) },
      { id: 'origen', etiqueta: 'País de origen y garantía', ok: tieneTexto(ficha.pais_origen) && tieneTexto(ficha.garantia) },
      {
        id: 'especificaciones',
        etiqueta: `Especificaciones ${especificado.value.hechas}/${especificado.value.total}`,
        ok: especificado.value.total > 0 && especificado.value.hechas === especificado.value.total,
      },
    ]
  }
  const conPrecio =
    tipo.value === 'proforma'
      ? proforma.lineas.every((linea) => tieneTexto(linea.descripcion) && linea.precio_unitario !== '')
      : ofertas.value.some((fila) => preciosCatalogo[fila.id] !== '' && preciosCatalogo[fila.id] != null)
  const condiciones = CONDICIONES_SERCOP.filter((id) => tieneTexto(extras.condiciones[id])).length
  return [
    { id: 'entidad', etiqueta: 'Entidad y objeto', ok: tieneTexto(proforma.entidad) && tieneTexto(proforma.objeto) },
    { id: 'precios', etiqueta: 'Precios escritos', ok: conPrecio },
    {
      id: 'condiciones',
      etiqueta: `Condiciones ${condiciones}/${CONDICIONES_SERCOP.length}`,
      ok: condiciones === CONDICIONES_SERCOP.length,
    },
    {
      id: 'respuestas',
      etiqueta: `Respuestas al TDR ${respuestas.value.hechas}/${respuestas.value.total}`,
      ok: respuestas.value.total > 0 && respuestas.value.hechas === respuestas.value.total,
    },
    { id: 'empresa', etiqueta: 'Datos de tu empresa', ok: !borrador.value?.faltantes?.length },
  ]
})

const BLOQUE_DE = { empresa: 'entidad', origen: 'bien' }

function irA(id) {
  document.getElementById(`bloque-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const conoceProceso = computed(() => Boolean(lectura.value || resumen.value))
const indice = computed(() => PASOS.findIndex((item) => item.id === paso.value))

const avance = computed(() => {
  const total = requisitos.value.length
  const hechos = requisitos.value.filter((item) => item.estado !== 'pendiente').length
  return { total, hechos, porcentaje: total ? Math.round((hechos / total) * 100) : 0 }
})

const totalesPrevios = computed(() => {
  const subtotal = proforma.lineas.reduce((suma, linea) => {
    const precio = Number(linea.precio_unitario)
    const cantidad = Number(linea.cantidad)
    return linea.precio_unitario === '' || !cantidad ? suma : suma + precio * cantidad
  }, 0)
  const impuesto = (subtotal * Number(proforma.impuesto_porcentaje || 0)) / 100
  return { subtotal, impuesto, total: subtotal + impuesto }
})

function estadoPaso(id) {
  if (id === paso.value) return 'actual'
  if (id === 'proceso' && conoceProceso.value) return 'hecho'
  if (id === 'requisitos' && reviso.value) return 'hecho'
  if (id === 'documento' && documento.value) return 'hecho'
  if (id === 'entrega' && documento.value && paso.value !== 'entrega') return 'hecho'
  return 'pendiente'
}

function disponible(id) {
  if (id === 'proceso') return true
  if (id === 'requisitos') return conoceProceso.value
  if (id === 'documento') return reviso.value
  return Boolean(documento.value)
}

function motivoBloqueo(id) {
  if (id === 'requisitos') return 'Primero lee el TDR o resume un proceso por su código.'
  if (id === 'documento') return 'Primero revisa los requisitos y pulsa Continuar.'
  return 'Primero arma la proforma, la cotización o la ficha. La descarga aparece al final.'
}

async function ejecutar(tarea) {
  error.value = ''
  ocupado.value = true
  try {
    await tarea()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = false
  }
}

/** Lo que dice el resumen de cada apartado. Si vino del listado, no se afirma que el TDR no lo trae. */
const SIN_EN_LISTADO = {
  necesita: 'El listado no trae el objeto de la compra.',
  entregar: 'El listado no trae los entregables.',
  condiciones: 'El listado no trae las condiciones.',
  documentos: 'El listado no publica documentos.',
  fechas: 'El listado no trae fechas.',
  presupuesto: 'El listado no publica presupuesto.',
}

function textoResumen(clave) {
  const valor = resumen.value?.[clave]
  if (valor) return valor
  if (resumen.value?.fuente === 'ficha') return SIN_EN_LISTADO[clave]
  return 'No está en el documento.'
}

/** Los datos que el formulario del TDR trae con su etiqueta, en el orden en que se piden en la oferta. */
const DATOS_CLAVE = [
  { clave: 'plazo_entrega', etiqueta: 'Plazo de entrega' },
  { clave: 'forma_pago', etiqueta: 'Forma de pago' },
  { clave: 'lugar_entrega', etiqueta: 'Lugar de entrega' },
  { clave: 'garantia', etiqueta: 'Garantía' },
  { clave: 'vigencia_proforma', etiqueta: 'Vigencia de la proforma' },
  { clave: 'presupuesto', etiqueta: 'Presupuesto referencial' },
]
// Qué casilla de «Condiciones de la oferta» llena cada dato del TDR.
const CONDICION_DE = {
  plazo_entrega: 'plazo_entrega',
  forma_pago: 'forma_pago',
  lugar_entrega: 'lugar_entrega',
  garantia: 'garantia',
  vigencia_proforma: 'validez',
}

// Qué casillas de «Condiciones de la oferta» se llenaron con lo que el TDR dice con etiqueta. Un TDR
// real a veces trae el dato pegado a una cláusula entera: por eso se marcan para que se revisen.
const condicionesDelTdrIds = computed(
  () => new Set(datosClave.value.map((dato) => CONDICION_DE[dato.clave]).filter(Boolean)),
)

const datosClave = computed(() => {
  const fuente = lectura.value?.secciones || {}
  return DATOS_CLAVE.map((dato) => ({ ...dato, valor: fuente[dato.clave] || '' })).filter(
    (dato) => dato.valor,
  )
})

/** Una condición en una frase: el TDR a veces trae el dato pegado al artículo que lo rodea. */
function corto(valor, tope = 160) {
  const texto = String(valor || '').replace(/\s+/g, ' ').trim()
  if (texto.length <= tope) return texto
  const punto = texto.lastIndexOf('. ', tope)
  const corte = punto > tope / 2 ? punto : texto.lastIndexOf(' ', tope)
  return `${texto.slice(0, corte > 0 ? corte : tope).replace(/[\s,:;.]+$/, '')}…`
}

function condicionesDelTdr() {
  for (const dato of datosClave.value) {
    const casilla = CONDICION_DE[dato.clave]
    if (casilla && !extras.condiciones[casilla]) {
      extras.condiciones[casilla] = corto(textoLegible(dato.valor))
      marcarAuto(`condicion.${casilla}`, extras.condiciones[casilla])
    }
    if (casilla === 'plazo_entrega' && !extras.condiciones.plazo_ejecucion) {
      extras.condiciones.plazo_ejecucion = corto(textoLegible(dato.valor), 60)
      marcarAuto('condicion.plazo_ejecucion', extras.condiciones.plazo_ejecucion)
    }
  }
  // El código del proceso lleva el RUC de la entidad: NIC-0968570550001-2026-00042.
  const ruc = String(lectura.value?.codigo || codigo.value || '').match(/-(\d{13})-/)
  if (ruc && !extras.entidad.ruc) {
    extras.entidad.ruc = ruc[1]
    marcarAuto('entidad.ruc', ruc[1])
  }
  llenarEntidad(lectura.value?.entidad_datos)
}

/** El título que referencia a la ínfima: «Proforma — objeto · código». */
const tituloSugerido = computed(() => {
  const objeto = String(proforma.objeto || '').replace(/\s+/g, ' ').trim()
  const corto = objeto.length > 110 ? `${objeto.slice(0, objeto.lastIndexOf(' ', 110)).replace(/[\s,;:.]+$/, '')}…` : objeto
  const codigoProceso = String(lectura.value?.codigo || codigo.value || '').trim()
  const nombre = tipo.value === 'cotizacion' ? 'Cotización' : 'Proforma'
  return [corto ? `${nombre} — ${corto}` : nombre, codigoProceso].filter(Boolean).join(' · ').slice(0, 300)
})
const tituloTocado = ref(false)
// Los títulos que la empresa ya usó: cada proforma lleva uno distinto (el servidor también lo exige).
const titulosUsados = ref([])
const tituloLibreSugerido = computed(() => tituloLibre(tituloSugerido.value, titulosUsados.value))
const tituloEnUso = computed(() => tituloRepetido(proforma.titulo, titulosUsados.value))
const tituloAlternativo = computed(() => tituloLibre(proforma.titulo, titulosUsados.value))

watch(tituloLibreSugerido, (valor) => {
  if (!tituloTocado.value) proforma.titulo = valor
}, { immediate: true })

function usarTituloSugerido() {
  tituloTocado.value = false
  proforma.titulo = tituloLibreSugerido.value
}

function usarTituloAlternativo() {
  tituloTocado.value = true
  proforma.titulo = tituloAlternativo.value
}

async function cargarTitulosUsados() {
  try {
    const datos = await api.titulosProformas()
    titulosUsados.value = Array.isArray(datos?.titulos) ? datos.titulos : []
  } catch {
    // Sin la lista, el servidor sigue rechazando un título repetido al guardar.
  }
}

/** RUC, dirección y teléfono de la entidad, tal como los arma el backend desde la ficha publicada. */
function llenarEntidad(datos) {
  for (const campo of ['ruc', 'direccion', 'telefono']) {
    const valor = String(datos?.[campo] || '').trim()
    if (valor && !extras.entidad[campo]) {
      extras.entidad[campo] = valor
      marcarAuto(`entidad.${campo}`, valor)
    }
  }
}

/** El objeto de la contratación sale del resumen del TDR o de la ficha, si nadie lo escribió. */
function llenarObjeto(necesita) {
  if (proforma.objeto || !necesita) return
  proforma.objeto = objetoDe(necesita)
  marcarAuto('objeto', proforma.objeto)
}

/**
 * El objeto de la contratación en una línea. El TDR lo trae mezclado con párrafos enteros: se toma
 * el título entre comillas («ADQUISICIÓN DE REPUESTOS…») o, si no hay, el comienzo del texto.
 */
function objetoDe(texto) {
  const plano = String(texto || '').replace(/\s+/g, ' ').trim()
  const titulo = plano.match(/["“«]([^"”»]{10,300})["”»]/)
  if (titulo) return titulo[1].trim()
  // Sin título entre comillas: hasta donde empieza el siguiente campo del formulario («FECHA:»).
  const campo = plano.search(/\s[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{3,}:/)
  const recorte = campo > 20 ? plano.slice(0, campo) : plano
  if (recorte.length <= 280) return recorte
  return `${recorte.slice(0, 280).replace(/\s+\S*$/, '')}…`
}

/**
 * De «ya leí el TDR» a «solo faltan mis precios», sin pasos intermedios.
 *
 * Pasan solos a la proforma los ítems que pide la entidad (con su CPC, unidad y cantidad), los datos
 * de la empresa, las condiciones que el TDR trae con etiqueta y las respuestas a los requisitos. Todo
 * sale del TDR y del perfil; lo único que queda es el valor unitario de cada ítem. Lo que se arma con
 * la plantilla no gasta créditos de IA.
 */
function armarAutomatico() {
  return ejecutar(async () => {
    llenarObjeto(resumen.value?.necesita)
    condicionesDelTdr()
    llenarDesdeItems(false)
    if (!borrador.value) {
      aplicarBorrador(
        await api.generarOferta({
          lectura_id: lectura.value?.lectura_id || null,
          entidad: proforma.entidad,
          objeto: proforma.objeto,
          con_ia: false,
        }),
      )
    }
    reviso.value = true
    paso.value = 'documento'
    const total = itemsPedidos.value.length
    aviso.value = total
      ? `Armé tu proforma con los ${total} ${total === 1 ? 'ítem' : 'ítems'} del proceso, tus datos y lo que dice el TDR. Solo falta escribir tus precios.`
      : 'Armé tu proforma con tus datos y lo que dice el TDR. Este proceso no publica sus ítems: agrégalos con su CPC y escribe tus precios.'
    if (tipo.value === 'cotizacion') cargarCatalogo().catch((fallo) => (error.value = fallo.message))
  })
}

function completarProceso() {
  llenarObjeto(resumen.value?.necesita)
  condicionesDelTdr()
  paso.value = 'requisitos'
  aviso.value = ''
  cargarRequisitos().catch((fallo) => (error.value = fallo.message))
}

// Progreso del OCR de un escaneo o una foto. El OCR corre en este navegador (`utils/ocr.js`): el
// servidor solo recibe el texto, como un .txt, y lo lee igual que un TDR con texto.
const ocr = reactive({ activo: false, porcentaje: 0, pagina: 0, paginas: 0 })

async function textoPorOcr(elegido) {
  Object.assign(ocr, { activo: true, porcentaje: 0, pagina: 0, paginas: 0 })
  try {
    const { texto } = await textoDeArchivo(elegido, {
      onProgreso: (avance) => {
        ocr.porcentaje = Math.max(0, Math.min(100, Math.round(Number(avance?.porcentaje) || 0)))
        ocr.pagina = avance?.pagina || 0
        ocr.paginas = avance?.paginas || 0
      },
    })
    if (!String(texto || '').trim()) throw new Error('No encontré texto en el documento escaneado.')
    const base = String(elegido.name || 'documento').replace(/\.[^.]+$/, '') || 'documento'
    return new File([texto], `${base}.txt`, { type: 'text/plain' })
  } catch (fallo) {
    // Si el OCR no está o no pudo, se dice y el resto del asistente sigue: se puede traer el TDR
    // por su código o subir un PDF con texto.
    throw new Error(
      `${fallo?.message || 'No se pudo leer el escaneo.'} Sube un PDF con texto seleccionable o trae el TDR por su código.`,
    )
  } finally {
    ocr.activo = false
  }
}

/** Un PDF con texto va tal cual; una foto, o un PDF escaneado que el servidor no pudo leer, por OCR. */
async function leerArchivoSubido(elegido) {
  if (esImagen(elegido)) return { ...(await api.leerDocumento(await textoPorOcr(elegido))), uso_ocr: true }
  try {
    return await api.leerDocumento(elegido)
  } catch (fallo) {
    if (!/texto seleccionable|escaneo/i.test(fallo?.message || '')) throw fallo
    return { ...(await api.leerDocumento(await textoPorOcr(elegido))), uso_ocr: true }
  }
}

function leer() {
  return ejecutar(async () => {
    if (!archivo.value) throw new Error('Elige un PDF, una foto o un archivo de texto.')
    const resultado = await leerArchivoSubido(archivo.value)
    lectura.value = resultado
    resumen.value = resultado.resumen
    proceso.value = { codigo: '', entidad: '', archivo: archivo.value.name, documentos: [], anexos: [] }
    // Sin código del proceso, el RUC, la dirección y el teléfono de la entidad salen del propio TDR.
    llenarEntidad(resultado.entidad_datos)
    await cargarRequisitos()
    if (resultado.uso_ocr) {
      aviso.value =
        'Leímos el escaneo con OCR. Revisa cifras y fechas: el reconocimiento puede confundir caracteres.'
    }
  })
}

// Los sondeos se paran con la pestaña oculta y siguen al volver (ver `utils/sondeo.js`).
const esperar = esperarVisible

// Dónde va la bajada del TDR. Lo muestra la barra de progreso del paso 1.
const sondeo = reactive({ fase: '', enCola: 0, esperaLimite: 0 })
const proceso = ref(null)
let cancelado = false
onBeforeUnmount(() => {
  cancelado = true
  soltarVistaPdf()
})

/**
 * Repite una llamada que el servidor frenó por pedir demasiado rápido.
 *
 * Un 429 no es un error de la persona: es el servidor pidiendo un respiro. Se espera lo que dijo
 * (con la cuenta atrás a la vista) y se reintenta, en vez de enseñar «inténtalo en 91 segundos» y
 * dejar la tarea a medias.
 */
async function conReintento(llamada, { maxEspera = 60 } = {}) {
  for (let intento = 0; ; intento += 1) {
    try {
      return await llamada()
    } catch (fallo) {
      if (!fallo?.esLimite || intento >= 2 || fallo.esperaSeg > maxEspera) throw fallo
      for (let resta = Math.max(1, fallo.esperaSeg); resta > 0; resta -= 1) {
        if (cancelado) throw fallo
        sondeo.esperaLimite = resta
        await esperar(1000)
      }
      sondeo.esperaLimite = 0
    }
  }
}

/** Trae el TDR sin martillar al servidor: una petición, y luego preguntar el estado con calma. */
async function traerDelPortal(clave) {
  sondeo.fase = 'buscando'
  let resultado = await conReintento(() => api.prepararDesdeCodigo(clave, true))
  let pausa = 1500
  let limite = Date.now() + 120_000
  while (resultado.estado !== 'listo') {
    sondeo.fase = 'bajando'
    const antes = Date.now()
    await esperar(pausa)
    // El rato con la pestaña oculta no cuenta para el tope: no se preguntó nada mientras tanto.
    limite += Math.max(0, Date.now() - antes - pausa)
    if (cancelado) return null
    if (Date.now() > limite) {
      throw new Error('El TDR todavía no está listo. Vuelve a pulsar el botón en un minuto.')
    }
    const estado = await conReintento(() => api.estadoDesdeCodigo(clave))
    sondeo.enCola = estado.en_cola || 0
    if (estado.estado === 'error') throw new Error(estado.mensaje || 'No se pudo bajar el TDR.')
    if (estado.estado === 'listo') {
      sondeo.fase = 'leyendo'
      resultado = await conReintento(() => api.prepararDesdeCodigo(clave, false))
    }
    pausa = siguientePausa(pausa, { maximo: 4000 })
  }
  // El TDR ya está; los ítems (CPC, unidad, cantidad) los lee el worker con prioridad. Se espera un
  // poco: sin ellos la tabla de costos de la proforma empezaría vacía.
  const limiteItems = Date.now() + 40_000
  while (!resultado.items_leidos && Date.now() < limiteItems) {
    sondeo.fase = 'items'
    await esperar(2000)
    if (cancelado) return null
    const estado = await conReintento(() => api.estadoDesdeCodigo(clave))
    if (estado.items_listos) {
      resultado = await conReintento(() => api.prepararDesdeCodigo(clave, false))
      break
    }
  }
  return resultado
}

function pedirResumen() {
  return ejecutar(async () => {
    const clave = codigo.value.trim()
    if (!clave) {
      if (!lectura.value?.lectura_id) throw new Error('Escribe el código del proceso o sube el TDR.')
      resumen.value = (await api.resumenDocumento({ lectura_id: lectura.value.lectura_id })).resumen
      return
    }
    trayendo.value = true
    try {
      const resultado = await traerDelPortal(clave)
      if (!resultado) return
      lectura.value = resultado
      resumen.value = resultado.resumen
      proceso.value = {
        codigo: resultado.codigo,
        entidad: resultado.entidad,
        registroId: resultado.registro_id,
        documentos: resultado.documentos_lista || [],
        // TDR, pliegos, especificaciones y solo el acta más reciente: lo que se leyó para la proforma.
        anexos: resultado.anexos || [],
        items: resultado.items_pedidos || [],
      }
      llenarDesdeItems(false)
      llenarObjeto(resultado.resumen?.necesita)
      if (!proforma.entidad && resultado.entidad) {
        proforma.entidad = resultado.entidad
        marcarAuto('entidad', resultado.entidad)
      }
      llenarEntidad(resultado.entidad_datos)
      await aplicarEmpresa()
      await cargarRequisitos()
      sondeo.fase = 'listo'
    } finally {
      trayendo.value = false
    }
  })
}

const itemsPedidos = computed(() => proceso.value?.items || [])

/**
 * Los ítems que la entidad pide cotizar pasan a las líneas de la proforma, con su CPC, unidad y
 * cantidad. Solo falta el valor unitario, que lo escribe quien oferta. Sin `reemplazar`, no pisa
 * lo que la persona ya empezó a escribir.
 */
const sinTildes = (texto) =>
  String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ').trim().toLowerCase()

/**
 * Las características de cada ítem, tomadas de las especificaciones del TDR: la línea que nombra el
 * ítem y las viñetas que le siguen, hasta donde empieza el ítem siguiente. Sin coincidencia, nada.
 */
function especificacionesDe(item, items) {
  const texto = lectura.value?.secciones?.especificaciones || ''
  if (!texto) return ''
  const lineas = String(texto).split('\n').map((l) => l.trim()).filter(Boolean)
  const clave = (d) => sinTildes(d).slice(0, 40)
  const propia = clave(item.descripcion)
  if (propia.length < 6) return ''
  const otras = items.filter((o) => o !== item).map((o) => clave(o.descripcion)).filter((c) => c.length >= 6)
  const inicio = lineas.findIndex((l) => sinTildes(l).includes(propia))
  if (inicio < 0) return ''
  const detalle = []
  for (const linea of lineas.slice(inicio + 1, inicio + 16)) {
    const plano = sinTildes(linea)
    if (otras.some((o) => plano.includes(o))) break
    detalle.push(/^[•·\-–*]/.test(linea) ? linea.replace(/^[\-–*·]\s*/, '• ') : `• ${linea}`)
  }
  return detalle.join('\n')
}

function llenarDesdeItems(reemplazar) {
  const items = proceso.value?.items || []
  if (!items.length) return false
  const sinEmpezar = proforma.lineas.every(
    (linea) => !tieneTexto(linea.descripcion) && linea.precio_unitario === '',
  )
  if (!sinEmpezar && !reemplazar) return false
  proforma.lineas = items.map((item) => ({
    descripcion: [item.descripcion, especificacionesDe(item, items)].filter(Boolean).join('\n'),
    cantidad: item.cantidad || 1,
    unidad: item.unidad || '',
    precio_unitario: '',
    cpc: item.cpc || '',
    cpc_nombre: item.cpc_nombre || '',
  }))
  autollenado.add('lineas')
  return true
}

const dinero = (valor) => {
  const numero = Number(String(valor ?? '').replace(',', '.'))
  return Number.isFinite(numero) && String(valor).trim() !== '' ? `USD ${decimal(numero)}` : String(valor || '')
}

// El presupuesto que sacó el servidor del acta más reciente, la ficha o el TDR (en ese orden), con su
// fuente. Sin él, la proforma se puede generar igual: solo no hay contra qué medirla.
const presupuesto = computed(() => presupuestoValido(lectura.value?.presupuesto))
const textoPresupuesto = computed(() => {
  const p = presupuesto.value
  if (!p) return ''
  const iva = p.incluye_iva === true ? ' (incluye IVA)' : p.incluye_iva === false ? ' (no incluye IVA)' : ''
  return `${dinero(p.valor)}${iva} · fuente: ${p.etiqueta_fuente || lectura.value?.presupuesto_fuente || 'proceso'}`
})
const usoPresupuesto = computed(() =>
  tipo.value === 'proforma'
    ? usoDelPresupuesto(totalesPrevios.value, proforma.lineas, presupuesto.value)
    : null,
)

const bajandoAnexo = ref('')
async function bajarAnexo(anexo) {
  if (!anexo?.documento_id || !proceso.value?.registroId) return
  bajandoAnexo.value = anexo.documento_id
  error.value = ''
  try {
    const { contenido, nombre } = await api.archivoTdr(proceso.value.registroId, anexo.documento_id)
    guardarEnDisco(contenido, nombre || anexo.nombre)
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    bajandoAnexo.value = ''
  }
}

/** Lo que la entidad pide, en el orden en que se piensa una oferta. Solo lo que el TDR trae. */
const hechosDelProceso = computed(() => {
  const s = lectura.value?.secciones || {}
  const r = resumen.value || {}
  return [
    ['Qué necesita', r.necesita || s.objeto],
    ['Plazo de entrega', s.plazo_entrega || s.plazos],
    ['Forma de pago', s.forma_pago],
    ['Lugar de entrega', s.lugar_entrega],
    ['Garantía', s.garantia],
    ['Vigencia de la proforma', s.vigencia_proforma],
    ['Presupuesto referencial', textoPresupuesto.value || dinero(r.presupuesto || s.presupuesto)],
    ['Fechas', r.fechas],
  ]
    .map(([etiqueta, valor]) => [etiqueta, textoLegible(valor)])
    .filter(([, valor]) => valor)
    .map(([etiqueta, valor]) => ({ etiqueta, valor, largo: valor.length > 220 }))
})
// Un TDR real mezcla párrafos legales con los datos: se enseñan cuatro líneas y el resto se abre.
const expandido = reactive({})

// El detalle del TDR, sin repetir lo que ya está arriba.
const YA_MOSTRADAS = [
  'objeto', 'numero', 'plazo_entrega', 'plazos', 'forma_pago', 'lugar_entrega', 'garantia',
  'vigencia_proforma', 'presupuesto',
]
const detalleDelTdr = computed(() =>
  Object.entries(lectura.value?.secciones || {})
    .map(([clave, texto]) => [clave, textoLegible(texto)])
    .filter(([clave, texto]) => !YA_MOSTRADAS.includes(clave) && texto)
    .map(([clave, texto]) => ({
      clave,
      titulo: NOMBRES_SECCION[clave] || clave.replace(/_/g, ' '),
      texto,
      // Para la cabecera plegada: la primera frase, así se sabe de qué va sin abrirla.
      adelanto: corto(texto.split('\n')[0], 90),
    })),
)

const FASES = [
  { id: 'buscando', texto: 'Buscando el proceso' },
  { id: 'bajando', texto: 'Bajando el TDR del portal' },
  { id: 'leyendo', texto: 'Leyendo sus apartados' },
  { id: 'items', texto: 'Trayendo los ítems que pide la entidad' },
]
const faseActual = computed(() => FASES.findIndex((fase) => fase.id === sondeo.fase))

async function aplicarEmpresa() {
  const perfil = await api.verPerfil()
  ofertas.value = perfil.ofertas || []
  if (!tituloEmpresa.value) {
    tituloEmpresa.value = perfil.razon_social || perfil.nombre_comercial || perfil.nombre || ''
    marcarAuto('empresa', tituloEmpresa.value)
  }
  const contacto =
    (perfil.contactos || []).find((fila) => fila.principal) || (perfil.contactos || [])[0]
  if (contacto && !proforma.contacto) {
    proforma.contacto = [contacto.nombre, contacto.telefono, contacto.email].filter(Boolean).join(' · ')
    marcarAuto('contacto', proforma.contacto)
  }
  if (!ficha.nombre && ofertas.value[0]) llenarFicha(ofertas.value[0])
}

/** El catálogo da el nombre y las características ofertadas; lo requerido sale del TDR. */
function llenarFicha(fila) {
  ficha.nombre = fila.nombre || ''
  const ofertadas = lista(fila.descripcion).map((texto) => ({ requerido: '', ofertado: texto }))
  const requeridas = ficha.especificaciones.filter((espec) => tieneTexto(espec.requerido))
  ficha.especificaciones = requeridas.length ? requeridas : ofertadas
}

function empezarDesdeCodigo(codigoNuevo) {
  codigo.value = codigoNuevo
  lectura.value = null
  resumen.value = null
  proceso.value = null
  sondeo.fase = ''
  documento.value = null
  reviso.value = false
  proforma.entidad = ''
  proforma.objeto = ''
  proforma.contacto = ''
  proforma.lineas = [lineaVacia()]
  borrador.value = null
  extras.carta = ''
  extras.cumplimiento = []
  paso.value = 'proceso'
  // Otro proceso, otra entidad: el RUC, la dirección y las condiciones del anterior ya no valen.
  extras.entidad = { ruc: '', direccion: '', telefono: '' }
  // El título que se escribió a mano era de la otra ínfima: vuelve a la sugerencia.
  tituloTocado.value = false
  for (const { id } of CONDICIONES) extras.condiciones[id] = ''
  autollenado.clear()
  return pedirResumen()
}

async function cargarCreditos() {
  creditos.value = await api.verCreditos()
}

/** Pone el borrador en el formulario. Un precio ya escrito en la misma línea se conserva. */
function aplicarBorrador(datos) {
  if (datos.entidad && !proforma.entidad) {
    proforma.entidad = datos.entidad
    marcarAuto('entidad', datos.entidad)
  }
  if (datos.objeto) {
    proforma.objeto = datos.objeto
    marcarAuto('objeto', datos.objeto)
  }
  // Si la entidad publicó sus ítems, son ellos los que se cotizan: el borrador no los reemplaza.
  if (!itemsPedidos.value.length) {
    const previas = proforma.lineas
    proforma.lineas = (datos.lineas || []).map((linea, n) => ({
      descripcion: linea.descripcion,
      cantidad: linea.cantidad || 1,
      unidad: linea.unidad || '',
      precio_unitario: previas[n]?.descripcion === linea.descripcion ? previas[n].precio_unitario : '',
      cpc: '',
      cpc_nombre: '',
    }))
    if (!proforma.lineas.length) proforma.lineas = [lineaVacia()]
  }
  const empresa = datos.empresa || {}
  extras.empresa = empresa
  if (!tituloEmpresa.value && empresa.razon_social) tituloEmpresa.value = empresa.razon_social
  if (!proforma.contacto) {
    proforma.contacto = [empresa.representante, empresa.telefono, empresa.email]
      .filter(Boolean)
      .join(' · ')
    marcarAuto('contacto', proforma.contacto)
  }
  extras.carta = datos.carta || ''
  // Lo que el borrador no trae no borra lo que ya salió del TDR.
  for (const { id } of CONDICIONES) {
    const propuesta = datos.condiciones?.[id]
    if (propuesta) {
      extras.condiciones[id] = propuesta
      marcarAuto(`condicion.${id}`, propuesta)
    } else if (!condicionesDelTdrIds.value.has(id)) {
      extras.condiciones[id] = ''
    }
  }
  extras.experiencia = (datos.experiencia || []).join('\n')
  extras.personal = (datos.personal || []).join('\n')
  extras.equipo = (datos.equipo || []).join('\n')
  extras.cumplimiento = (datos.cumplimiento || []).map((fila) => ({ ...fila }))
  borrador.value = {
    origen: datos.origen,
    modelo: datos.modelo,
    faltantes: datos.faltantes || [],
  }
}

function armar(conIa) {
  return ejecutar(async () => {
    generando.value = conIa ? 'ia' : 'plantilla'
    aviso.value = conIa ? 'La IA está redactando tu oferta con los datos de tu empresa…' : ''
    try {
      const datos = await api.generarOferta({
        lectura_id: lectura.value?.lectura_id || null,
        entidad: proforma.entidad,
        objeto: proforma.objeto,
        con_ia: conIa,
      })
      aplicarBorrador(datos)
      if (datos.saldo != null && creditos.value) creditos.value.disponibles = datos.saldo
      aviso.value =
        datos.aviso ||
        (datos.origen === 'ia'
          ? 'Listo. La IA armó el borrador. Revísalo y escribe tus precios.'
          : 'Listo. El borrador salió del TDR y de tu empresa. Revísalo y escribe tus precios.')
    } catch (fallo) {
      if (fallo.codigo === 'sin_creditos') verCompras.value = true
      aviso.value = ''
      throw fallo
    } finally {
      generando.value = ''
    }
  })
}

/** Solo completa las respuestas vacías y añade los requisitos que falten. No toca precios ni carta. */
function responderConPlantilla() {
  return ejecutar(async () => {
    const datos = await api.generarOferta({
      lectura_id: lectura.value?.lectura_id || null,
      entidad: proforma.entidad,
      objeto: proforma.objeto,
      con_ia: false,
    })
    const propuestas = new Map(
      (datos.cumplimiento || []).map((fila) => [String(fila.requisito || '').trim(), fila.como_cumple]),
    )
    let completadas = 0
    for (const fila of extras.cumplimiento) {
      const propuesta = propuestas.get(String(fila.requisito || '').trim())
      if (propuesta && !tieneTexto(fila.como_cumple)) {
        fila.como_cumple = propuesta
        completadas += 1
      }
      propuestas.delete(String(fila.requisito || '').trim())
    }
    for (const [requisito, comoCumple] of propuestas) {
      extras.cumplimiento.push({ requisito, como_cumple: comoCumple || '' })
      completadas += 1
    }
    for (const { id } of CONDICIONES) {
      if (!tieneTexto(extras.condiciones[id]) && datos.condiciones?.[id]) {
        extras.condiciones[id] = datos.condiciones[id]
      }
    }
    if (!extras.empresa?.ruc && datos.empresa) extras.empresa = datos.empresa
    aviso.value = completadas
      ? `La plantilla completó ${completadas} respuestas. Revísalas: son tu declaración ante la entidad.`
      : 'No había respuestas vacías que la plantilla pudiera completar.'
  })
}

function comprar(codigoPaquete) {
  return ejecutar(async () => {
    const compra = await api.comprarCreditos(codigoPaquete)
    aviso.value = compra.mensaje
    await cargarCreditos()
  })
}

function lista(texto) {
  return String(texto || '')
    .split('\n')
    .map((fila) => fila.trim())
    .filter(Boolean)
}

function extrasParaGuardar() {
  const empresa = { ...extras.empresa }
  if (tituloEmpresa.value) empresa.razon_social = tituloEmpresa.value
  return {
    empresa,
    carta: extras.carta,
    codigo: String(lectura.value?.codigo || codigo.value || '').trim(),
    entidad: { ...extras.entidad },
    numero: extras.numero,
    necesidad: extras.necesidad,
    integridad: tipo.value === 'proforma' ? extras.integridad : false,
    condiciones: { ...extras.condiciones },
    experiencia: lista(extras.experiencia),
    personal: lista(extras.personal),
    equipo: lista(extras.equipo),
    cumplimiento: extras.cumplimiento.filter((fila) => String(fila.requisito || '').trim()),
    origen: borrador.value?.origen || 'manual',
    // Viaja con la proforma: el servidor la mide contra él y no la guarda si lo supera.
    presupuesto: presupuesto.value || undefined,
  }
}

async function cargarRequisitos() {
  const datos = await api.requisitosDocumento(lectura.value?.lectura_id)
  requisitos.value = datos.requisitos || []
}

function marcar(item, estado) {
  return ejecutar(async () => {
    await api.marcarRequisito(item.id, estado)
    item.estado = estado
  })
}

function continuarDocumento() {
  reviso.value = true
  paso.value = 'documento'
  aviso.value = 'Elige un solo documento. Al generarlo pasas a la descarga.'
  if (tipo.value === 'cotizacion') cargarCatalogo().catch((fallo) => (error.value = fallo.message))
}

function agregarLinea() {
  proforma.lineas.push(lineaVacia())
}

function quitarLinea(indiceLinea) {
  if (proforma.lineas.length > 1) proforma.lineas.splice(indiceLinea, 1)
}

function agregarCumple() {
  extras.cumplimiento.push({ requisito: '', como_cumple: '' })
}

function quitarCumple(indiceFila) {
  extras.cumplimiento.splice(indiceFila, 1)
}

/** Los requisitos del paso 2 que aún no están, en el mismo orden: R1 aquí es R1 allá. */
function traerRequisitos() {
  const presentes = new Set(extras.cumplimiento.map((fila) => String(fila.requisito || '').trim()))
  let nuevos = 0
  for (const item of requisitos.value) {
    if (presentes.has(item.texto.trim())) continue
    extras.cumplimiento.push({
      requisito: item.texto,
      como_cumple: item.estado === 'no_aplica' ? 'No aplica a esta contratación, tal como lo establece el propio TDR.' : '',
    })
    nuevos += 1
  }
  aviso.value = nuevos
    ? `Se añadieron ${nuevos} requisitos del TDR. Responde los que están en amarillo.`
    : 'Todos los requisitos del TDR ya están en la lista.'
}

function traerEspecificaciones() {
  const presentes = new Set(ficha.especificaciones.map((fila) => String(fila.requerido || '').trim()))
  const vacias = ficha.especificaciones.filter((fila) => !tieneTexto(fila.requerido) && !tieneTexto(fila.ofertado))
  for (const fila of vacias) ficha.especificaciones.splice(ficha.especificaciones.indexOf(fila), 1)
  let nuevos = 0
  for (const item of requisitos.value) {
    if (item.estado === 'no_aplica' || presentes.has(item.texto.trim())) continue
    ficha.especificaciones.push({ requerido: item.texto, ofertado: '' })
    nuevos += 1
  }
  aviso.value = nuevos
    ? `Se añadieron ${nuevos} especificaciones del TDR. Escribe lo que ofertas en cada una.`
    : 'No hay más requisitos del TDR para añadir.'
}

function agregarEspecificacion() {
  ficha.especificaciones.push({ requerido: '', ofertado: '' })
}

function quitarEspecificacion(indiceFila) {
  ficha.especificaciones.splice(indiceFila, 1)
}

function generar() {
  if (tipo.value === 'proforma') return guardarProforma()
  if (tipo.value === 'cotizacion') return guardarCotizacion()
  return guardarFicha()
}

function datosComunes() {
  return {
    entidad: proforma.entidad,
    objeto: proforma.objeto,
    contacto: proforma.contacto,
    impuesto_porcentaje: Number(proforma.impuesto_porcentaje),
    // El proceso del que sale la proforma. Sin él, «Mis ofertas» no sabe su código ni su cierre, y
    // el recordatorio del día antes no puede saltar.
    registro_id: lectura.value?.registro_id || null,
  }
}

/** Lo que le falta al documento según el servidor. Si no responde, la firma lo vuelve a comprobar. */
async function cargarVerificacion() {
  verificacion.value = null
  if (!documento.value || documento.value.tipo === 'Ficha técnica') return
  try {
    verificacion.value = await api.verificarDocumento(documento.value.id)
  } catch {
    verificacion.value = null
  }
}

const puedeFirmar = computed(() => !verificacion.value?.errores?.length)

const vistaPdf = reactive({ cargando: false, url: '', blob: null, cajas: [], error: '' })

function soltarVistaPdf() {
  if (vistaPdf.url) URL.revokeObjectURL(vistaPdf.url)
  Object.assign(vistaPdf, { cargando: false, url: '', blob: null, cajas: [], error: '' })
}

/**
 * El PDF lo arma **este navegador**: el servidor solo entrega los datos guardados. Así descargar,
 * previsualizar y volver a descargar no gastan CPU del servidor, que es lo que se agota primero con
 * pocas personas a la vez. La ficha técnica sigue maquetándose en el servidor.
 */
async function prepararPdf() {
  soltarVistaPdf()
  if (!documento.value || documento.value.tipo === 'Ficha técnica') return
  vistaPdf.cargando = true
  try {
    const guardado = await api.verDocumento(documento.value.id)
    const { blob, cajas } = await armarProformaPdf(guardado)
    vistaPdf.blob = blob
    vistaPdf.cajas = cajas
    vistaPdf.url = URL.createObjectURL(blob)
  } catch {
    vistaPdf.error = 'No se pudo armar la vista previa aquí. La descarga usará el servidor.'
  } finally {
    vistaPdf.cargando = false
  }
}

function dejarListo(creado, nombre, cifras) {
  documento.value = { id: creado.id, tipo: nombre, cifras }
  contraste.value = null
  paso.value = 'entrega'
  prepararPdf()
  cargarVerificacion()
  aviso.value = `${nombre} lista. Word sirve para seguir editándola. PDF sirve para enviarla.`
}

function guardarProforma() {
  return ejecutar(async () => {
    if (usoPresupuesto.value?.supera) {
      throw new Error('La proforma supera el presupuesto de la entidad. Baja los precios para poder generarla.')
    }
    if (proforma.lineas.some((linea) => !tieneTexto(linea.descripcion))) {
      throw new Error('Cada línea necesita la descripción del producto o servicio.')
    }
    const lineas = proforma.lineas.map((linea) => ({
      descripcion: linea.descripcion,
      cantidad: Number(linea.cantidad),
      unidad: linea.unidad || '',
      precio_unitario: linea.precio_unitario === '' ? null : Number(linea.precio_unitario),
      cpc: linea.cpc || '',
      cpc_nombre: linea.cpc_nombre || '',
    }))
    if (lineas.some((linea) => linea.precio_unitario === null)) {
      throw new Error('Cada línea necesita el precio unitario que tú confirmas.')
    }
    const titulo = (proforma.titulo || tituloLibreSugerido.value || 'Proforma').trim()
    if (tituloRepetido(titulo, titulosUsados.value)) {
      throw new Error(`Ya tienes una proforma con el título «${titulo}». Cámbialo en «Título de la proforma».`)
    }
    const creada = await api.crearProforma({
      ...datosComunes(),
      titulo,
      lineas,
      extras: extrasParaGuardar(),
    })
    titulosUsados.value = [...titulosUsados.value, creada.titulo || titulo]
    dejarListo(creada, 'Proforma', creada.cifras)
  })
}

function guardarCotizacion() {
  return ejecutar(async () => {
    const lineas = ofertas.value
      .filter((fila) => preciosCatalogo[fila.id] !== '' && preciosCatalogo[fila.id] != null)
      .map((fila) => ({
        descripcion: fila.nombre,
        cantidad: Number(cantidadesCatalogo[fila.id] || 1),
        precio_unitario: Number(preciosCatalogo[fila.id]),
      }))
    if (!lineas.length) throw new Error('Escribe el precio de al menos un producto del catálogo.')
    const titulo = (proforma.titulo || tituloLibreSugerido.value || 'Cotización').trim()
    if (tituloRepetido(titulo, titulosUsados.value)) {
      throw new Error(`Ya tienes una cotización con el título «${titulo}». Cámbialo en «Título».`)
    }
    const creada = await api.crearCotizacion({
      ...datosComunes(),
      titulo,
      objeto: proforma.objeto || 'Cotización de catálogo',
      lineas,
      extras: extrasParaGuardar(),
    })
    titulosUsados.value = [...titulosUsados.value, creada.titulo || titulo]
    dejarListo(creada, 'Cotización', creada.cifras)
  })
}

function guardarFicha() {
  return ejecutar(async () => {
    if (!tieneTexto(ficha.nombre)) throw new Error('Escribe el nombre del producto o servicio.')
    const empresa = { ...extras.empresa }
    if (tituloEmpresa.value) empresa.razon_social = tituloEmpresa.value
    const creada = await api.crearFicha({
      ...ficha,
      especificaciones: ficha.especificaciones.filter(
        (fila) => tieneTexto(fila.requerido) || tieneTexto(fila.ofertado),
      ),
      entidad: proforma.entidad,
      objeto: proforma.objeto,
      contacto: ficha.contacto || proforma.contacto,
      extras: { empresa },
    })
    dejarListo(creada, 'Ficha técnica', null)
  })
}

function contrastar() {
  return ejecutar(async () => {
    contraste.value = await api.contrastarDocumento(lectura.value.lectura_id, documento.value.id)
  })
}

/** Los fallos se cuentan dentro del chat: arriba de la página no los ve quien está preguntando. */
async function preguntar(texto) {
  const consulta = (texto ?? pregunta.value).trim()
  if (!consulta || pensando.value) return
  conversacion.value.push({ quien: 'usuario', texto: consulta })
  pregunta.value = ''
  pensando.value = true
  try {
    const respuesta = await api.preguntar(consulta, lectura.value?.lectura_id || null)
    conversacion.value.push({ quien: 'asistente', ...respuesta })
  } catch (fallo) {
    conversacion.value.push({ quien: 'asistente', texto: fallo.message, fallo: true })
  } finally {
    pensando.value = false
  }
}

// Revocar la URL en el mismo instante del clic cancelaba la descarga en algunos navegadores: el
// ayudante común espera a que termine de escribirse.
function guardarArchivo(bajado, nombre) {
  guardarEnDisco(bajado.contenido, bajado.nombre || nombre)
}

function bajar(formato) {
  return ejecutar(async () => {
    if (formato === 'pdf' && vistaPdf.blob) {
      guardarArchivo({ contenido: vistaPdf.blob, nombre: 'proforma.pdf' }, 'proforma.pdf')
      return
    }
    guardarArchivo(await api.bajarDocumento(documento.value.id, formato), `documento.${formato}`)
  })
}

function elegirCertificado(evento) {
  firma.archivo = evento.target.files?.[0] || null
}

function firmar() {
  return ejecutar(async () => {
    if (!firma.archivo) throw new Error('Elige tu archivo de firma (.p12 o .pfx).')
    if (!firma.clave) throw new Error('Escribe la clave de tu firma electrónica.')
    firmando.value = true
    try {
      const lugar = firma.lugar || extras.empresa?.ciudad || ''
      const firmado = vistaPdf.blob
        ? await api.firmarPdf(documento.value.id, vistaPdf.blob, vistaPdf.cajas, firma.archivo, firma.clave, lugar)
        : await api.firmarDocumento(documento.value.id, firma.archivo, firma.clave, lugar)
      guardarArchivo(firmado, 'documento-firmado.pdf')
      const recuadros = firmado.firmas > 1 ? ` en sus ${firmado.firmas} recuadros` : ''
      aviso.value = `PDF firmado${firmado.firmante ? ` por ${firmado.firmante}` : ''}${recuadros}. Tu certificado y tu clave no se guardaron.`
    } finally {
      firma.clave = ''
      firmando.value = false
    }
  })
}

function ir(id) {
  if (!disponible(id)) {
    error.value = motivoBloqueo(id)
    return
  }
  error.value = ''
  aviso.value = ''
  paso.value = id
  if (id === 'requisitos') cargarRequisitos().catch((fallo) => (error.value = fallo.message))
  if (id === 'documento' && tipo.value === 'cotizacion') {
    cargarCatalogo().catch((fallo) => (error.value = fallo.message))
  }
}

/** La acción «Siguiente» de cada paso. Es la principal y va siempre abajo a la derecha. */
const SIGUIENTE = {
  proceso: { texto: 'Siguiente: requisitos', hacer: () => completarProceso() },
  requisitos: { texto: 'Siguiente: armar mi proforma', hacer: () => armarAutomatico() },
  documento: { texto: 'Generar', hacer: () => generar() },
  entrega: { texto: 'Descargar PDF', hacer: () => bajar('pdf') },
}
const ANTERIOR = { requisitos: 'proceso', documento: 'requisitos', entrega: 'documento' }

const siguiente = computed(() => {
  const accion = SIGUIENTE[paso.value]
  let texto = accion.texto
  if (paso.value === 'documento') {
    texto = `Generar ${TIPOS.find((opcion) => opcion.id === tipo.value).etiqueta.toLowerCase()}`
  }
  const bloqueado =
    ocupado.value ||
    (paso.value === 'proceso' && !conoceProceso.value) ||
    (paso.value === 'documento' && tipo.value === 'cotizacion' && !ofertas.value.length) ||
    (paso.value === 'documento' && Boolean(usoPresupuesto.value?.supera))
  return { texto, bloqueado, hacer: accion.hacer }
})

function atras() {
  const anterior = ANTERIOR[paso.value]
  if (anterior) ir(anterior)
}

/** En la lista de requisitos, la casilla alterna entre cumplido y pendiente. */
function alternar(item) {
  return marcar(item, item.estado === 'cumplido' ? 'pendiente' : 'cumplido')
}

function elegirTipo(id) {
  tipo.value = id
  if (id === 'cotizacion') cargarCatalogo().catch((fallo) => (error.value = fallo.message))
}

async function cargarCatalogo() {
  if (ofertas.value.length) return
  const perfil = await api.verPerfil()
  ofertas.value = perfil.ofertas || []
}

function elegirArchivo(evento) {
  archivo.value = evento.target.files?.[0] || null
}

function usarOferta(fila) {
  llenarFicha(fila)
  tipo.value = 'ficha'
}

function fechaLegible(iso) {
  return iso ? new Date(iso).toLocaleString('es-EC') : ''
}

watch(
  () => props.marca,
  () => {
    if (props.codigoInicial) empezarDesdeCodigo(props.codigoInicial)
  },
  // La pestaña se monta al abrirse por primera vez, y la primera vez puede ser justo el «Llenar
  // TDR» de una ínfima: el código ya viene puesto y hay que atenderlo al montar.
  { immediate: true },
)

onMounted(() => {
  // Sin lectura no hay checklist que enseñar: el paso de requisitos se abre después de leer un TDR
  // o resumir un proceso, y ahí se piden los de esa lectura. Pedirlos al montar traía el checklist
  // de **todas** las lecturas de la empresa (medido: 6,8 MB) cada vez que se abría esta pestaña.
  if (lectura.value?.lectura_id) cargarRequisitos().catch(() => {})
  aplicarEmpresa().catch(() => {})
  cargarCreditos().catch(() => {})
  cargarTitulosUsados()
})
</script>

<template>
  <div class="docs">
    <header class="docs__cabecera">
      <div>
        <h2 class="docs__titulo">Preparar oferta</h2>
        <p class="docs__subtitulo">
          Del TDR a tu proforma en cuatro pasos. Lo que ya sabemos viene lleno; tú escribes tus precios.
        </p>
      </div>
      <span v-if="documento" class="etiqueta etiqueta--ok">{{ documento.tipo }} lista</span>
      <span v-else-if="lectura" class="etiqueta">TDR leído</span>
    </header>

    <nav class="asistente" aria-label="Pasos para preparar la oferta">
      <ol class="asistente__pasos">
        <li
          v-for="(opcion, posicion) in PASOS"
          :key="opcion.id"
          class="asistente__paso"
          :class="`asistente__paso--${estadoPaso(opcion.id)}`"
        >
          <button
            type="button"
            class="asistente__boton"
            :aria-current="paso === opcion.id ? 'step' : undefined"
            :aria-disabled="!disponible(opcion.id)"
            :title="disponible(opcion.id) ? '' : motivoBloqueo(opcion.id)"
            @click="ir(opcion.id)"
          >
            <span class="asistente__numero" aria-hidden="true">
              {{ estadoPaso(opcion.id) === 'hecho' ? '✓' : posicion + 1 }}
            </span>
            <span class="asistente__texto">
              <strong>{{ opcion.etiqueta }}</strong>
              <small>{{ opcion.resultado }}</small>
            </span>
          </button>
        </li>
      </ol>
    </nav>

    <p v-if="error" class="docs__mensaje docs__mensaje--error" role="alert">{{ error }}</p>
    <p v-if="aviso" class="docs__mensaje docs__mensaje--info" role="status">{{ aviso }}</p>

    <section class="docs__panel" aria-labelledby="docs-paso-titulo">
      <header class="docs__paso-cabecera">
        <p class="docs__paso-numero">Paso {{ indice + 1 }} de {{ PASOS.length }}</p>
        <h3 id="docs-paso-titulo">{{ PASOS[indice].etiqueta }}</h3>
        <p class="docs__nota">{{ PASOS[indice].ayuda }}</p>
      </header>

    <div v-if="paso === 'proceso'" class="docs__cuerpo">
      <form class="proceso__buscar" @submit.prevent="pedirResumen">
        <label>
          <span class="proceso__etiqueta">Código del proceso</span>
          <input
            v-model="codigo"
            placeholder="Ej. NIC-1768120280001-2026-00003"
            autocomplete="off"
            spellcheck="false"
            :disabled="trayendo"
          />
        </label>
        <button
          class="boton"
          :class="conoceProceso ? 'boton--secundario' : 'boton--principal'"
          type="submit"
          :disabled="ocupado || !codigo.trim()"
        >
          {{ trayendo ? 'Trayendo el TDR…' : conoceProceso ? 'Traer otro TDR' : 'Traer el TDR' }}
        </button>
      </form>

      <details class="proceso__subir">
        <summary>¿Ya tienes el archivo? Súbelo en lugar de bajarlo</summary>
        <form class="docs__subida" @submit.prevent="leer">
          <input
            type="file"
            accept=".pdf,.txt,application/pdf,text/plain,image/*"
            aria-describedby="docs-subida-ayuda"
            @change="elegirArchivo"
          />
          <button class="boton boton--secundario" type="submit" :disabled="ocupado || !archivo">
            {{ ocr.activo ? 'Leyendo el escaneo…' : ocupado && !trayendo ? 'Leyendo…' : 'Leer TDR' }}
          </button>
        </form>
        <p id="docs-subida-ayuda" class="docs__nota">
          PDF, texto o una foto del documento. Los escaneos y las fotos se leen con OCR en tu navegador.
        </p>
        <div v-if="ocr.activo" class="proceso__ocr" role="status" aria-live="polite">
          <span>
            Reconociendo el texto{{ ocr.paginas > 1 ? ` · página ${ocr.pagina || 1} de ${ocr.paginas}` : '' }}…
            {{ ocr.porcentaje }} %
          </span>
          <div class="docs__barra" aria-hidden="true"><span :style="{ width: `${ocr.porcentaje}%` }" /></div>
        </div>
      </details>

      <ol
        v-if="trayendo"
        class="proceso__progreso"
        aria-live="polite"
        aria-label="Progreso de la bajada del TDR"
      >
        <li
          v-for="(fase, n) in FASES"
          :key="fase.id"
          :class="{ 'es-hecha': n < faseActual, 'es-actual': n === faseActual }"
        >
          <span class="proceso__punto" aria-hidden="true">{{ n < faseActual ? '✓' : n + 1 }}</span>
          <span>
            {{ fase.texto }}
            <small v-if="fase.id === 'bajando' && sondeo.enCola > 1"> · {{ sondeo.enCola }} en la cola</small>
          </span>
        </li>
      </ol>
      <p v-if="trayendo && sondeo.esperaLimite" class="docs__mensaje docs__mensaje--info" role="status">
        Hay muchas consultas seguidas. Reintento en {{ sondeo.esperaLimite }} s…
      </p>

      <p v-if="!resumen && !trayendo" class="docs__vacio">
        Aún no hay un TDR. Escribe el código y pulsa «Traer el TDR», o súbelo si ya lo tienes.
      </p>

      <template v-if="resumen">
        <article class="proceso__ficha">
          <header>
            <p v-if="proceso?.codigo" class="proceso__codigo">{{ proceso.codigo }}</p>
            <p v-else-if="proceso?.archivo" class="proceso__codigo">{{ proceso.archivo }}</p>
            <h4 v-if="proceso?.entidad">{{ proceso.entidad }}</h4>
            <ul class="proceso__chips">
              <li class="proceso__chip proceso__chip--ok">TDR leído</li>
              <li v-if="itemsPedidos.length" class="proceso__chip">
                {{ itemsPedidos.length }} {{ itemsPedidos.length === 1 ? 'ítem' : 'ítems' }} a cotizar
              </li>
              <li v-if="requisitos.length" class="proceso__chip">
                {{ requisitos.length }} requisitos detectados
              </li>
              <li v-if="lectura?.cambios_acta?.length" class="proceso__chip">
                El acta más reciente corrige {{ lectura.cambios_acta.length }}
                {{ lectura.cambios_acta.length === 1 ? 'dato' : 'datos' }}
              </li>
            </ul>
          </header>
          <dl v-if="hechosDelProceso.length" class="proceso__hechos">
            <div
              v-for="dato in hechosDelProceso"
              :key="dato.etiqueta"
              :class="{ 'proceso__hecho--ancho': dato.largo }"
            >
              <dt>{{ dato.etiqueta }}</dt>
              <TextoTdr
                como="dd"
                :texto="dato.valor"
                :class="{ proceso__recorte: dato.largo && !expandido[dato.etiqueta] }"
              />
              <button
                v-if="dato.largo"
                type="button"
                class="proceso__mas"
                :aria-expanded="Boolean(expandido[dato.etiqueta])"
                @click="expandido[dato.etiqueta] = !expandido[dato.etiqueta]"
              >
                {{ expandido[dato.etiqueta] ? 'Ver menos' : 'Ver más' }}
              </button>
            </div>
          </dl>
          <p v-else class="docs__vacio">
            Este TDR no trae datos con etiqueta. Mira sus apartados abajo.
          </p>
        </article>

        <section v-if="itemsPedidos.length" class="proceso__items" aria-label="Ítems que pide la entidad">
          <h4>Lo que pide cotizar</h4>
          <ul>
            <li v-for="item in itemsPedidos" :key="item.numero">
              <span class="docs__num">{{ item.numero }}</span>
              <span class="proceso__item-texto">
                {{ item.descripcion }}
                <small>
                  {{ [item.cpc && `CPC ${item.cpc}`, item.cantidad && `${decimal(item.cantidad)} ${item.unidad || ''}`.trim()].filter(Boolean).join(' · ') }}
                </small>
              </span>
            </li>
          </ul>
        </section>

        <section v-if="detalleDelTdr.length" class="proceso__detalle" aria-label="Apartados del TDR">
          <h4>Apartados del TDR</h4>
          <details v-for="(parte, n) in detalleDelTdr" :key="parte.clave" :open="n < 1">
            <summary>
              <strong>{{ parte.titulo }}</strong>
              <small>{{ parte.adelanto }}</small>
            </summary>
            <TextoTdr :texto="parte.texto" />
          </details>
        </section>

        <section v-if="proceso?.anexos?.length" class="proceso__docs" aria-label="Anexos leídos">
          <h4>Anexos para la proforma</h4>
          <p class="docs__nota">
            Se leen todos los archivos de la ínfima (PDF, Word, Excel y ZIP) para armar la proforma. De
            las actas, solo la más reciente: corrige a las anteriores.
          </p>
          <ul>
            <li v-for="(anexo, n) in proceso.anexos" :key="`${anexo.nombre}-${n}`" class="proceso__anexo">
              <span class="proceso__icono proceso__icono--tipo">{{ anexo.etiqueta_tipo }}</span>
              <span class="proceso__anexo-nombre">
                {{ anexo.nombre }}
                <small v-if="anexo.leido">Leído</small>
                <small v-else-if="anexo.estado === 'pendiente'">Bajando…</small>
                <small v-else-if="anexo.estado === 'error'">No se pudo bajar</small>
                <small v-else-if="anexo.estado === 'sin_texto'" class="proceso__anexo-aviso">
                  No se pudo leer: {{ anexo.motivo }}
                </small>
              </span>
              <button
                v-if="anexo.documento_id"
                type="button"
                class="boton boton--fantasma boton--pequeno"
                :disabled="bajandoAnexo === anexo.documento_id"
                @click="bajarAnexo(anexo)"
              >
                {{ bajandoAnexo === anexo.documento_id ? 'Bajando…' : 'Descargar' }}
              </button>
            </li>
          </ul>
        </section>
        <section v-else-if="proceso?.documentos?.length" class="proceso__docs">
          <h4>Documentos del proceso</h4>
          <ul>
            <li v-for="(doc, n) in proceso.documentos" :key="n">
              <span class="proceso__icono" aria-hidden="true">{{ doc.tipo || 'DOC' }}</span>
              <span>{{ doc.nombre }}</span>
            </li>
          </ul>
        </section>

        <p class="docs__atajo">
          ¿Tienes prisa?
          <button type="button" class="docs__enlace" :disabled="ocupado" @click="armarAutomatico">
            Arma la proforma ya
          </button>
          y revisa los requisitos después.
        </p>
      </template>
    </div>

    <div v-if="paso === 'requisitos'" class="docs__cuerpo">
      <div v-if="avance.total" class="docs__avance">
        <span class="etiqueta">{{ avance.hechos }} de {{ avance.total }} marcados</span>
        <div class="docs__barra" aria-hidden="true">
          <span :style="{ width: `${avance.porcentaje}%` }" />
        </div>
      </div>
      <p v-if="!requisitos.length" class="docs__vacio">
        Este proceso no dejó requisitos para marcar. Pulsa «Siguiente» y arma la proforma.
      </p>
      <ul class="checklist" aria-label="Requisitos del TDR">
        <li
          v-for="(item, n) in requisitos"
          :key="item.id"
          class="checklist__item"
          :class="`checklist__item--${item.estado}`"
        >
          <label class="checklist__marca">
            <input
              type="checkbox"
              :checked="item.estado === 'cumplido'"
              :disabled="item.estado === 'no_aplica'"
              @click.prevent="alternar(item)"
            />
            <span class="docs__num">R{{ n + 1 }}</span>
            <TextoTdr como="span" class="checklist__texto" :texto="item.texto" />
          </label>
          <button
            type="button"
            class="checklist__no-aplica"
            :aria-pressed="item.estado === 'no_aplica'"
            @click="marcar(item, item.estado === 'no_aplica' ? 'pendiente' : 'no_aplica')"
          >
            No aplica
          </button>
        </li>
      </ul>
    </div>

    <div v-if="paso === 'documento'" class="docs__cuerpo">
      <p v-if="autollenado.size" class="docs__autollenado" role="status">
        <span class="docs__auto">autollenado · revisa</span>
        Llenamos {{ autollenado.size }} {{ autollenado.size === 1 ? 'dato' : 'datos' }} con tu perfil, la
        ficha del proceso y el TDR. Revísalos; lo que te toca es escribir tus precios.
      </p>
      <h4 class="docs__armar-titulo">Tipo de documento</h4>
      <div class="docs__tipos" role="radiogroup" aria-label="Tipo de documento">
        <button
          v-for="opcion in TIPOS"
          :key="opcion.id"
          type="button"
          class="docs__tipo"
          :class="{ 'docs__tipo--activo': tipo === opcion.id }"
          role="radio"
          :aria-checked="tipo === opcion.id"
          @click="elegirTipo(opcion.id)"
        >
          <strong>{{ opcion.etiqueta }}</strong>
          <small>{{ opcion.pista }}</small>
        </button>
      </div>

      <div v-if="tipo !== 'ficha'" class="docs__armar">
        <h4 class="docs__armar-titulo">¿Quieres que redactemos la carta y las respuestas?</h4>
        <div class="docs__opciones">
          <button type="button" class="docs__opcion" :disabled="ocupado" @click="armar(false)">
            <svg class="docs__opcion-icono" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 2h9l5 5v15H6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
              <path d="M15 2v5h5M9 12h8M9 16h8M9 8h3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
            <strong>{{ generando === 'plantilla' ? 'Armando…' : 'Rehacer sin IA' }}</strong>
            <small>Usa el TDR y los datos de tu empresa: carta, líneas, condiciones y una respuesta para cada requisito (R1, R2…). Gratis.</small>
          </button>
          <button type="button" class="docs__opcion docs__opcion--ia" :disabled="ocupado" @click="armar(true)">
            <svg class="docs__opcion-icono" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 20 15 9" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              <path d="m14 6 1-3 1 3 3 1-3 1-1 3-1-3-3-1zM19 13l.6-1.6L21 11l-1.4-.5L19 9l-.6 1.5L17 11l1.4.4zM8 4l.5-1.3L10 2l-1.5-.6L8 0l-.5 1.4L6 2l1.5.7z" fill="currentColor" />
            </svg>
            <strong>{{ generando === 'ia' ? 'Generando…' : 'Generar con IA' }}</strong>
            <small>
              Redacta la carta, las líneas y cómo cumples cada requisito con todos los datos de tu
              empresa. {{ creditos?.costos?.generar_oferta || 3 }} créditos.
            </small>
            <span v-if="creditos" class="docs__saldo">{{ creditos.ilimitado ? "IA sin límite (super admin)" : `${creditos.disponibles} créditos disponibles` }}</span>
          </button>
        </div>
        <p v-if="creditos && !creditos.ia_activa" class="docs__nota">
          La IA todavía no está conectada en el servidor. «Generar con IA» arma la oferta con la
          plantilla, sin gastar créditos.
        </p>
        <button type="button" class="boton boton--fantasma boton--pequeno docs__comprar" @click="verCompras = !verCompras">
          {{ verCompras ? 'Ocultar paquetes' : 'Comprar más créditos' }}
        </button>
        <div v-if="verCompras && creditos" class="docs__paquetes">
          <article v-for="paquete in creditos.paquetes" :key="paquete.codigo" class="docs__paquete">
            <strong>{{ paquete.nombre }}</strong>
            <span>{{ paquete.creditos }} créditos</span>
            <span class="docs__precio">$ {{ decimal(paquete.precio_usd) }}</span>
            <button type="button" class="boton boton--secundario boton--pequeno" :disabled="ocupado" @click="comprar(paquete.codigo)">
              Solicitar
            </button>
          </article>
          <p class="docs__nota">
            La compra queda pendiente hasta que se confirme el pago; entonces los créditos se suman solos.
          </p>
          <ul v-if="creditos.compras?.length" class="docs__compras">
            <li v-for="compra in creditos.compras" :key="compra.id">
              {{ compra.paquete }} · {{ compra.creditos }} créditos · {{ compra.estado }}
            </li>
          </ul>
        </div>
      </div>

      <div v-if="tipo !== 'ficha' && borrador?.faltantes?.length" class="docs__faltan" role="status">
        <p>
          <strong>Faltan datos de tu empresa.</strong> Puedes seguir: lo que falte no se imprime
          en la oferta.
        </p>
        <div class="docs__faltan-lista">
          <span v-for="dato in borrador.faltantes" :key="dato.etiqueta" class="docs__falta">{{ dato.etiqueta }}</span>
        </div>
        <button type="button" class="boton boton--secundario boton--pequeno" @click="emit('perfil')">
          Completar en Perfil de empresa
        </button>
      </div>

      <nav class="docs__control" aria-label="Lo que revisa la entidad">
        <strong>Lo que revisa la entidad</strong>
        <button
          v-for="punto in revision"
          :key="punto.id"
          type="button"
          class="docs__control-punto"
          :class="punto.ok ? 'docs__control-punto--ok' : 'docs__control-punto--falta'"
          @click="punto.id === 'empresa' && !punto.ok ? emit('perfil') : irA(BLOQUE_DE[punto.id] || punto.id)"
        >
          <span aria-hidden="true">{{ punto.ok ? '✓' : '!' }}</span>{{ punto.etiqueta }}
        </button>
      </nav>

      <section v-if="tipo !== 'ficha'" id="bloque-titulo" class="docs__bloque docs__bloque--titulo">
        <div class="formulario">
          <label v-if="tipo !== 'ficha'" class="formulario__campo formulario__campo--ancho">
            <span>
              <strong>Título de la proforma</strong> <small>(referente a la ínfima; sale en el PDF y en «Mis ofertas»)</small>
              <em v-if="!tituloTocado && proforma.titulo" class="docs__auto">sugerido · puedes cambiarlo</em>
            </span>
            <input
              v-model="proforma.titulo"
              maxlength="300"
              class="docs__titulo-input"
              :placeholder="tituloSugerido"
              :aria-invalid="tituloEnUso"
              @input="tituloTocado = true"
            />
            <span v-if="tituloEnUso" class="docs__titulo-repetido" role="alert">
              Ya tienes una proforma con este título y no se puede repetir.
              <button type="button" class="docs__enlace-chico" @click="usarTituloAlternativo">
                Usar «{{ tituloAlternativo }}»
              </button>
            </span>
            <button
              v-if="tituloTocado && proforma.titulo !== tituloLibreSugerido"
              type="button"
              class="docs__enlace-chico"
              @click="usarTituloSugerido"
            >
              Usar el título sugerido
            </button>
          </label>
        </div>
      </section>

      <section id="bloque-entidad" class="docs__bloque">
        <header class="docs__bloque-cabecera">
          <span class="docs__letra">1</span>
          <div>
            <h4>{{ tipo === 'ficha' ? 'Datos del proceso' : 'Destinatario y objeto' }}</h4>
            <small>A quién va dirigido y qué compra. Sale arriba del documento, con la fecha de emisión.</small>
          </div>
        </header>
        <div class="formulario">
          <label class="formulario__campo">
            <span>
              Tu empresa
              <em v-if="esAuto('empresa', tituloEmpresa)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="tituloEmpresa" placeholder="Razón social del perfil" />
          </label>
          <label class="formulario__campo" :class="{ 'docs__campo--falta': !proforma.entidad }">
            <span>
              Entidad contratante
              <em v-if="esAuto('entidad', proforma.entidad)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="proforma.entidad" placeholder="Ej. GAD Municipal de Quito" />
          </label>
          <label class="formulario__campo">
            <span>
              RUC de la entidad
              <em v-if="esAuto('entidad.ruc', extras.entidad.ruc)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="extras.entidad.ruc" type="text" inputmode="numeric" maxlength="13" placeholder="Sale del código de la ínfima o del TDR" />
          </label>
          <label class="formulario__campo">
            <span>
              Dirección de la entidad
              <em v-if="esAuto('entidad.direccion', extras.entidad.direccion)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="extras.entidad.direccion" type="text" />
          </label>
          <label class="formulario__campo">
            <span>
              Teléfono de la entidad
              <em v-if="esAuto('entidad.telefono', extras.entidad.telefono)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="extras.entidad.telefono" type="text" />
          </label>
          <label class="formulario__campo formulario__campo--ancho" :class="{ 'docs__campo--falta': !proforma.objeto }">
            <span>
              Objeto de contratación <small>(tal como lo dice el TDR)</small>
              <em v-if="esAuto('objeto', proforma.objeto)" class="docs__auto">autollenado · revisa</em>
            </span>
            <textarea v-model="proforma.objeto" rows="2" placeholder="Ej. Mantenimiento de impresoras" />
          </label>
          <label v-if="tipo !== 'ficha'" class="formulario__campo">
            <span>
              Contacto <small>(opcional)</small>
              <em v-if="esAuto('contacto', proforma.contacto)" class="docs__auto">autollenado · revisa</em>
            </span>
            <input v-model="proforma.contacto" placeholder="Nombre, teléfono, correo" />
          </label>
          <label v-if="tipo !== 'ficha'" class="formulario__campo">
            <span>IVA (%)</span>
            <input v-model.number="proforma.impuesto_porcentaje" type="number" min="0" max="100" />
          </label>
        </div>
      </section>

      <section v-if="tipo === 'proforma'" id="bloque-precios" class="docs__bloque docs__lineas">
        <header class="docs__bloque-cabecera">
          <span class="docs__letra">2</span>
          <div>
            <h4>Costos que pide la entidad</h4>
            <small>Un renglón por cada ítem del proceso, con su CPC, unidad y cantidad. Tú escribes el valor unitario.</small>
          </div>
        </header>
        <p v-if="itemsPedidos.length" class="docs__nota">
          <em v-if="autollenado.has('lineas')" class="docs__auto">autollenado · revisa</em>
          La entidad pide <strong>{{ itemsPedidos.length }}</strong>
          {{ itemsPedidos.length === 1 ? 'ítem' : 'ítems' }} con su CPC, unidad y cantidad; ya están en la
          tabla. Solo escribe el valor unitario.
          <button type="button" class="docs__enlace" @click="llenarDesdeItems(true)">
            Volver a traer los ítems de la entidad
          </button>
        </p>
        <p v-else class="docs__nota">
          Este proceso no publica sus ítems en el listado. Agrégalos a mano, con el CPC que pide el TDR.
        </p>
        <p class="docs__nota docs__nota--aviso">
          El precio no se inventa: lo escribes tú. Ni la plantilla ni la IA proponen importes. Con IVA en 0 %
          el PDF imprime solo el TOTAL, como el formulario del SOCE.
        </p>
        <div class="docs__tabla-lineas">
          <div class="docs__linea docs__linea--soce docs__linea--cabecera" aria-hidden="true">
            <span>No.</span><span>CPC</span><span>Descripción del producto</span><span>Unidad</span><span>Cantidad</span><span>Valor unitario ofertado</span><span>Valor total</span><span />
          </div>
          <div v-for="(linea, n) in proforma.lineas" :key="n" class="docs__linea docs__linea--soce">
            <span class="docs__num">{{ n + 1 }}</span>
            <span class="docs__cpc">
              <input v-model="linea.cpc" placeholder="CPC" maxlength="20" aria-label="CPC" />
              <small v-if="linea.cpc_nombre" :title="linea.cpc_nombre">{{ linea.cpc_nombre }}</small>
            </span>
            <textarea v-model="linea.descripcion" rows="2" placeholder="Producto o servicio que ofreces" aria-label="Descripción" />
            <input v-model="linea.unidad" placeholder="Unidad" aria-label="Unidad" maxlength="30" />
            <input v-model.number="linea.cantidad" type="number" min="0.01" step="0.01" aria-label="Cantidad" />
            <input
              v-model="linea.precio_unitario"
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              aria-label="Valor unitario ofertado"
              :class="{ 'docs__entrada--falta': linea.precio_unitario === '' }"
            />
            <span class="docs__subtotal">
              {{ linea.precio_unitario === '' ? '—' : decimal(Number(linea.precio_unitario) * Number(linea.cantidad || 0)) }}
            </span>
            <button type="button" class="boton boton--fantasma boton--icono" :disabled="proforma.lineas.length === 1" aria-label="Quitar línea" @click="quitarLinea(n)">✕</button>
          </div>
        </div>
        <div class="docs__pie">
          <button type="button" class="boton boton--secundario boton--pequeno" @click="agregarLinea">+ Añadir línea</button>
          <dl class="docs__totales">
            <div><dt>Subtotal</dt><dd>{{ decimal(totalesPrevios.subtotal) }}</dd></div>
            <div v-if="Number(proforma.impuesto_porcentaje) > 0">
              <dt>IVA {{ proforma.impuesto_porcentaje }} %</dt><dd>{{ decimal(totalesPrevios.impuesto) }}</dd>
            </div>
            <div class="docs__total"><dt>TOTAL</dt><dd>{{ decimal(totalesPrevios.total) }}</dd></div>
          </dl>
        </div>
        <div class="docs__presupuesto" aria-label="Presupuesto de la entidad">
          <template v-if="usoPresupuesto">
            <p class="docs__presupuesto-cabecera">
              <span>Presupuesto de la entidad: <strong>{{ textoPresupuesto }}</strong></span>
              <span class="docs__presupuesto-uso">
                Usas {{ decimal(usoPresupuesto.comparado) }} {{ usoPresupuesto.base }} ·
                {{ Math.round(usoPresupuesto.porcentaje) }} %
              </span>
            </p>
            <div
              class="docs__barra docs__barra--presupuesto"
              role="meter"
              aria-label="Parte del presupuesto que usa la proforma"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-valuenow="Math.round(usoPresupuesto.ancho)"
            >
              <span :style="{ width: `${usoPresupuesto.ancho}%` }" />
            </div>
            <p v-if="usoPresupuesto.supera" class="docs__presupuesto-error" role="alert">
              Supera el presupuesto en USD {{ decimal(usoPresupuesto.exceso) }}. Baja los precios para poder
              generar la proforma: una oferta por encima del presupuesto no se puede adjudicar.
            </p>
            <p v-else class="docs__nota">Te quedan USD {{ decimal(usoPresupuesto.restante) }} hasta el presupuesto.</p>
            <p v-for="texto in usoPresupuesto.avisos" :key="texto" class="docs__nota docs__nota--aviso">{{ texto }}</p>
          </template>
          <p v-else class="docs__nota">
            No conocemos el presupuesto de este proceso: ni la ficha ni los anexos lo publican. Revisa el TDR;
            puedes generar la proforma igual.
          </p>
        </div>
      </section>

      <section v-if="tipo === 'cotizacion'" id="bloque-precios" class="docs__bloque docs__catalogo">
        <header class="docs__bloque-cabecera">
          <span class="docs__letra">2</span>
          <div>
            <h4>Productos del catálogo y precios</h4>
            <small>Escribe el precio unitario sin IVA de lo que vas a cotizar. Lo que quede sin precio no sale.</small>
          </div>
        </header>
        <p v-if="!ofertas.length" class="docs__vacio">
          El catálogo está vacío. Agrega productos en Mi empresa, o elige Proforma y escribe las líneas aquí.
        </p>
        <div v-for="fila in ofertas" :key="fila.id" class="docs__producto">
          <div>
            <strong>{{ fila.nombre }}</strong>
            <small v-if="fila.descripcion">{{ fila.descripcion }}</small>
          </div>
          <input v-model.number="cantidadesCatalogo[fila.id]" type="number" min="1" placeholder="Cant." aria-label="Cantidad" />
          <input v-model="preciosCatalogo[fila.id]" type="number" min="0" step="0.01" placeholder="Precio" aria-label="Precio unitario" />
          <button type="button" class="boton boton--fantasma boton--pequeno" @click="usarOferta(fila)">Ficha</button>
        </div>
      </section>

      <template v-if="tipo !== 'ficha'">
        <section id="bloque-condiciones" class="docs__bloque">
          <header class="docs__bloque-cabecera">
            <span class="docs__letra">3</span>
            <div>
              <h4>Condiciones de la oferta</h4>
              <small>
                La entidad pide siempre vigencia (mínimo 45 días), plazo, forma de pago y lugar de
                entrega. Las marcadas en amarillo faltan.
              </small>
            </div>
          </header>
          <div class="formulario">
            <label
              v-for="item in CONDICIONES"
              :key="item.id"
              class="formulario__campo"
              :class="{ 'docs__campo--falta': CONDICIONES_SERCOP.includes(item.id) && !extras.condiciones[item.id] }"
            >
              <span>
                {{ item.etiqueta }}
                <small v-if="CONDICIONES_SERCOP.includes(item.id)">(obligatoria)</small>
                <em v-if="esAuto(`condicion.${item.id}`, extras.condiciones[item.id])" class="docs__auto">
                  autollenado · revisa
                </em>
              </span>
              <textarea v-model="extras.condiciones[item.id]" rows="2" :placeholder="item.pista" />
            </label>
          </div>
          <div class="formulario">
            <label class="formulario__campo">
              <span>Nº de proforma <small>(el tuyo, ej. PFA-02-050-2026)</small></span>
              <input v-model="extras.numero" type="text" />
            </label>
            <label class="formulario__campo">
              <span>Código de la necesidad de contratación <small>(NC-…, si el proceso la tiene)</small></span>
              <input v-model="extras.necesidad" type="text" />
            </label>
          </div>
          <label v-if="tipo === 'proforma'" class="docs__integridad">
            <input v-model="extras.integridad" type="checkbox" />
            <span>
              Incluir el <strong>Formulario de Perfil de Integridad del Proveedor</strong>
              (Anexo I, Resolución R.E-SERCOP-2026-0005). Se agrega al final del PDF con su propio
              recuadro de firma. Las fuentes oficiales que revisé no confirman que se exija en la
              ínfima cuantía: <strong>pregunta a la entidad</strong> y quítalo si no lo pide.
            </span>
          </label>
        </section>

        <section id="bloque-respuestas" class="docs__bloque">
          <header class="docs__bloque-cabecera">
            <span class="docs__letra">4</span>
            <div>
              <h4>Respuestas al TDR</h4>
              <small>
                Cada requisito con su número (R1, R2…) y cómo lo cumples. Si el TDR dice que no
                aplica, escríbelo. Se imprime como tabla en el PDF.
              </small>
            </div>
            <span class="etiqueta" :class="respuestas.total && respuestas.hechas === respuestas.total ? 'etiqueta--ok' : ''">
              {{ respuestas.hechas }} de {{ respuestas.total }} respondidos
            </span>
          </header>
          <div v-if="respuestas.total" class="docs__barra" aria-hidden="true">
            <span :style="{ width: `${respuestas.porcentaje}%` }" />
          </div>
          <div class="docs__acciones">
            <button
              type="button"
              class="boton boton--secundario boton--pequeno"
              :disabled="!requisitos.length"
              :title="requisitos.length ? '' : 'Este proceso no dejó requisitos en el paso 2'"
              @click="traerRequisitos"
            >
              Traer los requisitos del paso 2
            </button>
            <button type="button" class="boton boton--secundario boton--pequeno" :disabled="ocupado" @click="responderConPlantilla">
              Completar las vacías con la plantilla
            </button>
            <label v-if="respuestas.total" class="docs__interruptor">
              <input v-model="soloPendientes" type="checkbox" />
              Ver solo los que faltan
            </label>
          </div>
          <p v-if="!extras.cumplimiento.length" class="docs__vacio">
            Todavía no hay requisitos. Tráelos del paso 2, pulsa «Armar sin IA» o «Generar con IA»
            arriba, o añádelos uno a uno.
          </p>
          <template v-for="(fila, n) in extras.cumplimiento" :key="n">
            <article
              v-if="!soloPendientes || !fila.como_cumple"
              class="docs__cumple-fila"
              :class="fila.como_cumple ? 'docs__cumple-fila--ok' : 'docs__cumple-fila--falta'"
            >
              <div class="docs__cumple-cabecera">
                <span class="docs__num">R{{ n + 1 }}</span>
                <span class="docs__cumple-estado">{{ fila.como_cumple ? 'Respondido' : 'Falta tu respuesta' }}</span>
                <button type="button" class="boton boton--fantasma boton--pequeno" @click="quitarCumple(n)">Quitar</button>
              </div>
              <label class="formulario__campo formulario__campo--ancho">
                <span>Lo que pide el TDR</span>
                <textarea v-model="fila.requisito" rows="2" placeholder="Pega o escribe el requisito" />
              </label>
              <label class="formulario__campo formulario__campo--ancho">
                <span>Cómo lo cumples</span>
                <textarea
                  v-model="fila.como_cumple"
                  rows="3"
                  placeholder="Ej. Aceptamos el plazo de 10 días. Si el TDR dice que no aplica, escríbelo aquí."
                />
              </label>
            </article>
          </template>
          <button type="button" class="boton boton--secundario boton--pequeno docs__izquierda" @click="agregarCumple">
            + Añadir requisito
          </button>
        </section>

        <details id="bloque-experiencia" class="docs__bloque docs__plegable">
          <summary class="docs__bloque-cabecera">
            <span class="docs__letra">5</span>
            <div>
              <h4>Experiencia, personal y equipo</h4>
              <small>Solo si el TDR los pide. Una por línea. Lo vacío no se imprime.</small>
            </div>
          </summary>
          <div class="formulario">
            <label class="formulario__campo">
              <span>Experiencia relevante</span>
              <textarea v-model="extras.experiencia" rows="4" placeholder="Objeto · Entidad · Año" />
            </label>
            <label class="formulario__campo">
              <span>Personal técnico</span>
              <textarea v-model="extras.personal" rows="4" placeholder="Nombre · Cargo · Título" />
            </label>
            <label class="formulario__campo">
              <span>Equipo disponible</span>
              <textarea v-model="extras.equipo" rows="4" placeholder="Equipo · Cantidad" />
            </label>
          </div>
        </details>

        <details id="bloque-carta" class="docs__bloque docs__plegable" :open="!extras.carta">
          <summary class="docs__bloque-cabecera">
            <span class="docs__letra">6</span>
            <div>
              <h4>Carta de presentación</h4>
              <small>{{ extras.carta ? 'Ya redactada. Ábrela para revisarla.' : 'Opcional. La redactan la plantilla o la IA, o la escribes tú.' }}</small>
            </div>
          </summary>
          <textarea
            v-model="extras.carta"
            rows="8"
            placeholder="Pulsa «Armar sin IA» o «Generar con IA» para redactarla, o escríbela aquí."
          />
        </details>
      </template>

      <template v-else>
        <section id="bloque-bien" class="docs__bloque">
          <header class="docs__bloque-cabecera">
            <span class="docs__letra">2</span>
            <div>
              <h4>Identificación del bien o servicio</h4>
              <small>Marca, modelo, país de origen y garantía: la entidad los compara con el TDR.</small>
            </div>
          </header>
          <div class="formulario">
            <label class="formulario__campo" :class="{ 'docs__campo--falta': !ficha.nombre }">
              <span>Producto o servicio</span>
              <input v-model="ficha.nombre" placeholder="Ej. Impresora láser monocromática" />
            </label>
            <label class="formulario__campo" :class="{ 'docs__campo--falta': !ficha.marca }">
              <span>Marca</span>
              <input v-model="ficha.marca" placeholder="Ej. HP" />
            </label>
            <label class="formulario__campo" :class="{ 'docs__campo--falta': !ficha.modelo }">
              <span>Modelo</span>
              <input v-model="ficha.modelo" placeholder="Ej. LaserJet M404dn" />
            </label>
            <label class="formulario__campo" :class="{ 'docs__campo--falta': !ficha.pais_origen }">
              <span>País de origen</span>
              <input v-model="ficha.pais_origen" placeholder="Ej. China" />
            </label>
            <label class="formulario__campo">
              <span>Año de fabricación <small>(bienes)</small></span>
              <input v-model="ficha.anio_fabricacion" placeholder="Ej. 2025" maxlength="20" />
            </label>
            <label class="formulario__campo">
              <span>Código CPC <small>(opcional)</small></span>
              <input v-model="ficha.cpc" placeholder="Ej. 452200011" maxlength="40" />
            </label>
            <label class="formulario__campo formulario__campo--ancho" :class="{ 'docs__campo--falta': !ficha.garantia }">
              <span>Garantía técnica</span>
              <input v-model="ficha.garantia" placeholder="Ej. 12 meses por defectos de fábrica, con servicio técnico en Quito" />
            </label>
            <label class="formulario__campo formulario__campo--ancho">
              <span>Contacto para consultas técnicas <small>(opcional)</small></span>
              <input v-model="ficha.contacto" placeholder="Nombre, teléfono, correo" />
            </label>
          </div>
        </section>

        <section id="bloque-especificaciones" class="docs__bloque">
          <header class="docs__bloque-cabecera">
            <span class="docs__letra">3</span>
            <div>
              <h4>Especificaciones técnicas</h4>
              <small>
                A la izquierda lo que pide la entidad; a la derecha lo que ofertas. Omitir una
                especificación es causal de rechazo.
              </small>
            </div>
            <span class="etiqueta" :class="especificado.total && especificado.hechas === especificado.total ? 'etiqueta--ok' : ''">
              {{ especificado.hechas }} de {{ especificado.total }} ofertadas
            </span>
          </header>
          <div class="docs__acciones">
            <button
              type="button"
              class="boton boton--secundario boton--pequeno"
              :disabled="!requisitos.length"
              :title="requisitos.length ? '' : 'Este proceso no dejó requisitos en el paso 2'"
              @click="traerEspecificaciones"
            >
              Traer los requisitos del paso 2
            </button>
          </div>
          <p v-if="!ficha.especificaciones.length" class="docs__vacio">
            Sin especificaciones. Tráelas del TDR o añádelas una a una.
          </p>
          <article
            v-for="(fila, n) in ficha.especificaciones"
            :key="n"
            class="docs__espec"
            :class="fila.ofertado ? 'docs__cumple-fila--ok' : 'docs__cumple-fila--falta'"
          >
            <span class="docs__num">E{{ n + 1 }}</span>
            <label class="formulario__campo">
              <span>Requerido por la entidad</span>
              <textarea v-model="fila.requerido" rows="2" placeholder="Lo que dice el TDR (opcional)" />
            </label>
            <label class="formulario__campo">
              <span>Lo que ofertas</span>
              <textarea v-model="fila.ofertado" rows="2" placeholder="Ej. 40 ppm, dúplex automático" />
            </label>
            <button type="button" class="boton boton--fantasma boton--icono" aria-label="Quitar especificación" @click="quitarEspecificacion(n)">✕</button>
          </article>
          <button type="button" class="boton boton--secundario boton--pequeno docs__izquierda" @click="agregarEspecificacion">
            + Añadir especificación
          </button>
        </section>
      </template>

    </div>

    <div v-if="paso === 'entrega'" class="docs__cuerpo">
      <div v-if="documento?.cifras" class="docs__cifras">
        Subtotal {{ decimal(documento.cifras.subtotal) }} · IVA {{ decimal(documento.cifras.impuesto) }} ·
        Total {{ decimal(documento.cifras.total) }}
      </div>
      <section
        v-if="verificacion"
        class="docs__verificacion"
        :class="verificacion.errores.length ? 'docs__verificacion--falta' : 'docs__verificacion--lista'"
        aria-live="polite"
      >
        <h4>
          {{ verificacion.errores.length
            ? `Faltan ${verificacion.errores.length} dato(s) para enviarla`
            : 'La oferta tiene lo que una entidad revisa' }}
        </h4>
        <ul v-if="verificacion.errores.length">
          <li v-for="fila in verificacion.errores" :key="fila.codigo + fila.texto">{{ fila.texto }}</li>
        </ul>
        <ul v-if="verificacion.avisos.length" class="docs__verificacion-avisos">
          <li v-for="fila in verificacion.avisos" :key="fila.codigo + fila.texto">{{ fila.texto }}</li>
        </ul>
        <button
          v-if="verificacion.errores.length"
          class="boton boton--secundario"
          type="button"
          @click="ir('documento')"
        >
          Corregir en el documento
        </button>
      </section>
      <section v-if="documento?.tipo !== 'Ficha técnica'" class="docs__previa" aria-label="Vista previa del PDF">
        <p v-if="vistaPdf.cargando" class="docs__nota" role="status">Armando el PDF en tu navegador…</p>
        <p v-else-if="vistaPdf.error" class="docs__nota docs__nota--aviso">{{ vistaPdf.error }}</p>
        <iframe v-if="vistaPdf.url" class="docs__marco" :src="vistaPdf.url" title="Vista previa de tu proforma" />
      </section>
      <div class="docs__bajar">
        <button type="button" class="boton boton--secundario" :disabled="ocupado" @click="bajar('docx')">
          Descargar Word
        </button>
        <small class="docs__nota">
          PDF para enviarla tal como quedó (botón de abajo); Word si vas a corregir textos o precios.
        </small>
      </div>

      <details class="docs__firma docs__plegable">
        <summary><h4>Firmar con tu firma electrónica <small>(opcional en la proforma)</small></h4></summary>
      <form class="docs__firma-form" autocomplete="off" @submit.prevent="firmar">
        <p class="docs__nota">
          En la ínfima cuantía la firma electrónica es exigible en la orden de compra o la factura;
          en la proforma es opcional. Si firmas, el sello de FirmaEC queda en <strong>cada recuadro
          de firma</strong> del PDF: uno por requisito del TDR, el final y el del formulario de
          integridad.
        </p>
        <p class="docs__nota">
          Sirve el archivo .p12 o .pfx de FirmaEC, Security Data, ANF, Banco Central o cualquier
          entidad acreditada. Se usa solo para firmar este PDF: el certificado y la clave no se
          guardan.
        </p>
        <div class="formulario">
          <label class="formulario__campo">
            <span>Archivo de firma (.p12 / .pfx)</span>
            <input type="file" accept=".p12,.pfx,application/x-pkcs12" @change="elegirCertificado" />
          </label>
          <label class="formulario__campo">
            <span>Clave de la firma</span>
            <input v-model="firma.clave" type="password" autocomplete="new-password" placeholder="La clave de tu certificado" />
          </label>
          <label class="formulario__campo">
            <span>Lugar <small>(opcional)</small></span>
            <input v-model="firma.lugar" :placeholder="extras.empresa?.ciudad || 'Ej. Quito'" maxlength="80" />
          </label>
        </div>
        <div class="docs__pie-paso">
          <button
            class="boton boton--secundario"
            type="submit"
            :disabled="ocupado || !firma.archivo || !firma.clave || !puedeFirmar"
            :title="puedeFirmar ? '' : 'Completa los datos que faltan antes de firmar.'"
          >
            {{ firmando ? 'Firmando…' : 'Firmar y descargar PDF' }}
          </button>
        </div>
      </form>
      </details>

      <div v-if="documento?.tipo !== 'Ficha técnica'" class="docs__revision">
        <h4>¿Responde al TDR?</h4>
        <p class="docs__nota">Opcional. Compara lo que escribiste con los requisitos del TDR leído.</p>
        <button class="boton boton--secundario" type="button" :disabled="ocupado || !lectura" @click="contrastar">
          Comparar con el TDR
        </button>
        <p v-if="!lectura" class="docs__vacio">Hace falta haber subido el TDR en el paso 1.</p>
        <div v-if="contraste" class="docs__contraste">
          <article class="docs__columna docs__columna--ok">
            <h4>Cubiertos ({{ contraste.cubiertos.length }})</h4>
            <ul><li v-for="texto in contraste.cubiertos" :key="texto">{{ texto }}</li></ul>
          </article>
          <article class="docs__columna docs__columna--error">
            <h4>No cubiertos ({{ contraste.no_cubiertos.length }})</h4>
            <ul><li v-for="texto in contraste.no_cubiertos" :key="texto">{{ texto }}</li></ul>
          </article>
          <article class="docs__columna docs__columna--aviso">
            <h4>Inconsistencias ({{ contraste.inconsistencias.length }})</h4>
            <ul><li v-for="texto in contraste.inconsistencias" :key="texto">{{ texto }}</li></ul>
          </article>
        </div>
        <p v-if="contraste" class="docs__nota">{{ contraste.observaciones }}</p>
      </div>
    </div>

      <footer class="asistente__pie" :class="{ 'asistente__pie--fijo': paso === 'documento' }">
        <button v-if="ANTERIOR[paso]" class="boton boton--secundario" type="button" @click="atras">
          <span aria-hidden="true">←</span> Atrás
        </button>
        <span class="asistente__estado">
          <template v-if="paso === 'proceso'">
            {{ conoceProceso ? 'TDR leído. Sigue cuando quieras.' : 'Trae el TDR para seguir.' }}
          </template>
          <template v-else-if="paso === 'requisitos'">
            {{ avance.total ? `${avance.hechos} de ${avance.total} marcados. Puedes seguir igual.` : '' }}
          </template>
          <template v-else-if="paso === 'documento' && usoPresupuesto?.supera">
            Supera el presupuesto de la entidad: baja los precios para generar.
          </template>
          <template v-else-if="paso === 'documento'">
            {{ revision.filter((punto) => !punto.ok).length
              ? `${revision.filter((punto) => !punto.ok).length} punto(s) por revisar. Puedes generar igual.`
              : 'Todo listo para la entidad.' }}
          </template>
          <template v-else>Guardada en «Mis ofertas».</template>
        </span>
        <button
          class="boton boton--principal"
          type="button"
          :disabled="siguiente.bloqueado"
          @click="siguiente.hacer"
        >
          {{ ocupado && paso !== 'entrega' ? 'Un momento…' : siguiente.texto }}
          <span v-if="paso !== 'entrega'" aria-hidden="true">→</span>
        </button>
      </footer>
    </section>

    <details class="docs__ayuda">
      <summary>Asistente del TDR. Pregunta por plazos, requisitos, entregables o forma de pago.</summary>
      <div class="docs__ejemplos">
        <button v-for="ejemplo in EJEMPLOS" :key="ejemplo" type="button" class="docs__chip" :disabled="pensando" @click="preguntar(ejemplo)">
          {{ ejemplo }}
        </button>
      </div>
      <div class="docs__chat" aria-live="polite">
        <p v-if="!conversacion.length" class="docs__vacio">
          {{ lectura ? 'El TDR ya está leído: pregúntame lo que quieras de él.' : 'Trae el TDR en el paso 1 y pregúntame por él.' }}
        </p>
        <div
          v-for="(mensaje, n) in conversacion"
          :key="n"
          :class="['docs__burbuja', `docs__burbuja--${mensaje.quien}`, { 'docs__burbuja--fallo': mensaje.fallo }]"
        >
          <p class="docs__texto">{{ mensaje.texto || mensaje.respuesta }}</p>
          <ul v-if="mensaje.datos?.length">
            <li v-for="(dato, posicion) in mensaje.datos" :key="posicion">
              {{ typeof dato === 'string' ? dato : dato.texto || dato.necesita || JSON.stringify(dato) }}
            </li>
          </ul>
          <small v-if="mensaje.aviso">{{ mensaje.aviso }}</small>
          <small v-for="fuente in mensaje.fuentes || []" :key="fuente.consultado_en">
            Fuente: {{ fuente.origen }} · {{ fechaLegible(fuente.consultado_en) }}
          </small>
        </div>
        <div v-if="pensando" class="docs__burbuja docs__burbuja--asistente docs__burbuja--pensando">Pensando…</div>
      </div>
      <form class="docs__preguntar" @submit.prevent="preguntar()">
        <input v-model="pregunta" placeholder="Escribe tu pregunta…" aria-label="Pregunta" maxlength="500" />
        <button class="boton boton--secundario" type="submit" :disabled="pensando || pregunta.trim().length < 2">Preguntar</button>
      </form>
    </details>
  </div>
</template>

<style scoped>
.docs { display: flex; flex-direction: column; gap: var(--e-4); }
.docs__cabecera { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: var(--e-3); }
.docs__titulo { font-size: var(--t-xl); font-weight: 700; }
.docs__subtitulo { margin-top: 4px; max-width: 62ch; color: var(--texto-suave); font-size: var(--t-sm); line-height: 1.5; }
.docs__panel, .docs__ayuda { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-5); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); }
.docs__panel h3 { font-size: var(--t-lg); font-weight: 650; }
.docs__revision h4 { font-size: var(--t-md); font-weight: 650; }
.docs__panel h4 { margin-bottom: 4px; color: var(--texto); font-size: var(--t-sm); font-weight: 650; }
.docs__nota { color: var(--texto-suave); font-size: var(--t-sm); line-height: 1.55; }
.docs__nota--aviso { padding: var(--e-2) var(--e-3); border-radius: var(--r-2); background: var(--superficie-2); color: var(--texto-suave); }
.docs__mensaje { padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.docs__mensaje--error { border-color: var(--error-suave); background: var(--error-suave); color: var(--error); }
.docs__mensaje--info { color: var(--texto); }
.docs__vacio { color: var(--texto-tenue); font-size: var(--t-sm); }
.docs__subida, .docs__pie-paso, .docs__bajar, .docs__tipos { display: flex; flex-wrap: wrap; gap: var(--e-3); align-items: center; }
.docs__subida input { flex: 1 1 280px; }
.docs__secciones, .docs__resumen, .docs__contraste { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--e-3); }
.docs__seccion, .docs__resumen article { padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); line-height: 1.55; }
.docs__fila { display: flex; align-items: center; justify-content: space-between; gap: var(--e-3); }
.docs__barra { flex: 1; height: 6px; overflow: hidden; border-radius: var(--r-redondo); background: var(--superficie-3); }
.docs__barra span { display: block; height: 100%; background: var(--acento); transition: width var(--normal) var(--curva); }
.docs__lista { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.docs__tipos { align-items: stretch; }
.docs__tipo { flex: 1 1 180px; display: flex; flex-direction: column; gap: 4px; padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); color: var(--texto); text-align: left; cursor: pointer; }
.docs__tipo small { color: var(--texto-tenue); font-size: var(--t-xs); line-height: 1.4; }
.docs__tipo--activo { border-color: var(--acento); background: var(--acento-tenue); box-shadow: 0 0 0 3px var(--acento-suave); }
.docs__lineas, .docs__catalogo, .docs__revision { display: flex; flex-direction: column; gap: var(--e-2); }
.docs__linea { display: grid; gap: var(--e-2); }
.docs__subtotal { font-weight: 600; font-variant-numeric: tabular-nums; text-align: right; }
.docs__pie { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--e-3); padding-top: var(--e-3); border-top: 1px solid var(--borde); }
.docs__totales { display: grid; gap: 4px; min-width: 200px; font-size: var(--t-sm); }
.docs__totales div { display: flex; justify-content: space-between; gap: var(--e-4); }
.docs__total { padding-top: 4px; border-top: 1px solid var(--borde); font-weight: 700; }
.docs__producto { display: grid; grid-template-columns: minmax(0, 1fr) 90px 120px auto; gap: var(--e-2); align-items: center; padding: var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
.docs__producto small { display: block; color: var(--texto-tenue); font-size: var(--t-xs); }
.docs__cifras { font-weight: 650; font-variant-numeric: tabular-nums; }
.docs__archivo { flex: 1 1 220px; display: flex; flex-direction: column; gap: 4px; padding: var(--e-4); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); color: var(--texto); text-align: left; cursor: pointer; }
.docs__archivo small { color: var(--texto-suave); font-size: var(--t-xs); }

.docs__columna { padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.docs__columna ul { display: grid; gap: 4px; padding-left: 1.1rem; }
.docs__columna h4 { display: inline-block; padding: 1px 0.6rem; border-radius: var(--r-redondo); font-size: var(--t-xs); }
.docs__columna--ok h4 { background: var(--ok-suave); color: var(--ok); }
.docs__columna--error h4 { background: var(--error-suave); color: var(--error); }
.docs__columna--aviso h4 { background: var(--aviso-suave); color: var(--aviso); }
.docs__clave { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-4); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); }
.docs__clave dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: var(--e-3); }
.docs__clave dt { color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; }
.docs__clave dd { font-size: var(--t-sm); }
.docs__integridad { display: flex; gap: var(--e-3); align-items: flex-start; margin-top: var(--e-3); font-size: var(--t-sm); line-height: 1.5; }
.docs__integridad input { margin-top: 0.25rem; }
.docs__verificacion { display: flex; flex-direction: column; gap: var(--e-2); align-items: flex-start; padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.docs__verificacion ul { display: grid; gap: 4px; padding-left: 1.1rem; }
.docs__verificacion--falta h4 { color: var(--aviso); }
.docs__verificacion--lista h4 { color: var(--ok); }
.docs__verificacion-avisos { color: var(--texto-suave); }
.docs__ayuda summary { font-weight: 650; cursor: pointer; }
.docs__ejemplos { display: flex; flex-wrap: wrap; gap: var(--e-2); }
.docs__chip { padding: 0.35rem 0.8rem; border: 1px solid var(--borde-fuerte); border-radius: var(--r-redondo); background: var(--superficie); color: var(--texto-suave); font-size: var(--t-xs); cursor: pointer; }
.docs__chat { display: flex; flex-direction: column; gap: var(--e-3); max-height: 320px; overflow-y: auto; }
.docs__burbuja { max-width: 85%; padding: var(--e-3) var(--e-4); border-radius: var(--r-3); font-size: var(--t-sm); line-height: 1.5; }
.docs__burbuja ul { margin-top: var(--e-2); padding-left: 1.1rem; }
.docs__burbuja small { display: block; margin-top: var(--e-2); color: var(--texto-tenue); font-size: 0.7rem; }
.docs__burbuja--usuario { align-self: flex-end; background: var(--acento-suave); color: var(--texto); }
.docs__burbuja--asistente { align-self: flex-start; border: 1px solid var(--borde); background: var(--superficie); }
.docs__preguntar { display: flex; gap: var(--e-2); }
.docs__preguntar input { flex: 1; }
.docs__panel .formulario { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); align-items: start; }
/* Casillas y radios quedan fuera: a todo el ancho dejaban sin espacio al texto de su etiqueta. */
.docs__panel textarea, .docs__panel input:not([type='file'], [type='checkbox'], [type='radio']) { width: 100%; }
.docs__panel textarea { min-height: 2.6rem; line-height: 1.45; resize: vertical; }
.formulario__campo small { color: var(--texto-tenue); font-weight: 400; }
.docs__linea { grid-template-columns: minmax(260px, 1fr) 90px 110px 130px 100px 36px; align-items: start; }
.docs__linea--cabecera { color: var(--texto-tenue); font-size: var(--t-xs); font-weight: 600; }
.docs__linea .docs__subtotal { padding-top: 0.55rem; }
.docs__armar { display: flex; flex-direction: column; gap: var(--e-3); }
.docs__armar-titulo { margin: 0; }
.docs__opciones { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--e-3); }
.docs__opcion { position: relative; display: flex; flex-direction: column; gap: 6px; padding: var(--e-4) var(--e-5); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); color: var(--texto); text-align: left; cursor: pointer; transition: border-color var(--rapido) var(--curva), box-shadow var(--rapido) var(--curva); }
.docs__opcion:hover:not(:disabled) { border-color: var(--acento); box-shadow: var(--sombra-2); }
.docs__opcion:disabled { opacity: 0.6; cursor: progress; }
.docs__opcion small { color: var(--texto-suave); font-size: var(--t-xs); line-height: 1.45; }
.docs__opcion-icono { width: 30px; height: 30px; color: var(--acento); }

.docs__saldo { align-self: flex-start; margin-top: 4px; padding: 2px 10px; border-radius: var(--r-redondo); background: var(--acento-tenue); color: var(--acento-fuerte); font-size: var(--t-xs); font-weight: 600; }
.docs__comprar { align-self: flex-start; }
.docs__paquetes { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--e-3); }
.docs__paquetes .docs__nota, .docs__compras { grid-column: 1 / -1; }
.docs__paquete { display: flex; flex-direction: column; gap: 4px; padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.docs__precio { font-size: var(--t-lg); font-weight: 700; }
.docs__compras { margin: 0; padding-left: 1.1rem; color: var(--texto-suave); font-size: var(--t-xs); }
.docs__faltan { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie-2); font-size: var(--t-sm); }
.docs__faltan button { align-self: flex-start; }
.docs__faltan-lista { display: flex; flex-wrap: wrap; gap: 6px; }
.docs__falta { padding: 2px 10px; border-radius: var(--r-redondo); background: var(--aviso-suave); color: var(--aviso); font-size: var(--t-xs); font-weight: 600; }
.docs__cumple-fila { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie-2); }
.docs__cumple-fila button { align-self: flex-start; }
.docs__firma { display: flex; flex-direction: column; gap: var(--e-3); padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
.docs__firma h4 { margin: 0; }
.docs__texto { white-space: pre-line; }
.docs__num { flex: none; min-width: 2.4rem; padding: 2px 8px; border-radius: var(--r-redondo); background: var(--acento-tenue); color: var(--acento-fuerte); font-size: var(--t-xs); font-weight: 700; text-align: center; font-variant-numeric: tabular-nums; }
.docs__control { position: sticky; top: 0; z-index: 2; display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.docs__control strong { margin-right: var(--e-2); }
.docs__control-punto { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border: 1px solid var(--borde); border-radius: var(--r-redondo); background: var(--superficie); color: var(--texto-suave); font-size: var(--t-xs); font-weight: 600; cursor: pointer; }
.docs__control-punto span { display: grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; font-size: 0.65rem; }
.docs__control-punto--ok { color: var(--texto-suave); }
.docs__control-punto--ok span { background: var(--ok-suave); color: var(--ok); }
.docs__control-punto--falta { color: var(--texto); }
.docs__control-punto--falta span { background: var(--aviso-suave); color: var(--aviso); }
.docs__bloque { display: flex; flex-direction: column; gap: var(--e-3); padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); scroll-margin-top: 80px; }
.docs__bloque-cabecera { display: flex; align-items: flex-start; gap: var(--e-3); }
.docs__bloque-cabecera > div { flex: 1; }
.docs__bloque-cabecera h4 { margin: 0; color: var(--texto); font-size: var(--t-base); }
.docs__bloque-cabecera small { display: block; margin-top: 2px; color: var(--texto-suave); font-size: var(--t-xs); line-height: 1.45; }
.docs__letra { display: grid; place-items: center; flex: none; width: 28px; height: 28px; border-radius: 50%; background: var(--acento-tenue); color: var(--acento-fuerte); font-size: var(--t-sm); font-weight: 700; }
.docs__plegable > summary { list-style: none; cursor: pointer; }
.docs__plegable > summary::-webkit-details-marker { display: none; }
.docs__plegable > summary::after { content: '▾'; color: var(--texto-tenue); transition: transform 0.15s ease; }
.docs__plegable:not([open]) > summary::after { transform: rotate(-90deg); }
.docs__plegable[open] > summary { margin-bottom: var(--e-2); }
.docs__acciones { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); }
.docs__interruptor { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; color: var(--texto-suave); font-size: var(--t-xs); cursor: pointer; }
.docs__izquierda { align-self: flex-start; }
.docs__campo--falta input, .docs__campo--falta textarea, .docs__entrada--falta { border-color: var(--borde-fuerte); background: var(--superficie-2); }

.docs__cumple-cabecera { display: flex; align-items: center; gap: var(--e-2); }
.docs__cumple-estado { flex: 1; color: var(--texto-suave); font-size: var(--t-xs); font-weight: 600; }
.docs__cumple-fila--falta .docs__cumple-estado { color: var(--aviso); }
.docs__cumple-fila--ok .docs__cumple-estado { color: var(--ok); }
.docs__espec { display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(0, 1fr) 36px; gap: var(--e-2); align-items: start; padding: var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); }
.docs__espec .docs__num { margin-top: 1.6rem; }
.docs__espec .boton { margin-top: 1.4rem; }

.docs__burbuja--fallo { border-color: var(--error); background: var(--error-suave); color: var(--error); }
.docs__burbuja--pensando { color: var(--texto-tenue); font-style: italic; }
.docs__chat { max-height: 420px; }
@media (max-width: 800px) {
  .docs__linea, .docs__producto { grid-template-columns: 1fr 1fr; }
  .docs__linea textarea { grid-column: 1 / -1; }
  .docs__linea--cabecera { display: none; }
  .docs__espec { grid-template-columns: auto minmax(0, 1fr) 36px; }
  .docs__espec label { grid-column: 1 / -1; }
  .docs__control { position: static; }
}

/* --- Paso 1: buscar, ver el progreso y leer el proceso ------------------------------------------ */
.proceso__intro { display: flex; flex-direction: column; gap: var(--e-1); }
.proceso__buscar { display: flex; flex-wrap: wrap; align-items: end; gap: var(--e-3); }
.proceso__buscar label { flex: 1 1 22rem; }
.proceso__etiqueta { display: block; margin-bottom: 4px; color: var(--texto-suave); font-size: var(--t-sm); }
.proceso__buscar input { width: 100%; padding: 0.65rem 0.8rem; font-size: var(--t-md); font-variant-numeric: tabular-nums; }
.proceso__subir summary { cursor: pointer; color: var(--texto-suave); font-size: var(--t-sm); }
.proceso__subir[open] summary { margin-bottom: var(--e-3); }
.proceso__progreso { display: flex; flex-wrap: wrap; gap: var(--e-3); margin: 0; padding: var(--e-3) var(--e-4); list-style: none; border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); }
.proceso__progreso li { display: flex; align-items: center; gap: var(--e-2); color: var(--texto-tenue); font-size: var(--t-sm); }
.proceso__progreso li.es-actual { color: var(--acento-fuerte); font-weight: 650; }
.proceso__progreso li.es-hecha { color: var(--texto-suave); }
.proceso__punto { display: inline-grid; place-items: center; width: 1.5rem; height: 1.5rem; border-radius: var(--r-redondo); background: var(--superficie-3); font-size: var(--t-xs); font-weight: 700; }
.es-actual .proceso__punto { background: var(--acento); color: var(--superficie); animation: proceso-pulso 1.2s ease-in-out infinite; }
.es-hecha .proceso__punto { background: var(--acento-tenue); color: var(--acento-fuerte); }
@keyframes proceso-pulso { 50% { box-shadow: 0 0 0 6px var(--acento-suave); } }
@media (prefers-reduced-motion: reduce) { .es-actual .proceso__punto { animation: none; } }

.proceso__ficha { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-5); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie-2); }
.proceso__codigo { color: var(--texto-suave); font-size: var(--t-sm); font-variant-numeric: tabular-nums; letter-spacing: 0.02em; }
.proceso__ficha h4 { margin: 2px 0 var(--e-2); color: var(--texto); font-size: var(--t-lg); line-height: 1.3; overflow-wrap: anywhere; }
.proceso__chips { display: flex; flex-wrap: wrap; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.proceso__chip { padding: 2px 0.7rem; border-radius: var(--r-redondo); background: var(--superficie-3); color: var(--texto-suave); font-size: var(--t-xs); font-weight: 600; }
.proceso__chip--ok { background: var(--ok-suave); color: var(--ok); }
.proceso__hechos { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: var(--e-4) var(--e-5); margin: 0; }
.proceso__hechos dt { margin-bottom: 2px; color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; letter-spacing: 0.03em; text-transform: uppercase; }
.proceso__hechos dd { margin: 0; font-size: var(--t-base); line-height: 1.5; overflow-wrap: anywhere; }
.proceso__hecho--ancho { grid-column: 1 / -1; }
.proceso__recorte { display: -webkit-box; -webkit-line-clamp: 4; line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.proceso__mas { margin-top: 2px; padding: 0; border: 0; background: none; color: var(--acento-fuerte); font-size: var(--t-xs); font-weight: 650; cursor: pointer; }
.proceso__mas:hover, .proceso__mas:focus-visible { text-decoration: underline; }

.proceso__docs h4, .proceso__detalle h4 { margin-bottom: var(--e-2); }
.proceso__docs ul { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.proceso__docs li { display: flex; align-items: center; gap: var(--e-3); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.proceso__icono { flex: none; padding: 2px 0.5rem; border-radius: var(--r-1); background: var(--acento-suave); color: var(--acento-fuerte); font-size: var(--t-xs); font-weight: 700; }
.proceso__icono--tipo { min-width: 8.5rem; text-align: center; font-weight: 650; }
.proceso__anexo-nombre { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.proceso__anexo-aviso { display: block; color: var(--aviso); }
.docs__bloque--titulo { border: 2px solid var(--acento); background: var(--acento-tenue); }
.docs__titulo-input { font-size: var(--t-lg); font-weight: 600; }
.docs__titulo-repetido { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); color: var(--peligro); font-size: var(--t-sm); }
.proceso__anexo-nombre small { display: block; color: var(--texto-tenue); font-size: var(--t-xs); }
.proceso__ocr { display: flex; flex-direction: column; gap: var(--e-2); margin-top: var(--e-2); color: var(--texto-suave); font-size: var(--t-sm); }
.proceso__ocr .docs__barra { flex: none; }
/* Indicador del presupuesto: barra neutra con el acento; el exceso se dice con texto, no con color. */
.docs__presupuesto { display: flex; flex-direction: column; gap: var(--e-2); padding-top: var(--e-3); }
.docs__presupuesto-cabecera { display: flex; flex-wrap: wrap; justify-content: space-between; gap: var(--e-2) var(--e-4); font-size: var(--t-sm); }
.docs__presupuesto-uso { color: var(--texto-suave); font-variant-numeric: tabular-nums; }
.docs__barra--presupuesto { flex: none; }
.docs__presupuesto-error { padding: var(--e-2) var(--e-3); border-radius: var(--r-2); background: var(--error-suave); color: var(--error); font-size: var(--t-sm); }
@media (max-width: 640px) {
  .proceso__anexo { flex-wrap: wrap; }
  .proceso__icono--tipo { min-width: 0; }
}
.proceso__detalle { display: flex; flex-direction: column; gap: var(--e-2); }
.proceso__detalle details { border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
.proceso__detalle summary { display: flex; flex-direction: column; gap: 2px; padding: var(--e-3) var(--e-4); cursor: pointer; font-size: var(--t-sm); }
.proceso__detalle summary small { color: var(--texto-tenue); font-size: var(--t-xs); }
.proceso__detalle details[open] summary small { display: none; }
.proceso__detalle details[open] summary { border-bottom: 1px solid var(--borde); }
.proceso__detalle details > .texto-tdr { padding: var(--e-3) var(--e-4); font-size: var(--t-sm); line-height: 1.65; }

.docs__enlace-chico {
  align-self: flex-start;
  border: 0;
  padding: 0;
  background: none;
  color: var(--acento);
  font-size: var(--t-xs);
  text-decoration: underline;
  cursor: pointer;
}

/* --- Costos que pide la entidad: una fila por ítem, como la proforma del SOCE ------------------- */
.docs__tabla-lineas { display: flex; flex-direction: column; gap: var(--e-2); overflow-x: auto; padding-bottom: var(--e-2); }
.docs__linea--soce { grid-template-columns: 2.2rem 9.5rem minmax(260px, 1fr) 5.5rem 5.5rem 8.5rem 7rem 2.25rem; min-width: 56rem; align-items: start; }
.docs__num { padding-top: 0.55rem; color: var(--texto-tenue); font-size: var(--t-sm); font-variant-numeric: tabular-nums; text-align: center; }
.docs__cpc { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.docs__cpc small { display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; color: var(--texto-suave); font-size: var(--t-xs); line-height: 1.3; overflow-wrap: anywhere; }
.docs__enlace { margin-left: var(--e-2); padding: 0; border: 0; background: none; color: var(--acento-fuerte); font: inherit; font-weight: 650; cursor: pointer; }
.docs__enlace:hover, .docs__enlace:focus-visible { text-decoration: underline; }

/* --- Vista previa del PDF armado en el navegador ----------------------------------------------- */
.docs__previa { display: flex; flex-direction: column; gap: var(--e-2); }
.docs__marco { width: 100%; height: min(70vh, 640px); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
/* --- Asistente: indicador de pasos, cabecera de cada paso y barra Atrás / Siguiente ------------- */
.asistente__pasos { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--e-2); margin: 0; padding: 0; list-style: none; counter-reset: paso; }
.asistente__paso { position: relative; }
.asistente__paso:not(:last-child)::after { content: ''; position: absolute; top: 50%; right: calc(var(--e-2) * -1); width: var(--e-2); height: 1px; background: var(--borde-fuerte); }
.asistente__boton { display: flex; align-items: center; gap: var(--e-2); width: 100%; padding: var(--e-2) var(--e-3); border: 1px solid transparent; border-radius: var(--r-2); background: transparent; color: var(--texto-suave); text-align: left; cursor: pointer; transition: background var(--rapido) var(--curva), border-color var(--rapido) var(--curva); }
.asistente__boton:hover { background: var(--superficie-2); }
.asistente__boton:focus-visible { outline: 2px solid var(--acento); outline-offset: 2px; }
.asistente__boton[aria-disabled='true'] { cursor: not-allowed; }
.asistente__paso--actual .asistente__boton { border-color: var(--borde); background: var(--superficie); color: var(--texto); }
.asistente__paso--pendiente .asistente__boton { color: var(--texto-tenue); }
.asistente__numero { display: grid; place-items: center; flex: none; width: 28px; height: 28px; border: 1px solid var(--borde-fuerte); border-radius: 50%; background: var(--superficie); font-size: var(--t-xs); font-weight: 700; font-variant-numeric: tabular-nums; }
.asistente__paso--actual .asistente__numero { border-color: var(--acento); background: var(--acento); color: var(--superficie); }
.asistente__paso--hecho .asistente__numero { border-color: var(--acento-suave); background: var(--acento-tenue); color: var(--acento-fuerte); }
.asistente__texto { display: flex; flex-direction: column; min-width: 0; }
.asistente__texto strong { font-size: var(--t-sm); font-weight: 650; }
.asistente__texto small { overflow: hidden; color: var(--texto-tenue); font-size: var(--t-xs); text-overflow: ellipsis; white-space: nowrap; }
.docs__paso-cabecera { display: flex; flex-direction: column; gap: 2px; }
.docs__paso-numero { color: var(--texto-tenue); font-size: var(--t-xs); font-weight: 650; letter-spacing: 0.04em; text-transform: uppercase; }
.docs__cuerpo { display: flex; flex-direction: column; gap: var(--e-4); }
.asistente__pie { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3); padding-top: var(--e-4); border-top: 1px solid var(--borde); }
.asistente__pie .boton--principal { margin-left: auto; }
.asistente__estado { flex: 1 1 12rem; color: var(--texto-suave); font-size: var(--t-xs); text-align: right; }
.asistente__pie--fijo { position: sticky; bottom: 0; z-index: 2; margin: 0 calc(var(--e-5) * -1) calc(var(--e-5) * -1); padding: var(--e-3) var(--e-5); border-radius: 0 0 var(--r-3) var(--r-3); background: var(--superficie); box-shadow: var(--sombra-2); }

/* --- Autollenado: una insignia sobria junto a la etiqueta del campo ----------------------------- */
.docs__auto { display: inline-block; margin-left: var(--e-2); padding: 0 0.5rem; border-radius: var(--r-redondo); background: var(--acento-tenue); color: var(--acento-fuerte); font-size: var(--t-xs); font-style: normal; font-weight: 600; line-height: 1.6; vertical-align: middle; white-space: nowrap; }
.docs__autollenado { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie-2); color: var(--texto-suave); font-size: var(--t-sm); }
.docs__autollenado .docs__auto { margin-left: 0; }
.docs__atajo { color: var(--texto-suave); font-size: var(--t-sm); }
.docs__atajo .docs__enlace { margin: 0 2px; }
.docs__enlace:disabled { opacity: 0.6; cursor: progress; }
.docs__avance { display: flex; align-items: center; gap: var(--e-3); }

/* --- Paso 1: ítems que pide la entidad ------------------------------------------------------------ */
.proceso__items ul { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.proceso__items li { display: flex; align-items: flex-start; gap: var(--e-3); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.proceso__items .docs__num { padding-top: 2px; }
.proceso__item-texto { display: flex; flex-direction: column; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
.proceso__item-texto small { color: var(--texto-tenue); font-size: var(--t-xs); }

/* --- Paso 2: requisitos como lista de comprobación ----------------------------------------------- */
.checklist { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.checklist__item { display: flex; align-items: flex-start; gap: var(--e-3); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); transition: box-shadow var(--rapido) var(--curva); }
.checklist__item:hover { box-shadow: var(--sombra-1); }
.checklist__marca { display: flex; flex: 1; align-items: flex-start; gap: var(--e-3); min-width: 0; cursor: pointer; }
.checklist__marca input { flex: none; width: 1.1rem; height: 1.1rem; margin-top: 3px; accent-color: var(--acento); cursor: pointer; }
.checklist__texto { flex: 1; min-width: 0; line-height: 1.55; }
.checklist__item--cumplido .checklist__texto { color: var(--texto-suave); }
.checklist__item--no_aplica .checklist__texto { color: var(--texto-tenue); text-decoration: line-through; }
.checklist__no-aplica { flex: none; padding: 2px 0.65rem; border: 1px solid var(--borde); border-radius: var(--r-redondo); background: transparent; color: var(--texto-suave); font-size: var(--t-xs); font-weight: 600; cursor: pointer; }
.checklist__no-aplica[aria-pressed='true'] { border-color: var(--borde-fuerte); background: var(--superficie-3); color: var(--texto); }
.checklist__no-aplica:focus-visible { outline: 2px solid var(--acento); outline-offset: 2px; }

/* --- Paso 4: descargas y firma ---------------------------------------------------------------------- */
.docs__bajar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3); }
.docs__bajar .docs__nota { flex: 1 1 16rem; }
.docs__firma > summary { list-style: none; cursor: pointer; }
.docs__firma-form { display: flex; flex-direction: column; gap: var(--e-3); margin-top: var(--e-3); }

/* --- Móvil: el indicador se reduce a números y la barra apila las acciones ------------------------ */
@media (max-width: 640px) {
  .docs__panel, .docs__ayuda { padding: var(--e-4); }
  .asistente__pasos { gap: var(--e-1); }
  .asistente__paso:not(:last-child)::after { display: none; }
  .asistente__boton { flex-direction: column; justify-content: center; gap: 4px; padding: var(--e-2) var(--e-1); text-align: center; }
  .asistente__texto small { display: none; }
  .asistente__texto strong { font-size: var(--t-xs); }
  .asistente__pie { gap: var(--e-2); }
  .asistente__estado { order: -1; flex-basis: 100%; text-align: left; }
  .asistente__pie .boton { flex: 1 1 auto; justify-content: center; }
  .asistente__pie--fijo { margin: 0 calc(var(--e-4) * -1) calc(var(--e-4) * -1); padding: var(--e-3) var(--e-4); }
  .docs__linea--soce { grid-template-columns: 2.2rem minmax(0, 1fr) minmax(0, 1fr); min-width: 0; padding: var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); }
  .docs__linea--soce textarea, .docs__linea--soce .docs__cpc { grid-column: 2 / -1; }
  .docs__linea--soce .docs__subtotal { text-align: left; }
  .docs__linea--cabecera { display: none; }
  .docs__producto { grid-template-columns: 1fr 1fr; }
  .docs__producto > div { grid-column: 1 / -1; }
  .checklist__item { flex-wrap: wrap; }
  .checklist__no-aplica { margin-left: calc(1.1rem + var(--e-3)); }
  .proceso__buscar .boton { width: 100%; }
  .docs__preguntar { flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) {
  .asistente__boton, .checklist__item, .docs__opcion, .docs__barra span { transition: none; }
}
</style>
