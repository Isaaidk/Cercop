<script setup>
/**
 * Barra superior: identidad, estado del servicio, presencia y cuenta.
 *
 * En móvil se simplifica en lugar de encogerse: se oculta el nombre de la persona —queda el avatar,
 * que es lo que se reconoce— y los botones pasan a ser de solo icono. Aplastarlo todo en una fila
 * estrecha deja botones de tres milímetros que no se pueden pulsar con el dedo.
 */
import { computed } from 'vue'

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
  panelAbierto: { type: Boolean, default: false },
  /** Si los filtros se están viendo. En escritorio es la columna; en móvil, el cajón abierto. */
  filtrosAbiertos: { type: Boolean, default: true },
  /** Si hay algún filtro puesto, para avisar en el propio botón cuando la columna está escondida. */
  filtrosActivos: { type: Boolean, default: false },
})

const emit = defineEmits([
  'alternar-tema',
  'cerrar-sesion',
  'alternar-panel',
  'alternar-filtros',
  'cambiar-contrasena',
])

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
      class="barra__hamburguesa"
      :aria-label="filtrosAbiertos ? 'Ocultar los filtros' : 'Mostrar los filtros'"
      :aria-expanded="filtrosAbiertos"
      aria-controls="panel-filtros"
      :title="filtrosAbiertos ? 'Ocultar los filtros' : 'Mostrar los filtros'"
      @click="emit('alternar-filtros')"
    >
      <span aria-hidden="true">☰</span>
      <!-- El punto verde avisa de que hay filtros puestos aunque la columna esté escondida: sin
           él, la única forma de saberlo sería volver a mostrarla. -->
      <span
        v-if="filtrosActivos && !filtrosAbiertos"
        class="barra__hamburguesa-marca"
        aria-hidden="true"
      />
    </button>

    <div class="marca">
      <span class="marca__icono" aria-hidden="true">CP</span>
      <span class="marca__texto">
        Contratación pública
        <small>Panel de seguimiento</small>
      </span>
    </div>

    <div class="barra__acciones">
      <IndicadorPresencia
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
        @click="emit('alternar-tema')"
      >
        <span aria-hidden="true">{{ tema === 'oscuro' ? '☀' : '☾' }}</span>
      </button>

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
            <span v-if="admin" class="etiqueta etiqueta--acento">Administrador</span>
          </span>
        </button>

        <Transition name="fundido">
          <div v-if="panelAbierto" id="menu-cuenta" class="barra__menu superficie aparece">
            <p class="barra__menu-email">{{ email }}</p>
            <hr class="separador" />
            <button
              type="button"
              class="boton boton--secundario barra__menu-boton"
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
  padding: 0 var(--e-5);
  background: color-mix(in srgb, var(--superficie) 88%, transparent);
  /* El desenfoque hace que el contenido se intuya al desplazar por debajo, en lugar de desaparecer
     tras una franja opaca. Es una guía de que hay más página. */
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--borde);
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
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: var(--r-2);
  background: var(--acento);
  color: #fff;
  font-size: var(--t-xs);
  font-weight: 700;
}

.marca__texto {
  display: flex;
  flex-direction: column;
  font-weight: 650;
  line-height: 1.2;
  white-space: nowrap;
}

.marca__texto small {
  font-size: var(--t-xs);
  font-weight: 500;
  color: var(--texto-tenue);
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

.barra__menu-email {
  padding: var(--e-2) var(--e-2) var(--e-1);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  overflow-wrap: anywhere;
}

.barra__menu-boton {
  width: 100%;
  justify-content: flex-start;
}

/* La hamburguesa gobierna el panel de filtros en los dos anchos, así que se ve siempre: en móvil
   abre y cierra el cajón y en escritorio esconde y muestra la columna. Antes solo existía en móvil
   —en escritorio el panel estaba siempre a la vista y no había forma de esconderlo—. */
.barra__hamburguesa {
  position: relative;
  display: inline-flex;
  align-items: center;
  padding: 0.4rem;
  border: 1px solid var(--borde);
  border-radius: var(--r-1);
  background: var(--superficie);
  cursor: pointer;
}

.barra__hamburguesa-marca {
  position: absolute;
  top: 4px;
  right: 4px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ok);
  border: 1px solid var(--superficie);
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
  .barra {
    padding: 0 var(--e-4);
  }
}

@media (max-width: 639px) {
  .barra__datos,
  .barra__nombre {
    display: none;
  }

  .barra__perfil {
    padding: 0.25rem;
  }

  .marca__texto small {
    display: none;
  }

  .marca__texto {
    font-size: var(--t-sm);
  }
}
</style>
