<script setup>
/**
 * Campana de la barra superior: activar o apagar las notificaciones de este navegador, elegir si
 * también avisa de ínfimas según el perfil, y el sonido.
 *
 * Con el panel abierto, cuando llega un aviso suena la marimba y aparece un mensaje abajo a la
 * derecha. No pregunta nada al servidor por su cuenta: solo al abrir el menú (estado) y al pulsar.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import IconoPanel from '@/components/IconoPanel.vue'
import {
  activar,
  desactivar,
  escucharAvisos,
  esIosSinInstalar,
  estadoActual,
  haySoporte,
} from '@/utils/notificaciones'
import { fijarSonido, sonarAviso, sonidoActivo } from '@/utils/sonido'

const abierto = ref(false)
const cargando = ref(false)
const estado = ref({ soporte: haySoporte(), permiso: 'default', suscrito: false, avisarPerfil: false })
const avisarPerfil = ref(true)
const sonido = ref(sonidoActivo())
const error = ref('')
const avisos = ref([])
let dejarDeEscuchar = () => {}
let siguienteId = 0

async function refrescar() {
  estado.value = await estadoActual()
  if (estado.value.suscrito) avisarPerfil.value = estado.value.avisarPerfil
}

async function alternarMenu() {
  abierto.value = !abierto.value
  error.value = ''
  if (abierto.value) await refrescar().catch(() => {})
}

async function encender() {
  cargando.value = true
  error.value = ''
  try {
    await activar({ avisarPerfil: avisarPerfil.value })
    await refrescar()
    sonarAviso()
  } catch (e) {
    error.value = e?.message || 'No se pudieron activar las notificaciones.'
  } finally {
    cargando.value = false
  }
}

async function apagar() {
  cargando.value = true
  await desactivar()
  await refrescar().catch(() => {})
  cargando.value = false
}

async function cambiarPerfil() {
  if (estado.value.suscrito) await encender()
}

function cambiarSonido() {
  fijarSonido(sonido.value)
  if (sonido.value) sonarAviso({ forzar: true })
}

function mostrarAviso({ titulo, cuerpo }) {
  const id = ++siguienteId
  avisos.value = [...avisos.value.slice(-2), { id, titulo, cuerpo }]
  sonarAviso()
  setTimeout(() => cerrarAviso(id), 8000)
}

function cerrarAviso(id) {
  avisos.value = avisos.value.filter((aviso) => aviso.id !== id)
}

onMounted(() => {
  dejarDeEscuchar = escucharAvisos(mostrarAviso)
})
onBeforeUnmount(() => dejarDeEscuchar())
</script>

<template>
  <div class="notif">
    <button
      type="button"
      class="boton boton--fantasma boton--icono notif__campana"
      :class="{ 'notif__campana--activa': estado.suscrito }"
      aria-label="Notificaciones"
      title="Notificaciones"
      :aria-expanded="abierto"
      aria-controls="menu-notificaciones"
      @click="alternarMenu"
    >
      <IconoPanel nombre="campana" />
      <span v-if="estado.suscrito" class="notif__punto" aria-hidden="true"></span>
    </button>

    <Transition name="fundido">
      <div
        v-if="abierto"
        id="menu-notificaciones"
        class="notif__menu superficie aparece"
        role="dialog"
        aria-label="Notificaciones"
      >
        <p class="notif__titulo">Notificaciones</p>

        <p v-if="!estado.soporte" class="notif__texto">
          Este navegador no permite notificaciones. Prueba con Chrome, Edge o Firefox.
        </p>
        <p v-else-if="esIosSinInstalar()" class="notif__texto">
          En iPhone: toca «Compartir» → «Agregar a inicio», abre CercoApp desde ese ícono y vuelve
          aquí para activarlas.
        </p>
        <template v-else>
          <p class="notif__texto">
            <template v-if="estado.suscrito">
              Activadas en este navegador. Te avisamos aunque CercoApp esté cerrada.
            </template>
            <template v-else>
              Te avisamos al instante cuando salga una oportunidad para ti, aunque CercoApp esté
              cerrada.
            </template>
          </p>

          <label class="notif__opcion">
            <input v-model="avisarPerfil" type="checkbox" @change="cambiarPerfil" />
            <span>También ínfimas cuantías que encajan con mis CPC y mi perfil</span>
          </label>
          <p class="notif__ayuda">Tus alertas guardadas siempre avisan.</p>

          <button
            v-if="!estado.suscrito"
            type="button"
            class="boton boton--principal notif__accion"
            :disabled="cargando"
            @click="encender"
          >
            {{ cargando ? 'Activando…' : 'Activar notificaciones' }}
          </button>
          <button
            v-else
            type="button"
            class="boton boton--secundario notif__accion"
            :disabled="cargando"
            @click="apagar"
          >
            Apagar en este navegador
          </button>
        </template>

        <hr class="separador" />
        <label class="notif__opcion">
          <input v-model="sonido" type="checkbox" @change="cambiarSonido" />
          <span>Sonido de marimba al llegar un aviso</span>
        </label>
        <button type="button" class="boton boton--fantasma notif__probar" @click="sonarAviso({ forzar: true })">
          Probar sonido
        </button>

        <p v-if="error" class="notif__error" role="alert">{{ error }}</p>
      </div>
    </Transition>

    <div class="notif__flotantes" aria-live="polite">
      <TransitionGroup name="aviso-flotante">
        <div v-for="aviso in avisos" :key="aviso.id" class="notif__flotante superficie">
          <IconoPanel nombre="campana" :tamano="20" class="notif__flotante-icono" />
          <div class="notif__flotante-texto">
            <strong>{{ aviso.titulo }}</strong>
            <span>{{ aviso.cuerpo }}</span>
          </div>
          <button
            type="button"
            class="boton boton--fantasma boton--icono"
            aria-label="Cerrar aviso"
            @click="cerrarAviso(aviso.id)"
          >
            ✕
          </button>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.notif {
  position: relative;
}
.notif__campana {
  position: relative;
}
.notif__campana--activa {
  color: var(--acento);
}
.notif__punto {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ok);
}
.notif__menu {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: min(340px, calc(100vw - 32px));
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 50;
}
.notif__titulo {
  font-weight: 700;
  font-size: 1rem;
}
.notif__texto,
.notif__ayuda {
  font-size: 0.875rem;
  color: var(--texto-suave);
  line-height: 1.45;
}
.notif__ayuda {
  font-size: 0.8125rem;
  margin-top: -4px;
}
.notif__opcion {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  font-size: 0.9rem;
  line-height: 1.4;
  cursor: pointer;
}
.notif__opcion input {
  width: 18px;
  height: 18px;
  margin-top: 2px;
  flex: none;
}
.notif__accion {
  width: 100%;
  min-height: 44px;
}
.notif__probar {
  align-self: flex-start;
}
.notif__error {
  font-size: 0.875rem;
  color: var(--error);
}
.notif__flotantes {
  position: fixed;
  right: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 1000;
  pointer-events: none;
}
.notif__flotante {
  pointer-events: auto;
  width: min(360px, calc(100vw - 32px));
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 12px 14px 16px;
  border-left: 4px solid var(--acento);
  box-shadow: 0 10px 30px rgba(11, 46, 79, 0.18);
}
.notif__flotante-icono {
  color: var(--acento);
  flex: none;
  margin-top: 2px;
}
.notif__flotante-texto {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.9rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.aviso-flotante-enter-active,
.aviso-flotante-leave-active {
  transition:
    transform 0.32s cubic-bezier(0.2, 0.9, 0.3, 1.2),
    opacity 0.25s ease;
}
.aviso-flotante-enter-from {
  transform: translateY(16px) scale(0.96);
  opacity: 0;
}
.aviso-flotante-leave-to {
  transform: translateX(24px);
  opacity: 0;
}
.notif__campana--activa :deep(svg) {
  animation: campanita 0.9s ease 1;
}
@keyframes campanita {
  0%,
  100% {
    transform: rotate(0);
  }
  20% {
    transform: rotate(14deg);
  }
  40% {
    transform: rotate(-10deg);
  }
  60% {
    transform: rotate(6deg);
  }
  80% {
    transform: rotate(-3deg);
  }
}
@media (prefers-reduced-motion: reduce) {
  .aviso-flotante-enter-active,
  .aviso-flotante-leave-active {
    transition: opacity 0.15s linear;
  }
  .aviso-flotante-enter-from,
  .aviso-flotante-leave-to {
    transform: none;
  }
  .notif__campana--activa :deep(svg) {
    animation: none;
  }
}
</style>
