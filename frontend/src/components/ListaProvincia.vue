<script setup>
/**
 * Encabezado de las contrataciones de la provincia elegida, debajo del mapa.
 *
 * Aquí había un listado propio de fichas recortadas, y el problema es que era **una versión peor de
 * la tabla**: recortaba el objeto a 160 caracteres, recortaba la entidad a 46, no dejaba desplegar
 * el detalle y no paginaba. Quien pulsaba una provincia veía un resumen y no tenía forma de llegar al
 * dato completo de una ínfima cuantía sin cambiar de pestaña y volver a buscar.
 *
 * Ahora este componente solo pinta el encabezado —qué provincia es y cuántas hay— y la tabla que va
 * debajo es **la misma** de la pestaña de ínfimas cuantías, con su detalle desplegable y su
 * paginación. Reusarla
 * en lugar de copiarla es lo que garantiza que las dos pantallas no se separen: si mañana cambia una
 * columna, cambia en las dos.
 *
 * No pide datos propios: lee la misma página que la tabla, ya filtrada por la provincia y por todo lo
 * demás. Dos peticiones distintas podrían devolver dos conjuntos distintos y el mapa y la lista se
 * contradirían.
 */
import { computed } from 'vue'

import { datos } from '@/stores/datos'
import { filtros } from '@/stores/filtros'
import { numero } from '@/utils/formato'
import { nombreDeProvincia } from '@/utils/provincias'

const emit = defineEmits(['ver-todos'])

const provincias = computed(() => filtros.estado.provincias)

/**
 * Cómo se nombra la selección en el encabezado.
 *
 * Con una sola provincia se dice su nombre —«Contrataciones en Azuay»—, que es lo natural. Con
 * varias no se enumeran todas: con seis, el titular ocuparía tres lineas y dejaría de leerse. Se
 * dice cuántas son, y el detalle está a un clic de distancia en el propio mapa.
 */
const titulo = computed(() => {
  if (!provincias.value.length) return 'Contrataciones de una provincia'
  if (provincias.value.length === 1) return `Contrataciones en ${nombreDeProvincia(provincias.value[0])}`
  const nombres = provincias.value.map(nombreDeProvincia).join(' + ')
  return nombres.length <= 60 ? `Contrataciones en ${nombres}` : `Contrataciones en ${provincias.value.length} provincias`
})

const total = computed(() => datos.estado.total)
const cargando = computed(() => datos.estado.cargando)
</script>

<template>
  <section class="provincia aparece">
    <header class="provincia__cabecera">
      <div>
        <p class="provincia__titulo">
          {{ titulo }}
        </p>
        <p class="provincia__pista">
          <template v-if="!provincias.length">
            Pulsa una provincia en el mapa para ver solo sus contrataciones. Mientras no elijas
            ninguna, esta tabla muestra todo lo que cumple los filtros.
          </template>
          <template v-else-if="cargando">Buscando las contrataciones de esta provincia…</template>
          <template v-else>
            <span class="numeros">{{ numero(total) }}</span>
            {{ total === 1 ? 'contratación' : 'contrataciones' }} con los filtros actuales
          </template>
        </p>
      </div>

      <button
        v-if="provincias.length"
        type="button"
        class="boton boton--fantasma boton--pequeno"
        @click="emit('ver-todos')"
      >
        Ir a ínfimas cuantías
      </button>
    </header>
  </section>
</template>

<style scoped>
.provincia {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.provincia__cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  align-items: flex-start;
  justify-content: space-between;
}

.provincia__titulo {
  font-size: var(--t-md);
  font-weight: 700;
}

.provincia__pista {
  margin-top: var(--e-1);
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}
</style>
