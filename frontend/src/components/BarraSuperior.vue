<script setup>
/**
 * Barra superior: identidad, pantalla actual, presencia y cuenta.
 *
 * Desde el rediseño es **mínima**: la navegación se fue al menú lateral, y aquí queda solo lo que
 * vale en cualquier pantalla —dónde estoy, el tema, el plazo, quién está conectado y mi cuenta—. El
 * botón ☰ abre el menú lateral (cajón en móvil, plegar en escritorio) y el de «Filtros» aparece solo
 * en las pantallas que usan la columna de filtros.
 *
 * En móvil se simplifica en lugar de encogerse: se oculta el nombre de la persona —queda el avatar,
 * que es lo que se reconoce— y los botones pasan a ser de solo icono. Aplastarlo todo en una fila
 * estrecha deja botones de tres milímetros que no se pueden pulsar con el dedo.
 */
import { computed, ref } from 'vue'

import IconoPanel from '@/components/IconoPanel.vue'
import IndicadorPresencia from '@/components/IndicadorPresencia.vue'

const props = defineProps({
  conectados: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  personas: { type: Array, default: () => [] },
  alcance: { type: String, default: 'proceso' },
  enVivo: { type: Boolean, default: false },
  tema: { type: String, default: 'claro' },
  nombre: { type: String, default: '' },
  email: { type: String, default: '' },
  admin: { type: Boolean, default: false },
  /**
   * Si esta persona es el dueño de la plataforma.
   *
   * El punto de presencia se enseña solo entonces. No es lo mismo que `admin`: un administrador de
   * empresa administra su propia gente, y quién está conectado es información de la operación que
   * ve el dueño del sistema. Con `admin` en su lugar, cualquier cliente vería a sus usuarios
   * conectados y —peor— el servidor le respondería con un 403 que parecería un fallo del panel.
   */
  presencia: { type: Boolean, default: false },
  panelAbierto: { type: Boolean, default: false },
  /** Si los filtros se están viendo. En escritorio es la columna; en móvil, el cajón abierto. */
  filtrosAbiertos: { type: Boolean, default: true },
  /** Si hay algún filtro puesto, para avisar en el propio botón cuando la columna está escondida. */
  filtrosActivos: { type: Boolean, default: false },
  /**
   * Si esta pantalla tiene columna de filtros que abrir.
   *
   * La pestaña de ofertas trae sus propios filtros dentro de la pestaña y no usa los del panel, así
   * que ahí no hay nada que mostrar ni ocultar: el botón desaparece en lugar de quedar pulsable y
   * sin efecto, que se lee como un fallo.
   */
  conFiltros: { type: Boolean, default: true },
  /** Nombre de la pantalla que se está viendo, y del área a la que pertenece. */
  titulo: { type: String, default: '' },
  area: { type: String, default: '' },
  /** Si el menú lateral está a la vista: cajón abierto en móvil, columna desplegada en escritorio. */
  menuAbierto: { type: Boolean, default: true },
  /** Días que le quedan. `null` oculta el reloj: el superadministrador no tiene plazo. */
  diasRestantes: { type: Number, default: null },
  /** Texto del vencimiento, para el detalle al pasar el mouse. */
  textoPlazo: { type: String, default: '' },
})

const emit = defineEmits([
  'alternar-tema',
  'cerrar-sesion',
  'alternar-panel',
  'alternar-filtros',
  'alternar-menu',
  'cambiar-contrasena',
  'pedir-tiempo',
])

const relojAbierto = ref(false)
const pedidoEnviado = ref(false)

function alSalirReloj(evento) {
  const destino = evento.relatedTarget
  if (destino && evento.currentTarget.contains(destino)) return
  relojAbierto.value = false
}

const claseReloj = computed(() => {
  const dias = props.diasRestantes
  if (dias === null) return ''
  if (dias <= 1) return 'reloj--urgente'
  if (dias <= 7) return 'reloj--aviso'
  return 'reloj--holgado'
})

const iniciales = computed(() => {
  const fuente = props.nombre || props.email || '?'
  return fuente
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((parte) => parte[0].toUpperCase())
    .join('')
})
</script>

<template>
  <header class="barra">
    <button
      type="button"
      class="barra__boton-menu"
      :aria-label="menuAbierto ? 'Ocultar el menú' : 'Mostrar el menú'"
      :aria-expanded="menuAbierto"
      aria-controls="menu-lateral"
      :title="menuAbierto ? 'Ocultar el menú' : 'Mostrar el menú'"
      @click="emit('alternar-menu')"
    >
      <IconoPanel nombre="menu" :tamano="20" />
    </button>

    <div class="marca">
      <span class="marca__icono">
        <img src="/logo-cercoapp.png" alt="" width="32" height="32" />
      </span>
      <span class="marca__texto">CercoApp</span>
    </div>

    <!-- Dónde estoy. El área va en tono tenue y la pantalla en el del texto: se lee primero lo que
         importa, y el área solo sitúa. -->
    <p v-if="titulo" class="barra__titulo">
      <span v-if="area" class="barra__area">{{ area }}</span>
      <span v-if="area" class="barra__sep" aria-hidden="true">/</span>
      <span class="barra__pantalla">{{ titulo }}</span>
    </p>

    <div class="barra__acciones">
      <!-- Filtros: solo en las pantallas que usan la columna. En escritorio la esconde y la muestra;
           en móvil abre el cajón. El punto avisa de que hay filtros puestos aunque no se vean. -->
      <button
        v-if="conFiltros"
        type="button"
        class="boton boton--secundario boton--pequeno barra__filtros"
        :aria-label="filtrosAbiertos ? 'Ocultar los filtros' : 'Mostrar los filtros'"
        :aria-expanded="filtrosAbiertos"
        aria-controls="panel-filtros"
        :title="filtrosAbiertos ? 'Ocultar los filtros' : 'Mostrar los filtros'"
        @click="emit('alternar-filtros')"
      >
        <IconoPanel nombre="filtros" :tamano="16" />
        <span class="barra__filtros-texto">Filtros</span>
        <span v-if="filtrosActivos" class="barra__filtros-marca" aria-hidden="true" />
      </button>

      <IndicadorPresencia
        v-if="presencia"
        :conectados="conectados"
        :total="total"
        :personas="personas"
        :alcance="alcance"
        :en-vivo="enVivo"
      />

      <button
        type="button"
        class="boton boton--fantasma boton--icono"
        :aria-label="tema === 'oscuro' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'"
        :title="tema === 'oscuro' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'"
        @click="emit('alternar-tema')"
      >
        <IconoPanel :nombre="tema === 'oscuro' ? 'sol' : 'luna'" />
      </button>

      <div
        v-if="diasRestantes !== null"
        class="reloj"
        @mouseenter="relojAbierto = true"
        @mouseleave="relojAbierto = false"
        @focusin="relojAbierto = true"
        @focusout="alSalirReloj"
      >
        <button
          type="button"
          class="reloj__boton"
          :class="claseReloj"
          :aria-expanded="relojAbierto"
          aria-label="Tiempo de acceso que te queda"
        >
          <IconoPanel nombre="reloj" :tamano="17" />
        </button>
        <div v-if="relojAbierto" class="reloj__detalle superficie" role="status">
          <p>{{ textoPlazo }}</p>
          <button
            type="button"
            class="boton boton--secundario boton--pequeno"
            :disabled="pedidoEnviado"
            @click="pedidoEnviado = true; emit('pedir-tiempo')"
          >
            {{ pedidoEnviado ? 'Pedido enviado' : 'Pedir más tiempo' }}
          </button>
        </div>
      </div>

      <div class="barra__cuenta">
        <button
          type="button"
          class="barra__perfil"
          :aria-expanded="panelAbierto"
          aria-controls="menu-cuenta"
          @click="emit('alternar-panel')"
        >
          <span class="barra__avatar" aria-hidden="true">{{ iniciales }}</span>
          <span class="barra__datos">
            <span class="barra__nombre">{{ nombre || email }}</span>
          </span>
        </button>

        <Transition name="fundido">
          <div v-if="panelAbierto" id="menu-cuenta" class="barra__menu superficie aparece">
            <p class="barra__menu-nombre">{{ nombre || email }}</p>
            <p class="barra__menu-email">{{ email }}</p>
            <span v-if="admin" class="etiqueta etiqueta--acento barra__menu-rol">Administrador</span>
            <hr class="separador" />
            <button
              type="button"
              class="boton boton--fantasma barra__menu-boton"
              @click="emit('cambiar-contrasena')"
            >
              Cambiar mi contraseña
            </button>
            <button type="button" class="boton boton--peligro barra__menu-boton" @click="emit('cerrar-sesion')">
              Cerrar sesión
            </button>
          </div>
        </Transition>
      </div>
    </div>
  </header>
</template>

<style scoped>
.barra {
  position: sticky;
  top: 0;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: var(--e-3);
  height: var(--altura-cabecera);
  padding: 0 var(--e-4);
  background: color-mix(in srgb, var(--superficie) 88%, transparent);
  /* El desenfoque hace que el contenido se intuya al desplazar por debajo, en lugar de desaparecer
     tras una franja opaca. Es una guía de que hay más página. */
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--borde);
}

.reloj {
  position: relative;
}

.reloj__boton {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-md);
  cursor: pointer;
}

.reloj__boton {
  color: var(--texto-suave);
}

/* Con tiempo de sobra el reloj va en gris: el color se guarda para cuando hay que hacer algo. */
.reloj--holgado {
  color: var(--texto-suave);
}

.reloj--aviso {
  color: var(--aviso);
  border-color: var(--aviso);
}

.reloj--urgente {
  color: var(--error);
  border-color: var(--error);
}

.reloj__detalle {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  width: 240px;
  padding: var(--e-3);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  box-shadow: var(--sombra-2);
  font-size: var(--t-sm);
  line-height: 1.45;
}

.marca {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  min-width: 0;
}

.marca__icono {
  display: grid;
  place-items: center;
  flex: none;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  overflow: hidden;
}

.marca__icono img {
  display: block;
  width: 100%;
  height: 100%;
}

html[data-tema='oscuro'] .marca__icono {
  box-shadow: 0 0 0 1px rgb(255 255 255 / 16%);
}

.marca__texto {
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
}

/* La pantalla actual. Separada de la marca por una raya fina, como una miga de pan corta. */
.barra__titulo {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  min-width: 0;
  padding-left: var(--e-3);
  margin-left: var(--e-1);
  border-left: 1px solid var(--borde);
  font-size: var(--t-base);
  white-space: nowrap;
}

.barra__area {
  color: var(--texto-tenue);
}

.barra__sep {
  color: var(--borde-fuerte);
}

.barra__pantalla {
  font-weight: 650;
  color: var(--texto);
  overflow: hidden;
  text-overflow: ellipsis;
}

.barra__acciones {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin-left: auto;
}

.barra__cuenta {
  position: relative;
}

.barra__perfil {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.25rem 0.6rem 0.25rem 0.25rem;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  cursor: pointer;
  transition: border-color var(--rapido) var(--curva);
}

.barra__perfil:hover {
  border-color: var(--acento);
}

.barra__avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border-radius: 50%;
  background: var(--acento-suave);
  color: var(--acento-fuerte);
  font-size: var(--t-xs);
  font-weight: 700;
}

.barra__datos {
  display: flex;
  align-items: center;
  gap: var(--e-2);
}

.barra__nombre {
  font-size: var(--t-sm);
  font-weight: 550;
  max-width: 14ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.barra__menu {
  position: absolute;
  top: calc(100% + var(--e-2));
  right: 0;
  z-index: 40;
  width: 220px;
  padding: var(--e-2);
  box-shadow: var(--sombra-3);
}

.barra__menu-nombre {
  padding: var(--e-2) var(--e-2) 0;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.barra__menu-rol {
  margin: 0 var(--e-2) var(--e-2);
}

.barra__menu {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 2px;
}

.barra__menu-email {
  padding: 0 var(--e-2) var(--e-1);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  overflow-wrap: anywhere;
}

.barra__menu-boton {
  width: 100%;
  justify-content: flex-start;
}

/* El botón del menú lateral: en móvil abre el cajón y en escritorio pliega la columna. */
.barra__boton-menu {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  flex: none;
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: var(--texto-suave);
  cursor: pointer;
}

.barra__boton-menu:hover {
  background: var(--superficie-3);
  color: var(--texto);
}

.barra__filtros {
  position: relative;
}

.barra__filtros-marca {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--acento);
}

.fundido-enter-active,
.fundido-leave-active {
  transition: opacity var(--rapido) var(--curva), transform var(--rapido) var(--curva);
  transform-origin: top right;
}

.fundido-enter-from,
.fundido-leave-to {
  opacity: 0;
  transform: scale(0.96) translateY(-4px);
}

@media (max-width: 1023px) {
  .barra__area,
  .barra__sep {
    display: none;
  }
}

@media (max-width: 639px) {
  .barra {
    gap: var(--e-2);
    padding: 0 var(--e-3);
  }

  .barra__datos,
  .barra__nombre,
  .marca__texto,
  .barra__filtros-texto {
    display: none;
  }

  .barra__perfil {
    padding: 0.25rem;
  }

  .barra__titulo {
    padding-left: var(--e-2);
    margin-left: 0;
    font-size: var(--t-sm);
  }

  .barra__acciones {
    gap: var(--e-1);
  }
}
</style>
