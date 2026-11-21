<script setup>
/**
 * «Páginas finales (opcionales)»: una casilla por cada página que el generador puede añadir al final
 * de la proforma (formulario de integridad, carta de compromiso, respaldo…). La lista la define
 * `PAGINAS_FINALES` en `utils/proformaPdf.js`; la elección viaja en `extras.paginas_finales`.
 */
defineProps({
  paginas: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['update:modelValue'])

function cambiar(actual, id, valor) {
  emit('update:modelValue', { ...actual, [id]: valor })
}
</script>

<template>
  <fieldset class="finales">
    <legend>Páginas finales <small>(opcionales)</small></legend>
    <p class="finales__ayuda">Marca las que quieres añadir al final del PDF y del Word.</p>
    <label v-for="pagina in paginas" :key="pagina.id" class="finales__opcion">
      <input
        type="checkbox"
        :checked="modelValue[pagina.id] ?? Boolean(pagina.porDefecto)"
        :aria-describedby="pagina.descripcion ? `final-${pagina.id}` : undefined"
        @change="cambiar(modelValue, pagina.id, $event.target.checked)"
      />
      <span>
        <strong>{{ pagina.etiqueta }}</strong>
        <small v-if="pagina.descripcion" :id="`final-${pagina.id}`">{{ pagina.descripcion }}</small>
      </span>
    </label>
  </fieldset>
</template>

<style scoped>
.finales { display: grid; gap: var(--e-2); margin: 0; padding: 0; border: 0; }
.finales legend { padding: 0; font-size: var(--t-base); font-weight: 650; }
.finales legend small { color: var(--texto-tenue); font-weight: 400; }
.finales__ayuda { margin: 0 0 var(--e-1); color: var(--texto-suave); font-size: var(--t-sm); }
.finales__opcion { display: flex; align-items: flex-start; gap: var(--e-3); padding: var(--e-2) var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); font-size: var(--t-sm); cursor: pointer; }
.finales__opcion input { margin-top: 3px; accent-color: var(--acento); }
.finales__opcion span { display: grid; gap: 2px; }
.finales__opcion small { color: var(--texto-suave); font-size: var(--t-xs); line-height: 1.45; }
</style>
