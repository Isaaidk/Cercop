<script setup>
/**
 * Paginación de la tabla.
 *
 * Muestra una **ventana** de páginas alrededor de la actual en lugar de las doscientas que puede
 * llegar a haber. Una fila con doscientos botones no se puede usar: hay que desplazarse para llegar
 * al final y el número que se busca queda perdido en medio.
 *
 * El campo para saltar a una página concreta existe porque la ventana hace justo eso: esconde las
 * páginas lejanas. Sin él, ir a la 137 exigiría pulsar «siguiente» ciento treinta veces.
 */
import { computed, ref } from 'vue'

import { numero } from '@/utils/formato'

const props = defineProps({
  pagina: { type: Number, default: 1 },
  paginas: { type: Number, default: 0 },
  total: { type: Number, default: 0 },
  tamano: { type: Number, default: 25 },
})

const emit = defineEmits(['cambiar'])

const salto = ref('')

const desde = computed(() => (props.total ? (props.pagina - 1) * props.tamano + 1 : 0))
const hasta = computed(() => Math.min(props.pagina * props.tamano, props.total))

/** Cinco páginas centradas en la actual, recortadas en los extremos. */
const ventana = computed(() => {
  const cuantas = 5
  let inicio = Math.max(1, props.pagina - Math.floor(cuantas / 2))
  const fin = Math.min(props.paginas, inicio + cuantas - 1)
  inicio = Math.max(1, fin - cuantas + 1)

  const lista = []
  for (let n = inicio; n <= fin; n += 1) lista.push(n)
  return lista
})

function ir(pagina) {
  const destino = Math.min(Math.max(1, pagina), props.paginas)
  if (destino !== props.pagina) emit('cambiar', destino)
}

function saltar() {
  const valor = Number(salto.value)
  if (Number.isFinite(valor) && valor >= 1) ir(Math.trunc(valor))
  salto.value = ''
}
</script>

<template>
  <nav v-if="paginas > 1" class="paginacion" aria-label="Paginación de resultados">
    <p class="paginacion__resumen">
      Mostrando <span class="numeros">{{ numero(desde) }}</span>–<span class="numeros">{{ numero(hasta) }}</span>
      de <span class="numeros">{{ numero(total) }}</span>
    </p>

    <div class="paginacion__controles">
      <button
        type="button"
        class="boton boton--secundario boton--pequeno"
        :disabled="pagina <= 1"
        aria-label="Página anterior"
        @click="ir(pagina - 1)"
      >
        ‹ Anterior
      </button>

      <!-- Los botones se ocultan en móvil porque el hueco no da para cinco números y los controles
           de salto; quedan «anterior», «siguiente» y la posición, que es lo que se usa con el dedo. -->
      <ul class="paginacion__numeros">
        <li v-if="ventana[0] > 1">
          <button type="button" class="boton boton--fantasma boton--pequeno" @click="ir(1)">1</button>
        </li>
        <li v-if="ventana[0] > 2" class="paginacion__puntos" aria-hidden="true">…</li>

        <li v-for="n in ventana" :key="n">
          <button
            type="button"
            class="boton boton--pequeno"
            :class="n === pagina ? 'boton--principal' : 'boton--fantasma'"
            :aria-current="n === pagina ? 'page' : undefined"
            @click="ir(n)"
          >
            {{ n }}
          </button>
        </li>

        <li v-if="ventana[ventana.length - 1] < paginas - 1" class="paginacion__puntos" aria-hidden="true">
          …
        </li>
        <li v-if="ventana[ventana.length - 1] < paginas">
          <button type="button" class="boton boton--fantasma boton--pequeno" @click="ir(paginas)">
            {{ paginas }}
          </button>
        </li>
      </ul>

      <button
        type="button"
        class="boton boton--secundario boton--pequeno"
        :disabled="pagina >= paginas"
        aria-label="Página siguiente"
        @click="ir(pagina + 1)"
      >
        Siguiente ›
      </button>

      <form class="paginacion__salto" @submit.prevent="saltar">
        <label class="solo-lectores" for="salto-pagina">Ir a la página</label>
        <input
          id="salto-pagina"
          v-model="salto"
          class="entrada entrada--compacta"
          type="number"
          min="1"
          :max="paginas"
          :placeholder="String(paginas)"
          inputmode="numeric"
        />
        <button type="submit" class="boton boton--secundario boton--pequeno">Ir</button>
      </form>
    </div>
  </nav>
</template>

<style scoped>
.paginacion {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-4) var(--e-5);
  border-top: 1px solid var(--borde);
}

.paginacion__resumen {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.paginacion__controles {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  flex-wrap: wrap;
}

.paginacion__numeros {
  display: flex;
  align-items: center;
  gap: 2px;
  list-style: none;
  padding: 0;
  margin: 0;
}

.paginacion__puntos {
  padding: 0 var(--e-1);
  color: var(--texto-tenue);
}

.paginacion__salto {
  display: flex;
  gap: var(--e-2);
  align-items: center;
}

@media (max-width: 767px) {
  .paginacion__numeros,
  .paginacion__salto {
    display: none;
  }
}
</style>
