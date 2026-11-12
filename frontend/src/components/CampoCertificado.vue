<script setup>
/**
 * Un dato del certificado: la etiqueta en negrita arriba y el valor debajo, como en el certificado
 * del RUC del SRI y en el del RUP. Se copia esa forma a propósito: es la que la persona ya conoce y
 * en la que sabe buscar su RUC o su régimen sin leer la pantalla entera.
 *
 * Un dato vacío no se deja en blanco ni con una raya: dice «Sin registrar» y ofrece «Completar»,
 * para que quien no ve el dato sepa que falta y qué hacer, sin buscar un formulario aparte.
 */
defineProps({
  etiqueta: { type: String, required: true },
  valor: { type: [String, Number], default: '' },
  /** Ocupa la fila entera (dirección, razón social larga). */
  ancho: { type: Boolean, default: false },
  /** Sin botón cuando el dato no se edita aquí (p. ej. el RUC repetido en el bloque del RUP). */
  puedeCompletar: { type: Boolean, default: true },
})
const emit = defineEmits(['completar'])
</script>

<template>
  <div class="campo-cert" :class="{ 'campo-cert--ancho': ancho }">
    <dt class="campo-cert__etiqueta">{{ etiqueta }}</dt>
    <dd class="campo-cert__valor">
      <template v-if="valor !== '' && valor != null">{{ valor }}</template>
      <span v-else class="campo-cert__vacio">
        <span>Sin registrar</span>
        <button
          v-if="puedeCompletar"
          type="button"
          class="boton boton--secundario campo-cert__completar"
          :aria-label="`Completar ${etiqueta}`"
          @click="emit('completar')"
        >
          Completar
        </button>
      </span>
    </dd>
  </div>
</template>

<style scoped>
.campo-cert { display: flex; flex-direction: column; gap: var(--e-1); min-width: 0; padding: var(--e-3) 0; }
.campo-cert--ancho { grid-column: 1 / -1; }
.campo-cert__etiqueta { font-size: 1rem; font-weight: 700; color: var(--texto); }
.campo-cert__valor { margin: 0; font-size: var(--t-lg); color: var(--texto); overflow-wrap: anywhere; line-height: 1.45; }
.campo-cert__vacio { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--e-3); color: var(--texto-suave); font-style: italic; }
.campo-cert__completar { min-height: 44px; padding: 0.5rem 1rem; font-size: 1rem; font-style: normal; }
</style>
