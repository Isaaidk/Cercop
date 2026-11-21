<script setup>
/**
 * «Revisa antes de generar»: lo que impide generar (errores) separado de lo que solo conviene mirar
 * (avisos), agrupado por bloque del formulario y con los problemas repetidos plegados
 * («5 líneas sin valor unitario — ver»). Cada fila lleva al campo.
 */
import { computed, reactive } from 'vue'

import { agruparProblemas } from '@/utils/revisionProforma'

const props = defineProps({
  problemas: { type: Array, default: () => [] },
  // Antes del primer intento de generar, los errores se enseñan como «por completar», sin rojo.
  intento: { type: Boolean, default: false },
})
const emit = defineEmits(['ir'])

const grupos = computed(() => agruparProblemas(props.problemas))
const totalErrores = computed(() => props.problemas.filter((p) => p.nivel === 'error').length)
const totalAvisos = computed(() => props.problemas.filter((p) => p.nivel === 'aviso').length)
const abiertos = reactive({})
</script>

<template>
  <section
    v-if="totalErrores || totalAvisos"
    class="revision"
    :class="{ 'revision--error': intento && totalErrores }"
    aria-labelledby="revision-titulo"
  >
    <header class="revision__cabecera">
      <h4 id="revision-titulo">Revisa antes de generar</h4>
      <p class="revision__resumen">
        <span v-if="totalErrores" class="etiqueta" :class="intento ? 'etiqueta--error' : ''">
          {{ totalErrores }} por completar
        </span>
        <span v-if="totalAvisos" class="etiqueta etiqueta--aviso">
          {{ totalAvisos }} {{ totalAvisos === 1 ? 'aviso' : 'avisos' }}
        </span>
      </p>
    </header>

    <template v-for="(bloque, nivel) in { error: grupos.errores, aviso: grupos.avisos }" :key="nivel">
      <div v-if="bloque.length" class="revision__nivel" :class="`revision__nivel--${nivel}`">
        <p class="revision__nivel-titulo">
          {{ nivel === 'error' ? 'Impide generar' : 'Avisos (no impiden generar)' }}
        </p>
        <div v-for="seccion in bloque" :key="seccion.id" class="revision__seccion">
          <p class="revision__seccion-titulo">{{ seccion.etiqueta }}</p>
          <ul>
            <li v-for="fila in seccion.filas" :key="fila.clave">
              <template v-if="fila.resumen">
                <button
                  type="button"
                  class="revision__enlace"
                  :aria-expanded="Boolean(abiertos[`${nivel}-${fila.clave}`])"
                  @click="abiertos[`${nivel}-${fila.clave}`] = !abiertos[`${nivel}-${fila.clave}`]"
                >
                  {{ fila.resumen }} — {{ abiertos[`${nivel}-${fila.clave}`] ? 'ocultar' : 'ver' }}
                </button>
                <ul v-if="abiertos[`${nivel}-${fila.clave}`]" class="revision__sub">
                  <li v-for="p in fila.problemas" :key="`${p.id}|${p.mensaje}`">
                    <button type="button" class="revision__enlace" @click="emit('ir', p.id)">{{ p.mensaje }}</button>
                  </li>
                </ul>
              </template>
              <button v-else type="button" class="revision__enlace" @click="emit('ir', fila.problemas[0].id)">
                {{ fila.problemas[0].mensaje }}
              </button>
            </li>
          </ul>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.revision { display: grid; gap: var(--e-3); padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie); font-size: var(--t-sm); }
.revision--error { border-color: var(--error); }
.revision__cabecera { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--e-2); }
.revision__cabecera h4 { margin: 0; font-size: var(--t-base); font-weight: 650; }
.revision__resumen { display: flex; flex-wrap: wrap; gap: var(--e-2); margin: 0; }
.revision__nivel { display: grid; gap: var(--e-2); }
.revision__nivel-titulo { margin: 0; color: var(--texto-suave); font-size: var(--t-xs); font-weight: 650; letter-spacing: 0.03em; text-transform: uppercase; }
.revision__seccion { display: grid; grid-template-columns: minmax(9rem, 12rem) minmax(0, 1fr); gap: var(--e-1) var(--e-3); }
.revision__seccion-titulo { margin: 0; color: var(--texto-suave); }
.revision ul { display: grid; gap: 2px; margin: 0; padding: 0; list-style: none; }
.revision__sub { margin-top: 2px !important; padding-left: var(--e-3) !important; border-left: 2px solid var(--borde); }
.revision__enlace { padding: 0; border: 0; background: none; color: var(--texto); font: inherit; text-align: left; cursor: pointer; }
.revision__nivel--error .revision__enlace::before { content: '•'; margin-right: 6px; color: var(--error); }
.revision__nivel--aviso .revision__enlace::before { content: '•'; margin-right: 6px; color: var(--aviso); }
.revision__sub .revision__enlace::before { content: none; }
.revision__enlace:hover, .revision__enlace:focus-visible { color: var(--acento-fuerte); text-decoration: underline; }
.revision__enlace:focus-visible { outline: 2px solid var(--acento); outline-offset: 2px; }
@media (max-width: 640px) {
  .revision__seccion { grid-template-columns: 1fr; }
}
</style>
