<script setup>
/**
 * Gráfica de barras por provincia. **Es el filtro principal del panel.**
 *
 * Al pulsar una barra se filtra por esa provincia, y volver a pulsarla lo quita. Es la forma más
 * directa de responder a «¿dónde está pasando esto?»: se ve el reparto y se elige, sin pasar por un
 * desplegable.
 *
 * Se muestran las diez provincias con más contrataciones, no las veinticuatro. Con veinticuatro
 * barras en un panel lateral, las etiquetas quedan ilegibles y las últimas son una raya de un píxel.
 * El mapa y la lista de al lado se encargan del resto, y el pie de la gráfica dice cuántas quedan
 * fuera para que el recorte no pase inadvertido.
 */
import { computed } from 'vue'

import { opcionesBase, paletaSeries, useGrafica } from '@/composables/useGrafica'
import { abreviado, numero } from '@/utils/formato'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'

const LIMITE = 10

const listaCompleta = computed(() => datos.estado.resumenProvincias.porProvincia)
const visibles = computed(() => listaCompleta.value.slice(0, LIMITE))
const restantes = computed(() => Math.max(0, listaCompleta.value.length - LIMITE))
const ocultas = computed(() =>
  listaCompleta.value.slice(LIMITE).reduce((suma, p) => suma + p.total, 0),
)

const seleccionada = computed(() => filtros.estado.provincia)

const { lienzo } = useGrafica(
  () => {
    const series = paletaSeries()

    return {
      type: 'bar',
      data: {
        labels: visibles.value.map((p) => p.nombre),
        datasets: [
          {
            label: 'Contrataciones',
            data: visibles.value.map((p) => p.total),
            // La provincia filtrada se pinta con el color de acento y las demás con el degradado
            // normal: así se ve de un vistazo qué filtro está puesto sin leer la ficha de al lado.
            backgroundColor: visibles.value.map((p) =>
              seleccionada.value === p.codigo ? series[1] : `${series[0]}b3`,
            ),
            // El resaltado al pasar el cursor lo hace Chart.js con estos dos colores. Escribirlo a
            // mano obligaría a reconstruir la gráfica en cada movimiento del ratón: se destruiría y
            // volvería a crear decenas de veces por segundo, con su animación incluida.
            hoverBackgroundColor: series[0],
            borderRadius: 5,
            borderSkipped: false,
            maxBarThickness: 26,
          },
        ],
      },
      options: {
        ...opcionesBase(),
        indexAxis: 'y',
        // El alto se ajusta arriba por número de barras: con un alto fijo para diez provincias, las
        // etiquetas de abajo acabarían superpuestas.
        //
        // El filtro se aplica cambiando el estado del almacén y **nada más**. La gráfica se vuelve a
        // dibujar sola, porque el vigilante de `useGrafica` observa `seleccionada`. Redibujarla aquí
        // dentro, además, significaría destruirla mientras Chart.js está gestionando su propio clic.
        onClick: (evento, elementos) => {
          if (!elementos.length) return
          const provincia = visibles.value[elementos[0].index]
          if (provincia) filtros.alternarProvincia(provincia.codigo)
        },
        onHover: (evento, elementos) => {
          const puntero = elementos.length ? 'pointer' : 'default'
          evento.native?.target?.style?.setProperty('cursor', puntero)
        },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: 'transparent' },
            border: { display: false },
            ticks: { callback: (valor) => abreviado(valor) },
          },
          y: {
            grid: { display: false },
            border: { display: false },
            ticks: {
              // Se recorta el nombre de la provincia para que quepa en el ancho del panel lateral.
              callback(valor) {
                const nombre = this.getLabelForValue(valor)
                return nombre.length > 18 ? `${nombre.slice(0, 17)}…` : nombre
              },
            },
          },
        },
      },
    }
  },
  () => [visibles.value, seleccionada.value],
)

function elegir(codigo) {
  filtros.alternarProvincia(codigo)
}
</script>

<template>
  <section class="tarjeta grafica aparece retardo-2">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">Contrataciones por provincia</p>
        <p class="tarjeta__pista">Pulsa una barra para elegir la provincia y aplica los filtros</p>
      </div>
      <span v-if="seleccionada" class="etiqueta etiqueta--acento">{{ seleccionada }}</span>
    </header>

    <div class="tarjeta__cuerpo">
      <!-- El esqueleto solo en la primera carga. Antes se mostraba en **cada** cambio de filtro, y
           eso desmontaba el lienzo: la gráfica desaparecía, el canvas se sustituía por otro y, si el
           redibujado llegaba mientras estaba desmontado, se quedaba en blanco hasta el cambio
           siguiente. Con el lienzo siempre montado, los datos solo actualizan la gráfica. -->
      <div v-if="datos.estado.cargandoGraficas && !listaCompleta.length" class="esqueleto grafica__esqueleto" />

      <p v-else-if="!listaCompleta.length" class="grafica__vacio">
        Todavía no hay contrataciones que mostrar con estos filtros.
      </p>

      <template v-else>
        <!-- Se pinta la lista como alternativa accesible: la gráfica es un lienzo, y un lienzo no se
             puede leer con un lector de pantalla ni recorrer con el teclado. -->
        <div class="grafica__lienzo" :style="{ height: `${Math.max(220, visibles.length * 30)}px` }">
          <canvas ref="lienzo" role="img" aria-label="Gráfica de barras con las contrataciones por provincia" />
        </div>

        <ul class="grafica__lista solo-lectores">
          <li v-for="provincia in visibles" :key="provincia.codigo">
            {{ provincia.nombre }}: {{ numero(provincia.total) }} contrataciones
          </li>
        </ul>

        <div class="grafica__atajos">
          <button
            v-for="provincia in visibles.slice(0, 4)"
            :key="provincia.codigo"
            type="button"
            class="boton boton--pequeno"
            :class="seleccionada === provincia.codigo ? 'boton--principal' : 'boton--secundario'"
            @click="elegir(provincia.codigo)"
          >
            {{ provincia.nombre }}
          </button>
        </div>

        <p class="grafica__nota">
          <template v-if="restantes">
            Se muestran las {{ visibles.length }} provincias con más contrataciones.
            <template v-if="ocultas">
              Las otras {{ restantes }} suman {{ numero(ocultas) }} contrataciones.
            </template>
          </template>
          <template v-else>Están todas las provincias con datos.</template>
        </p>
      </template>
    </div>
  </section>
</template>

<style scoped>
.grafica {
  display: flex;
  flex-direction: column;
}

.grafica__lienzo {
  position: relative;
  width: 100%;
}

.grafica__esqueleto {
  display: block;
  height: 260px;
  border-radius: var(--r-2);
}

.grafica__vacio {
  padding: var(--e-6) var(--e-4);
  text-align: center;
  color: var(--texto-tenue);
  font-size: var(--t-sm);
}

.grafica__atajos {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin-top: var(--e-4);
  padding-top: var(--e-4);
  border-top: 1px solid var(--borde);
}

.grafica__nota {
  margin-top: var(--e-3);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.5;
}
</style>
