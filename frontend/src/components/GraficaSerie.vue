<script setup>
/**
 * Serie mensual de publicaciones.
 *
 * El eje vertical usa cifras abreviadas y el desplazamiento lateral se recorta: en un panel de tres
 * columnas, un eje con «12.480» repetido cinco veces ocupa más ancho que el propio trazado.
 *
 * El relleno bajo la línea no es decoración: ayuda a leer el volumen acumulado de un vistazo, que es
 * lo que se busca en una serie temporal de contratación pública —si el ritmo sube o baja—, más que el
 * valor exacto de un mes concreto, que sigue estando en la etiqueta emergente.
 */
import { computed } from 'vue'

import { abreviado, mesCorto, numero } from '@/utils/formato'
import { colorDeToken, opcionesBase, useGrafica } from '@/composables/useGrafica'
import { datos } from '@/stores/datos'

const serie = computed(() => datos.estado.estadisticas.serie_mensual || [])

const total = computed(() => serie.value.reduce((suma, mes) => suma + (mes.total || 0), 0))

const variacion = computed(() => {
  if (serie.value.length < 2) return null
  const ultimo = serie.value[serie.value.length - 1].total || 0
  const anterior = serie.value[serie.value.length - 2].total || 0
  if (!anterior) return null
  return Math.round(((ultimo - anterior) / anterior) * 100)
})

const { lienzo } = useGrafica(
  () => {
    const acento = colorDeToken('--serie-1')
    const borde = colorDeToken('--borde')
    const tenue = colorDeToken('--texto-tenue')

    return {
      type: 'line',
      data: {
        labels: serie.value.map((mes) => mesCorto(mes.mes)),
        datasets: [
          {
            label: 'Contrataciones publicadas',
            data: serie.value.map((mes) => mes.total),
            borderColor: acento,
            borderWidth: 2.5,
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: acento,
            pointBorderColor: colorDeToken('--superficie'),
            pointBorderWidth: 2,
            fill: true,
            backgroundColor: (contexto) => {
              const { ctx, chartArea } = contexto.chart
              if (!chartArea) return 'transparent'
              const degradado = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom)
              degradado.addColorStop(0, `${acento}45`)
              degradado.addColorStop(1, `${acento}00`)
              return degradado
            },
          },
        ],
      },
      options: {
        ...opcionesBase(),
        interaction: { mode: 'index', intersect: false },
        plugins: {
          ...opcionesBase().plugins,
          tooltip: {
            ...opcionesBase().plugins.tooltip,
            callbacks: {
              label: (contexto) => `${numero(contexto.parsed.y)} contrataciones`,
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { color: borde },
            ticks: { color: tenue, maxRotation: 0, autoSkipPadding: 8 },
          },
          y: {
            beginAtZero: true,
            grid: { color: borde, drawTicks: false },
            border: { display: false },
            ticks: { color: tenue, callback: (valor) => abreviado(valor) },
          },
        },
      },
    }
  },
  () => serie.value,
)
</script>

<template>
  <section class="tarjeta aparece retardo-3">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">Publicaciones por mes</p>
        <p class="tarjeta__pista">Evolución de los últimos doce meses</p>
      </div>
      <div class="resumen">
        <span class="resumen__cifra numeros">{{ numero(total) }}</span>
        <span v-if="variacion !== null" class="etiqueta" :class="variacion >= 0 ? 'etiqueta--ok' : 'etiqueta--error'">
          {{ variacion >= 0 ? '▲' : '▼' }} {{ Math.abs(variacion) }}% frente al mes anterior
        </span>
      </div>
    </header>

    <div class="tarjeta__cuerpo">
      <!-- Solo en la primera carga: ver la nota de `GraficaProvincias`. -->
      <div v-if="datos.estado.cargandoGraficas && !serie.length" class="esqueleto serie__esqueleto" />

      <p v-else-if="!serie.length" class="serie__vacio">
        Sin publicaciones con fecha en los filtros actuales.
      </p>

      <template v-else>
        <div class="serie__lienzo">
          <canvas ref="lienzo" role="img" aria-label="Gráfica de líneas con las publicaciones por mes" />
        </div>
        <ul class="solo-lectores">
          <li v-for="mes in serie" :key="mes.mes">{{ mesCorto(mes.mes) }}: {{ numero(mes.total) }}</li>
        </ul>
      </template>
    </div>
  </section>
</template>

<style scoped>
.resumen {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--e-1);
}

.resumen__cifra {
  font-size: var(--t-lg);
  font-weight: 700;
}

.serie__lienzo {
  position: relative;
  height: 240px;
}

.serie__esqueleto {
  display: block;
  height: 240px;
  border-radius: var(--r-2);
}

.serie__vacio {
  padding: var(--e-6) var(--e-4);
  text-align: center;
  color: var(--texto-tenue);
  font-size: var(--t-sm);
}
</style>
