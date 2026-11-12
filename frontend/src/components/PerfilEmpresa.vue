<script setup>
/**
 * Mi empresa: con estos datos se rellena la oferta y se decide qué oportunidades aplican.
 *
 * El cliente pidió que la información se vea **igual que el certificado del RUC del SRI y el del
 * RUP**, porque muchos usuarios son personas mayores y se perdían en un formulario agrupado a
 * nuestra manera. Por eso la pantalla tiene dos partes y nada más:
 *
 * 1. «Actualiza tus datos con tus documentos»: tres caminos grandes (subir el RUP, buscar por RUC
 *    en el SRI, buscar los contratos ya ganados). Se abre uno a la vez y siempre termina en una
 *    propuesta que la persona revisa y elige antes de guardar: nadie debería teclear lo que el SRI
 *    o el SERCOP ya tienen, pero tampoco ver su perfil cambiado sin haberlo pedido.
 * 2. La ficha con forma de certificado (`FichaEmpresaCertificado`), que se lee por defecto y se
 *    edita de a una sección.
 *
 * El RUP puede llegar como PDF del SOCE, como PDF escaneado o como foto del papel. El servidor lee
 * el PDF con texto; si no trae texto (escaneado) o es una foto, el texto se saca aquí, en el
 * navegador, con OCR (`@/utils/ocr`), y se manda a `leerRupTexto`: la imagen no sale del equipo.
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import { api } from '@/api/endpoints'
import FichaEmpresaCertificado from '@/components/FichaEmpresaCertificado.vue'
import IconoPanel from '@/components/IconoPanel.vue'
import { consultarContratosEnNavegador, consultarRucEnNavegador } from '@/utils/consultasPublicas'
import { esImagen, textoDeArchivo } from '@/utils/ocr'

const perfil = ref(null)
const cpcVigilados = ref([])
const error = ref('')
const aviso = ref('')
const ficha = ref(null)

const CLAVES_IDENTIDAD = [
  'razon_social',
  'nombre_comercial',
  'tipo_persona',
  'ruc',
  'fecha_inicio_actividades',
  'regimen_tributario',
  'obligado_contabilidad',
  'estado_rup',
  'email_contacto',
  'telefono',
  'sitio_web',
  'direccion',
  'ciudad',
  'presupuesto_min',
  'presupuesto_max',
  'capacidad_ejecucion',
]

/** El perfil guardado, normalizado para comparar con lo que proponen el SRI o el RUP. */
const identidad = computed(() => {
  const datos = perfil.value || {}
  const fila = {}
  for (const clave of CLAVES_IDENTIDAD) {
    const valor = datos[clave]
    if (clave === 'obligado_contabilidad') fila[clave] = Boolean(valor)
    else if (clave === 'fecha_inicio_actividades') fila[clave] = valor ? String(valor).slice(0, 10) : ''
    else fila[clave] = valor == null ? '' : valor
  }
  return fila
})

const lista = (clave) => perfil.value?.[clave] || []

// --------------------------------------------------------------------------- carga

async function cargarCpc() {
  // La tabla de CPC se completa con los códigos vigilados; si esta lista falla, la ficha sigue.
  try {
    const respuesta = await api.listarCpc()
    cpcVigilados.value = respuesta?.claves || []
  } catch {
    cpcVigilados.value = []
  }
}

async function cargar() {
  error.value = ''
  try {
    perfil.value = await api.verPerfil()
  } catch (fallo) {
    error.value = `No pudimos abrir los datos de tu empresa. ${fallo.message}`
  }
  await cargarCpc()
}

/** Lo que la ficha usa para guardar. Lanzan el error para que la ficha lo diga en su sección. */
const acciones = {
  async guardar(campos) {
    perfil.value = await api.guardarPerfil(campos)
  },
  async agregar(coleccion, campos) {
    await api.agregarPerfil(coleccion, campos)
    perfil.value = await api.verPerfil()
  },
  async quitar(coleccion, id) {
    await api.quitarPerfil(coleccion, id)
    perfil.value = await api.verPerfil()
  },
}

// --------------------------------------------------------------------------- caminos

const camino = ref('')

const CAMINOS = [
  {
    id: 'rup',
    icono: 'documentos',
    titulo: 'Subir mi RUP (PDF o foto)',
    texto: 'El certificado del SERCOP. Trae tus códigos CPC y tus datos.',
  },
  {
    id: 'ruc',
    icono: 'perfil',
    titulo: 'Buscar por mi RUC (SRI)',
    texto: 'Trae tu razón social, régimen, dirección y representante.',
  },
  {
    id: 'contratos',
    icono: 'trofeo',
    titulo: 'Buscar mis contratos',
    texto: 'Lo que ya le vendiste al Estado: tu experiencia y tus CPC.',
  },
]

/** Un camino a la vez: abrir otro cierra el anterior, y volver a pulsar el mismo lo cierra. */
async function elegirCamino(id) {
  aviso.value = ''
  camino.value = camino.value === id ? '' : id
  if (camino.value === 'ruc' && !ruc.valor && identidad.value.ruc) ruc.valor = String(identidad.value.ruc)
  if (!camino.value) return
  await nextTick()
  document.getElementById(`perfil-camino-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

// --------------------------------------------------------------------------- RUP (PDF, escaneado o foto)

const rup = reactive({
  leyendo: false,
  aplicando: false,
  datos: null,
  error: '',
  arrastrando: false,
  filtro: '',
  progreso: '',
  porcentaje: null,
  usoOcr: false,
})
const rupCpc = reactive({})
const rupCampos = reactive({})
const rupCiiu = reactive({})
const ETIQUETAS_RUP = {
  razon_social: 'Razón social',
  nombre_comercial: 'Nombre comercial',
  tipo_persona: 'Tipo de contribuyente',
  regimen_tributario: 'Régimen',
  obligado_contabilidad: 'Obligado a llevar contabilidad',
  estado_rup: 'Estado en el RUP',
  capacidad_ejecucion: 'Categoría',
  email_contacto: 'Email',
  telefono: 'Teléfono',
  direccion: 'Dirección',
  ciudad: 'Ciudad',
}

function valorRup(clave, valor) {
  if (clave === 'obligado_contabilidad') return valor ? 'Sí' : 'No'
  if (clave === 'tipo_persona') return valor === 'natural' ? 'Persona natural' : 'Sociedad'
  return valor
}

const esPdf = (archivo) => /\.pdf$/i.test(archivo?.name || '') || archivo?.type === 'application/pdf'

/**
 * El servidor no pudo sacar nada útil del PDF: dice que no trae texto (escaneado) o no encontró
 * ni un CPC ni un dato. Entonces vale la pena leerlo con OCR.
 */
function necesitaOcr(datos) {
  const escaneado = (datos?.avisos || []).some((texto) => /escaneado/i.test(texto))
  const vacio = !(datos?.cpc || []).length && !Object.keys(datos?.identidad || {}).length
  return escaneado || vacio
}

function alProgresar({ pagina, paginas, porcentaje, mensaje } = {}) {
  // «Página X de Y» es lo que más tranquiliza: dice que avanza y cuánto falta. Sin páginas (p. ej.
  // mientras baja el idioma la primera vez) se usa la frase que da el lector, si la da.
  rup.progreso =
    pagina && paginas
      ? `Leyendo página ${pagina} de ${paginas}…`
      : mensaje || 'Leyendo tu documento…'
  rup.porcentaje = Number.isFinite(porcentaje) ? Math.round(porcentaje) : null
}

function mostrarRup(datos) {
  for (const clave of Object.keys(rupCpc)) delete rupCpc[clave]
  for (const clave of Object.keys(rupCampos)) delete rupCampos[clave]
  for (const clave of Object.keys(rupCiiu)) delete rupCiiu[clave]
  ;(datos.cpc || []).forEach((fila) => (rupCpc[fila.codigo] = true))
  ;(datos.actividades || []).forEach((fila) => (rupCiiu[fila.ciiu] = true))
  rupCampos.representante = Boolean(datos.representante)
  rupCampos.cobertura = Boolean(datos.cobertura?.length)
  for (const [clave, valor] of Object.entries(datos.identidad || {})) {
    // Lo que ya tiene otro valor no se pisa sin que la persona lo marque.
    const hoy = identidad.value[clave]
    rupCampos[clave] = !hoy || hoy === valor
  }
  rup.datos = { ...datos, cpc: datos.cpc || [] }
}

async function leerRup(archivo) {
  if (!archivo) return
  rup.error = ''
  rup.datos = null
  aviso.value = ''
  if (!esPdf(archivo) && !esImagen(archivo)) {
    rup.error = 'Ese archivo no se puede leer. Sube tu RUP en PDF o una foto (JPG o PNG).'
    return
  }
  rup.leyendo = true
  rup.usoOcr = false
  rup.progreso = 'Leyendo tu documento…'
  rup.porcentaje = null
  let delServidor = null
  try {
    if (esPdf(archivo)) {
      delServidor = await api.leerRup(archivo)
      if (!necesitaOcr(delServidor)) {
        mostrarRup(delServidor)
        return
      }
    }
    // Foto o PDF escaneado: el texto se saca aquí con OCR y el servidor solo lo interpreta.
    rup.usoOcr = true
    let leido
    try {
      leido = await textoDeArchivo(archivo, { onProgreso: alProgresar })
    } catch (fallo) {
      rup.error =
        `No pudimos leer el documento. ${fallo.message || ''} ` +
        'Si tienes el PDF original del SOCE («Imprimir RUP»), súbelo: se lee mejor.'
      return
    }
    if (!String(leido?.texto || '').trim()) {
      rup.error = 'No encontramos texto en el documento. Prueba con una foto más nítida, de frente y con buena luz.'
      return
    }
    // Un PDF que el servidor no pudo leer a veces sí trae texto para pdf.js: entonces no hubo OCR
    // y no hace falta el aviso de «revisa bien los números».
    rup.usoOcr = leido.uso_ocr !== false
    rup.progreso = 'Buscando tus datos en el texto…'
    rup.porcentaje = null
    mostrarRup(await api.leerRupTexto(leido.texto))
  } catch (fallo) {
    rup.error = `No pudimos leer tu RUP. ${fallo.message}`
  } finally {
    rup.leyendo = false
    rup.progreso = ''
  }
}

function alSoltarRup(evento) {
  rup.arrastrando = false
  leerRup(evento.dataTransfer?.files?.[0])
}

const rupCpcVisibles = computed(() => {
  const filtro = rup.filtro.trim().toLowerCase()
  const filas = rup.datos?.cpc || []
  return filtro
    ? filas.filter((f) => f.codigo.includes(filtro) || f.descripcion.toLowerCase().includes(filtro))
    : filas
})
const rupElegidos = computed(() => (rup.datos?.cpc || []).filter((f) => rupCpc[f.codigo]))
const rupRucDistinto = computed(
  () => rup.datos?.ruc && identidad.value.ruc && rup.datos.ruc !== identidad.value.ruc,
)
const rupTieneDatos = computed(
  () => Object.keys(rup.datos?.identidad || {}).length || rup.datos?.representante || rup.datos?.cobertura?.length,
)

function marcarTodosRup(valor) {
  for (const fila of rupCpcVisibles.value) rupCpc[fila.codigo] = valor
}

async function aplicarRup() {
  if (!rup.datos) return
  rup.aplicando = true
  rup.error = ''
  try {
    const campos = Object.fromEntries(
      Object.entries(rup.datos.identidad || {}).filter(([clave]) => rupCampos[clave]),
    )
    const resultado = await api.aplicarRup({
      identidad: campos,
      representante: rupCampos.representante && rup.datos.representante ? rup.datos.representante : null,
      cpc: rupElegidos.value,
      actividades: (rup.datos.actividades || []).filter((fila) => rupCiiu[fila.ciiu]),
      cobertura: rupCampos.cobertura ? rup.datos.cobertura || [] : [],
    })
    await cargar()
    aviso.value =
      `Listo. Guardamos ${resultado.datos} datos, ${resultado.actividades} actividades y ` +
      `${resultado.cpc_vigilados} códigos CPC de tu RUP. Puedes revisarlos abajo.`
    rup.datos = null
    camino.value = ''
  } catch (fallo) {
    rup.error = `No se pudo guardar. ${fallo.message}`
  } finally {
    rup.aplicando = false
  }
}

// --------------------------------------------------------------------------- consulta del RUC

const ruc = reactive({ valor: '', consultando: false, propuesta: null, error: '', aplicando: false })
const elegidos = reactive({})

const ETIQUETAS_PROPUESTA = {
  razon_social: 'Razón social',
  nombre_comercial: 'Nombre comercial',
  tipo_persona: 'Tipo de persona',
  regimen_tributario: 'Régimen',
  obligado_contabilidad: 'Obligado a llevar contabilidad',
  fecha_inicio_actividades: 'Inicio de actividades',
  direccion: 'Dirección',
  ciudad: 'Ciudad',
}

function legible(clave, valor) {
  if (typeof valor === 'boolean') return valor ? 'Sí' : 'No'
  if (clave === 'tipo_persona') return valor === 'juridica' ? 'Sociedad' : 'Persona natural'
  return String(valor)
}

/** Lo que el perfil tiene ahora, para avisar de qué se reemplaza. */
function actual(clave) {
  const valor = identidad.value[clave]
  if (clave === 'obligado_contabilidad') return valor ? true : ''
  return valor === '' || valor == null ? '' : valor
}

function nuevasCoberturas() {
  const existentes = new Set(lista('cobertura').map((fila) => `${fila.provincia}|${fila.canton || ''}`))
  return (ruc.propuesta?.cobertura || []).filter(
    (fila) => !existentes.has(`${fila.provincia}|${fila.canton || ''}`),
  )
}

const filasPropuesta = computed(() => {
  const propuesta = ruc.propuesta
  if (!propuesta) return []
  const filas = Object.entries(propuesta.identidad).map(([clave, valor]) => {
    const previo = actual(clave)
    const distinto = previo !== '' && String(previo) !== String(valor)
    return {
      clave,
      etiqueta: ETIQUETAS_PROPUESTA[clave] || clave,
      valor: legible(clave, valor),
      reemplaza: distinto ? legible(clave, previo) : '',
    }
  })
  if (propuesta.representante) {
    const existe = lista('contactos').some((fila) => fila.cedula === propuesta.representante.cedula)
    if (!existe) {
      filas.push({
        clave: 'representante',
        etiqueta: 'Representante legal',
        valor: `${propuesta.representante.nombre} · ${propuesta.representante.cedula}`,
        reemplaza: '',
      })
    }
  }
  const provinciasNuevas = nuevasCoberturas()
  if (provinciasNuevas.length) {
    filas.push({
      clave: 'cobertura',
      etiqueta: 'Establecimientos abiertos (dónde entregas)',
      valor: provinciasNuevas.map((fila) => fila.provincia).join(', '),
      reemplaza: '',
    })
  }
  if (propuesta.actividad && !lista('actividades').length) {
    filas.push({
      clave: 'actividad',
      etiqueta: 'Actividad económica principal',
      valor: propuesta.actividad,
      reemplaza: '',
    })
  }
  return filas
})

async function consultarRuc() {
  ruc.error = ''
  ruc.propuesta = null
  aviso.value = ''
  const limpio = ruc.valor.replace(/\s/g, '')
  if (!/^\d{13}$/.test(limpio)) {
    ruc.error = 'El RUC debe tener 13 números, sin espacios ni guiones.'
    return
  }
  ruc.consultando = true
  try {
    // Primero desde el navegador: el SRI contesta a cualquier página y así el servidor no gasta nada.
    // Si no se puede llegar (red, bloqueo), se pide al servidor, que lo consulta por nosotros.
    try {
      ruc.propuesta = await consultarRucEnNavegador(limpio)
    } catch (fallo) {
      if (fallo.definitivo) throw fallo
      ruc.propuesta = await api.consultarRuc(limpio)
    }
    for (const clave of Object.keys(elegidos)) delete elegidos[clave]
    for (const fila of filasPropuesta.value) {
      // Lo que ya tiene un valor distinto no se pisa sin que la persona lo marque.
      elegidos[fila.clave] = !fila.reemplaza
    }
  } catch (fallo) {
    ruc.error = `No pudimos consultar al SRI. ${fallo.message}`
  } finally {
    ruc.consultando = false
  }
}

async function aplicarPropuesta() {
  const propuesta = ruc.propuesta
  if (!propuesta) return
  ruc.aplicando = true
  ruc.error = ''
  try {
    const campos = { ruc: propuesta.ruc }
    for (const [clave, valor] of Object.entries(propuesta.identidad)) {
      if (elegidos[clave]) campos[clave] = valor
    }
    await api.guardarPerfil(campos)
    if (elegidos.representante && propuesta.representante) {
      await api.agregarPerfil('contactos', propuesta.representante)
    }
    if (elegidos.cobertura) {
      for (const fila of nuevasCoberturas()) await api.agregarPerfil('cobertura', fila)
    }
    if (elegidos.actividad && propuesta.actividad) {
      await api.agregarPerfil('actividades', {
        ciiu: propuesta.actividad.slice(0, 200),
        principal: true,
      })
    }
    await cargar()
    ruc.propuesta = null
    ruc.valor = ''
    camino.value = ''
    aviso.value =
      'Listo. Guardamos los datos del SRI. Completa abajo lo que el SRI no publica: email, teléfono y estado en el RUP.'
  } catch (fallo) {
    ruc.error = `No se pudo guardar. ${fallo.message}`
  } finally {
    ruc.aplicando = false
  }
}

// --------------------------------------------------------------------------- historial de contratos

const hist = reactive({ cargando: false, datos: null, error: '', aplicando: false })
const cpcElegidos = reactive({})
const expElegidas = reactive({})

const puedeBuscarHistorial = computed(
  () => /^\d{13}$/.test(String(identidad.value.ruc || '')) && Boolean(identidad.value.razon_social),
)

/** Lo que los datos abiertos atribuyen a este RUC. Tarda ~15 s: consulta un servicio ajeno. */
async function buscarContratos() {
  hist.error = ''
  hist.datos = null
  aviso.value = ''
  hist.cargando = true
  try {
    let datos
    try {
      datos = await consultarContratosEnNavegador(identidad.value.ruc, identidad.value.razon_social)
    } catch {
      datos = await api.consultarContratos(identidad.value.ruc, identidad.value.razon_social)
    }
    for (const clave of Object.keys(cpcElegidos)) delete cpcElegidos[clave]
    for (const clave of Object.keys(expElegidas)) delete expElegidas[clave]
    datos.cpc.forEach((fila) => (cpcElegidos[fila.codigo] = true))
    datos.experiencia.forEach((_, n) => (expElegidas[n] = true))
    hist.datos = datos
  } catch (fallo) {
    hist.error = `No pudimos buscar tus contratos. ${fallo.message}`
  } finally {
    hist.cargando = false
  }
}

async function aplicarHistorial() {
  if (!hist.datos) return
  hist.aplicando = true
  hist.error = ''
  try {
    const codigos = hist.datos.cpc.filter((fila) => cpcElegidos[fila.codigo]).map((fila) => fila.codigo)
    if (codigos.length) await api.agregarCpc(codigos)
    const existentes = new Set(lista('experiencia').map((f) => `${f.entidad}|${f.anio}|${f.cpc}`))
    let agregadas = 0
    for (const [n, fila] of hist.datos.experiencia.entries()) {
      if (!expElegidas[n] || existentes.has(`${fila.entidad}|${fila.anio}|${fila.cpc}`)) continue
      const campos = Object.fromEntries(
        Object.entries(fila).filter(([, valor]) => valor !== null && valor !== ''),
      )
      await api.agregarPerfil('experiencia', campos)
      agregadas += 1
    }
    perfil.value = await api.verPerfil()
    await cargarCpc()
    aviso.value = `Listo. Agregamos ${codigos.length} códigos CPC y ${agregadas} contrato(s) a tu experiencia.`
    hist.datos = null
    camino.value = ''
  } catch (fallo) {
    hist.error = `No se pudo guardar. ${fallo.message}`
  } finally {
    hist.aplicando = false
  }
}

const usd = (valor) => (valor == null ? '' : `USD ${Number(valor).toLocaleString('es-EC')}`)

// --------------------------------------------------------------------------- qué falta

/** `seccion` y `campo` son los de la ficha: «Completar» abre esa sección con el cursor en el dato. */
const PUNTOS = computed(() => [
  { seccion: 'contribuyente', campo: 'ruc', etiqueta: 'RUC', ok: /^\d{13}$/.test(String(identidad.value.ruc || '')) },
  { seccion: 'contribuyente', campo: 'razon_social', etiqueta: 'Razón social', ok: Boolean(identidad.value.razon_social) },
  { seccion: 'contribuyente', campo: 'tipo_persona', etiqueta: 'Tipo de contribuyente', ok: Boolean(identidad.value.tipo_persona) },
  { seccion: 'contacto', campo: 'telefono', etiqueta: 'Email y teléfono', ok: Boolean(identidad.value.email_contacto && identidad.value.telefono) },
  { seccion: 'domicilio', campo: 'direccion', etiqueta: 'Dirección', ok: Boolean(identidad.value.direccion && identidad.value.ciudad) },
  { seccion: 'contactos', etiqueta: 'Representante legal', ok: lista('contactos').some((fila) => fila.tipo === 'representante_legal') },
  { seccion: 'dedicacion', etiqueta: 'A qué procesos te presentas', ok: lista('dedicaciones').length > 0 },
  { seccion: 'cpc', etiqueta: 'Bienes o servicios (CPC)', ok: lista('ofertas').length > 0 },
  { seccion: 'cobertura', etiqueta: 'Dónde entregas', ok: lista('cobertura').length > 0 },
  { seccion: 'experiencia', etiqueta: 'Experiencia', ok: lista('experiencia').length > 0 },
])
const completitud = computed(() => {
  const hechos = PUNTOS.value.filter((punto) => punto.ok).length
  return {
    hechos,
    total: PUNTOS.value.length,
    porcentaje: Math.round((hechos / PUNTOS.value.length) * 100),
  }
})
const faltan = computed(() => PUNTOS.value.filter((punto) => !punto.ok))

function completar(punto) {
  ficha.value?.abrir(punto.seccion, punto.campo || '')
}

onMounted(cargar)
</script>

<template>
  <div class="perfil">
    <header class="perfil__cabecera">
      <h2>Mi empresa</h2>
      <p>Con estos datos llenamos tus ofertas y te mostramos los procesos que te convienen.</p>
    </header>

    <p v-if="error" class="perfil__mensaje perfil__mensaje--error" role="alert">{{ error }}</p>

    <!-- ============================================================ documentos -->
    <section class="docs" aria-labelledby="perfil-docs-titulo">
      <div>
        <h3 id="perfil-docs-titulo">Actualiza tus datos con tus documentos</h3>
        <p class="docs__explica">Elige una opción. Leemos tus datos, tú revisas y decides qué guardar.</p>
      </div>

      <p v-if="aviso" class="perfil__mensaje perfil__mensaje--ok" role="status">{{ aviso }}</p>

      <div class="docs__caminos">
        <button
          v-for="opcion in CAMINOS"
          :key="opcion.id"
          type="button"
          class="camino"
          :class="{ 'camino--activo': camino === opcion.id }"
          :aria-expanded="camino === opcion.id"
          :aria-controls="`perfil-camino-${opcion.id}`"
          @click="elegirCamino(opcion.id)"
        >
          <IconoPanel :nombre="opcion.icono" :tamano="32" />
          <span class="camino__texto">
            <strong>{{ opcion.titulo }}</strong>
            <span>{{ opcion.texto }}</span>
          </span>
        </button>
      </div>

      <!-- ------------------------------------------------ RUP -->
      <div v-if="camino === 'rup'" id="perfil-camino-rup" class="docs__panel">
        <h4>Subir mi RUP</h4>
        <p class="docs__explica">
          Sirve el PDF que imprimes en el SOCE («Datos generales» → «Imprimir RUP»), un PDF escaneado o
          una foto del certificado. Si tienes también el certificado del RUC del SRI, puedes subirlo
          en el mismo PDF.
        </p>

        <label
          class="rup-zona"
          :class="{ 'rup-zona--activa': rup.arrastrando, 'rup-zona--ocupada': rup.leyendo }"
          @dragover.prevent="rup.arrastrando = true"
          @dragleave.prevent="rup.arrastrando = false"
          @drop.prevent="alSoltarRup"
        >
          <input
            class="solo-lectores"
            type="file"
            accept="application/pdf,image/*"
            :disabled="rup.leyendo"
            @change="leerRup($event.target.files[0]); $event.target.value = ''"
          />
          <IconoPanel nombre="descargar" :tamano="36" class="rup-zona__icono" />
          <strong>{{ rup.leyendo ? 'Leyendo tu RUP…' : 'Pulsa aquí para elegir tu RUP' }}</strong>
          <span v-if="!rup.leyendo" class="rup-zona__boton" aria-hidden="true">Elegir archivo o foto</span>
          <small>PDF o foto. También puedes arrastrar el archivo hasta aquí.</small>
        </label>

        <div v-if="rup.leyendo" class="rup-progreso" role="status" aria-live="polite">
          <strong>{{ rup.progreso || 'Leyendo tu documento…' }}</strong>
          <div
            class="rup-progreso__barra"
            :class="{ 'rup-progreso__barra--indefinida': rup.porcentaje == null }"
            role="progressbar"
            :aria-valuenow="rup.porcentaje ?? undefined"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <span :style="rup.porcentaje != null ? { width: rup.porcentaje + '%' } : null" />
          </div>
          <small v-if="rup.usoOcr">Las fotos y los documentos escaneados tardan un poco más. No cierres esta página.</small>
        </div>
        <p v-if="rup.error" class="perfil__mensaje perfil__mensaje--error" role="alert">{{ rup.error }}</p>

        <div v-if="rup.datos" class="perfil__propuesta">
          <p class="docs__explica">
            <strong>Revisa lo que encontramos.</strong> Lo marcado se guarda en tu perfil. Quita la
            marca de lo que no quieras cambiar.
          </p>
          <p v-if="rup.usoOcr" class="perfil__mensaje perfil__mensaje--aviso">
            Leímos el documento desde una imagen: revisa bien números y nombres antes de guardar.
          </p>
          <p v-for="texto in rup.datos.avisos" :key="texto" class="perfil__mensaje perfil__mensaje--aviso">{{ texto }}</p>
          <p v-if="rupRucDistinto" class="perfil__mensaje perfil__mensaje--aviso">
            El RUC del documento ({{ rup.datos.ruc }}) no es el de tu perfil ({{ identidad.ruc }}).
            Revisa que sea el documento de tu empresa.
          </p>

          <template v-if="rupTieneDatos">
            <h4>Datos encontrados</h4>
            <ul class="perfil__filas">
              <li v-for="(valor, clave) in rup.datos.identidad" :key="clave">
                <label>
                  <input v-model="rupCampos[clave]" type="checkbox" />
                  <span class="perfil__fila-texto">
                    <small>{{ ETIQUETAS_RUP[clave] || clave }}</small>
                    <strong>{{ valorRup(clave, valor) }}</strong>
                    <em v-if="identidad[clave] && identidad[clave] !== valor">Hoy dice: {{ valorRup(clave, identidad[clave]) }}</em>
                  </span>
                </label>
              </li>
              <li v-if="rup.datos.representante">
                <label>
                  <input v-model="rupCampos.representante" type="checkbox" />
                  <span class="perfil__fila-texto">
                    <small>Representante legal</small>
                    <strong>{{ rup.datos.representante.nombre }}</strong>
                    <em v-if="rup.datos.representante.cedula">C.I. {{ rup.datos.representante.cedula }}</em>
                  </span>
                </label>
              </li>
              <li v-if="rup.datos.cobertura?.length">
                <label>
                  <input v-model="rupCampos.cobertura" type="checkbox" />
                  <span class="perfil__fila-texto">
                    <small>Dónde entregas</small>
                    <strong>{{ rup.datos.cobertura.map((c) => [c.canton, c.provincia].filter(Boolean).join(', ')).join(' · ') }}</strong>
                  </span>
                </label>
              </li>
            </ul>
          </template>

          <template v-if="rup.datos.actividades?.length">
            <h4>
              Actividades económicas
              <span class="perfil__sello">{{ rup.datos.actividades.filter((f) => rupCiiu[f.ciiu]).length }} de {{ rup.datos.actividades.length }}</span>
            </h4>
            <ul class="rup-cpc">
              <li v-for="fila in rup.datos.actividades" :key="fila.ciiu">
                <label class="rup-cpc__fila" :class="{ 'rup-cpc__fila--activa': rupCiiu[fila.ciiu] }">
                  <input v-model="rupCiiu[fila.ciiu]" type="checkbox" />
                  <span class="rup-cpc__codigo numeros">{{ fila.ciiu }}</span>
                  <span class="rup-cpc__texto">{{ fila.descripcion }}</span>
                  <span class="rup-cpc__tipo">{{ fila.principal ? 'Principal' : '' }}</span>
                </label>
              </li>
            </ul>
          </template>
          <p v-if="rup.datos.documentos?.length" class="perfil__nota">
            Leído de: {{ rup.datos.documentos.join(' y ') }}.
          </p>

          <template v-if="rup.datos.cpc.length">
            <div class="rup-cpc__cabecera">
              <h4>
                Bienes, obras o servicios (CPC)
                <span class="perfil__sello">{{ rupElegidos.length }} de {{ rup.datos.cpc.length }} elegidos</span>
              </h4>
              <div class="rup-cpc__herramientas">
                <input v-model="rup.filtro" class="entrada" placeholder="Buscar por código o texto" aria-label="Buscar en la lista de CPC" />
                <button type="button" class="boton boton--secundario" @click="marcarTodosRup(true)">Marcar todos</button>
                <button type="button" class="boton boton--secundario" @click="marcarTodosRup(false)">Quitar todas las marcas</button>
              </div>
            </div>
            <ul class="rup-cpc">
              <li v-for="fila in rupCpcVisibles" :key="fila.codigo">
                <label class="rup-cpc__fila" :class="{ 'rup-cpc__fila--activa': rupCpc[fila.codigo] }">
                  <input v-model="rupCpc[fila.codigo]" type="checkbox" />
                  <span class="rup-cpc__codigo numeros">{{ fila.codigo }}</span>
                  <span class="rup-cpc__texto">{{ fila.descripcion }}</span>
                  <span class="rup-cpc__tipo">{{ '01234'.includes(fila.codigo[0]) ? 'Bien' : 'Servicio' }}</span>
                </label>
              </li>
            </ul>
            <p class="perfil__nota">
              Cada código marcado se usa para buscarte procesos y avisarte, y queda en tu tabla de
              bienes y servicios con su descripción. Lo que ya tenías no se repite.
            </p>
          </template>

          <div class="perfil__acciones">
            <button class="boton boton--principal" type="button" :disabled="rup.aplicando" @click="aplicarRup">
              {{ rup.aplicando ? 'Guardando…' : `Guardar lo marcado (${rupElegidos.length} CPC)` }}
            </button>
            <button class="boton boton--secundario" type="button" @click="rup.datos = null">Cancelar</button>
          </div>
        </div>
      </div>

      <!-- ------------------------------------------------ RUC -->
      <div v-if="camino === 'ruc'" id="perfil-camino-ruc" class="docs__panel">
        <h4>Buscar por mi RUC en el SRI</h4>
        <p class="docs__explica">
          Escribe tu RUC y pulsa «Buscar». Traemos lo que publica el SRI y tú eliges qué guardar. El
          SRI no publica tu email, tu teléfono ni tus códigos CPC: esos se completan abajo o con tu RUP.
        </p>
        <form class="perfil__ruc-form" @submit.prevent="consultarRuc">
          <label>
            <span class="perfil__etiqueta">Número de RUC</span>
            <input
              v-model="ruc.valor"
              inputmode="numeric"
              maxlength="13"
              autocomplete="off"
              placeholder="13 números"
              aria-describedby="perfil-ruc-error"
            />
          </label>
          <button class="boton boton--principal" type="submit" :disabled="ruc.consultando || ruc.valor.length < 13">
            {{ ruc.consultando ? 'Buscando…' : 'Buscar' }}
          </button>
        </form>
        <p class="perfil__nota">
          Usamos la consulta pública del SRI. Si no responde, intenta más tarde o llena los datos a mano.
        </p>
        <p v-if="ruc.error" id="perfil-ruc-error" class="perfil__mensaje perfil__mensaje--error" role="alert">
          {{ ruc.error }}
        </p>

        <div v-if="ruc.propuesta" class="perfil__propuesta">
          <h4>
            {{ ruc.propuesta.identidad.razon_social || ruc.propuesta.ruc }}
            <span class="perfil__sello" :class="{ 'perfil__sello--alerta': ruc.propuesta.estado_sri !== 'ACTIVO' }">
              {{ ruc.propuesta.estado_sri || 'Sin estado' }} en el SRI
            </span>
          </h4>
          <p class="docs__explica">
            <strong>Revisa lo que encontramos.</strong> Lo marcado se guarda en tu perfil.
          </p>
          <p v-for="texto in ruc.propuesta.avisos" :key="texto" class="perfil__mensaje perfil__mensaje--aviso">
            {{ texto }}
          </p>
          <ul class="perfil__filas">
            <li v-for="fila in filasPropuesta" :key="fila.clave">
              <label>
                <input v-model="elegidos[fila.clave]" type="checkbox" />
                <span class="perfil__fila-texto">
                  <small>{{ fila.etiqueta }}</small>
                  <strong>{{ fila.valor }}</strong>
                  <em v-if="fila.reemplaza">Hoy dice: {{ fila.reemplaza }}</em>
                </span>
              </label>
            </li>
          </ul>
          <p class="perfil__nota">El SRI no publica: {{ ruc.propuesta.no_publica.join(', ') }}.</p>
          <div class="perfil__acciones">
            <button class="boton boton--principal" type="button" :disabled="ruc.aplicando" @click="aplicarPropuesta">
              {{ ruc.aplicando ? 'Guardando…' : 'Guardar lo marcado' }}
            </button>
            <button class="boton boton--secundario" type="button" @click="ruc.propuesta = null">Cancelar</button>
          </div>
        </div>
      </div>

      <!-- ------------------------------------------------ contratos -->
      <div v-if="camino === 'contratos'" id="perfil-camino-contratos" class="docs__panel">
        <h4>Buscar mis contratos</h4>
        <p class="docs__explica">
          Buscamos en los datos públicos del SERCOP los contratos que ganó tu RUC. Te proponemos tus
          códigos CPC y tu experiencia. No reemplaza a tu RUP: muestra lo que ya vendiste.
        </p>
        <div class="perfil__acciones">
          <button
            class="boton boton--principal"
            type="button"
            :disabled="!puedeBuscarHistorial || hist.cargando"
            @click="buscarContratos"
          >
            {{ hist.cargando ? 'Buscando tus contratos…' : 'Buscar mis contratos' }}
          </button>
        </div>
        <p v-if="hist.cargando" class="perfil__nota" role="status">Tarda unos 15 segundos. No cierres esta página.</p>
        <p v-else-if="!puedeBuscarHistorial" class="perfil__mensaje perfil__mensaje--aviso">
          Primero necesitamos tu RUC y tu razón social. Usa «Buscar por mi RUC» o complétalos abajo
          en «Datos del contribuyente».
        </p>
        <p v-if="hist.error" class="perfil__mensaje perfil__mensaje--error" role="alert">{{ hist.error }}</p>

        <div v-if="hist.datos" class="perfil__propuesta">
          <p v-if="!hist.datos.verificados" class="perfil__mensaje perfil__mensaje--aviso">
            No encontramos contratos ganados con este RUC en los últimos 3 años. Si vendes con otro
            nombre o por catálogo, agrega tu experiencia a mano más abajo.
          </p>
          <template v-else>
            <p class="perfil__nota">
              Encontramos {{ hist.datos.contratos_total }} contratos. Revisamos los
              {{ hist.datos.revisados }} más recientes y {{ hist.datos.verificados }} son de tu RUC
              ({{ usd(hist.datos.monto_revisado) }}).
            </p>
            <h4>Códigos CPC con los que vendiste</h4>
            <ul class="perfil__filas">
              <li v-for="fila in hist.datos.cpc" :key="fila.codigo">
                <label>
                  <input v-model="cpcElegidos[fila.codigo]" type="checkbox" />
                  <span class="perfil__fila-texto">
                    <strong>{{ fila.codigo }}</strong>
                    <small>{{ fila.descripcion }}</small>
                    <em>{{ fila.veces }} contrato(s)</em>
                  </span>
                </label>
              </li>
            </ul>
            <h4>Contratos para tu experiencia</h4>
            <ul class="perfil__filas">
              <li v-for="(fila, n) in hist.datos.experiencia" :key="n">
                <label>
                  <input v-model="expElegidas[n]" type="checkbox" />
                  <span class="perfil__fila-texto">
                    <strong>{{ fila.entidad }}</strong>
                    <small>{{ fila.objeto }}</small>
                    <em>{{ [fila.anio, usd(fila.monto), fila.cpc && `CPC ${fila.cpc}`].filter(Boolean).join(' · ') }}</em>
                  </span>
                </label>
              </li>
            </ul>
            <p class="perfil__nota">{{ hist.datos.aviso }}</p>
            <div class="perfil__acciones">
              <button class="boton boton--principal" type="button" :disabled="hist.aplicando" @click="aplicarHistorial">
                {{ hist.aplicando ? 'Guardando…' : 'Guardar lo marcado' }}
              </button>
              <button class="boton boton--secundario" type="button" @click="hist.datos = null">Cancelar</button>
            </div>
          </template>
        </div>
      </div>
    </section>

    <!-- ============================================================ qué falta -->
    <section v-if="perfil" class="faltan" aria-labelledby="perfil-faltan-titulo">
      <div class="faltan__cifra">
        <h3 id="perfil-faltan-titulo">Tu información está completa al {{ completitud.porcentaje }} %</h3>
        <div
          class="faltan__barra"
          role="progressbar"
          :aria-valuenow="completitud.porcentaje"
          aria-valuemin="0"
          aria-valuemax="100"
          :aria-label="`${completitud.hechos} de ${completitud.total} datos completos`"
        >
          <span :style="{ width: completitud.porcentaje + '%' }" />
        </div>
      </div>
      <template v-if="faltan.length">
        <p>Te falta:</p>
        <ul class="faltan__lista">
          <li v-for="punto in faltan" :key="punto.etiqueta">
            <button type="button" class="boton boton--secundario" @click="completar(punto)">
              Completar: {{ punto.etiqueta }}
            </button>
          </li>
        </ul>
      </template>
      <p v-else class="faltan__listo">No te falta nada. ¡Bien hecho!</p>
    </section>

    <!-- ============================================================ ficha -->
    <FichaEmpresaCertificado
      v-if="perfil"
      ref="ficha"
      :perfil="perfil"
      :cpc-vigilados="cpcVigilados"
      :acciones="acciones"
    />
    <p v-else-if="!error" class="perfil__nota" role="status">Cargando los datos de tu empresa…</p>
  </div>
</template>

<style scoped>
/*
 * Pantalla pensada para personas mayores (pedido del cliente): texto de 17 px como mínimo, botones
 * de 48 px de alto con palabras, casillas grandes y contraste alto (texto en `--texto`, no en gris
 * tenue). Los colores son los tokens de main.css, así que el tema oscuro sale solo.
 */
.perfil { display: flex; flex-direction: column; gap: var(--e-6); padding-bottom: var(--e-7); font-size: var(--t-lg); line-height: 1.5; color: var(--texto); }
.perfil h2 { font-size: var(--t-3xl); font-weight: 750; line-height: 1.15; }
.perfil h3 { font-size: var(--t-2xl); font-weight: 700; line-height: 1.2; }
.perfil h4 { font-size: var(--t-xl); font-weight: 700; }
.perfil__cabecera p { margin-top: var(--e-1); color: var(--texto-suave); font-size: var(--t-lg); }
.perfil__nota { color: var(--texto-suave); font-size: 1rem; }
.perfil__etiqueta { display: block; margin-bottom: var(--e-1); font-weight: 700; font-size: var(--t-lg); }

.perfil :deep(.boton) { min-height: 48px; padding: 0.6rem 1.25rem; font-size: var(--t-lg); font-weight: 650; white-space: normal; text-align: center; }
.perfil :deep(.boton:focus-visible), .camino:focus-visible { outline: 3px solid var(--acento); outline-offset: 2px; }

.perfil__mensaje { padding: var(--e-3) var(--e-4); border-radius: var(--r-2); font-size: 1rem; font-weight: 600; }
.perfil__mensaje--error { background: var(--error-suave); color: var(--error); }
.perfil__mensaje--ok { background: var(--ok-suave); color: var(--ok); }
.perfil__mensaje--aviso { background: var(--aviso-suave); color: var(--aviso); }

/* --- Documentos ------------------------------------------------------------------------------ */
.docs { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-6); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); }
.docs__explica { color: var(--texto-suave); font-size: var(--t-lg); max-width: 65ch; margin-top: var(--e-1); }
.docs__explica strong { color: var(--texto); }
.docs__caminos { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--e-4); }
.camino { display: flex; align-items: flex-start; gap: var(--e-3); min-height: 6.5rem; padding: var(--e-4) var(--e-5); border: 2px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); color: var(--texto); text-align: left; font: inherit; cursor: pointer; transition: border-color var(--rapido) var(--curva), background-color var(--rapido) var(--curva); }
.camino:hover { border-color: var(--acento); }
.camino--activo { border-color: var(--acento); background: var(--acento-tenue); }
.camino :deep(.icono) { color: var(--acento); margin-top: 2px; }
.camino__texto { display: flex; flex-direction: column; gap: var(--e-1); }
.camino__texto strong { font-size: var(--t-xl); font-weight: 700; line-height: 1.25; }
.camino__texto span { font-size: 1rem; color: var(--texto-suave); }
.docs__panel { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-5); border: 2px solid var(--acento); border-radius: var(--r-3); background: var(--superficie); scroll-margin-top: 1rem; }

.rup-zona { display: flex; flex-direction: column; align-items: center; gap: var(--e-2); padding: var(--e-6) var(--e-5); border: 3px dashed var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie-2); text-align: center; cursor: pointer; font-size: var(--t-lg); transition: border-color var(--rapido), background var(--rapido); }
.rup-zona:hover, .rup-zona--activa { border-color: var(--acento); background: var(--acento-tenue); }
.rup-zona:focus-within { outline: 3px solid var(--acento); outline-offset: 2px; }
.rup-zona--ocupada { opacity: 0.75; cursor: progress; }
.rup-zona__icono { color: var(--acento); }
.rup-zona strong { font-size: var(--t-xl); }
.rup-zona__boton { display: inline-flex; align-items: center; min-height: 48px; padding: 0.6rem 1.5rem; border-radius: var(--r-2); background: var(--acento); color: var(--superficie); font-weight: 700; }
.rup-zona small { color: var(--texto-suave); font-size: 1rem; }

.rup-progreso { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-4); border-radius: var(--r-2); background: var(--acento-tenue); }
.rup-progreso strong { font-size: var(--t-xl); }
.rup-progreso small { font-size: 1rem; color: var(--texto-suave); }
.rup-progreso__barra { height: 12px; border-radius: var(--r-redondo); background: var(--superficie-3); overflow: hidden; }
.rup-progreso__barra span { display: block; height: 100%; background: var(--acento); transition: width var(--normal); }
.rup-progreso__barra--indefinida span { width: 35%; animation: rup-avance 1.4s ease-in-out infinite; }
@keyframes rup-avance { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
@media (prefers-reduced-motion: reduce) { .rup-progreso__barra--indefinida span { animation: none; width: 100%; opacity: 0.5; } }

.rup-cpc__cabecera { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--e-3); }
.rup-cpc__herramientas { display: flex; flex-wrap: wrap; gap: var(--e-2); align-items: center; }
.rup-cpc__herramientas .entrada { min-height: 48px; min-width: 16rem; font-size: var(--t-lg); }
.rup-cpc { display: flex; flex-direction: column; max-height: 32rem; overflow-y: auto; margin: 0; padding: 0; list-style: none; border: 1px solid var(--borde-fuerte); border-radius: var(--r-2); }
.rup-cpc__fila { display: grid; grid-template-columns: auto 8.5rem 1fr auto; gap: var(--e-3); align-items: center; min-height: 52px; padding: var(--e-3) var(--e-4); cursor: pointer; font-size: var(--t-lg); border-bottom: 1px solid var(--borde); }
.rup-cpc__fila:hover { background: var(--superficie-2); }
.rup-cpc__fila--activa { background: var(--acento-tenue); }
.rup-cpc__fila input, .perfil__filas input { width: 1.5rem; height: 1.5rem; flex: none; }
.rup-cpc__codigo { font-weight: 700; }
.rup-cpc__tipo { font-size: 1rem; color: var(--texto-suave); }

.perfil__ruc-form { display: flex; flex-wrap: wrap; align-items: end; gap: var(--e-3); }
.perfil__ruc-form input { width: 100%; min-width: 16rem; min-height: 52px; padding: 0.6rem 0.9rem; border: 2px solid var(--borde-fuerte); border-radius: var(--r-2); background: var(--superficie); color: var(--texto); font: inherit; font-size: var(--t-xl); font-variant-numeric: tabular-nums; letter-spacing: 0.06em; }
.perfil__ruc-form input:focus-visible { outline: 3px solid var(--acento); outline-offset: 1px; }
.perfil__propuesta { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-4); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie-2); }
.perfil__propuesta h4 { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); }
.perfil__sello { padding: 2px 0.7rem; border-radius: var(--r-redondo); background: var(--ok-suave); color: var(--ok); font-size: 1rem; font-weight: 650; }
.perfil__sello--alerta { background: var(--error-suave); color: var(--error); }
.perfil__filas { display: grid; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); gap: var(--e-3); list-style: none; padding: 0; margin: 0; }
.perfil__filas label { display: flex; gap: var(--e-3); align-items: flex-start; height: 100%; padding: var(--e-3) var(--e-4); border: 2px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); cursor: pointer; }
.perfil__filas label:has(input:checked) { border-color: var(--acento); background: var(--acento-tenue); }
.perfil__fila-texto { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.perfil__fila-texto small { color: var(--texto-suave); font-size: 1rem; font-weight: 600; }
.perfil__fila-texto strong { font-size: var(--t-lg); overflow-wrap: anywhere; }
.perfil__fila-texto em { color: var(--aviso); font-size: 1rem; font-style: normal; font-weight: 600; }
.perfil__acciones { display: flex; gap: var(--e-3); flex-wrap: wrap; align-items: center; }

/* --- Qué falta ------------------------------------------------------------------------------- */
.faltan { display: flex; flex-direction: column; gap: var(--e-3); padding: var(--e-5) var(--e-6); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie); }
.faltan h3 { font-size: var(--t-xl); }
.faltan__cifra { display: flex; flex-direction: column; gap: var(--e-2); }
.faltan__barra { height: 14px; border-radius: var(--r-redondo); background: var(--superficie-3); overflow: hidden; }
.faltan__barra span { display: block; height: 100%; background: var(--ok); transition: width var(--normal); }
.faltan__lista { display: flex; flex-wrap: wrap; gap: var(--e-2); list-style: none; margin: 0; padding: 0; }
.faltan__listo { color: var(--ok); font-weight: 700; }

@media (max-width: 900px) {
  .docs__caminos { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .perfil h2 { font-size: var(--t-2xl); }
  .perfil h3 { font-size: var(--t-xl); }
  .docs, .faltan { padding: var(--e-4); }
  .docs__panel { padding: var(--e-4); }
  .perfil__acciones .boton, .faltan__lista, .faltan__lista li, .faltan__lista .boton { width: 100%; }
  .rup-cpc__fila { grid-template-columns: auto 1fr; }
  .rup-cpc__texto, .rup-cpc__tipo { grid-column: 2; }
  .rup-cpc__herramientas, .rup-cpc__herramientas .entrada, .rup-cpc__herramientas .boton { width: 100%; min-width: 0; }
  .perfil__ruc-form, .perfil__ruc-form label, .perfil__ruc-form .boton { width: 100%; }
  .perfil__ruc-form input { min-width: 0; }
}
</style>
