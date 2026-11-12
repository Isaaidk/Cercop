<script setup>
/**
 * Un trozo de texto del TDR, legible: sin rellenos de puntos, con las viñetas en su línea y los
 * huecos del formulario marcados aparte. El hueco se pinta como insignia para que se lea como «la
 * entidad dejó esto en blanco» y no como parte de la frase.
 */
import { computed } from 'vue'

import { trozosTdr } from '@/utils/textoTdr'

const props = defineProps({
  texto: { type: String, default: '' },
  // `p` para un párrafo suelto; `span` dentro de otra etiqueta (un <dd>, un <label>).
  como: { type: String, default: 'p' },
})

const trozos = computed(() => trozosTdr(props.texto))
</script>

<template>
  <component :is="como" class="texto-tdr">
    <template v-for="(trozo, n) in trozos" :key="n">
      <span v-if="trozo.hueco" class="texto-tdr__hueco" title="La entidad dejó este dato en blanco">por completar</span>
      <template v-else>{{ trozo.texto }}</template>
    </template>
  </component>
</template>

<style scoped>
.texto-tdr { white-space: pre-line; overflow-wrap: anywhere; }
.texto-tdr__hueco {
  display: inline-block;
  padding: 0 0.4rem;
  border: 1px dashed var(--borde-fuerte);
  border-radius: var(--r-1);
  background: var(--superficie-2);
  color: var(--texto-tenue);
  font-size: 0.85em;
  font-style: italic;
  line-height: 1.4;
  white-space: nowrap;
}
</style>
