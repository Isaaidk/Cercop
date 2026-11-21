<script setup>
/**
 * Documentos habilitantes de una ínfima («Términos de referencia y anexos») dentro de su ficha.
 *
 * Es una lista **liviana**: nombre, tipo, fecha y formato de cada documento, sin cargar archivos.
 * La vista previa solo se pide cuando la persona la abre («Vista previa» o «Ver el TDR»): antes el
 * primer anexo listo se bajaba entero al abrir la ficha, y con fichas de varios MB eso pesaba en
 * cada clic aunque nadie fuera a leerlo.
 *
 * El nombre que se enseña es el que **le dio la entidad** («INFORME DE NECESIDAD», «Anexo»), tal
 * cual. Nuestro tipo («Términos de referencia (TDR)», «Otro anexo») va al lado como insignia
 * secundaria y nunca lo reemplaza: si la entidad subió el TDR como «Anexo», se lee «Anexo».
 *
 * No pide nada al portal al abrirse. Abrir el detalle de una fila no debe disparar una descarga:
 * con cientos de personas mirando filas, cada una encolaría archivos que quizá nunca iba a leer.
 * Al abrir solo se **pregunta** si el archivo ya está; si no, la persona decide pedirlo.
 *
 * Si el servidor no pudo bajar un documento (el portal no le respondió), cada uno ofrece «Ver en
 * el portal»: abrirlo con la conexión de la persona sí funciona. Es el mismo criterio que la
 * pantalla de documentos (`preparar_documentos.py`).
 *
 * La lista es la de los anexos que sirven para la proforma, con su tipo: TDR, pliegos,
 * especificaciones y, de las actas, **solo la más reciente** (la elige el servidor,
 * `dominio/anexos.py`). Cada uno listo se descarga por separado, con su extensión real.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'
import { guardarArchivo } from '@/utils/descargas'
import { fechaCorta } from '@/utils/formato'
import { conExtension, formatoDeTipo } from '@/utils/nombreArchivo'
import { puedeRellenarTdr } from '@/utils/roles'
import { hastaQueSeVea, siguientePausa } from '@/utils/sondeo'
import { descargarTdr, nombreLegible } from '@/utils/tdr'

const props = defineProps({
  registroId: { type: String, required: true },
  documentos: { type: Array, default: () => [] },
})

/** Si el servidor no explica el fallo: mismo mensaje que `MENSAJE_SIN_PORTAL` del backend. */
const MENSAJE_SIN_PORTAL =
  'El portal de compras públicas no respondió a CercoApp en este momento. Puedes abrir cada ' +
  'anexo en el portal desde tu computadora con «Ver en el portal» y guardarlo, o volver a ' +
  'intentarlo en unos minutos.'

const estado = ref([])
const anexos = ref([])
const bajandoUno = ref('')
const relleno = ref(null)
const error = ref('')
const esperando = ref(false)
const bajando = ref(false)
const urlVista = ref('')
const vista = ref(null) // { id, nombre, mime } del documento en vista previa
const cargandoVista = ref('')
const espera = ref(0)
let temporizador = 0
let vivo = true

const listos = computed(() => estado.value.filter((fila) => fila.estado === 'listo'))
const hayListo = computed(() => listos.value.length > 0)

const sePuedeVer = (mime, nombre) =>
  String(mime || '').includes('pdf') || String(mime || '').startsWith('image/') || /\.pdf$/i.test(nombre || '')

const lista = computed(() =>
  anexos.value.length
    ? anexos.value.map((anexo, posicion) => ({
        clave: `${anexo.nombre}-${posicion}`,
        nombre: anexo.nombre,
        descripcion: anexo.descripcion || '',
        tipo: anexo.etiqueta_tipo,
        fecha: anexo.fecha || '',
        formato: anexo.formato || formatoDeTipo(anexo.mime),
        mime: anexo.mime || '',
        id: anexo.estado === 'listo' ? anexo.id : null,
        estado: anexo.estado,
        error: anexo.error || '',
        portal: anexo.enlace_portal || '',
      }))
    : props.documentos.map((documento, posicion) => ({
        clave: documento.enlace || documento.nombre || posicion,
        nombre: nombreLegible(documento, posicion + 1),
        descripcion: documento.descripcion || '',
        tipo: '',
        fecha: String(documento.fecha || '').slice(0, 10),
        formato: '',
        mime: '',
        id: null,
        estado: '',
        error: '',
        portal: '',
      })),
)

const conError = computed(() => lista.value.filter((documento) => documento.estado === 'error'))
/** El aviso del fallo: el que explica el servidor, o el de «el portal no respondió». */
const avisoDeError = computed(() => conError.value.find((d) => d.error)?.error || MENSAJE_SIN_PORTAL)

function soltarVista() {
  if (urlVista.value) URL.revokeObjectURL(urlVista.value)
  urlVista.value = ''
  vista.value = null
}

async function verVistaPrevia(documento) {
  if (!documento?.id) return
  if (vista.value?.id === documento.id) {
    soltarVista()
    return
  }
  error.value = ''
  cargandoVista.value = documento.id
  try {
    const { contenido } = await api.archivoTdr(props.registroId, documento.id)
    if (!vivo) return
    soltarVista()
    urlVista.value = URL.createObjectURL(contenido)
    vista.value = { id: documento.id, nombre: documento.nombre, mime: contenido.type || documento.mime }
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargandoVista.value = ''
  }
}

async function bajarUno(documento) {
  error.value = ''
  bajandoUno.value = documento.id
  try {
    const { contenido, nombre } = await api.archivoTdr(props.registroId, documento.id)
    // El servidor manda el nombre con la extensión real; si no llegara, se arma aquí con el tipo.
    guardarArchivo(contenido, nombre || conExtension(documento.nombre, contenido.type || documento.mime))
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    bajandoUno.value = ''
  }
}

async function bajar() {
  error.value = ''
  bajando.value = true
  try {
    await descargarTdr(props.registroId)
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    bajando.value = false
  }
}

/** Espera lo que el servidor pidió cuando frena por exceso de peticiones. */
async function respirar(fallo) {
  if (!fallo?.esLimite || fallo.esperaSeg > 60) return false
  for (let resta = Math.max(1, fallo.esperaSeg); resta > 0 && vivo; resta -= 1) {
    espera.value = resta
    await new Promise((resolver) => setTimeout(resolver, 1000))
  }
  espera.value = 0
  return vivo
}

/** Lee el estado (solo datos, sin archivos). Devuelve si ya hay algún documento listo. */
async function consultar() {
  const respuesta = await api.estadoTdr(props.registroId)
  estado.value = respuesta.documentos || []
  anexos.value = respuesta.anexos || []
  if (!hayListo.value) return false
  if (!relleno.value && puedeRellenarTdr(sesion.estado.rol)) {
    relleno.value = await api.rellenoTdr(props.registroId)
  }
  return true
}

/** La vista previa del primer documento listo que se pueda ver, en el orden de lectura. */
async function abrirPrimeraVista() {
  const primero = lista.value.find((documento) => documento.id && sePuedeVer(documento.mime, documento.nombre))
  if (primero && !vista.value) await verVistaPrevia(primero)
}

async function pedir() {
  error.value = ''
  esperando.value = true
  try {
    await api.pedirTdr(props.registroId)
    await sondear(0, 2000)
  } catch (fallo) {
    if (await respirar(fallo)) return pedir()
    error.value = fallo.message
    esperando.value = false
  }
}

async function sondear(intento, pausa) {
  try {
    if (await consultar()) {
      esperando.value = false
      // La persona pidió «Ver el TDR»: ahora sí se carga la vista previa.
      await abrirPrimeraVista()
      return
    }
    if (conError.value.length || intento >= 40) {
      esperando.value = false
      if (!conError.value.length) error.value = 'El TDR todavía no está listo. Inténtalo en un minuto.'
      return
    }
  } catch (fallo) {
    if (await respirar(fallo)) return sondear(intento, pausa)
    error.value = fallo.message
    esperando.value = false
    return
  }
  window.clearTimeout(temporizador)
  // La espera crece: los primeros segundos son los que más importan, y después no hace falta
  // preguntar tan seguido para saber que el portal sigue trabajando. Con la pestaña oculta no se
  // pregunta: se sigue al volver (y ese rato no cuenta como intento).
  temporizador = window.setTimeout(async () => {
    await hastaQueSeVea()
    if (vivo) sondear(intento + 1, siguientePausa(pausa))
  }, pausa)
}

/** Al abrir solo se mira si el archivo ya está. No se pide nada ni se baja ningún archivo. */
async function revisar() {
  estado.value = []
  anexos.value = []
  relleno.value = null
  error.value = ''
  soltarVista()
  if (!props.documentos.length) return
  try {
    await consultar()
  } catch (fallo) {
    if (!(await respirar(fallo))) error.value = fallo.message
  }
}

onMounted(revisar)
watch(() => props.registroId, revisar)

onBeforeUnmount(() => {
  vivo = false
  window.clearTimeout(temporizador)
  soltarVista()
})
</script>

<template>
  <section v-if="documentos.length" class="tdr" aria-labelledby="titulo-tdr">
    <div class="tdr__caja">
      <header class="tdr__cabecera">
        <h3 id="titulo-tdr">Términos de referencia y anexos</h3>
        <span v-if="hayListo" class="tdr__estado tdr__estado--ok">Listo</span>
        <span v-else-if="esperando" class="tdr__estado" role="status">Preparando…</span>
      </header>
      <p class="tdr__ayuda">Documentos que publicó la entidad, con el nombre que ella les dio.</p>

      <ul class="tdr__archivos">
        <li v-for="documento in lista" :key="documento.clave" class="tdr__archivo">
          <div class="tdr__texto">
            <p class="tdr__nombre">{{ documento.nombre }}</p>
            <p v-if="documento.descripcion" class="tdr__descripcion">{{ documento.descripcion }}</p>
            <p class="tdr__meta">
              <span v-if="documento.tipo" class="etiqueta tdr__tipo">{{ documento.tipo }}</span>
              <span v-if="documento.fecha">Publicado el {{ fechaCorta(`${documento.fecha.slice(0, 10)}T12:00:00`) }}</span>
              <span v-if="documento.formato" class="tdr__formato">{{ documento.formato }}</span>
              <span v-if="documento.estado === 'pendiente'">Bajando…</span>
              <span v-else-if="documento.estado === 'error'" class="tdr__fallo">No se pudo bajar</span>
            </p>
          </div>
          <div class="tdr__botones">
            <button
              v-if="documento.id && sePuedeVer(documento.mime, documento.nombre)"
              type="button"
              class="boton boton--fantasma boton--pequeno"
              :aria-pressed="vista?.id === documento.id"
              :disabled="cargandoVista === documento.id"
              @click="verVistaPrevia(documento)"
            >
              {{ cargandoVista === documento.id ? 'Abriendo…' : vista?.id === documento.id ? 'Cerrar vista' : 'Vista previa' }}
            </button>
            <button
              v-if="documento.id"
              type="button"
              class="boton boton--secundario boton--pequeno"
              :disabled="bajandoUno === documento.id"
              :aria-label="`Descargar ${documento.nombre}`"
              @click="bajarUno(documento)"
            >
              {{ bajandoUno === documento.id ? 'Bajando…' : 'Descargar' }}
            </button>
            <a
              v-if="documento.portal && documento.estado === 'error'"
              class="boton boton--secundario boton--pequeno"
              :href="documento.portal"
              target="_blank"
              rel="noopener noreferrer"
              :aria-label="`Ver ${documento.nombre} en el portal de compras públicas (se abre en otra pestaña)`"
            >
              <span aria-hidden="true">↗</span>
              Ver en el portal
            </a>
          </div>
        </li>
      </ul>
    </div>

    <p v-if="espera" class="tdr__aviso" role="status">
      Hay muchas consultas seguidas. Reintento en {{ espera }} s…
    </p>
    <p v-if="error" class="tdr__error" role="alert">{{ error }}</p>
    <p v-if="conError.length && !error" class="tdr__error" role="alert">{{ avisoDeError }}</p>

    <div class="tdr__acciones">
      <button
        v-if="!hayListo"
        type="button"
        class="boton boton--principal boton--pequeno"
        :disabled="esperando"
        @click="pedir"
      >
        {{ esperando ? 'Bajando el TDR…' : conError.length ? 'Reintentar' : 'Ver el TDR' }}
      </button>
      <button
        v-else
        type="button"
        class="boton boton--secundario boton--pequeno"
        :disabled="bajando"
        @click="bajar"
      >
        {{ bajando ? 'Preparando la descarga…' : 'Descargar todos' }}
      </button>
    </div>

    <template v-if="vista && urlVista">
      <iframe
        v-if="!String(vista.mime).startsWith('image/')"
        class="tdr__marco"
        :src="urlVista"
        :title="`Vista previa de ${vista.nombre}`"
      />
      <img v-else class="tdr__marco" :src="urlVista" :alt="`Vista previa de ${vista.nombre}`" />
    </template>

    <aside v-if="relleno" class="tdr__borrador">
      <h4>Borrador de oferta</h4>
      <template v-if="!relleno.aplica">
        <p class="tdr__nota">Con tu perfil actual esta ínfima no se rellena sola:</p>
        <ul class="tdr__motivos">
          <li v-for="motivo in relleno.motivos || []" :key="motivo">{{ motivo }}</li>
        </ul>
      </template>
      <template v-else>
        <section v-for="seccion in relleno.legible || []" :key="seccion.titulo" class="tdr__seccion">
          <h5>{{ seccion.titulo }}</h5>
          <dl v-if="seccion.tipo === 'datos'">
            <div v-for="fila in seccion.filas" :key="fila.etiqueta">
              <dt>{{ fila.etiqueta }}</dt>
              <dd>{{ fila.valor }}</dd>
            </div>
          </dl>
          <ul v-else-if="seccion.filas.length">
            <li v-for="fila in seccion.filas" :key="fila">{{ fila }}</li>
          </ul>
          <p v-else class="tdr__nota">Nada en tu perfil coincide.</p>
        </section>
      </template>
    </aside>
  </section>
</template>

<style scoped>
.tdr { display: flex; flex-direction: column; gap: var(--e-3); margin-top: var(--e-4); }
/* Caja informativa azul: es información de la entidad, no un aviso. */
.tdr__caja { display: flex; flex-direction: column; gap: var(--e-2); padding: var(--e-3) var(--e-4); border: 1px solid var(--acento-suave); border-radius: var(--r-3); background: var(--acento-tenue); }
.tdr__cabecera { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2) var(--e-3); }
.tdr__cabecera h3 { font-size: var(--t-md); font-weight: 650; color: var(--acento-fuerte); }
.tdr__ayuda { font-size: var(--t-xs); color: var(--texto-suave); }
.tdr__estado { padding: 2px 0.65rem; border-radius: var(--r-redondo); background: var(--superficie-3); color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; }
.tdr__estado--ok { background: var(--ok-suave); color: var(--ok); }
.tdr__archivos { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.tdr__archivo { display: flex; align-items: center; justify-content: space-between; gap: var(--e-3); padding: var(--e-2) var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.tdr__texto { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.tdr__nombre { font-weight: 600; color: var(--texto); overflow-wrap: anywhere; }
.tdr__descripcion { color: var(--texto-suave); overflow-wrap: anywhere; }
.tdr__meta { display: flex; flex-wrap: wrap; align-items: center; gap: 2px var(--e-2); color: var(--texto-suave); font-size: var(--t-xs); }
.tdr__tipo { font-weight: 600; }
.tdr__formato { font-family: var(--fuente-numeros); font-weight: 650; }
.tdr__fallo { color: var(--error); font-weight: 600; }
.tdr__botones { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--e-2); flex: none; }
.tdr__acciones { display: flex; gap: var(--e-2); }
.tdr__marco { width: 100%; min-height: 28rem; border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
.tdr__nota { color: var(--texto-suave); font-size: var(--t-sm); }
/* Avisos sin barra de color al costado: la guía deja el color de estado para insignias y textos. */
.tdr__aviso { padding: var(--e-2) var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie-2); color: var(--texto-suave); font-size: var(--t-sm); }
.tdr__error { padding: var(--e-2) var(--e-3); border-radius: var(--r-2); background: var(--error-suave); color: var(--error); font-size: var(--t-sm); }
.tdr__borrador { display: flex; flex-direction: column; gap: var(--e-3); padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); }
.tdr__borrador h4 { font-size: var(--t-md); font-weight: 650; }
.tdr__seccion h5 { margin-bottom: var(--e-2); color: var(--texto); font-size: var(--t-sm); font-weight: 650; }
.tdr__seccion dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); gap: var(--e-2) var(--e-4); margin: 0; }
.tdr__seccion dt { color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; text-transform: uppercase; letter-spacing: 0.03em; }
.tdr__seccion dd { margin: 0; font-size: var(--t-sm); overflow-wrap: anywhere; }
.tdr__seccion ul, .tdr__motivos { display: flex; flex-direction: column; gap: var(--e-1); margin: 0; padding-left: 1.1rem; font-size: var(--t-sm); }
@media (max-width: 640px) {
  .tdr__caja { padding: var(--e-3); }
  .tdr__marco { min-height: 60vh; }
  .tdr__archivo { flex-direction: column; align-items: stretch; }
  .tdr__botones { justify-content: flex-start; }
  .tdr__botones .boton, .tdr__acciones .boton { flex: 1 1 auto; justify-content: center; }
}
@media (prefers-reduced-motion: no-preference) { .tdr__marco { transition: opacity var(--normal); } }
</style>
