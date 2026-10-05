<script setup>
/**
 * Reparto de una dimensión del histórico en barras horizontales.
 *
 * Es la gráfica que responde a «¿de qué tipo son?»: cada barra es un valor del campo —un tipo de
 * procedimiento, un estado— con lo que hay de cada uno **con los filtros puestos**. El reparto llega
 * del servidor calculado **sin el criterio propio**, así que la barra del valor elegido en el filtro
 * sigue enseñando su parte y las demás no se caen a cero.
 *
 * **No filtra al pulsar**, y es una decisión, no un olvido: el panel no tiene un control de tipo de
 * procedimiento en el panel lateral, así que pulsar una barra dejaría un filtro en vigor que no se
 * vería en ningún sitio ni se podría quitar desde donde importa. Cuando exista ese control —y con él
 * el chip que lo deshace—, esta gráfica podrá filtrar como las de provincia y fuente.
 *
 * Las etiquetas son largas de verdad —«Catálogo electrónico - Compra directa en el convenio…»—, así
 * que se recortan para el eje y se enseñan enteras en el globo y en la lista accesible: recortar sin
 * dejar la forma de leer el valor completo cambiaría un problema de ancho por uno de información.
 */
import { computed } from 'vue'

import { opcionesBase, paletaSeries, useGrafica } from '@/composables/useGrafica'
import { filtros } from '@/stores/filtros'
import { nombreDeFamilia } from '@/utils/familias'
import { abreviado, numero } from '@/utils/formato'

const props = defineProps({
  titulo: { type: String, required: true },
  /** La coletilla que explica qué es cada barra, después de la familia. */
  pista: { type: String, default: '' },
  /** Filas ya traducidas: `{ etiqueta, total }`, de mayor a menor. */
  filas: { type: Array, default: () => [] },
  /** Cuánto mide la etiqueta antes de recortarla. */
  anchoEtiqueta: { type: Number, default: 30 },
})

const LIMITE = 10

const visibles = computed(() => props.filas.slice(0, LIMITE))
const restantes = computed(() => Math.max(0, props.filas.length - LIMITE))
const ocultas = computed(() =>
  props.filas.slice(LIMITE).reduce((suma, fila) => suma + (fila.total || 0), 0),
)

const { lienzo } = useGrafica(
  () => {
    const series = paletaSeries()

    return {
      type: 'bar',
      data: {
        labels: visibles.value.map((fila) => fila.etiqueta),
        datasets: [
          {
            label: props.titulo,
            data: visibles.value.map((fila) => fila.total),
            backgroundColor: visibles.value.map(
              (_fila, indice) => series[indice % series.length],
            ),
            hoverBackgroundColor: visibles.value.map(
              (_fila, indice) => series[indice % series.length],
            ),
            borderRadius: 5,
            borderSkipped: false,
            maxBarThickness: 26,
          },
        ],
      },
      options: {
        ...opcionesBase(),
        indexAxis: 'y',
        // El alto se ajusta arriba por número de barras: con un alto fijo, las etiquetas de las
        // últimas acaban superpuestas.
        plugins: {
          ...opcionesBase().plugins,
          tooltip: {
            ...opcionesBase().plugins.tooltip,
            callbacks: {
              label: (contexto) => `${numero(contexto.parsed.x ?? contexto.parsed)} contrataciones`,
            },
          },
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
              callback(valor) {
                const etiqueta = this.getLabelForValue(valor)
                return etiqueta.length > props.anchoEtiqueta
                  ? `${etiqueta.slice(0, props.anchoEtiqueta - 1)}…`
                  : etiqueta
              },
            },
          },
        },
      },
    }
  },
  () => visibles.value,
)
</script>

<template>
  <section class="tarjeta grafica aparece">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">{{ titulo }}</p>
        <p class="tarjeta__pista">
          {{ nombreDeFamilia(filtros.estado.categoria) }} · {{ pista }}
        </p>
      </div>
    </header>

    <div class="tarjeta__cuerpo">
      <div v-if="!filas.length" class="grafica__vacio">
        Todavía no hay contrataciones que mostrar con estos filtros.
      </div>

      <template v-else>
        <div class="grafica__lienzo" :style="{ height: `${Math.max(220, visibles.length * 30)}px` }">
          <canvas
            ref="lienzo"
            role="img"
            :aria-label="`Gráfica de barras con las contrataciones por ${titulo.toLowerCase()}`"
          />
        </div>

        <ul class="grafica__lista solo-lectores">
          <li v-for="fila in visibles" :key="fila.etiqueta">
            {{ fila.etiqueta }}: {{ numero(fila.total) }} contrataciones
          </li>
        </ul>

        <p class="grafica__nota">
          <template v-if="restantes">
            Se muestran los {{ visibles.length }} valores con más contrataciones.
            <template v-if="ocultas">
              Los otros {{ restantes }} suman {{ numero(ocultas) }} contrataciones.
            </template>
          </template>
          <template v-else>Están todos los valores con datos.</template>
        </p>
      </template>
    </div>
  </section>
</template>
