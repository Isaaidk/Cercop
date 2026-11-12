<script setup>
/**
 * «Asistente»: el chat con el que se busca, se pregunta y se prepara una oferta sin recorrer el menú.
 *
 * Es la pantalla con la que se abre el panel. La usan también personas mayores y poco técnicas, así
 * que todo va más grande que en el resto del panel (texto de 1 rem, el campo de escribir de 1,1 rem,
 * botones de al menos 44 px) y cada respuesta dice qué se puede hacer después con botones, no con
 * comandos.
 *
 * Qué hace
 * --------
 * - Al abrirse pide `/v1/asistente/inicio` (saludo, resumen, sugerencias y conversaciones) y vuelve a
 *   la conversación en la que se quedó: la recordada en este navegador o, si no hay, `ultima_id`.
 * - Cada envío pinta enseguida la burbuja de quien escribe y un «Pensando…»; al llegar la respuesta
 *   se sustituyen por los mensajes que devuelve el servidor. Si falla, se dice en la misma burbuja y
 *   se ofrece «Reintentar».
 * - Las tarjetas (`TarjetaAsistente`) avisan con `preparar(registro)` e `ir(pestana)`; esta pantalla
 *   solo los reenvía al panel, que es quien sabe abrir «Preparar oferta» o cambiar de pantalla.
 *
 * El texto del asistente se pinta con `segmentarTexto` y plantillas normales, **nunca** con `v-html`:
 * viene de un modelo y podría traer cualquier cosa.
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import IconoPanel from '@/components/IconoPanel.vue'
import TarjetaAsistente from '@/components/TarjetaAsistente.vue'
import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'
import {
  LIMITE_TEXTO,
  chipsDeResumen,
  fechaRelativa,
  primerNombre,
  segmentarTexto,
  sugerenciaVisible,
  sugerenciasVisibles,
  textoContador,
} from '@/utils/asistente'

const props = defineProps({
  /** Si la pantalla está a la vista: al volver a ella se enfoca el campo de escribir. */
  activa: { type: Boolean, default: false },
})

const emit = defineEmits(['preparar', 'ir'])

const CLAVE_CONVERSACION = 'asistente:conversacion'

const SUGERENCIAS_BASE = [
  'Muéstrame las ínfimas que puedo ofertar',
  '¿Qué ofertas tengo por cerrar?',
  'Crea una alerta para mis productos',
]

// ------------------------------------------------------------------------------------- estado

const inicio = ref(null)
const cargandoInicio = ref(true)
const errorInicio = ref('')

const conversaciones = ref([])
const actualId = ref(null)
const mensajes = ref([])
const cargandoMensajes = ref(false)
const errorMensajes = ref('')

const borrador = ref('')
const enviando = ref(false)
/** `{ texto, mensaje, idTemporal }` del último envío que falló. */
const errorEnvio = ref(null)

const creditos = ref(null)
const iaDisponible = ref(true)

/** Lista de conversaciones abierta (solo cuenta en móvil y tableta, donde es un cajón). */
const listaAbierta = ref(false)
/** Id de la conversación con el menú «⋯» abierto, la que se está renombrando y la que se va a borrar. */
const menuDe = ref(null)
const renombrando = ref(null)
const nuevoTitulo = ref('')
const borrando = ref(null)
const ocupadoLista = ref(false)
const avisoLista = ref('')

const listaMensajes = ref(null)
const campo = ref(null)
const campoTitulo = ref(null)

/**
 * Se incrementa cada vez que cambia la conversación a la vista. Una respuesta que llega cuando ya se
 * está mirando otra conversación no se pinta encima de ella.
 */
let vista = 0

// ------------------------------------------------------------------------------------- derivados

const nombre = computed(() => primerNombre(inicio.value?.saludo?.nombre || sesion.estado.nombre))
const empresa = computed(() => inicio.value?.saludo?.empresa || '')
/**
 * Vistas vigentes de quien escribe, o `null` si no se saben (sin cargar, o dueño de la plataforma).
 * Sirven para no ofrecer una sugerencia que lleve a una vista oculta: el servidor ya filtra lo que
 * manda, esto cubre las sugerencias fijas del panel y los chips.
 */
const vistasVigentes = computed(() => {
  if (!sesion.estado.vistasCargadas || sesion.esDePlataforma.value) return null
  return sesion.estado.vistas.filter((fila) => fila.vigente).map((fila) => fila.vista)
})
const chips = computed(() =>
  chipsDeResumen(inicio.value?.resumen).filter((chip) =>
    sugerenciaVisible(chip.mensaje, vistasVigentes.value),
  ),
)
const sugerenciasInicio = computed(() => {
  const lista = inicio.value?.sugerencias
  return sugerenciasVisibles(
    Array.isArray(lista) && lista.length ? lista : SUGERENCIAS_BASE,
    vistasVigentes.value,
  )
})

const actual = computed(() => conversaciones.value.find((item) => item.id === actualId.value) || null)
const vacia = computed(() => !mensajes.value.length && !cargandoMensajes.value && !errorMensajes.value)

/** Las sugerencias se enseñan solo bajo la última respuesta: en las viejas ya no vienen a cuento. */
const ultimaRespuestaId = computed(() => {
  for (let i = mensajes.value.length - 1; i >= 0; i -= 1) {
    if (mensajes.value[i].rol === 'asistente') return mensajes.value[i].id
  }
  return null
})

const contador = computed(() => textoContador(borrador.value.length))
const sePuedeEnviar = computed(
  () => Boolean(borrador.value.trim()) && borrador.value.length <= LIMITE_TEXTO && !enviando.value,
)

// ------------------------------------------------------------------------------------- memoria

function recordar(id) {
  try {
    if (id) localStorage.setItem(CLAVE_CONVERSACION, id)
    else localStorage.removeItem(CLAVE_CONVERSACION)
  } catch {
    /* sin almacén, se vuelve a la última del servidor */
  }
}

function recordada() {
  try {
    return localStorage.getItem(CLAVE_CONVERSACION)
  } catch {
    return null
  }
}

// ------------------------------------------------------------------------------------- carga

async function cargarInicio() {
  cargandoInicio.value = true
  errorInicio.value = ''
  try {
    const respuesta = (await api.asistenteInicio()) || {}
    inicio.value = respuesta
    conversaciones.value = Array.isArray(respuesta.conversaciones) ? respuesta.conversaciones : []
    iaDisponible.value = respuesta.ia_disponible !== false
    creditos.value = respuesta.creditos ?? null

    // Solo si no se empezó a escribir otra conversación mientras cargaba.
    if (actualId.value === null && !mensajes.value.length) {
      const guardada = recordada()
      const existe = (id) => id && conversaciones.value.some((item) => item.id === id)
      const elegida = existe(guardada) ? guardada : existe(respuesta.ultima_id) ? respuesta.ultima_id : null
      if (elegida) await abrirConversacion(elegida, { cerrarLista: false })
    }
  } catch (fallo) {
    errorInicio.value = fallo?.message || 'No pudimos cargar el asistente.'
  } finally {
    cargandoInicio.value = false
  }
}

async function abrirConversacion(id, { cerrarLista = true } = {}) {
  cerrarMenus()
  if (cerrarLista) listaAbierta.value = false
  vista += 1
  const mia = vista
  actualId.value = id
  recordar(id)
  mensajes.value = []
  errorEnvio.value = null
  errorMensajes.value = ''
  cargandoMensajes.value = true
  try {
    const respuesta = await api.asistenteConversacion(id)
    if (mia !== vista) return
    mensajes.value = Array.isArray(respuesta?.mensajes) ? respuesta.mensajes : []
  } catch (fallo) {
    if (mia !== vista) return
    if (fallo?.estado === 404) {
      // Se borró desde otro dispositivo: se quita de la lista y se empieza una nueva.
      conversaciones.value = conversaciones.value.filter((item) => item.id !== id)
      nuevaConversacion()
      return
    }
    errorMensajes.value = fallo?.message || 'No pudimos abrir esta conversación.'
  } finally {
    if (mia === vista) {
      cargandoMensajes.value = false
      desplazarAbajo()
    }
  }
}

function nuevaConversacion() {
  cerrarMenus()
  listaAbierta.value = false
  vista += 1
  actualId.value = null
  recordar(null)
  mensajes.value = []
  errorEnvio.value = null
  errorMensajes.value = ''
  cargandoMensajes.value = false
  enfocar()
}

// ------------------------------------------------------------------------------------- enviar

/** Pone la conversación arriba de la lista con sus datos nuevos (título, fecha). */
function ponerArriba(conversacion) {
  if (!conversacion?.id) return
  conversaciones.value = [conversacion, ...conversaciones.value.filter((item) => item.id !== conversacion.id)]
}

/**
 * Envía un mensaje. Sin argumento envía lo escrito en el campo (y lo vacía); con texto —un chip, una
 * sugerencia, «Reintentar»— envía ese texto y deja el campo como estaba.
 */
async function enviar(textoDado) {
  const desdeCampo = typeof textoDado !== 'string'
  const texto = String(desdeCampo ? borrador.value : textoDado).trim()
  if (!texto || enviando.value) return
  if (texto.length > LIMITE_TEXTO) return

  detenerDictado()
  if (desdeCampo) {
    borrador.value = ''
    ajustarAltura()
  }
  errorEnvio.value = null

  const temporal = { id: `temporal-${Date.now()}`, rol: 'usuario', texto, tarjetas: [], temporal: true }
  mensajes.value = [...mensajes.value, temporal]
  enviando.value = true
  const mia = vista
  const conversacionAlEnviar = actualId.value
  desplazarAbajo()

  try {
    const respuesta = (await api.asistenteEnviar({ texto, conversacion_id: conversacionAlEnviar })) || {}
    ponerArriba(respuesta.conversacion)
    if (mia === vista) {
      const nuevos = Array.isArray(respuesta.mensajes) ? respuesta.mensajes : []
      mensajes.value = [...mensajes.value.filter((m) => m.id !== temporal.id), ...nuevos]
      if (!conversacionAlEnviar && respuesta.conversacion?.id) {
        actualId.value = respuesta.conversacion.id
        recordar(respuesta.conversacion.id)
      }
    }
    const saldo = respuesta.creditos?.saldo
    if (saldo !== null && saldo !== undefined) creditos.value = saldo
  } catch (fallo) {
    if (mia === vista) {
      errorEnvio.value = {
        texto,
        idTemporal: temporal.id,
        mensaje: fallo?.message || 'No pudimos enviar tu mensaje. Revisa tu conexión.',
      }
    }
  } finally {
    enviando.value = false
    if (mia === vista) {
      desplazarAbajo()
      enfocar()
    }
  }
}

function reintentar() {
  const fallido = errorEnvio.value
  if (!fallido) return
  mensajes.value = mensajes.value.filter((m) => m.id !== fallido.idTemporal)
  errorEnvio.value = null
  enviar(fallido.texto)
}

function alPulsarTecla(evento) {
  if (evento.key !== 'Enter' || evento.shiftKey || evento.isComposing) return
  evento.preventDefault()
  enviar()
}

// ------------------------------------------------------------------------------------- campo

function enfocar() {
  nextTick(() => campo.value?.focus())
}

/** El campo crece con el texto hasta seis líneas; desde ahí aparece su barra. */
function ajustarAltura() {
  nextTick(() => {
    const el = campo.value
    if (!el) return
    el.style.height = 'auto'
    const estilo = getComputedStyle(el)
    const linea = parseFloat(estilo.lineHeight) || 26
    const bordes = (parseFloat(estilo.borderTopWidth) || 0) + (parseFloat(estilo.borderBottomWidth) || 0)
    const relleno = (parseFloat(estilo.paddingTop) || 0) + (parseFloat(estilo.paddingBottom) || 0)
    const maximo = linea * 6 + relleno + bordes
    const deseado = el.scrollHeight + bordes
    el.style.height = `${Math.min(deseado, maximo)}px`
    el.style.overflowY = deseado > maximo ? 'auto' : 'hidden'
  })
}

function desplazarAbajo() {
  nextTick(() => {
    const el = listaMensajes.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ------------------------------------------------------------------------------------- dictado

const Reconocimiento =
  typeof window !== 'undefined' ? window.SpeechRecognition || window.webkitSpeechRecognition || null : null
const dictadoDisponible = Boolean(Reconocimiento)
const escuchando = ref(false)
const avisoDictado = ref('')
let reconocedor = null

function alternarDictado() {
  if (escuchando.value) {
    detenerDictado()
    return
  }
  avisoDictado.value = ''
  let nuevo
  try {
    nuevo = new Reconocimiento()
  } catch {
    avisoDictado.value = 'Tu navegador no deja dictar ahora. Escribe tu mensaje.'
    return
  }
  nuevo.lang = 'es-EC'
  nuevo.interimResults = true
  nuevo.continuous = false
  const base = borrador.value.trim() ? `${borrador.value.replace(/\s+$/, '')} ` : ''
  nuevo.onresult = (evento) => {
    let dicho = ''
    for (const resultado of evento.results) dicho += resultado[0]?.transcript || ''
    borrador.value = (base + dicho).slice(0, LIMITE_TEXTO)
    ajustarAltura()
  }
  nuevo.onerror = (evento) => {
    if (evento.error === 'not-allowed' || evento.error === 'service-not-allowed') {
      avisoDictado.value = 'Permite el uso del micrófono en tu navegador para poder dictar.'
    } else if (evento.error === 'no-speech') {
      avisoDictado.value = 'No te escuché. Pulsa el micrófono y vuelve a hablar.'
    } else if (evento.error !== 'aborted') {
      avisoDictado.value = 'No se pudo usar el micrófono. Escribe tu mensaje.'
    }
  }
  nuevo.onend = () => {
    escuchando.value = false
    reconocedor = null
    enfocar()
  }
  try {
    nuevo.start()
    reconocedor = nuevo
    escuchando.value = true
  } catch {
    avisoDictado.value = 'No se pudo usar el micrófono. Escribe tu mensaje.'
  }
}

function detenerDictado() {
  try {
    reconocedor?.stop()
  } catch {
    /* ya estaba parado */
  }
}

// ------------------------------------------------------------------------------------- lista

function cerrarMenus() {
  menuDe.value = null
  renombrando.value = null
  borrando.value = null
  avisoLista.value = ''
}

function alternarMenu(id) {
  const abrir = menuDe.value !== id
  cerrarMenus()
  if (abrir) menuDe.value = id
}

function empezarRenombrar(conversacion) {
  cerrarMenus()
  renombrando.value = conversacion.id
  nuevoTitulo.value = conversacion.titulo || ''
  nextTick(() => {
    const el = Array.isArray(campoTitulo.value) ? campoTitulo.value[0] : campoTitulo.value
    el?.focus()
    el?.select()
  })
}

async function guardarTitulo(conversacion) {
  const titulo = nuevoTitulo.value.trim()
  if (!titulo || titulo === conversacion.titulo) {
    renombrando.value = null
    return
  }
  ocupadoLista.value = true
  avisoLista.value = ''
  try {
    const actualizada = await api.renombrarConversacion(conversacion.id, titulo)
    conversaciones.value = conversaciones.value.map((item) =>
      item.id === conversacion.id ? { ...item, ...(actualizada || { titulo }) } : item,
    )
    renombrando.value = null
  } catch (fallo) {
    avisoLista.value = fallo?.message || 'No pudimos cambiar el nombre.'
  } finally {
    ocupadoLista.value = false
  }
}

function pedirBorrar(conversacion) {
  cerrarMenus()
  borrando.value = conversacion.id
}

async function borrar(conversacion) {
  ocupadoLista.value = true
  avisoLista.value = ''
  try {
    await api.borrarConversacion(conversacion.id)
    conversaciones.value = conversaciones.value.filter((item) => item.id !== conversacion.id)
    borrando.value = null
    if (actualId.value === conversacion.id) nuevaConversacion()
  } catch (fallo) {
    avisoLista.value = fallo?.message || 'No pudimos borrar la conversación.'
  } finally {
    ocupadoLista.value = false
  }
}

/** Un clic fuera del menú «⋯» lo cierra; Escape cierra el menú y el cajón. */
function alClicarDocumento(evento) {
  if (menuDe.value && !evento.target?.closest?.('.conversacion__menu, .conversacion__opciones')) {
    menuDe.value = null
  }
}

function alPulsarEscape(evento) {
  if (evento.key !== 'Escape') return
  if (menuDe.value) menuDe.value = null
  else if (listaAbierta.value) listaAbierta.value = false
}

// ------------------------------------------------------------------------------------- tarjetas

function preparar(registro) {
  emit('preparar', registro)
}

function ir(pestana) {
  emit('ir', pestana)
}

// ------------------------------------------------------------------------------------- vida

onMounted(() => {
  cargarInicio()
  ajustarAltura()
  if (props.activa) enfocar()
  document.addEventListener('click', alClicarDocumento)
  document.addEventListener('keydown', alPulsarEscape)
})

onBeforeUnmount(() => {
  detenerDictado()
  document.removeEventListener('click', alClicarDocumento)
  document.removeEventListener('keydown', alPulsarEscape)
})

watch(
  () => props.activa,
  (ahora) => {
    if (ahora) {
      desplazarAbajo()
      enfocar()
    } else {
      detenerDictado()
    }
  },
)
</script>

<template>
  <div class="asistente" :class="{ 'asistente--lista-abierta': listaAbierta }">
    <!-- Conversaciones guardadas: columna en escritorio, cajón en móvil y tableta. -->
    <aside id="asistente-conversaciones" class="asistente__lateral" aria-label="Tus conversaciones">
      <div class="asistente__lateral-cabecera">
        <p class="asistente__lateral-titulo">Conversaciones</p>
        <button
          type="button"
          class="boton boton--fantasma boton--icono asistente__cerrar-lista"
          aria-label="Cerrar la lista de conversaciones"
          @click="listaAbierta = false"
        >
          <IconoPanel nombre="cerrar" :tamano="20" />
        </button>
      </div>

      <button type="button" class="boton boton--principal asistente__nueva" @click="nuevaConversacion">
        <IconoPanel nombre="mas" :tamano="18" /> Nueva conversación
      </button>

      <p v-if="avisoLista" class="asistente__aviso-lista" role="alert">{{ avisoLista }}</p>

      <div v-if="cargandoInicio && !conversaciones.length" class="asistente__esqueletos" aria-hidden="true">
        <div v-for="n in 3" :key="n" class="esqueleto asistente__esqueleto" />
      </div>
      <p v-else-if="!conversaciones.length" class="asistente__sin-conversaciones">
        Aquí verás tus conversaciones para retomarlas cuando quieras.
      </p>

      <ul v-else class="conversaciones">
        <li
          v-for="conversacion in conversaciones"
          :key="conversacion.id"
          class="conversacion"
          :class="{ 'conversacion--activa': conversacion.id === actualId }"
        >
          <!-- Renombrar -->
          <form
            v-if="renombrando === conversacion.id"
            class="conversacion__formulario"
            @submit.prevent="guardarTitulo(conversacion)"
          >
            <label class="solo-lectores" :for="`titulo-${conversacion.id}`">Nuevo nombre de la conversación</label>
            <input
              :id="`titulo-${conversacion.id}`"
              ref="campoTitulo"
              v-model="nuevoTitulo"
              class="conversacion__campo"
              type="text"
              maxlength="120"
              @keydown.esc.stop="renombrando = null"
            />
            <div class="conversacion__acciones">
              <button type="submit" class="boton boton--principal conversacion__boton" :disabled="ocupadoLista">
                Guardar
              </button>
              <button type="button" class="boton boton--secundario conversacion__boton" @click="renombrando = null">
                Cancelar
              </button>
            </div>
          </form>

          <!-- Confirmar el borrado -->
          <div v-else-if="borrando === conversacion.id" class="conversacion__confirmar" role="group" :aria-label="`Borrar ${conversacion.titulo}`">
            <p>¿Borrar «{{ conversacion.titulo || 'Conversación' }}»? No se puede deshacer.</p>
            <div class="conversacion__acciones">
              <button
                type="button"
                class="boton boton--peligro conversacion__boton conversacion__boton--peligro"
                :disabled="ocupadoLista"
                @click="borrar(conversacion)"
              >
                Sí, borrar
              </button>
              <button type="button" class="boton boton--secundario conversacion__boton" @click="borrando = null">
                Cancelar
              </button>
            </div>
          </div>

          <template v-else>
            <button
              type="button"
              class="conversacion__abrir"
              :aria-current="conversacion.id === actualId ? 'true' : undefined"
              @click="abrirConversacion(conversacion.id)"
            >
              <span class="conversacion__titulo">{{ conversacion.titulo || 'Conversación' }}</span>
              <span class="conversacion__fecha">{{ fechaRelativa(conversacion.actualizada_en) }}</span>
            </button>
            <button
              type="button"
              class="conversacion__opciones"
              :aria-label="`Opciones de «${conversacion.titulo || 'Conversación'}»`"
              aria-haspopup="menu"
              :aria-expanded="menuDe === conversacion.id"
              @click.stop="alternarMenu(conversacion.id)"
            >
              <IconoPanel nombre="opciones" :tamano="22" />
            </button>
            <div v-if="menuDe === conversacion.id" class="conversacion__menu" role="menu">
              <button type="button" role="menuitem" class="conversacion__menu-item" @click="empezarRenombrar(conversacion)">
                Cambiar nombre
              </button>
              <button
                type="button"
                role="menuitem"
                class="conversacion__menu-item conversacion__menu-item--peligro"
                @click="pedirBorrar(conversacion)"
              >
                Borrar
              </button>
            </div>
          </template>
        </li>
      </ul>
    </aside>

    <div v-if="listaAbierta" class="asistente__velo" aria-hidden="true" @click="listaAbierta = false" />

    <!-- El chat -->
    <section class="asistente__chat" aria-label="Conversación con el asistente">
      <header class="asistente__barra">
        <button
          type="button"
          class="boton boton--secundario asistente__ver-lista"
          aria-controls="asistente-conversaciones"
          :aria-expanded="listaAbierta"
          @click="listaAbierta = true"
        >
          <IconoPanel nombre="conversaciones" :tamano="18" /> Conversaciones
        </button>
        <h2 class="asistente__titulo">{{ actual?.titulo || 'Asistente' }}</h2>
        <span
          v-if="creditos !== null"
          class="etiqueta asistente__creditos numeros"
          title="Las preguntas que necesitan inteligencia artificial gastan créditos"
        >
          IA: {{ creditos }} {{ creditos === 1 ? 'crédito' : 'créditos' }}
        </span>
        <button
          v-if="actualId"
          type="button"
          class="boton boton--fantasma asistente__nueva-barra"
          @click="nuevaConversacion"
        >
          <IconoPanel nombre="mas" :tamano="18" /> Nueva
        </button>
      </header>

      <div
        ref="listaMensajes"
        class="asistente__mensajes"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        :aria-busy="cargandoMensajes || enviando ? 'true' : 'false'"
      >
        <!-- Cargando una conversación -->
        <div v-if="cargandoMensajes" class="asistente__cargando" aria-label="Cargando la conversación">
          <div class="esqueleto asistente__esqueleto-mensaje" />
          <div class="esqueleto asistente__esqueleto-mensaje asistente__esqueleto-mensaje--derecha" />
          <div class="esqueleto asistente__esqueleto-mensaje" />
        </div>

        <p v-else-if="errorMensajes" class="asistente__error" role="alert">
          {{ errorMensajes }}
          <button type="button" class="boton boton--secundario asistente__boton" @click="abrirConversacion(actualId)">
            Reintentar
          </button>
        </p>

        <!-- Conversación nueva: saludo, resumen y sugerencias -->
        <div v-if="vacia" class="bienvenida">
          <p class="bienvenida__hola">{{ nombre ? `Hola, ${nombre}` : 'Hola' }}</p>
          <p v-if="empresa" class="bienvenida__empresa">{{ empresa }}</p>
          <p class="bienvenida__frase">
            Cuéntame qué necesitas: buscar ínfimas, revisar un proceso, crear una alerta o armar una proforma.
          </p>

          <p v-if="errorInicio" class="asistente__error" role="alert">
            {{ errorInicio }}
            <button type="button" class="boton boton--secundario asistente__boton" @click="cargarInicio">
              Reintentar
            </button>
          </p>

          <div v-if="chips.length" class="bienvenida__chips" aria-label="Tu resumen de hoy">
            <button
              v-for="chip in chips"
              :key="chip.clave"
              type="button"
              class="chip chip--resumen"
              :disabled="enviando"
              @click="enviar(chip.mensaje)"
            >
              {{ chip.texto }}
            </button>
          </div>

          <div class="bienvenida__sugerencias">
            <p class="bienvenida__subtitulo">Puedes empezar con:</p>
            <button
              v-for="sugerencia in sugerenciasInicio"
              :key="sugerencia"
              type="button"
              class="sugerencia"
              :disabled="enviando"
              @click="enviar(sugerencia)"
            >
              <span class="sugerencia__texto">{{ sugerencia }}</span>
              <IconoPanel nombre="flecha" :tamano="18" />
            </button>
          </div>
        </div>

        <!-- Mensajes -->
        <template v-if="!cargandoMensajes">
          <article
            v-for="mensaje in mensajes"
            :key="mensaje.id"
            class="mensaje"
            :class="[
              `mensaje--${mensaje.rol === 'usuario' ? 'usuario' : 'asistente'}`,
              { 'mensaje--fallido': errorEnvio && errorEnvio.idTemporal === mensaje.id },
            ]"
          >
            <p class="solo-lectores">{{ mensaje.rol === 'usuario' ? 'Tú dijiste:' : 'El asistente dice:' }}</p>
            <!-- Lo que escribió la persona se pinta tal cual, con sus saltos de línea. -->
            <div v-if="mensaje.texto && mensaje.rol === 'usuario'" class="mensaje__burbuja">{{ mensaje.texto }}</div>
            <div v-else-if="mensaje.texto" class="mensaje__burbuja">
              <template v-for="(bloque, b) in segmentarTexto(mensaje.texto)" :key="b">
                <ul v-if="bloque.tipo === 'lista'" class="mensaje__lista">
                  <li v-for="(elemento, e) in bloque.elementos" :key="e">
                    <template v-for="(trozo, t) in elemento" :key="t">
                      <strong v-if="trozo.negrita">{{ trozo.texto }}</strong>
                      <template v-else>{{ trozo.texto }}</template>
                    </template>
                  </li>
                </ul>
                <p v-else class="mensaje__parrafo">
                  <template v-for="(linea, l) in bloque.lineas" :key="l">
                    <br v-if="l > 0" />
                    <template v-for="(trozo, t) in linea" :key="t">
                      <strong v-if="trozo.negrita">{{ trozo.texto }}</strong>
                      <template v-else>{{ trozo.texto }}</template>
                    </template>
                  </template>
                </p>
              </template>
            </div>

            <!-- Falló el envío: se dice aquí mismo, junto al mensaje. -->
            <div v-if="errorEnvio && errorEnvio.idTemporal === mensaje.id" class="mensaje__fallo" role="alert">
              <span>{{ errorEnvio.mensaje }}</span>
              <button type="button" class="boton boton--secundario asistente__boton" @click="reintentar">
                Reintentar
              </button>
            </div>

            <div v-if="mensaje.rol !== 'usuario' && mensaje.tarjetas?.length" class="mensaje__tarjetas">
              <TarjetaAsistente
                v-for="(tarjeta, indice) in mensaje.tarjetas"
                :key="indice"
                :tarjeta="tarjeta"
                @preparar="preparar"
                @ir="ir"
              />
            </div>

            <div
              v-if="mensaje.rol !== 'usuario' && mensaje.id === ultimaRespuestaId && mensaje.sugerencias?.length"
              class="mensaje__sugerencias"
              aria-label="Sugerencias"
            >
              <button
                v-for="sugerencia in sugerenciasVisibles(mensaje.sugerencias, vistasVigentes)"
                :key="sugerencia"
                type="button"
                class="chip"
                :disabled="enviando"
                @click="enviar(sugerencia)"
              >
                {{ sugerencia }}
              </button>
            </div>
          </article>
        </template>

        <!-- Pensando… -->
        <div v-if="enviando" class="mensaje mensaje--asistente" role="status">
          <div class="mensaje__burbuja pensando">
            <span>Pensando</span>
            <span class="pensando__puntos" aria-hidden="true"><i /><i /><i /></span>
          </div>
        </div>
      </div>

      <p v-if="!iaDisponible" class="asistente__nota">
        Ahora mismo la inteligencia artificial no está disponible: las preguntas complejas tendrán que
        esperar, pero las consultas rápidas (ínfimas, alertas, ofertas) siguen funcionando.
      </p>

      <!-- Escribir -->
      <form class="redactor" @submit.prevent="enviar()">
        <label class="solo-lectores" for="asistente-texto">Escribe tu mensaje al asistente</label>
        <div class="redactor__caja" :class="{ 'redactor__caja--escuchando': escuchando }">
          <textarea
            id="asistente-texto"
            ref="campo"
            v-model="borrador"
            class="redactor__campo"
            rows="1"
            :maxlength="LIMITE_TEXTO"
            :placeholder="escuchando ? 'Te escucho…' : 'Escribe aquí tu pregunta…'"
            aria-describedby="asistente-ayuda"
            @input="ajustarAltura"
            @keydown="alPulsarTecla"
          />
          <button
            v-if="dictadoDisponible"
            type="button"
            class="redactor__boton redactor__boton--micro"
            :class="{ 'redactor__boton--activo': escuchando }"
            :aria-label="escuchando ? 'Dejar de dictar' : 'Dictar con el micrófono'"
            :title="escuchando ? 'Dejar de dictar' : 'Dictar con el micrófono'"
            :aria-pressed="escuchando"
            @click="alternarDictado"
          >
            <IconoPanel nombre="microfono" :tamano="22" />
          </button>
          <button
            type="submit"
            class="redactor__boton redactor__boton--enviar"
            :disabled="!sePuedeEnviar"
            aria-label="Enviar mensaje"
            title="Enviar"
          >
            <IconoPanel nombre="enviar" :tamano="22" />
          </button>
        </div>
        <div class="redactor__pie">
          <span id="asistente-ayuda" class="redactor__ayuda">
            <template v-if="avisoDictado">{{ avisoDictado }}</template>
            <template v-else-if="escuchando">Habla ahora. Pulsa el micrófono para terminar.</template>
            <template v-else>Enter para enviar · Mayús + Enter para otra línea</template>
          </span>
          <span v-if="contador" class="redactor__contador numeros" aria-live="polite">{{ contador }}</span>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
/*
 * Todo va más grande que en el resto del panel a propósito: esta pantalla la usan también personas
 * mayores. Texto de 1 rem, el campo de 1,1 rem y botones de al menos 44 px.
 */
.asistente {
  position: relative;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  color: var(--texto);
  font-size: 1rem;
  line-height: 1.5;
}

/* ---------------------------------------------------------------- lista de conversaciones */

.asistente__lateral {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  min-height: 0;
  min-width: 0;
  padding: var(--e-4) var(--e-3);
  border-right: 1px solid var(--borde);
  background: var(--superficie-2);
  overflow-y: auto;
  overflow-x: hidden;
}

.asistente__lateral-cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
  padding: 0 var(--e-1);
}

.asistente__lateral-titulo {
  font-size: 0.9375rem;
  font-weight: 700;
  color: var(--texto-suave);
}

.asistente__cerrar-lista {
  display: none;
  min-width: 44px;
  min-height: 44px;
}

.asistente__nueva {
  min-height: 48px;
  font-size: 1rem;
  width: 100%;
}

.asistente__aviso-lista {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
  font-size: 0.9375rem;
}

.asistente__esqueletos {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.asistente__esqueleto {
  height: 52px;
}

.asistente__sin-conversaciones {
  padding: 0 var(--e-1);
  color: var(--texto-suave);
  font-size: 0.9375rem;
}

.conversaciones {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.conversacion {
  position: relative;
  display: flex;
  align-items: stretch;
  gap: 2px;
  border-radius: var(--r-2);
}

.conversacion:hover {
  background: var(--superficie-3);
}

.conversacion--activa,
.conversacion--activa:hover {
  background: var(--acento-suave);
}

.conversacion__abrir {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 52px;
  padding: var(--e-2) var(--e-3);
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: var(--texto);
  text-align: left;
  cursor: pointer;
}

.conversacion__titulo {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1rem;
  font-weight: 600;
}

.conversacion--activa .conversacion__titulo {
  color: var(--acento-fuerte);
}

.conversacion__fecha {
  font-size: 0.875rem;
  color: var(--texto-suave);
}

.conversacion__opciones {
  flex: none;
  display: grid;
  place-items: center;
  width: 44px;
  min-height: 44px;
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: var(--texto-suave);
  cursor: pointer;
}

.conversacion__opciones:hover {
  background: var(--superficie);
  color: var(--texto);
}

.conversacion__menu {
  position: absolute;
  top: calc(100% - 4px);
  right: 4px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  min-width: 11rem;
  padding: var(--e-1);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
  box-shadow: var(--sombra-2);
}

.conversacion__menu-item {
  min-height: 44px;
  padding: 0 var(--e-3);
  border: 0;
  border-radius: var(--r-1);
  background: transparent;
  color: var(--texto);
  font-size: 1rem;
  text-align: left;
  cursor: pointer;
}

.conversacion__menu-item:hover {
  background: var(--superficie-3);
}

.conversacion__menu-item--peligro {
  color: var(--error);
}

.conversacion__formulario,
.conversacion__confirmar {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-2);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
}

.conversacion__confirmar p {
  font-size: 0.9375rem;
  overflow-wrap: anywhere;
}

.conversacion__campo {
  width: 100%;
  min-height: 44px;
  padding: var(--e-2) var(--e-3);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  background: var(--superficie);
  font-size: 1rem;
}

.conversacion__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.conversacion__boton {
  flex: 1;
  min-height: 44px;
  font-size: 0.9375rem;
}

.conversacion__boton--peligro {
  border-color: var(--error);
}

/* ---------------------------------------------------------------- chat */

.asistente__chat {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}

.asistente__barra {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  min-height: 60px;
  padding: var(--e-2) var(--e-4);
  border-bottom: 1px solid var(--borde);
}

.asistente__ver-lista {
  display: none;
  min-height: 44px;
  font-size: 0.9375rem;
}

.asistente__titulo {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 1.125rem;
  font-weight: 700;
}

.asistente__creditos {
  font-size: 0.8125rem;
}

.asistente__nueva-barra {
  min-height: 44px;
  font-size: 0.9375rem;
}

.asistente__mensajes {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  padding: var(--e-5);
  overscroll-behavior: contain;
}

.asistente__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.asistente__esqueleto-mensaje {
  height: 64px;
  width: min(70%, 520px);
  border-radius: var(--r-3);
}

.asistente__esqueleto-mensaje--derecha {
  align-self: flex-end;
  height: 44px;
  width: min(45%, 320px);
}

.asistente__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
}

.asistente__boton {
  min-height: 44px;
  font-size: 0.9375rem;
}

.asistente__nota {
  margin: 0 var(--e-5);
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  color: var(--texto-suave);
  font-size: 0.9375rem;
}

/* Bienvenida */
.bienvenida {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  width: 100%;
  max-width: 720px;
  margin: auto;
  padding: var(--e-4) 0;
}

.bienvenida__hola {
  font-size: 2rem;
  font-weight: 700;
  line-height: 1.2;
}

.bienvenida__empresa {
  font-size: 1.125rem;
  color: var(--texto-suave);
}

.bienvenida__frase {
  margin-top: var(--e-2);
  font-size: 1.125rem;
}

.bienvenida__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin-top: var(--e-2);
}

.bienvenida__subtitulo {
  margin-top: var(--e-3);
  font-size: 0.9375rem;
  font-weight: 650;
  color: var(--texto-suave);
}

.bienvenida__sugerencias {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.sugerencia {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  min-height: 52px;
  padding: var(--e-2) var(--e-4);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-3);
  background: var(--superficie);
  color: var(--texto);
  font-size: 1.0625rem;
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--rapido) var(--curva),
    background-color var(--rapido) var(--curva);
}

.sugerencia:hover:not(:disabled) {
  border-color: var(--acento);
  background: var(--acento-tenue);
}

.sugerencia:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.sugerencia__texto {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.chip {
  min-height: 44px;
  padding: var(--e-2) var(--e-4);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  color: var(--texto);
  font-size: 1rem;
  text-align: left;
  cursor: pointer;
  transition:
    border-color var(--rapido) var(--curva),
    background-color var(--rapido) var(--curva);
}

.chip:hover:not(:disabled) {
  border-color: var(--acento);
  color: var(--acento-fuerte);
}

.chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.chip--resumen {
  border-color: var(--acento-suave);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  font-weight: 650;
}

/* Mensajes */
.mensaje {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  min-width: 0;
  max-width: min(100%, 760px);
}

.mensaje--usuario {
  align-self: flex-end;
  align-items: flex-end;
  max-width: min(85%, 620px);
}

.mensaje--asistente {
  align-self: flex-start;
  width: 100%;
}

.mensaje__burbuja {
  min-width: 0;
  max-width: 100%;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-3);
  font-size: 1rem;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.mensaje--usuario .mensaje__burbuja {
  border-bottom-right-radius: var(--r-1);
  background: var(--acento-suave);
  color: var(--texto);
  white-space: pre-wrap;
}

.mensaje--asistente .mensaje__burbuja {
  align-self: flex-start;
  border-bottom-left-radius: var(--r-1);
  background: var(--superficie-2);
  border: 1px solid var(--borde);
}

.mensaje--fallido .mensaje__burbuja {
  opacity: 0.75;
}

.mensaje__parrafo + .mensaje__parrafo,
.mensaje__parrafo + .mensaje__lista,
.mensaje__lista + .mensaje__parrafo,
.mensaje__lista + .mensaje__lista {
  margin-top: var(--e-2);
}

.mensaje__lista {
  margin: 0;
  padding-left: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
}

.mensaje__fallo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--e-2);
  color: var(--error);
  font-size: 0.9375rem;
}

.mensaje__tarjetas {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  width: 100%;
  min-width: 0;
}

.mensaje__sugerencias {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

/* Pensando… */
.pensando {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  color: var(--texto-suave);
}

.pensando__puntos {
  display: inline-flex;
  gap: 4px;
}

.pensando__puntos i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  animation: puntos-asistente 1.2s ease-in-out infinite;
}

.pensando__puntos i:nth-child(2) {
  animation-delay: 0.15s;
}

.pensando__puntos i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes puntos-asistente {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .pensando__puntos i {
    animation: none;
    opacity: 0.6;
  }
}

/* ---------------------------------------------------------------- redactor */

.redactor {
  flex: none;
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  padding: var(--e-3) var(--e-5) var(--e-4);
  border-top: 1px solid var(--borde);
  background: var(--superficie);
}

.redactor__caja {
  display: flex;
  align-items: flex-end;
  gap: var(--e-2);
  padding: var(--e-2);
  border: 2px solid var(--borde-fuerte);
  border-radius: var(--r-3);
  background: var(--superficie);
  transition: border-color var(--rapido) var(--curva);
}

.redactor__caja:focus-within {
  border-color: var(--acento);
}

.redactor__caja--escuchando {
  border-color: var(--acento);
  background: var(--acento-tenue);
}

.redactor__campo {
  flex: 1;
  min-width: 0;
  min-height: 44px;
  padding: var(--e-2);
  border: 0;
  background: transparent;
  color: var(--texto);
  font-size: 1.125rem;
  line-height: 1.5;
  resize: none;
  overflow-y: hidden;
}

.redactor__campo:focus,
.redactor__campo:focus-visible {
  outline: none;
}

.redactor__campo::placeholder {
  color: var(--texto-tenue);
}

.redactor__boton {
  flex: none;
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border: 0;
  border-radius: var(--r-2);
  cursor: pointer;
  transition:
    background-color var(--rapido) var(--curva),
    color var(--rapido) var(--curva);
}

.redactor__boton--micro {
  background: transparent;
  color: var(--texto-suave);
}

.redactor__boton--micro:hover {
  background: var(--superficie-3);
  color: var(--texto);
}

.redactor__boton--activo,
.redactor__boton--activo:hover {
  background: var(--acento);
  color: #fff;
}

.redactor__boton--enviar {
  background: var(--acento);
  color: #fff;
}

.redactor__boton--enviar:hover:not(:disabled) {
  background: var(--acento-fuerte);
}

.redactor__boton--enviar:disabled {
  background: var(--superficie-3);
  color: var(--texto-tenue);
  cursor: not-allowed;
}

.redactor__pie {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  min-height: 1.5rem;
  padding: 0 var(--e-1);
  font-size: 0.875rem;
  color: var(--texto-suave);
}

.redactor__ayuda {
  min-width: 0;
}

.redactor__contador {
  flex: none;
  font-weight: 650;
}

/* ---------------------------------------------------------------- móvil y tableta */

.asistente__velo {
  display: none;
}

@media (max-width: 1023px) {
  .asistente {
    grid-template-columns: minmax(0, 1fr);
  }

  /* La lista se vuelve un cajón dentro de la propia pantalla del asistente. */
  .asistente__lateral {
    position: absolute;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 10;
    width: min(320px, 88%);
    border-right: 1px solid var(--borde);
    box-shadow: var(--sombra-3);
    transform: translateX(-104%);
    visibility: hidden;
    transition:
      transform var(--normal) var(--curva),
      visibility var(--normal);
  }

  .asistente--lista-abierta .asistente__lateral {
    transform: translateX(0);
    visibility: visible;
  }

  .asistente__velo {
    display: block;
    position: absolute;
    inset: 0;
    z-index: 9;
    background: rgb(0 0 0 / 30%);
  }

  .asistente__cerrar-lista,
  .asistente__ver-lista {
    display: inline-flex;
  }
}

@media (max-width: 639px) {
  .asistente {
    border-radius: var(--r-2);
  }

  .asistente__barra {
    padding: var(--e-2) var(--e-3);
    gap: var(--e-2);
    flex-wrap: wrap;
  }

  .asistente__titulo {
    order: 5;
    flex-basis: 100%;
    font-size: 1rem;
  }

  .asistente__mensajes {
    padding: var(--e-4) var(--e-3);
  }

  .asistente__nota {
    margin: 0 var(--e-3);
  }

  .redactor {
    padding: var(--e-2) var(--e-3) var(--e-3);
  }

  .bienvenida__hola {
    font-size: 1.625rem;
  }

  .mensaje--usuario {
    max-width: 92%;
  }

  .redactor__boton {
    width: 44px;
    height: 44px;
  }
}
</style>
