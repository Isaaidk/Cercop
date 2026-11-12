<script setup>
/**
 * Menú lateral del panel: las áreas y sus pantallas, a la izquierda.
 *
 * Sustituye a la fila de pastillas de áreas y a las pestañas que había encima del contenido. Con
 * doce pantallas, la fila obligaba a pulsar un área para descubrir qué había dentro; en una columna
 * se ve todo a la vez y cada área dice en una línea para qué sirve, que es lo que pidió el cliente:
 * que el usuario no se agobie buscando dónde está cada cosa.
 *
 * Este componente solo pinta y avisa. Qué pantallas existen para cada rol, cuáles están cerradas por
 * plazo y qué pasa al elegir una lo decide `VistaPanel`, que es donde ya vivía esa lógica: si el menú
 * tuviera su propia copia de los permisos, un cambio de rol se quedaría a medias en uno de los dos.
 *
 * Dos formas según el ancho:
 * - **Escritorio**: columna fija que se puede plegar a solo iconos. Plegado, cada icono lleva su
 *   nombre en el `title` y en `aria-label`, porque un icono solo no se lee igual para todos.
 * - **Móvil y tableta**: cajón que entra desde la izquierda con el botón ☰ de la barra superior y se
 *   cierra al elegir una pantalla, al tocar el velo o con Escape.
 */
import { onBeforeUnmount, onMounted } from 'vue'

import IconoPanel from '@/components/IconoPanel.vue'
import { numero } from '@/utils/formato'

const props = defineProps({
  /** Áreas visibles para quien está delante: `{ id, etiqueta, pista, opciones: [{ id, etiqueta }] }`. */
  areas: { type: Array, required: true },
  activa: { type: String, required: true },
  /** Plegado a solo iconos (escritorio). */
  plegado: { type: Boolean, default: false },
  /** Cajón abierto (móvil). */
  abierto: { type: Boolean, default: false },
  esMovil: { type: Boolean, default: false },
  /** Cuántas hay de cada familia, para el número discreto junto a «Ínfimas cuantías» y «Procesos». */
  cuentas: { type: Object, default: () => ({}) },
  /** Devuelve el motivo del cierre si la pantalla está cerrada por plazo, o `''`. */
  motivoCierre: { type: Function, default: () => '' },
})

const emit = defineEmits(['elegir', 'alternar-plegado', 'cerrar'])

/** Plegado solo tiene sentido en escritorio: en el cajón siempre se ve el nombre completo. */
const soloIconos = () => props.plegado && !props.esMovil

function elegir(id) {
  emit('elegir', id)
  if (props.esMovil) emit('cerrar')
}

function alPulsarTecla(evento) {
  if (evento.key === 'Escape' && props.abierto) emit('cerrar')
}

onMounted(() => document.addEventListener('keydown', alPulsarTecla))
onBeforeUnmount(() => document.removeEventListener('keydown', alPulsarTecla))
</script>

<template>
  <div
    v-if="esMovil && abierto"
    class="menu__velo"
    aria-hidden="true"
    @click="emit('cerrar')"
  />
  <nav
    id="menu-lateral"
    class="menu"
    :class="{
      'menu--plegado': soloIconos(),
      'menu--cajon': esMovil,
      'menu--abierto': esMovil && abierto,
    }"
    aria-label="Menú del panel"
    :aria-hidden="esMovil && !abierto ? 'true' : undefined"
    :inert="esMovil && !abierto ? true : undefined"
  >
    <div v-if="esMovil" class="menu__cabecera">
      <span class="menu__marca">
        <img src="/logo-cercoapp.png" alt="" width="28" height="28" />
        CercoApp
      </span>
      <button
        type="button"
        class="boton boton--fantasma boton--icono"
        aria-label="Cerrar el menú"
        @click="emit('cerrar')"
      >
        <IconoPanel nombre="cerrar" />
      </button>
    </div>

    <div class="menu__desplazable">
      <section v-for="area in areas" :key="area.id" class="menu__area">
        <!-- Un área de una sola pantalla (Inicio) no necesita cabecera: sería repetir su nombre. -->
        <header v-if="area.opciones.length > 1 || area.pista" v-show="!soloIconos()" class="menu__area-cabecera">
          <p class="menu__area-titulo">{{ area.etiqueta }}</p>
          <p v-if="area.pista" class="menu__area-pista">{{ area.pista }}</p>
        </header>
        <hr v-if="soloIconos() && area !== areas[0]" class="menu__raya" />

        <ul class="menu__lista">
          <li v-for="opcion in area.opciones" :key="opcion.id">
            <button
              type="button"
              class="menu__item"
              :class="{
                'menu__item--activo': activa === opcion.id,
                'menu__item--cerrado': motivoCierre(opcion.id),
              }"
              :aria-current="activa === opcion.id ? 'page' : undefined"
              :aria-label="soloIconos() ? opcion.etiqueta : undefined"
              :title="motivoCierre(opcion.id) || (soloIconos() ? opcion.etiqueta : undefined)"
              @click="elegir(opcion.id)"
            >
              <IconoPanel :nombre="motivoCierre(opcion.id) ? 'candado' : opcion.id" />
              <span v-if="!soloIconos()" class="menu__texto">{{ opcion.etiqueta }}</span>
              <span
                v-if="!soloIconos() && cuentas[opcion.id]"
                class="menu__cuenta numeros"
                :aria-label="`${numero(cuentas[opcion.id])} resultados`"
              >
                {{ numero(cuentas[opcion.id]) }}
              </span>
            </button>
          </li>
        </ul>
      </section>
    </div>

    <button
      v-if="!esMovil"
      type="button"
      class="menu__plegar"
      :aria-label="plegado ? 'Desplegar el menú' : 'Plegar el menú'"
      :title="plegado ? 'Desplegar el menú' : 'Plegar el menú'"
      :aria-expanded="!plegado"
      @click="emit('alternar-plegado')"
    >
      <IconoPanel :nombre="plegado ? 'desplegar' : 'plegar'" :tamano="16" />
      <span v-if="!plegado">Plegar menú</span>
    </button>
  </nav>
</template>

<style scoped>
.menu {
  position: sticky;
  top: var(--altura-cabecera);
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--altura-cabecera));
  width: 100%;
  background: var(--superficie);
  border-right: 1px solid var(--borde);
}

.menu__desplazable {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: var(--e-3) var(--e-3) var(--e-4);
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  scrollbar-width: thin;
}

.menu__area {
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
}

.menu__area-cabecera {
  padding: 0 var(--e-2) var(--e-1);
}

.menu__area-titulo {
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--texto-tenue);
}

.menu__area-pista {
  margin-top: 1px;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.35;
}

.menu__raya {
  height: 1px;
  margin: 0 var(--e-2) var(--e-1);
  border: 0;
  background: var(--borde);
}

.menu__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.menu__item {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  width: 100%;
  min-height: 38px;
  padding: 0.45rem var(--e-3);
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: var(--texto-suave);
  font-size: var(--t-base);
  font-weight: 550;
  text-align: left;
  cursor: pointer;
  transition:
    background-color var(--rapido) var(--curva),
    color var(--rapido) var(--curva);
}

.menu__item:hover {
  background: var(--superficie-3);
  color: var(--texto);
}

/* El elegido es el único elemento del menú con el color de acento: así se encuentra de un vistazo. */
.menu__item--activo,
.menu__item--activo:hover {
  background: var(--acento-suave);
  color: var(--acento-fuerte);
  font-weight: 650;
}

.menu__item--cerrado {
  opacity: 0.6;
}

.menu__texto {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu__cuenta {
  padding: 0 0.4rem;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto-suave);
  font-size: 0.7rem;
  font-weight: 650;
}

.menu__item--activo .menu__cuenta {
  background: var(--superficie);
  color: var(--acento-fuerte);
}

.menu__plegar {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin: var(--e-2) var(--e-3) var(--e-3);
  padding: 0.45rem var(--e-3);
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  font-weight: 600;
  cursor: pointer;
}

.menu__plegar:hover {
  background: var(--superficie-3);
  color: var(--texto);
}

/* Plegado: solo iconos, centrados. */
.menu--plegado .menu__desplazable {
  padding-left: var(--e-2);
  padding-right: var(--e-2);
  gap: var(--e-2);
}

.menu--plegado .menu__item,
.menu--plegado .menu__plegar {
  justify-content: center;
  padding-left: 0;
  padding-right: 0;
}

.menu--plegado .menu__plegar {
  margin-left: var(--e-2);
  margin-right: var(--e-2);
}

/* Cajón de móvil: fuera del flujo, entra desde la izquierda. */
.menu--cajon {
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 60;
  width: min(300px, 86vw);
  height: auto;
  transform: translateX(-102%);
  /* `visibility` también transiciona: al cerrar espera a que termine el deslizamiento antes de
     esconderse, y escondido no recibe el foco del tabulador. */
  transition:
    transform var(--normal) var(--curva),
    visibility var(--normal);
  visibility: hidden;
}

.menu--abierto {
  transform: translateX(0);
  visibility: visible;
  box-shadow: var(--sombra-3);
}

.menu__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
  height: var(--altura-cabecera);
  padding: 0 var(--e-3) 0 var(--e-4);
  border-bottom: 1px solid var(--borde);
}

.menu__marca {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-weight: 650;
}

.menu__marca img {
  border-radius: 50%;
}

.menu__velo {
  position: fixed;
  inset: 0;
  z-index: 55;
  background: rgb(0 0 0 / 35%);
  animation: aparecer var(--rapido) var(--curva) both;
}
</style>
