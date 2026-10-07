<script setup>
/**
 * Un campo de términos que se escriben a mano: un cuadro, un botón y las fichas de lo puesto.
 *
 * Por qué existe este componente
 * ------------------------------
 * El panel lateral tiene tres campos así —palabras clave, CPC y descripción del producto— y la
 * pestaña de ofertas necesitaba otros dos con el mismo comportamiento: añadir con el botón o con
 * Intro, no admitir dos veces lo mismo, no admitir una palabra de una o dos letras, poder quitar
 * cualquier ficha y explicar por qué no se añadió algo. Escribir eso cinco veces es escribir cinco
 * veces dónde está el mínimo y qué cuenta como repetido, y la primera que se separara daría dos
 * pantallas que aceptan cosas distintas.
 *
 * Lo que **no** hace: decidir si aplica. Los términos se quedan en el borrador de quien lo usa y se
 * aplican con el botón de esa pantalla, así que este componente solo avisa de lo que añade y de lo
 * que quita.
 *
 * El estado vive en quien lo usa (`terminos` entra y los cambios salen), porque el del panel lateral
 * es el del almacén de filtros y el de ofertas es local: el mismo control sirve para los dos.
 */
import { computed, ref } from 'vue'

import { LONGITUD_MINIMA_TERMINO, claveDeTermino } from '@/utils/terminos'

const props = defineProps({
  /** Qué se escribe aquí, en el idioma de la pantalla. */
  etiqueta: { type: String, required: true },
  /** Una línea explicando qué busca este campo. */
  ayuda: { type: String, default: '' },
  /** Ejemplo dentro del cuadro. */
  marcador: { type: String, default: '' },
  /** Los términos puestos. */
  terminos: { type: Array, default: () => [] },
  /** Longitud mínima, por si algún campo necesitara otra. */
  minimo: { type: Number, default: LONGITUD_MINIMA_TERMINO },
})

const emit = defineEmits(['agregar', 'quitar'])

const texto = ref('')
const error = ref('')

const puedeAgregar = computed(() => texto.value.trim().length >= props.minimo)

function agregar() {
  const limpio = texto.value.trim()
  if (limpio.length < props.minimo) {
    error.value = `«${limpio}» tiene menos de ${props.minimo} letras.`
    return
  }
  const clave = claveDeTermino(limpio)
  if (props.terminos.some((termino) => claveDeTermino(termino) === clave)) {
    error.value = `«${limpio}» ya está en la lista.`
    return
  }
  error.value = ''
  texto.value = ''
  emit('agregar', limpio)
}

function quitar(termino) {
  error.value = ''
  emit('quitar', termino)
}
</script>

<template>
  <div class="terminos">
    <label class="campo__etiqueta" :for="`terminos-${etiqueta}`">{{ etiqueta }}</label>

    <p v-if="ayuda" class="terminos__ayuda">{{ ayuda }}</p>

    <form class="terminos__nueva" @submit.prevent="agregar">
      <input
        :id="`terminos-${etiqueta}`"
        v-model="texto"
        class="entrada"
        type="text"
        :placeholder="marcador || `Escribe al menos ${minimo} letras y pulsa Añadir`"
      />
      <button
        type="submit"
        class="boton boton--secundario boton--pequeno"
        :disabled="!puedeAgregar"
      >
        Añadir
      </button>
    </form>

    <ul v-if="terminos.length" class="terminos__lista">
      <li v-for="termino in terminos" :key="termino">
        <button
          type="button"
          class="terminos__chip"
          :aria-label="`Quitar ${termino}`"
          @click="quitar(termino)"
        >
          <span class="terminos__chip-texto">{{ termino }}</span>
          <span aria-hidden="true">✕</span>
        </button>
      </li>
    </ul>

    <p v-else class="terminos__vacio">Sin términos: este criterio no está en uso.</p>

    <p v-if="error" class="terminos__error" role="alert">{{ error }}</p>
  </div>
</template>

<style scoped>
.terminos {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.terminos__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.terminos__nueva {
  display: flex;
  gap: var(--e-2);
  align-items: center;
}

.terminos__nueva .entrada {
  flex: 1 1 auto;
  min-width: 0;
}

.terminos__lista {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  list-style: none;
  padding: 0;
  margin: var(--e-1) 0;
}

/* Las mismas fichas que en el resto del panel: es la misma idea y se lee igual. */
.terminos__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-sm);
  color: var(--texto-suave);
  cursor: pointer;
  transition:
    background-color var(--rapido) var(--curva),
    border-color var(--rapido) var(--curva),
    color var(--rapido) var(--curva);
}

.terminos__chip:hover {
  border-color: var(--acento);
  color: var(--texto);
}

.terminos__chip-texto {
  font-weight: 550;
}

.terminos__vacio {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.terminos__error {
  font-size: var(--t-xs);
  color: var(--error);
}
</style>
