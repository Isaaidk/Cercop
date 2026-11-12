<script setup>
/**
 * Vista previa del TDR dentro del detalle de una ínfima.
 *
 * El archivo se pide con el token de la sesión y se muestra desde una URL local: un iframe con la
 * ruta de la API no enviaría Authorization.
 *
 * No pide nada al abrirse. Abrir el detalle de una fila no debe disparar una descarga del portal:
 * con cientos de personas mirando filas, cada una encolaría archivos que quizá nunca iba a leer.
 * Al abrir solo se **pregunta** si el archivo ya está; si no, la persona decide pedirlo.
 *
 * La lista es la de los anexos que sirven para la proforma, con su tipo: TDR, pliegos,
 * especificaciones y, de las actas, **solo la más reciente** (la elige el servidor,
 * `dominio/anexos.py`). Cada uno listo se descarga por separado.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { hastaQueSeVea, siguientePausa } from '@/utils/sondeo'
import { sesion } from '@/stores/sesion'
import { guardarArchivo } from '@/utils/descargas'
import { puedeRellenarTdr } from '@/utils/roles'
import { descargarTdr, nombreLegible } from '@/utils/tdr'

const props = defineProps({
  registroId: { type: String, required: true },
  documentos: { type: Array, default: () => [] },
})

const estado = ref([])
const anexos = ref([])
const bajandoUno = ref('')
const relleno = ref(null)
const error = ref('')
const esperando = ref(false)
const bajando = ref(false)
const urlVista = ref('')
const espera = ref(0)
let temporizador = 0
let vivo = true

// Para la vista previa, el primer anexo listo en el orden de lectura: el TDR antes que el acta.
const listo = computed(() => {
  const primero = anexos.value.find((anexo) => anexo.estado === 'listo' && anexo.id)
  return (
    (primero && estado.value.find((fila) => fila.id === primero.id)) ||
    estado.value.find((fila) => fila.estado === 'listo')
  )
})
const esPdf = computed(
  () => (listo.value?.mime || '').includes('pdf') || /\.pdf$/i.test(listo.value?.nombre || ''),
)
const esImagen = computed(() => (listo.value?.mime || '').startsWith('image/'))
const lista = computed(() =>
  anexos.value.length
    ? anexos.value.map((anexo, posicion) => ({
        clave: `${anexo.nombre}-${posicion}`,
        nombre: anexo.nombre,
        tipo: anexo.etiqueta_tipo,
        id: anexo.estado === 'listo' ? anexo.id : null,
        estado: anexo.estado,
      }))
    : props.documentos.map((documento, posicion) => ({
        clave: documento.enlace || documento.nombre || posicion,
        nombre: nombreLegible(documento, posicion + 1),
        tipo: '',
        id: null,
        estado: '',
      })),
)
const conError = computed(() => estado.value.find((fila) => fila.estado === 'error'))

function soltarVista() {
  if (urlVista.value) URL.revokeObjectURL(urlVista.value)
  urlVista.value = ''
}

async function mostrarArchivo(fila) {
  soltarVista()
  const { contenido } = await api.archivoTdr(props.registroId, fila.id)
  if (vivo) urlVista.value = URL.createObjectURL(contenido)
}

async function bajarUno(documento) {
  error.value = ''
  bajandoUno.value = documento.id
  try {
    const { contenido, nombre } = await api.archivoTdr(props.registroId, documento.id)
    guardarArchivo(contenido, nombre || documento.nombre)
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

async function consultar() {
  const respuesta = await api.estadoTdr(props.registroId)
  estado.value = respuesta.documentos || []
  anexos.value = respuesta.anexos || []
  if (listo.value) {
    await mostrarArchivo(listo.value)
    if (puedeRellenarTdr(sesion.estado.rol)) {
      relleno.value = await api.rellenoTdr(props.registroId)
    }
    return true
  }
  return false
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
      return
    }
    if (conError.value || intento >= 40) {
      esperando.value = false
      if (!conError.value) error.value = 'El TDR todavía no está listo. Inténtalo en un minuto.'
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

/** Al abrir solo se mira si el archivo ya está. No se pide nada. */
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
  <section v-if="documentos.length" class="tdr" aria-label="Términos de referencia">
    <header class="tdr__cabecera">
      <h3>Términos de referencia y anexos</h3>
      <span v-if="listo" class="tdr__estado tdr__estado--ok">Listo</span>
      <span v-else-if="esperando" class="tdr__estado">Preparando…</span>
    </header>

    <ul class="tdr__archivos">
      <li v-for="documento in lista" :key="documento.clave">
        <span class="tdr__icono" :class="{ 'tdr__icono--tipo': documento.tipo }">
          {{ documento.tipo || 'PDF' }}
        </span>
        <span class="tdr__nombre">
          {{ documento.nombre }}
          <small v-if="documento.estado === 'pendiente'">Bajando…</small>
          <small v-else-if="documento.estado === 'error'">No se pudo bajar</small>
        </span>
        <button
          v-if="documento.id"
          type="button"
          class="boton boton--fantasma boton--pequeno"
          :disabled="bajandoUno === documento.id"
          @click="bajarUno(documento)"
        >
          {{ bajandoUno === documento.id ? 'Bajando…' : 'Descargar' }}
        </button>
      </li>
    </ul>

    <p v-if="espera" class="tdr__aviso" role="status">
      Hay muchas consultas seguidas. Reintento en {{ espera }} s…
    </p>
    <p v-if="error" class="tdr__error" role="alert">{{ error }}</p>
    <p v-if="conError && !error" class="tdr__error" role="alert">
      No se pudo bajar el TDR del portal. Vuelve a intentarlo.
    </p>

    <div class="tdr__acciones">
      <button
        v-if="!listo"
        type="button"
        class="boton boton--principal boton--pequeno"
        :disabled="esperando"
        @click="pedir"
      >
        {{ esperando ? 'Bajando el TDR…' : conError ? 'Reintentar' : 'Ver el TDR' }}
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

    <iframe v-if="esPdf && urlVista" class="tdr__marco" :src="urlVista" title="Vista previa del TDR" />
    <img v-else-if="esImagen && urlVista" class="tdr__marco" :src="urlVista" alt="Vista previa del TDR" />
    <p v-else-if="listo" class="tdr__nota">
      El archivo está listo. Pulsa «Descargar» para guardarlo.
    </p>

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
.tdr__cabecera { display: flex; align-items: center; gap: var(--e-3); }
.tdr__cabecera h3 { font-size: var(--t-md); font-weight: 650; }
.tdr__estado { padding: 2px 0.65rem; border-radius: var(--r-redondo); background: var(--superficie-3); color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; }
.tdr__estado--ok { background: var(--ok-suave); color: var(--ok); }
.tdr__archivos { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.tdr__archivos li { display: flex; align-items: center; gap: var(--e-3); padding: var(--e-2) var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); font-size: var(--t-sm); }
.tdr__icono { flex: none; padding: 1px 0.45rem; border-radius: var(--r-1); background: var(--acento-suave); color: var(--acento-fuerte); font-size: var(--t-xs); font-weight: 700; }
.tdr__icono--tipo { min-width: 8.5rem; text-align: center; font-weight: 650; }
.tdr__nombre { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.tdr__nombre small { display: block; color: var(--texto-tenue); font-size: var(--t-xs); }
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
  .tdr__marco { min-height: 60vh; }
  .tdr__archivos li { flex-wrap: wrap; }
  .tdr__icono--tipo { min-width: 0; }
  .tdr__acciones .boton { flex: 1 1 auto; }
}
@media (prefers-reduced-motion: no-preference) { .tdr__marco { transition: opacity var(--normal); } }
</style>
