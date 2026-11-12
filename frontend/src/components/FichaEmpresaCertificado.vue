<script setup>
/**
 * La información de la empresa leída **como los certificados que la persona ya conoce**: el del RUC
 * del SRI y el del RUP del SERCOP. Mismo orden, mismas etiquetas, etiqueta en negrita arriba y valor
 * debajo, secciones con título grande y una línea.
 *
 * Lo pidió el cliente pensando en usuarios de edad avanzada: el perfil era un formulario largo,
 * agrupado a nuestra manera («Datos legales», «Qué ofreces»…), y se perdían buscando su dirección o
 * sus CPC. Con el certificado en la mano encuentran cada dato en el mismo sitio que en el papel.
 *
 * Reglas de la pantalla:
 * - Se lee por defecto. Cada sección tiene «Editar», y se edita una sola a la vez.
 * - Un dato vacío dice «Sin registrar» con «Completar», que abre su sección y pone el cursor en él.
 * - Solo se muestran los campos que CercoApp guarda. El certificado del SRI tiene más (artesano,
 *   jurisdicción, fechas de cese…), pero un recuadro que no se puede llenar solo confunde.
 * - Lo que no está en ningún certificado pero sirve para ofertar (montos, palabras clave,
 *   experiencia, equipo) va aparte, al final, con su propio título.
 *
 * No habla con la API: recibe `acciones` (guardar, agregar, quitar), que devuelven promesas y
 * lanzan error si algo falla, para poder decir el resultado dentro de la sección y no arriba de
 * todo, donde la persona no lo ve.
 */
import { computed, reactive, ref } from 'vue'

import CampoCertificado from '@/components/CampoCertificado.vue'
import ColeccionPerfil from '@/components/ColeccionPerfil.vue'
import SeccionCertificado from '@/components/SeccionCertificado.vue'
import { PROVINCIAS } from '@/utils/provincias'

const props = defineProps({
  perfil: { type: Object, default: null },
  /** Términos de la lista de CPC vigilados (`api.listarCpc().claves`). */
  cpcVigilados: { type: Array, default: () => [] },
  acciones: { type: Object, required: true },
})

// --------------------------------------------------------------------------- opciones y etiquetas

const TIPOS_PERSONA = [
  { valor: '', etiqueta: 'Sin indicar' },
  { valor: 'natural', etiqueta: 'Persona natural' },
  { valor: 'juridica', etiqueta: 'Sociedad' },
]
const ESTADOS_RUP = [
  { valor: '', etiqueta: 'Sin indicar' },
  { valor: 'habilitado', etiqueta: 'Habilitado' },
  { valor: 'pasivo', etiqueta: 'Pasivo' },
  { valor: 'suspendido', etiqueta: 'Suspendido' },
  { valor: 'no_registrado', etiqueta: 'No registrado' },
]
const TIPOS_CONTRATACION = [
  { valor: 'bienes', etiqueta: 'Bienes' },
  { valor: 'servicios', etiqueta: 'Servicios' },
  { valor: 'obras', etiqueta: 'Obras' },
  { valor: 'consultoria', etiqueta: 'Consultoría' },
]
const PROCEDIMIENTOS = [
  { valor: 'infima', etiqueta: 'Ínfima cuantía' },
  { valor: 'subasta_inversa', etiqueta: 'Subasta inversa' },
  { valor: 'catalogo', etiqueta: 'Catálogo' },
  { valor: 'licitacion', etiqueta: 'Licitación' },
]
const TIPOS_CONTACTO = [
  { valor: 'representante_legal', etiqueta: 'Representante legal' },
  { valor: 'comercial', etiqueta: 'Comercial' },
  { valor: 'tecnico', etiqueta: 'Técnico' },
]
const nombreDe = (opciones, valor) => opciones.find((item) => item.valor === valor)?.etiqueta || valor || ''

/**
 * Cómo se edita cada dato de la ficha. `tipo`: texto (por omisión), select, sino, date, number,
 * email. «sino» son dos botones grandes Sí / No: una casilla pequeña cuesta verla y acertarle.
 */
const DATOS = {
  razon_social: { etiqueta: 'Razón social, o apellidos y nombres', ancho: true },
  ruc: { etiqueta: 'Número RUC', pista: '13 números', inputmode: 'numeric', maxlength: 13 },
  nombre_comercial: { etiqueta: 'Nombre comercial' },
  tipo_persona: { etiqueta: 'Tipo', tipo: 'select', opciones: TIPOS_PERSONA },
  regimen_tributario: {
    etiqueta: 'Régimen',
    sugerencias: ['General', 'RIMPE · Emprendedor', 'RIMPE · Negocio Popular'],
  },
  fecha_inicio_actividades: { etiqueta: 'Inicio de actividades', tipo: 'date' },
  obligado_contabilidad: { etiqueta: 'Obligado a llevar contabilidad', tipo: 'sino' },
  ciudad: { etiqueta: 'Cantón o ciudad' },
  direccion: {
    etiqueta: 'Dirección',
    ancho: true,
    ayuda: 'Calle, número, intersección y una referencia, como en tu RUC.',
  },
  telefono: { etiqueta: 'Teléfono o celular', inputmode: 'tel', autocomplete: 'tel' },
  email_contacto: { etiqueta: 'Email', tipo: 'email', autocomplete: 'email' },
  sitio_web: { etiqueta: 'Sitio web', inputmode: 'url', pista: 'https://' },
  estado_rup: {
    etiqueta: 'Estado en el RUP',
    tipo: 'select',
    opciones: ESTADOS_RUP,
    ayuda: 'Elige el que dice tu certificado del RUP.',
  },
  capacidad_ejecucion: {
    etiqueta: 'Categoría',
    ancho: true,
    pista: 'Ej. Categoría RUP: Micro empresa',
    ayuda: 'La que figura en tu RUP. También puedes anotar cuánto puedes entregar.',
  },
  presupuesto_min: { etiqueta: 'Monto mínimo (USD)', tipo: 'number' },
  presupuesto_max: { etiqueta: 'Monto máximo (USD)', tipo: 'number' },
}

/** Qué datos abre cada sección al pulsar «Editar». */
const EDICION = {
  contribuyente: [
    'razon_social',
    'ruc',
    'nombre_comercial',
    'tipo_persona',
    'regimen_tributario',
    'fecha_inicio_actividades',
    'obligado_contabilidad',
  ],
  domicilio: ['ciudad', 'direccion'],
  contacto: ['telefono', 'email_contacto', 'sitio_web'],
  rup: ['estado_rup', 'capacidad_ejecucion'],
  presupuesto: ['presupuesto_min', 'presupuesto_max'],
}
const SECCION_DE = Object.fromEntries(
  Object.entries(EDICION).flatMap(([seccion, claves]) => claves.map((clave) => [clave, seccion])),
)

// --------------------------------------------------------------------------- colecciones

const CAMPOS = {
  contactos: [
    { clave: 'tipo', etiqueta: 'Rol', tipo: 'select', opciones: TIPOS_CONTACTO, requerido: true, inicial: 'representante_legal' },
    { clave: 'nombre', etiqueta: 'Nombre', requerido: true },
    { clave: 'cedula', etiqueta: 'Cédula' },
    { clave: 'cargo', etiqueta: 'Cargo' },
    { clave: 'email', etiqueta: 'Email' },
    { clave: 'telefono', etiqueta: 'Teléfono' },
  ],
  dedicaciones: [
    { clave: 'tipo_contratacion', etiqueta: 'Qué contratas', tipo: 'select', opciones: TIPOS_CONTRATACION, requerido: true, inicial: 'bienes' },
    { clave: 'tipo_procedimiento', etiqueta: 'Tipo de proceso', tipo: 'select', opciones: PROCEDIMIENTOS, requerido: true, inicial: 'infima' },
    { clave: 'monto_min', etiqueta: 'Monto mínimo (USD)', tipo: 'number' },
    { clave: 'monto_max', etiqueta: 'Monto máximo (USD)', tipo: 'number' },
    { clave: 'principal', etiqueta: 'Principal', tipo: 'check', texto: 'Es lo que más hago', inicial: false },
  ],
  actividades: [
    { clave: 'ciiu', etiqueta: 'Código de la actividad (CIIU)', requerido: true, pista: 'Ej. G4659' },
    { clave: 'descripcion', etiqueta: 'Descripción', ancho: true },
    { clave: 'principal', etiqueta: 'Principal', tipo: 'check', texto: 'Es la actividad principal', inicial: false },
  ],
  // `cpc` no es una columna: se escribe en la descripción como «CPC xxxxx», igual que lo deja la
  // carga del RUP, para que la tabla de bienes y servicios muestre el código.
  ofertas: [
    { clave: 'tipo', etiqueta: 'Tipo', tipo: 'select', opciones: [{ valor: 'producto', etiqueta: 'Bien (producto)' }, { valor: 'servicio', etiqueta: 'Servicio' }], requerido: true, inicial: 'producto' },
    { clave: 'cpc', etiqueta: 'Código CPC (si lo sabes)', pista: 'Ej. 452300011' },
    { clave: 'nombre', etiqueta: 'Producto o servicio', requerido: true, ancho: true },
    { clave: 'descripcion', etiqueta: 'Características (una por línea)', ancho: true },
  ],
  palabras: [{ clave: 'texto', etiqueta: 'Palabra o frase', requerido: true, pista: 'Ej. mantenimiento de computadoras' }],
  cobertura: [
    { clave: 'provincia', etiqueta: 'Provincia', tipo: 'select', opciones: PROVINCIAS.map((p) => ({ valor: p.nombre, etiqueta: p.nombre })), requerido: true, inicial: 'Pichincha' },
    { clave: 'canton', etiqueta: 'Cantón (si quieres)' },
  ],
  experiencia: [
    { clave: 'entidad', etiqueta: 'Entidad que contrató', requerido: true },
    { clave: 'objeto', etiqueta: 'Qué se contrató', ancho: true },
    { clave: 'monto', etiqueta: 'Monto (USD)', tipo: 'number' },
    { clave: 'anio', etiqueta: 'Año', tipo: 'number', pista: '2025' },
    { clave: 'cpc', etiqueta: 'Código CPC' },
    { clave: 'tipo_contratacion', etiqueta: 'Tipo', tipo: 'select', opciones: TIPOS_CONTRATACION },
  ],
  personal: [
    { clave: 'perfil', etiqueta: 'Cargo o perfil', requerido: true },
    { clave: 'titulo', etiqueta: 'Título' },
    { clave: 'anios', etiqueta: 'Años de experiencia', tipo: 'number' },
  ],
  equipo: [
    { clave: 'nombre', etiqueta: 'Equipo o herramienta', requerido: true },
    { clave: 'cantidad', etiqueta: 'Cantidad', tipo: 'number', inicial: 1 },
    { clave: 'estado', etiqueta: 'Estado', pista: 'Ej. funcionando' },
  ],
}

const unir = (...partes) => partes.filter(Boolean).join(' · ')
const dinero = (valor) => (valor == null || valor === '' ? '' : `USD ${Number(valor).toLocaleString('es-EC')}`)

const RESUMENES = {
  contactos: (f) => unir(nombreDe(TIPOS_CONTACTO, f.tipo), f.nombre),
  dedicaciones: (f) => unir(nombreDe(TIPOS_CONTRATACION, f.tipo_contratacion), nombreDe(PROCEDIMIENTOS, f.tipo_procedimiento)),
  actividades: (f) => (f.descripcion ? `${f.ciiu} - ${f.descripcion}` : f.ciiu),
  ofertas: (f) => unir(f.tipo === 'servicio' ? 'Servicio' : 'Bien', f.nombre),
  palabras: (f) => f.texto,
  cobertura: (f) => unir(f.provincia, f.canton),
  experiencia: (f) => unir(f.entidad, f.anio),
  personal: (f) => f.perfil,
  equipo: (f) => `${f.nombre} (${f.cantidad ?? 1})`,
}
const DETALLES = {
  contactos: (f) => unir(f.cargo, f.cedula && `C.I. ${f.cedula}`, f.email, f.telefono),
  dedicaciones: (f) =>
    unir(f.principal ? 'Principal' : '', f.monto_min != null || f.monto_max != null ? `${dinero(f.monto_min) || 'desde 0'} a ${dinero(f.monto_max) || 'sin tope'}` : ''),
  actividades: (f) => (f.principal ? 'Actividad principal' : ''),
  ofertas: (f) => String(f.descripcion || '').split('\n').filter(Boolean).slice(0, 3).join(' · '),
  experiencia: (f) => unir(f.objeto, dinero(f.monto), f.cpc ? `CPC ${f.cpc}` : ''),
  personal: (f) => unir(f.titulo, f.anios ? `${f.anios} años` : ''),
  equipo: (f) => f.estado,
}

// --------------------------------------------------------------------------- lectura

const lista = (clave) => props.perfil?.[clave] || []

/** Los datos del perfil como se muestran y se editan: textos, sin nulos, fecha AAAA-MM-DD. */
const identidad = computed(() => {
  const datos = props.perfil || {}
  const fila = {}
  for (const clave of Object.keys(DATOS)) {
    const valor = datos[clave]
    if (clave === 'obligado_contabilidad') fila[clave] = valor == null ? null : Boolean(valor)
    else if (clave === 'fecha_inicio_actividades') fila[clave] = valor ? String(valor).slice(0, 10) : ''
    else fila[clave] = valor == null ? '' : String(valor)
  }
  return fila
})

function fechaLegible(texto) {
  if (!texto) return ''
  const [anio, mes, dia] = texto.split('-')
  return dia ? `${dia}/${mes}/${anio}` : texto
}

/** Valor tal como se lee en la ficha (no como se guarda). */
function ver(clave) {
  const valor = identidad.value[clave]
  if (clave === 'obligado_contabilidad') return valor == null ? '' : valor ? 'SÍ' : 'NO'
  if (clave === 'tipo_persona') return valor ? nombreDe(TIPOS_PERSONA, valor).toUpperCase() : ''
  if (clave === 'estado_rup') return valor ? nombreDe(ESTADOS_RUP, valor).toUpperCase() : ''
  if (clave === 'fecha_inicio_actividades') return fechaLegible(valor)
  if (clave === 'presupuesto_min' || clave === 'presupuesto_max') return dinero(valor)
  return valor
}

const etiquetaNombre = computed(() =>
  identidad.value.tipo_persona === 'natural' ? 'Apellidos y nombres' : 'Razón social',
)

/**
 * La tabla «Bienes, obras o servicios» del RUP: Código | Producto. Sale de «Qué ofreces» (la carga
 * del RUP deja ahí cada CPC con «CPC xxxxx» en la descripción) y se completa con los códigos que la
 * empresa vigila y que aún no tienen producto, para que ningún CPC suyo quede fuera de la vista.
 */
const filasCpc = computed(() => {
  const filas = []
  const vistos = new Set()
  for (const oferta of lista('ofertas')) {
    const hallado = /CPC\s*([\d.]+)/i.exec(String(oferta.descripcion || ''))
    const codigo = hallado ? hallado[1] : ''
    if (codigo) vistos.add(codigo)
    filas.push({ clave: `o-${oferta.id}`, codigo, producto: oferta.nombre })
  }
  for (const termino of props.cpcVigilados) {
    const texto = String(termino || '').trim()
    if (/^\d{4,}$/.test(texto) && !vistos.has(texto)) {
      vistos.add(texto)
      filas.push({ clave: `v-${texto}`, codigo: texto, producto: '' })
    }
  }
  return filas.sort((a, b) => (a.codigo || '~').localeCompare(b.codigo || '~'))
})
const CPC_A_LA_VISTA = 25
const verTodosCpc = ref(false)
const filasCpcVisibles = computed(() =>
  verTodosCpc.value ? filasCpc.value : filasCpc.value.slice(0, CPC_A_LA_VISTA),
)

// --------------------------------------------------------------------------- edición

const editando = ref('')
const guardando = ref(false)
const borrador = reactive({})
const mensajes = reactive({})
const errores = reactive({})

function limpiarMensajes() {
  for (const clave of Object.keys(mensajes)) delete mensajes[clave]
  for (const clave of Object.keys(errores)) delete errores[clave]
}

/**
 * Abre una sección para editar. Si había otra abierta se cierra sin guardar: una sola a la vez, y
 * lo que quedó a medias no se guarda por sorpresa. `campo` pone el cursor en ese dato.
 */
function abrir(seccion, campo = '') {
  limpiarMensajes()
  for (const clave of Object.keys(borrador)) delete borrador[clave]
  for (const clave of EDICION[seccion] || []) borrador[clave] = identidad.value[clave]
  editando.value = seccion
  // La sección pone el foco en su primer campo al abrirse; esto va después, en el dato pedido.
  setTimeout(() => {
    const destino = campo ? document.getElementById(`cert-${campo}`) : null
    const bloque = document.getElementById(`perfil-${seccion}`)
    bloque?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    destino?.focus({ preventScroll: true })
  }, 60)
}

/** «Completar» de un dato: abre la sección que lo edita. */
function completar(clave) {
  abrir(SECCION_DE[clave] || 'contribuyente', clave)
}

function cancelar() {
  errores[editando.value] = ''
  editando.value = ''
}

function camposDelBorrador() {
  const campos = {}
  for (const [clave, valor] of Object.entries(borrador)) {
    if (clave === 'presupuesto_min' || clave === 'presupuesto_max') {
      campos[clave] = valor === '' || valor == null ? null : Number(valor)
    } else if (clave === 'obligado_contabilidad') {
      if (valor != null) campos[clave] = Boolean(valor)
    } else {
      campos[clave] = typeof valor === 'string' ? valor.trim() : valor
    }
  }
  return campos
}

/** Lo que se puede revisar antes de ir al servidor, dicho en una frase sencilla. */
function revisar(campos) {
  if ('ruc' in campos && campos.ruc && !/^\d{13}$/.test(campos.ruc)) {
    return 'El RUC debe tener 13 números, sin espacios ni guiones.'
  }
  if (campos.email_contacto && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(campos.email_contacto)) {
    return 'El email no parece completo. Revisa que tenga @ y un punto, por ejemplo nombre@correo.com.'
  }
  if (campos.presupuesto_min != null && campos.presupuesto_max != null && campos.presupuesto_min > campos.presupuesto_max) {
    return 'El monto mínimo no puede ser mayor que el máximo.'
  }
  return ''
}

async function guardar() {
  const seccion = editando.value
  if (!seccion) return
  const campos = camposDelBorrador()
  const problema = revisar(campos)
  if (problema) {
    errores[seccion] = problema
    return
  }
  guardando.value = true
  errores[seccion] = ''
  try {
    await props.acciones.guardar(campos)
    editando.value = ''
    mensajes[seccion] = 'Listo. Tus datos quedaron guardados.'
  } catch (fallo) {
    errores[seccion] = `No se pudo guardar. ${fallo.message || 'Intenta de nuevo en un momento.'}`
  } finally {
    guardando.value = false
  }
}

const ocupado = ref(false)

async function agregar(seccion, coleccion, campos) {
  errores[seccion] = ''
  let fila = campos
  if (coleccion === 'ofertas') {
    const { cpc, ...resto } = campos
    const codigo = String(cpc || '').replace(/\D/g, '')
    const descripcion = [codigo && `CPC ${codigo}`, resto.descripcion].filter(Boolean).join('\n')
    fila = descripcion ? { ...resto, descripcion } : resto
  }
  ocupado.value = true
  try {
    await props.acciones.agregar(coleccion, fila)
  } catch (fallo) {
    errores[seccion] = `No se pudo agregar. ${fallo.message || 'Intenta de nuevo en un momento.'}`
  } finally {
    ocupado.value = false
  }
}

async function quitar(seccion, coleccion, id) {
  errores[seccion] = ''
  try {
    await props.acciones.quitar(coleccion, id)
  } catch (fallo) {
    errores[seccion] = `No se pudo quitar. ${fallo.message || 'Intenta de nuevo en un momento.'}`
  }
}

defineExpose({ abrir })
</script>

<template>
  <div class="cert">
    <!-- ================================================================ RUC (SRI) -->
    <article class="cert__hoja" aria-labelledby="cert-sri-titulo">
      <header class="cert__cabecera">
        <p class="cert__sobre">Certificado</p>
        <h2 id="cert-sri-titulo">Registro Único de Contribuyentes</h2>
        <p class="cert__explica">Los datos de tu empresa en el mismo orden que tu certificado del RUC del SRI.</p>
      </header>

      <SeccionCertificado
        id="contribuyente"
        titulo="Datos del contribuyente"
        :editando="editando === 'contribuyente'"
        :guardando="guardando"
        :mensaje="mensajes.contribuyente"
        :error="errores.contribuyente"
        @editar="abrir('contribuyente')"
        @guardar="guardar"
        @cancelar="cancelar"
      >
        <dl class="cert__fila cert__fila--2">
          <CampoCertificado :etiqueta="etiquetaNombre" :valor="ver('razon_social')" @completar="completar('razon_social')" />
          <CampoCertificado etiqueta="Número RUC" :valor="ver('ruc')" @completar="completar('ruc')" />
        </dl>
        <dl class="cert__fila cert__fila--3">
          <CampoCertificado etiqueta="Nombre comercial" :valor="ver('nombre_comercial')" @completar="completar('nombre_comercial')" />
          <CampoCertificado etiqueta="Régimen" :valor="ver('regimen_tributario')" @completar="completar('regimen_tributario')" />
          <CampoCertificado etiqueta="Inicio de actividades" :valor="ver('fecha_inicio_actividades')" @completar="completar('fecha_inicio_actividades')" />
        </dl>
        <dl class="cert__fila cert__fila--3">
          <CampoCertificado etiqueta="Obligado a llevar contabilidad" :valor="ver('obligado_contabilidad')" @completar="completar('obligado_contabilidad')" />
          <CampoCertificado etiqueta="Tipo" :valor="ver('tipo_persona')" @completar="completar('tipo_persona')" />
        </dl>
        <template #edicion>
          <div class="cert__formulario">
            <template v-for="clave in EDICION.contribuyente" :key="clave">
              <fieldset v-if="DATOS[clave].tipo === 'sino'" class="cert__campo cert__sino">
                <legend>{{ DATOS[clave].etiqueta }}</legend>
                <div class="cert__sino-opciones">
                  <label><input :id="`cert-${clave}`" v-model="borrador[clave]" type="radio" :value="true" /> Sí</label>
                  <label><input v-model="borrador[clave]" type="radio" :value="false" /> No</label>
                </div>
              </fieldset>
              <label v-else class="cert__campo" :class="{ 'cert__campo--ancho': DATOS[clave].ancho }">
                <span class="cert__campo-etiqueta">{{ DATOS[clave].etiqueta }}</span>
                <select v-if="DATOS[clave].tipo === 'select'" :id="`cert-${clave}`" v-model="borrador[clave]">
                  <option v-for="opcion in DATOS[clave].opciones" :key="opcion.valor" :value="opcion.valor">{{ opcion.etiqueta }}</option>
                </select>
                <input
                  v-else
                  :id="`cert-${clave}`"
                  v-model="borrador[clave]"
                  :type="DATOS[clave].tipo || 'text'"
                  :inputmode="DATOS[clave].inputmode"
                  :maxlength="DATOS[clave].maxlength"
                  :placeholder="DATOS[clave].pista || ''"
                  :list="DATOS[clave].sugerencias ? `cert-lista-${clave}` : undefined"
                />
                <datalist v-if="DATOS[clave].sugerencias" :id="`cert-lista-${clave}`">
                  <option v-for="texto in DATOS[clave].sugerencias" :key="texto" :value="texto" />
                </datalist>
                <small v-if="DATOS[clave].ayuda" class="cert__campo-ayuda">{{ DATOS[clave].ayuda }}</small>
              </label>
            </template>
          </div>
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="domicilio"
        titulo="Domicilio tributario"
        :editando="editando === 'domicilio'"
        :guardando="guardando"
        :mensaje="mensajes.domicilio"
        :error="errores.domicilio"
        @editar="abrir('domicilio')"
        @guardar="guardar"
        @cancelar="cancelar"
      >
        <h4 class="cert__subtitulo">Ubicación geográfica</h4>
        <dl class="cert__fila cert__fila--2">
          <CampoCertificado etiqueta="Cantón o ciudad" :valor="ver('ciudad')" @completar="completar('ciudad')" />
        </dl>
        <h4 class="cert__subtitulo">Dirección</h4>
        <dl class="cert__fila">
          <CampoCertificado etiqueta="Calle, número, intersección y referencia" :valor="ver('direccion')" ancho @completar="completar('direccion')" />
        </dl>
        <template #edicion>
          <div class="cert__formulario">
            <label v-for="clave in EDICION.domicilio" :key="clave" class="cert__campo" :class="{ 'cert__campo--ancho': DATOS[clave].ancho }">
              <span class="cert__campo-etiqueta">{{ DATOS[clave].etiqueta }}</span>
              <input :id="`cert-${clave}`" v-model="borrador[clave]" type="text" />
              <small v-if="DATOS[clave].ayuda" class="cert__campo-ayuda">{{ DATOS[clave].ayuda }}</small>
            </label>
          </div>
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="contacto"
        titulo="Medios de contacto"
        :editando="editando === 'contacto'"
        :guardando="guardando"
        :mensaje="mensajes.contacto"
        :error="errores.contacto"
        @editar="abrir('contacto')"
        @guardar="guardar"
        @cancelar="cancelar"
      >
        <dl class="cert__fila cert__fila--3">
          <CampoCertificado etiqueta="Teléfono o celular" :valor="ver('telefono')" @completar="completar('telefono')" />
          <CampoCertificado etiqueta="Email" :valor="ver('email_contacto')" @completar="completar('email_contacto')" />
          <CampoCertificado etiqueta="Sitio web" :valor="ver('sitio_web')" @completar="completar('sitio_web')" />
        </dl>
        <template #edicion>
          <div class="cert__formulario">
            <label v-for="clave in EDICION.contacto" :key="clave" class="cert__campo">
              <span class="cert__campo-etiqueta">{{ DATOS[clave].etiqueta }}</span>
              <input
                :id="`cert-${clave}`"
                v-model="borrador[clave]"
                :type="DATOS[clave].tipo || 'text'"
                :inputmode="DATOS[clave].inputmode"
                :autocomplete="DATOS[clave].autocomplete"
                :placeholder="DATOS[clave].pista || ''"
              />
            </label>
          </div>
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="contactos"
        titulo="Representante legal y contactos"
        ayuda="El representante legal firma tus ofertas."
        modo="lista"
        :editando="editando === 'contactos'"
        :error="errores.contactos"
        @editar="abrir('contactos')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('contactos').length" class="cert__vinetas">
          <li v-for="fila in lista('contactos')" :key="fila.id">
            <strong>{{ RESUMENES.contactos(fila) }}</strong>
            <span v-if="DETALLES.contactos(fila)" class="cert__detalle">{{ DETALLES.contactos(fila) }}</span>
          </li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('contactos')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Personas de contacto"
            vacio="Agrega al representante legal para que firme tus ofertas."
            :filas="lista('contactos')"
            :campos="CAMPOS.contactos"
            :resumen="RESUMENES.contactos"
            :detalle="DETALLES.contactos"
            :ocupado="ocupado"
            @agregar="(c) => agregar('contactos', 'contactos', c)"
            @quitar="(id) => quitar('contactos', 'contactos', id)"
          />
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="actividades"
        titulo="Actividades económicas"
        modo="lista"
        :editando="editando === 'actividades'"
        :error="errores.actividades"
        @editar="abrir('actividades')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('actividades').length" class="cert__vinetas">
          <li v-for="fila in lista('actividades')" :key="fila.id">
            <span class="cert__mayusculas">{{ RESUMENES.actividades(fila) }}</span>
            <span v-if="fila.principal" class="cert__insignia">Principal</span>
          </li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('actividades')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Actividades"
            ayuda="Copia el código y la descripción de tu RUC, por ejemplo G4659 - VENTA AL POR MAYOR…"
            :filas="lista('actividades')"
            :campos="CAMPOS.actividades"
            :resumen="RESUMENES.actividades"
            :detalle="DETALLES.actividades"
            :ocupado="ocupado"
            @agregar="(c) => agregar('actividades', 'actividades', c)"
            @quitar="(id) => quitar('actividades', 'actividades', id)"
          />
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="cobertura"
        titulo="Establecimientos y cobertura"
        ayuda="Provincias y cantones donde tienes local o puedes entregar."
        modo="lista"
        :editando="editando === 'cobertura'"
        :error="errores.cobertura"
        @editar="abrir('cobertura')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('cobertura').length" class="cert__vinetas">
          <li v-for="fila in lista('cobertura')" :key="fila.id">{{ RESUMENES.cobertura(fila) }}</li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('cobertura')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Provincias y cantones"
            vacio="Indica dónde puedes entregar."
            :filas="lista('cobertura')"
            :campos="CAMPOS.cobertura"
            :resumen="RESUMENES.cobertura"
            :ocupado="ocupado"
            @agregar="(c) => agregar('cobertura', 'cobertura', c)"
            @quitar="(id) => quitar('cobertura', 'cobertura', id)"
          />
        </template>
      </SeccionCertificado>
    </article>

    <!-- ================================================================ RUP (SERCOP) -->
    <article class="cert__hoja" aria-labelledby="cert-rup-titulo">
      <header class="cert__cabecera">
        <p class="cert__sobre">Certificado</p>
        <h2 id="cert-rup-titulo">Registro Único de Proveedores (RUP)</h2>
        <p class="cert__explica">Lo que dice tu certificado del SERCOP: tu categoría y lo que puedes vender al Estado.</p>
      </header>

      <SeccionCertificado
        id="rup"
        titulo="Datos de la persona"
        :editando="editando === 'rup'"
        :guardando="guardando"
        :mensaje="mensajes.rup"
        :error="errores.rup"
        @editar="abrir('rup')"
        @guardar="guardar"
        @cancelar="cancelar"
      >
        <dl class="cert__fila cert__fila--2">
          <CampoCertificado etiqueta="Nombre completo" :valor="ver('razon_social')" @completar="completar('razon_social')" />
          <CampoCertificado etiqueta="RUC" :valor="ver('ruc')" @completar="completar('ruc')" />
        </dl>
        <dl class="cert__fila cert__fila--2">
          <CampoCertificado etiqueta="Categoría" :valor="ver('capacidad_ejecucion')" @completar="completar('capacidad_ejecucion')" />
          <CampoCertificado etiqueta="Estado en el RUP" :valor="ver('estado_rup')" @completar="completar('estado_rup')" />
        </dl>
        <p class="cert__nota">La dirección principal es la misma del domicilio tributario, más arriba.</p>
        <template #edicion>
          <div class="cert__formulario">
            <label v-for="clave in EDICION.rup" :key="clave" class="cert__campo" :class="{ 'cert__campo--ancho': DATOS[clave].ancho }">
              <span class="cert__campo-etiqueta">{{ DATOS[clave].etiqueta }}</span>
              <select v-if="DATOS[clave].tipo === 'select'" :id="`cert-${clave}`" v-model="borrador[clave]">
                <option v-for="opcion in DATOS[clave].opciones" :key="opcion.valor" :value="opcion.valor">{{ opcion.etiqueta }}</option>
              </select>
              <input v-else :id="`cert-${clave}`" v-model="borrador[clave]" type="text" :placeholder="DATOS[clave].pista || ''" />
              <small v-if="DATOS[clave].ayuda" class="cert__campo-ayuda">{{ DATOS[clave].ayuda }}</small>
            </label>
          </div>
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="cpc"
        titulo="Bienes, obras o servicios suministrados (CPC)"
        modo="lista"
        :editando="editando === 'cpc'"
        :error="errores.cpc"
        @editar="abrir('cpc')"
        @cancelar="cancelar"
      >
        <div v-if="filasCpc.length" class="cert__tabla-marco">
          <table class="cert__tabla">
            <thead>
              <tr>
                <th scope="col">Código</th>
                <th scope="col">Producto</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="fila in filasCpcVisibles" :key="fila.clave">
                <td class="cert__codigo numeros">{{ fila.codigo || 'Sin código' }}</td>
                <td>
                  <span v-if="fila.producto" class="cert__mayusculas">{{ fila.producto }}</span>
                  <span v-else class="cert__detalle">Sin descripción. Este código está en tu lista de búsqueda por CPC.</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="cert__vacio">
          Sin registrar. Lo más fácil es subir tu RUP: trae todos tus códigos.
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('cpc')">Completar a mano</button>
        </p>
        <button
          v-if="filasCpc.length > CPC_A_LA_VISTA"
          type="button"
          class="boton boton--secundario cert__completar"
          @click="verTodosCpc = !verTodosCpc"
        >
          {{ verTodosCpc ? 'Mostrar menos' : `Ver los ${filasCpc.length} códigos` }}
        </button>
        <template #edicion>
          <ColeccionPerfil
            titulo="Tus productos y servicios"
            ayuda="Con esto se llenan las líneas de tu proforma. Las características van una por línea."
            vacio="Agrega lo que vendes para armar proformas más rápido."
            :filas="lista('ofertas')"
            :campos="CAMPOS.ofertas"
            :resumen="RESUMENES.ofertas"
            :detalle="DETALLES.ofertas"
            :ocupado="ocupado"
            @agregar="(c) => agregar('cpc', 'ofertas', c)"
            @quitar="(id) => quitar('cpc', 'ofertas', id)"
          />
        </template>
      </SeccionCertificado>
    </article>

    <!-- ================================================================ datos para ofertar -->
    <article class="cert__hoja" aria-labelledby="cert-ofertas-titulo">
      <header class="cert__cabecera">
        <p class="cert__sobre">No están en los certificados</p>
        <h2 id="cert-ofertas-titulo">Datos para preparar tus ofertas</h2>
        <p class="cert__explica">Nos ayudan a elegir qué procesos te convienen y a llenar tus documentos.</p>
      </header>

      <SeccionCertificado
        id="dedicacion"
        titulo="A qué procesos te presentas"
        modo="lista"
        :editando="editando === 'dedicacion'"
        :error="errores.dedicacion"
        @editar="abrir('dedicacion')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('dedicaciones').length" class="cert__vinetas">
          <li v-for="fila in lista('dedicaciones')" :key="fila.id">
            <strong>{{ RESUMENES.dedicaciones(fila) }}</strong>
            <span v-if="DETALLES.dedicaciones(fila)" class="cert__detalle">{{ DETALLES.dedicaciones(fila) }}</span>
          </li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('dedicacion')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Tipo de contratación y de proceso"
            vacio="Sin esto no sabemos a qué procesos te presentas."
            :filas="lista('dedicaciones')"
            :campos="CAMPOS.dedicaciones"
            :resumen="RESUMENES.dedicaciones"
            :detalle="DETALLES.dedicaciones"
            :ocupado="ocupado"
            @agregar="(c) => agregar('dedicacion', 'dedicaciones', c)"
            @quitar="(id) => quitar('dedicacion', 'dedicaciones', id)"
          />
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="presupuesto"
        titulo="Montos que te interesan"
        :editando="editando === 'presupuesto'"
        :guardando="guardando"
        :mensaje="mensajes.presupuesto"
        :error="errores.presupuesto"
        @editar="abrir('presupuesto')"
        @guardar="guardar"
        @cancelar="cancelar"
      >
        <dl class="cert__fila cert__fila--2">
          <CampoCertificado etiqueta="Monto mínimo" :valor="ver('presupuesto_min')" @completar="completar('presupuesto_min')" />
          <CampoCertificado etiqueta="Monto máximo" :valor="ver('presupuesto_max')" @completar="completar('presupuesto_max')" />
        </dl>
        <template #edicion>
          <div class="cert__formulario">
            <label v-for="clave in EDICION.presupuesto" :key="clave" class="cert__campo">
              <span class="cert__campo-etiqueta">{{ DATOS[clave].etiqueta }}</span>
              <input :id="`cert-${clave}`" v-model="borrador[clave]" type="number" min="0" inputmode="decimal" />
            </label>
          </div>
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="palabras"
        titulo="Palabras clave"
        ayuda="Con ellas te buscamos oportunidades."
        modo="lista"
        :editando="editando === 'palabras'"
        :error="errores.palabras"
        @editar="abrir('palabras')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('palabras').length" class="cert__vinetas">
          <li v-for="fila in lista('palabras')" :key="fila.id">{{ fila.texto }}</li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('palabras')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Palabras o frases"
            :filas="lista('palabras')"
            :campos="CAMPOS.palabras"
            :resumen="RESUMENES.palabras"
            :ocupado="ocupado"
            @agregar="(c) => agregar('palabras', 'palabras', c)"
            @quitar="(id) => quitar('palabras', 'palabras', id)"
          />
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="experiencia"
        titulo="Experiencia en contratos"
        ayuda="Se usa cuando un proceso pide experiencia."
        modo="lista"
        :editando="editando === 'experiencia'"
        :error="errores.experiencia"
        @editar="abrir('experiencia')"
        @cancelar="cancelar"
      >
        <ul v-if="lista('experiencia').length" class="cert__vinetas">
          <li v-for="fila in lista('experiencia')" :key="fila.id">
            <strong>{{ RESUMENES.experiencia(fila) }}</strong>
            <span v-if="DETALLES.experiencia(fila)" class="cert__detalle">{{ DETALLES.experiencia(fila) }}</span>
          </li>
        </ul>
        <p v-else class="cert__vacio">
          Sin registrar
          <button type="button" class="boton boton--secundario cert__completar" @click="abrir('experiencia')">Completar</button>
        </p>
        <template #edicion>
          <ColeccionPerfil
            titulo="Contratos"
            :filas="lista('experiencia')"
            :campos="CAMPOS.experiencia"
            :resumen="RESUMENES.experiencia"
            :detalle="DETALLES.experiencia"
            :ocupado="ocupado"
            @agregar="(c) => agregar('experiencia', 'experiencia', c)"
            @quitar="(id) => quitar('experiencia', 'experiencia', id)"
          />
        </template>
      </SeccionCertificado>

      <SeccionCertificado
        id="respaldo"
        titulo="Personal y equipo"
        ayuda="Se usa cuando un proceso pide personal o equipo mínimo."
        modo="lista"
        :editando="editando === 'respaldo'"
        :error="errores.respaldo"
        @editar="abrir('respaldo')"
        @cancelar="cancelar"
      >
        <dl class="cert__fila cert__fila--2">
          <div class="cert__bloque">
            <dt class="cert__bloque-titulo">Personal técnico</dt>
            <dd>
              <ul v-if="lista('personal').length" class="cert__vinetas">
                <li v-for="fila in lista('personal')" :key="fila.id">
                  <strong>{{ RESUMENES.personal(fila) }}</strong>
                  <span v-if="DETALLES.personal(fila)" class="cert__detalle">{{ DETALLES.personal(fila) }}</span>
                </li>
              </ul>
              <span v-else class="cert__sin">Sin registrar</span>
            </dd>
          </div>
          <div class="cert__bloque">
            <dt class="cert__bloque-titulo">Equipo y herramientas</dt>
            <dd>
              <ul v-if="lista('equipo').length" class="cert__vinetas">
                <li v-for="fila in lista('equipo')" :key="fila.id">
                  <strong>{{ RESUMENES.equipo(fila) }}</strong>
                  <span v-if="DETALLES.equipo(fila)" class="cert__detalle">{{ DETALLES.equipo(fila) }}</span>
                </li>
              </ul>
              <span v-else class="cert__sin">Sin registrar</span>
            </dd>
          </div>
        </dl>
        <template #edicion>
          <ColeccionPerfil
            titulo="Personal técnico"
            :filas="lista('personal')"
            :campos="CAMPOS.personal"
            :resumen="RESUMENES.personal"
            :detalle="DETALLES.personal"
            :ocupado="ocupado"
            @agregar="(c) => agregar('respaldo', 'personal', c)"
            @quitar="(id) => quitar('respaldo', 'personal', id)"
          />
          <ColeccionPerfil
            titulo="Equipo y herramientas"
            :filas="lista('equipo')"
            :campos="CAMPOS.equipo"
            :resumen="RESUMENES.equipo"
            :detalle="DETALLES.equipo"
            :ocupado="ocupado"
            @agregar="(c) => agregar('respaldo', 'equipo', c)"
            @quitar="(id) => quitar('respaldo', 'equipo', id)"
          />
        </template>
      </SeccionCertificado>
    </article>
  </div>
</template>

<style scoped>
/* Texto base de 17 px y contraste alto: la pantalla la usan personas mayores (pedido del cliente). */
.cert { display: flex; flex-direction: column; gap: var(--e-6); font-size: var(--t-lg); color: var(--texto); line-height: 1.5; }
.cert__hoja { display: flex; flex-direction: column; gap: var(--e-6); padding: var(--e-6); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); }
.cert__cabecera { display: flex; flex-direction: column; gap: var(--e-1); }
.cert__sobre { font-size: 1rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: var(--texto-suave); }
.cert__cabecera h2 { font-size: var(--t-2xl); font-weight: 750; line-height: 1.2; color: var(--texto); }
.cert__explica { font-size: var(--t-lg); color: var(--texto-suave); max-width: 60ch; }

.cert__subtitulo { font-size: var(--t-lg); font-weight: 700; color: var(--texto); margin-top: var(--e-2); }
.cert__fila { display: grid; grid-template-columns: 1fr; column-gap: var(--e-6); margin: 0; border-bottom: 1px solid var(--borde); }
.cert__fila:last-of-type { border-bottom: 0; }
.cert__fila--2 { grid-template-columns: 2fr 1fr; }
.cert__fila--3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.cert__nota { font-size: 1rem; color: var(--texto-suave); }

.cert__vinetas { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding-left: 1.5rem; list-style: disc; }
.cert__vinetas li { overflow-wrap: anywhere; }
.cert__vinetas li::marker { color: var(--texto); }
.cert__vinetas strong { font-weight: 600; }
.cert__detalle { display: block; font-size: 1rem; color: var(--texto-suave); }
.cert__mayusculas { text-transform: uppercase; }
.cert__insignia { margin-left: var(--e-2); padding: 0 0.55rem; border-radius: var(--r-redondo); background: var(--acento-suave); color: var(--acento-fuerte); font-size: 1rem; font-weight: 650; }
.cert__vacio { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-3); color: var(--texto-suave); font-style: italic; }
.cert__sin { color: var(--texto-suave); font-style: italic; }
.cert__completar { min-height: 44px; padding: 0.5rem 1rem; font-size: 1rem; font-style: normal; align-self: flex-start; }
.cert__bloque { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-3) 0; }
.cert__bloque dd { margin: 0; }
.cert__bloque-titulo { font-size: 1rem; font-weight: 700; }

.cert__tabla-marco { overflow-x: auto; border: 1px solid var(--borde-fuerte); border-radius: var(--r-2); }
.cert__tabla { width: 100%; border-collapse: collapse; font-size: var(--t-lg); }
.cert__tabla th { padding: var(--e-3) var(--e-4); text-align: left; font-weight: 700; background: var(--superficie-3); color: var(--texto); border-bottom: 2px solid var(--borde-fuerte); }
.cert__tabla td { padding: var(--e-3) var(--e-4); vertical-align: top; border-bottom: 1px solid var(--borde); overflow-wrap: anywhere; }
.cert__tabla tbody tr:last-child td { border-bottom: 0; }
.cert__codigo { width: 9rem; font-weight: 700; white-space: nowrap; }

.cert__formulario { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: var(--e-4) var(--e-5); }
.cert__campo { display: flex; flex-direction: column; gap: var(--e-1); min-width: 0; margin: 0; padding: 0; border: 0; }
.cert__campo--ancho { grid-column: 1 / -1; }
.cert__campo-etiqueta, .cert__sino legend { font-size: var(--t-lg); font-weight: 700; color: var(--texto); padding: 0; }
.cert__campo input, .cert__campo select { width: 100%; min-height: 52px; padding: 0.65rem 0.9rem; border: 2px solid var(--borde-fuerte); border-radius: var(--r-2); background: var(--superficie); color: var(--texto); font: inherit; font-size: var(--t-lg); }
.cert__campo input:focus-visible, .cert__campo select:focus-visible { outline: 3px solid var(--acento); outline-offset: 1px; border-color: var(--acento); }
.cert__campo-ayuda { font-size: 1rem; color: var(--texto-suave); }
.cert__sino-opciones { display: flex; flex-wrap: wrap; gap: var(--e-3); margin-top: var(--e-1); }
.cert__sino-opciones label { display: inline-flex; align-items: center; gap: var(--e-2); min-height: 52px; min-width: 6rem; padding: 0 var(--e-4); border: 2px solid var(--borde-fuerte); border-radius: var(--r-2); cursor: pointer; font-size: var(--t-lg); }
.cert__sino-opciones label:has(input:checked) { border-color: var(--acento); background: var(--acento-tenue); font-weight: 700; }
.cert__sino-opciones input { width: 1.4rem; height: 1.4rem; }

@media (max-width: 640px) {
  .cert__hoja { padding: var(--e-4); gap: var(--e-5); }
  .cert__fila--2, .cert__fila--3 { grid-template-columns: 1fr; }
  .cert__cabecera h2 { font-size: var(--t-xl); }
  .cert__codigo { width: auto; }
  .cert__completar { width: 100%; }
}
</style>
