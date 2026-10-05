<script setup>
/**
 * Reparto por fuente (NCO y OCDS) en una dona.
 *
 * Solo tiene sentido con más de una fuente. Con una sola, una dona de un único color ocupando toda
 * la tarjeta no informa de nada: dice «todo viene de donde viene». En ese caso se muestra la cifra y
 * el nombre, que es lo que de verdad se quiere saber.
 *
 * Al pulsar un segmento se filtra por esa fuente. Es coherente con el resto del panel —donde pulsar
 * una gráfica filtra— y evita tener que buscarla en el desplegable lateral.
 */
import { computed } from 'vue'

import { numero } from '@/utils/formato'
import { opcionesBase, paletaSeries, useGrafica } from '@/composables/useGrafica'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { nombreDeFamilia } from '@/utils/familias'

const fuentes = computed(() => datos.estado.estadisticas.por_fuente || [])
const seleccionada = computed(() => filtros.estado.fuente)

const total = computed(() => fuentes.value.reduce((suma, f) => suma + (f.total || 0), 0))

const { lienzo } = useGrafica(
  () => {
    const series = paletaSeries()

    return {
      type: 'doughnut',
      data: {
        labels: fuentes.value.map((f) => f.fuente),
        datasets: [
          {
            data: fuentes.value.map((f) => f.total),
            backgroundColor: fuentes.value.map((f, indice) =>
              seleccionada.value && seleccionada.value !== f.fuente
                ? `${series[indice % series.length]}33`
                : series[indice % series.length],
            ),
            borderColor: 'transparent',
            borderWidth: 0,
            hoverOffset: 8,
          },
        ],
      },
      options: {
        ...opcionesBase({ conLeyenda: true }),
        cutout: '64%',
        scales: {},
        onClick: (evento, elementos) => {
          if (!elementos.length) return
          const fuente = fuentes.value[elementos[0].index]
          if (!fuente) return
          filtros.actualizar({ fuente: seleccionada.value === fuente.fuente ? null : fuente.fuente })
        },
        onHover: (evento, elementos) => {
          evento.native?.target?.style?.setProperty('cursor', elementos.length ? 'pointer' : 'default')
        },
        plugins: {
          ...opcionesBase({ conLeyenda: true }).plugins,
          tooltip: {
            ...opcionesBase().plugins.tooltip,
            callbacks: {
              label: (contexto) => {
                const valor = contexto.parsed || 0
                const porcentaje = total.value ? Math.round((valor / total.value) * 100) : 0
                return `${numero(valor)} contrataciones (${porcentaje}%)`
              },
            },
          },
        },
      },
    }
  },
  () => [fuentes.value, seleccionada.value],
)

function elegir(fuente) {
  filtros.actualizar({ fuente: seleccionada.value === fuente ? null : fuente })
}
</script>

<template>
  <section class="tarjeta aparece retardo-4">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">Origen de los datos</p>
        <p class="tarjeta__pista">
          {{ nombreDeFamilia(filtros.estado.categoria) }} · pulsa un segmento para filtrar por esa
          fuente
        </p>
      </div>
    </header>

    <div class="tarjeta__cuerpo">
      <!-- Solo en la primera carga: ver la nota de `GraficaProvincias`. -->
      <div v-if="datos.estado.cargandoGraficas && !fuentes.length" class="esqueleto fuentes__esqueleto" />

      <p v-else-if="!fuentes.length" class="fuentes__vacio">Sin datos de origen.</p>

      <!-- Con una sola fuente, la dona no aporta: se dice la cifra y se acabó. -->
      <div v-else-if="fuentes.length === 1" class="fuentes__unica">
        <p class="fuentes__unica-cifra numeros">{{ numero(total) }}</p>
        <p class="fuentes__unica-texto">
          contrataciones, todas de la fuente <strong>{{ fuentes[0].fuente }}</strong>
        </p>
      </div>

      <template v-else>
        <div class="fuentes__lienzo">
          <canvas ref="lienzo" role="img" aria-label="Gráfica de dona con el reparto por fuente de datos" />
          <div class="fuentes__centro">
            <span class="fuentes__total numeros">{{ numero(total) }}</span>
            <span class="fuentes__total-pie">total</span>
          </div>
        </div>

        <ul class="fuentes__lista">
          <li v-for="fuente in fuentes" :key="fuente.fuente">
            <button
              type="button"
              class="fuentes__fila"
              :class="{ 'fuentes__fila--activa': seleccionada === fuente.fuente }"
              @click="elegir(fuente.fuente)"
            >
              <span class="fuentes__nombre">{{ fuente.fuente }}</span>
              <span class="numeros">{{ numero(fuente.total) }}</span>
              <span class="fuentes__porcentaje numeros">
                {{ total ? Math.round((fuente.total / total) * 100) : 0 }}%
              </span>
            </button>
          </li>
        </ul>
      </template>
    </div>
  </section>
</template>

<style scoped>
.fuentes__lienzo {
  position: relative;
  height: 220px;
}

.fuentes__centro {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  pointer-events: none;
}

.fuentes__total {
  font-size: var(--t-xl);
  font-weight: 750;
  letter-spacing: -0.02em;
}

.fuentes__total-pie {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.fuentes__lista {
  list-style: none;
  padding: 0;
  margin: var(--e-4) 0 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.fuentes__fila {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: var(--e-3);
  width: 100%;
  padding: var(--e-2) var(--e-3);
  border: 1px solid transparent;
  border-radius: var(--r-1);
  background: transparent;
  font-size: var(--t-sm);
  cursor: pointer;
  transition: background-color var(--rapido) var(--curva), border-color var(--rapido) var(--curva);
}

.fuentes__fila:hover {
  background: var(--superficie-2);
}

.fuentes__fila--activa {
  border-color: var(--acento);
  background: var(--acento-tenue);
}

.fuentes__nombre {
  text-align: left;
  font-weight: 600;
}

.fuentes__porcentaje {
  color: var(--texto-tenue);
  min-width: 4ch;
  text-align: right;
}

.fuentes__unica {
  padding: var(--e-5) var(--e-2);
  text-align: center;
}

.fuentes__unica-cifra {
  font-size: var(--t-3xl);
  font-weight: 750;
  letter-spacing: -0.03em;
  color: var(--acento);
}

.fuentes__unica-texto {
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.fuentes__esqueleto {
  display: block;
  height: 220px;
  border-radius: var(--r-2);
}

.fuentes__vacio {
  padding: var(--e-6) var(--e-4);
  text-align: center;
  color: var(--texto-tenue);
  font-size: var(--t-sm);
}
</style>
