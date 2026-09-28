<script setup>
/**
 * El punto de presencia: verde si la persona tiene el panel abierto, rojo si no.
 *
 * El color **no es lo único que informa**. Va acompañado de un texto que dice qué significa y, para
 * cada rojo, por qué: «sin señal, el navegador dejó de responder», «cerró la sesión», «entró desde
 * otro dispositivo». Un punto rojo sin explicación obliga a preguntar.
 *
 * Se avisa además cuando el alcance no es compartido. Sin Redis, la presencia vive en la memoria de
 * un solo proceso: con una sola instancia es correcta y con varias daría respuestas incompletas sin
 * fallar. Publicarlo es lo que permite advertirlo en lugar de creerlo.
 */
import { computed } from 'vue'

import { numero } from '@/utils/formato'

const props = defineProps({
  conectados: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  personas: { type: Array, default: () => [] },
  alcance: { type: String, default: 'proceso' },
  enVivo: { type: Boolean, default: false },
})

const abierto = defineModel('abierto', { type: Boolean, default: false })

const conectadas = computed(() => props.personas.filter((p) => p.estado === 'verde'))
const desconectadas = computed(() => props.personas.filter((p) => p.estado !== 'verde'))

const resumen = computed(() => {
  if (!props.total) return 'Sin cuentas registradas'
  if (!props.conectados) return `Nadie conectado de ${numero(props.total)}`
  return `${numero(props.conectados)} de ${numero(props.total)} conectados`
})
</script>

<template>
  <div class="presencia">
    <button
      type="button"
      class="presencia__boton"
      :aria-expanded="abierto"
      aria-controls="lista-presencia"
      @click="abierto = !abierto"
    >
      <span class="presencia__punto" :class="{ 'presencia__punto--vivo': conectados.length }" aria-hidden="true">
        <span v-if="conectados.length" class="presencia__onda" />
      </span>
      <span class="presencia__resumen">{{ resumen }}</span>
      <span v-if="!enVivo" class="etiqueta etiqueta--aviso" title="El canal en vivo no está conectado">
        sin canal
      </span>
    </button>

    <Transition name="desplegar">
      <div v-if="abierto" id="lista-presencia" class="presencia__panel superficie aparece">
        <header class="presencia__cabecera">
          <p class="presencia__titulo">Quién tiene el panel abierto</p>
          <p v-if="alcance === 'proceso'" class="presencia__aviso">
            Solo se ven las sesiones de este servidor. Con varias instancias hacen falta datos
            compartidos para verlas todas.
          </p>
        </header>

        <ul v-if="conectadas.length" class="presencia__lista">
          <li v-for="persona in conectadas" :key="persona.usuario_id" class="presencia__fila">
            <span class="presencia__punto presencia__punto--vivo presencia__punto--pequeno" aria-hidden="true" />
            <span class="presencia__nombre">{{ persona.usuario_id.slice(0, 8) }}…</span>
            <span class="presencia__motivo">{{ persona.descripcion }}</span>
          </li>
        </ul>

        <p v-else class="presencia__vacio">No hay nadie conectado ahora mismo.</p>

        <template v-if="desconectadas.length">
          <p class="presencia__separador">Desconectados</p>
          <ul class="presencia__lista presencia__lista--tenue">
            <li v-for="persona in desconectadas" :key="persona.usuario_id" class="presencia__fila">
              <span class="presencia__punto presencia__punto--pequeno" aria-hidden="true" />
              <span class="presencia__nombre">{{ persona.usuario_id.slice(0, 8) }}…</span>
              <span class="presencia__motivo">{{ persona.descripcion }}</span>
            </li>
          </ul>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.presencia {
  position: relative;
}

.presencia__boton {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.35rem 0.7rem 0.35rem 0.55rem;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-sm);
  color: var(--texto-suave);
  cursor: pointer;
  transition: border-color var(--rapido) var(--curva), color var(--rapido) var(--curva);
}

.presencia__boton:hover {
  border-color: var(--acento);
  color: var(--texto);
}

.presencia__punto {
  position: relative;
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--texto-tenue);
  transition: background-color var(--normal) var(--curva);
}

.presencia__punto--vivo {
  background: var(--ok);
}

.presencia__punto--pequeno {
  width: 7px;
  height: 7px;
}

/* La onda solo aparece cuando hay alguien conectado. Es el único elemento que se mueve en la barra,
   así que atrae la mirada justo a donde hay información nueva. */
.presencia__onda {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--ok);
  animation: onda 2.2s ease-out infinite;
}

.presencia__resumen {
  font-weight: 550;
  white-space: nowrap;
}

.presencia__panel {
  position: absolute;
  top: calc(100% + var(--e-2));
  right: 0;
  z-index: 40;
  width: min(340px, calc(100vw - 2 * var(--e-4)));
  padding: var(--e-3);
  box-shadow: var(--sombra-3);
}

.presencia__cabecera {
  padding-bottom: var(--e-2);
  margin-bottom: var(--e-2);
  border-bottom: 1px solid var(--borde);
}

.presencia__titulo {
  font-size: var(--t-sm);
  font-weight: 650;
}

.presencia__aviso {
  margin-top: var(--e-1);
  font-size: var(--t-xs);
  color: var(--aviso);
  line-height: 1.45;
}

.presencia__lista {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  max-height: 260px;
  overflow-y: auto;
}

.presencia__fila {
  display: grid;
  grid-template-columns: auto 1fr;
  align-items: center;
  gap: var(--e-2) var(--e-3);
  padding: var(--e-2);
  border-radius: var(--r-1);
}

.presencia__fila:hover {
  background: var(--superficie-2);
}

.presencia__nombre {
  font-size: var(--t-sm);
  font-family: var(--fuente-numeros);
  color: var(--texto-suave);
}

.presencia__motivo {
  grid-column: 2;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.4;
}

.presencia__lista--tenue .presencia__nombre,
.presencia__lista--tenue .presencia__motivo {
  opacity: 0.8;
}

.presencia__separador {
  margin: var(--e-3) 0 var(--e-2);
  padding-top: var(--e-2);
  border-top: 1px solid var(--borde);
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--texto-tenue);
}

.presencia__vacio {
  padding: var(--e-3) 0;
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

.desplegar-enter-active,
.desplegar-leave-active {
  transition: opacity var(--rapido) var(--curva), transform var(--rapido) var(--curva);
  transform-origin: top right;
}

.desplegar-enter-from,
.desplegar-leave-to {
  opacity: 0;
  transform: scale(0.96) translateY(-4px);
}
</style>
