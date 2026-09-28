<script setup>
/**
 * Mapa del Ecuador con las 24 provincias.
 *
 * Cada provincia se pulsa para filtrar: al seleccionarla, la tabla y las gráficas pasan a mostrar
 * solo las contrataciones de esa provincia **y de las palabras clave que ya estuvieran puestas**. Es
 * la pieza que hace que el mapa sea un filtro y no un adorno.
 *
 * Tres decisiones sobre la accesibilidad y la lectura
 * --------------------------------------------------
 * **Cada provincia es un botón de verdad.** Se dibuja con un `path`, pero lleva `role="button"` y
 * `tabindex="0"` y responde a Intro y a la barra espaciadora. Un mapa en el que solo se puede hacer
 * clic con el ratón deja fuera a quien navega con teclado, y no hay ninguna razón para hacerlo: son
 * veinticuatro elementos y cada uno necesita dos atributos.
 *
 * **El color solo no informa.** El sombreado indica el volumen, pero la cifra exacta aparece en la
 * etiqueta emergente y en la lista de al lado. Un mapa de calor sin números ni leyenda obliga a
 * adivinar.
 *
 * **La escala es lineal y lo dice.** Unos pocos cantones concentran la mayoría de las contrataciones,
 * así que con una escala lineal casi todas las provincias salen muy claras. Se podría exagerar con
 * una escala logarítmica para que se vean mejor y sería engañoso: aquí el sombreado es proporcional
 * al número, y la leyenda lo advierte para que nadie interprete de más.
 */
import { computed, onMounted, ref } from 'vue'

import { cargarMapa } from '@/utils/mapa'
import { numero } from '@/utils/formato'
import { codigoDeProvincia, nombreDeProvincia } from '@/utils/provincias'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'

const cargando = ref(true)
const error = ref('')
const mapa = ref({ provincias: [], viewBox: '0 0 620 520', recuadroIslas: null })
/** Guarda el **código** de la provincia bajo el cursor, no su nombre en el mapa. */
const resaltada = ref(null)

const seleccionada = computed(() => filtros.estado.provincia)

/** Totales indexados por código de provincia, que es la clave canónica del panel. */
const totales = computed(() => {
  const indice = new Map()
  for (const provincia of datos.estado.resumenProvincias.porProvincia) {
    indice.set(provincia.codigo, provincia.total)
  }
  return indice
})

const maximo = computed(() =>
  Math.max(1, ...datos.estado.resumenProvincias.porProvincia.map((p) => p.total)),
)

/**
 * Las provincias ya resueltas a la clave del panel, con su total.
 *
 * El GeoJSON nombra las provincias como las escribe la cartografía —«Manabí», «Los Ríos»,
 * «Galápagos»—, y los totales están indexados por el código interno, que va sin tildes: «Manabi»,
 * «Los Rios», «Galapagos». Sin traducir, `totales.get(nombre)` devolvería vacío para esas siete
 * provincias y el mapa las pintaría **en gris, como si no tuvieran datos**, además de enviar al
 * servidor una grafía que la fuente no usa y no encontrar ninguna contratación.
 *
 * Se traduce una sola vez aquí y el resto del componente trabaja con `codigo`.
 */
const provincias = computed(() =>
  mapa.value.provincias.map((provincia) => {
    const codigo = codigoDeProvincia(provincia.nombre) || provincia.nombre
    return { ...provincia, codigo, total: totales.value.get(codigo) || 0 }
  }),
)

/**
 * Intensidad del sombreado, de 0 a 1.
 *
 * La raíz cuadrada comprime las diferencias para que las provincias con poco volumen no queden todas
 * del mismo color casi blanco. Es una decisión estética y por eso está documentada: el número real
 * sigue estando disponible en la etiqueta y en la lista, así que la forma no oculta el dato.
 */
function intensidad(total) {
  if (!total) return 0
  return Math.sqrt(total / maximo.value)
}

function colorDe(total) {
  const fuerza = intensidad(total)
  if (!fuerza) return 'var(--mapa-tierra)'
  return `color-mix(in srgb, var(--mapa-seleccion) ${Math.round(18 + fuerza * 78)}%, var(--mapa-tierra))`
}

function elegir(codigo) {
  filtros.alternarProvincia(codigo)
}

function conTeclado(evento, codigo) {
  if (evento.key === 'Enter' || evento.key === ' ') {
    evento.preventDefault()
    elegir(codigo)
  }
}

onMounted(async () => {
  try {
    mapa.value = await cargarMapa()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
})
</script>

<template>
  <div class="mapa">
    <div v-if="cargando" class="mapa__cargando">
      <span class="esqueleto mapa__esqueleto" />
    </div>

    <p v-else-if="error" class="mapa__error" role="alert">{{ error }}</p>

    <template v-else>
      <svg
        class="mapa__lienzo"
        :viewBox="mapa.viewBox"
        role="group"
        aria-label="Mapa de las provincias del Ecuador. Cada provincia se puede seleccionar para filtrar."
      >
        <g>
          <path
            v-for="provincia in provincias"
            :key="provincia.codigo"
            :d="provincia.d"
            class="provincia"
            :class="{
              'provincia--seleccionada': seleccionada === provincia.codigo,
              'provincia--resaltada': resaltada === provincia.codigo,
              'provincia--vacia': !provincia.total,
            }"
            :fill="colorDe(provincia.total)"
            role="button"
            tabindex="0"
            :aria-pressed="seleccionada === provincia.codigo"
            :aria-label="`${nombreDeProvincia(provincia.codigo)}: ${numero(provincia.total)} contrataciones`"
            @click="elegir(provincia.codigo)"
            @keydown="conTeclado($event, provincia.codigo)"
            @mouseenter="resaltada = provincia.codigo"
            @mouseleave="resaltada = null"
            @focus="resaltada = provincia.codigo"
            @blur="resaltada = null"
          />
        </g>

        <!--
          Galápagos va en un recuadro aparte, con línea de puntos: es la convención de los mapas
          oficiales del Ecuador y evita que el continente quede reducido a una franja por culpa de
          más de mil kilómetros de océano.
        -->
        <g v-if="mapa.recuadroIslas" class="mapa__islas">
          <rect
            :x="mapa.recuadroIslas.x"
            :y="mapa.recuadroIslas.y"
            :width="mapa.recuadroIslas.ancho"
            :height="mapa.recuadroIslas.alto"
            class="mapa__recuadro"
          />
          <text
            :x="mapa.recuadroIslas.x + 4"
            :y="mapa.recuadroIslas.y + mapa.recuadroIslas.alto - 5"
            class="mapa__etiqueta-islas"
          >
            Galápagos
          </text>
        </g>

        <text :x="12" :y="16" class="mapa__nota">Selecciona una provincia para filtrar</text>
      </svg>

      <!-- Etiqueta emergente: da la cifra exacta del sombreado que se está mirando. -->
      <Transition name="fundido">
        <div v-if="resaltada" class="mapa__ficha aparece">
          <strong>{{ nombreDeProvincia(resaltada) }}</strong>
          <span class="numeros">{{ numero(totales.get(resaltada) || 0) }}</span>
          <small>contrataciones</small>
          <span v-if="seleccionada === resaltada" class="etiqueta etiqueta--acento">Filtrando</span>
        </div>
      </Transition>

      <div class="mapa__leyenda">
        <span class="mapa__leyenda-titulo">Menos</span>
        <span
          v-for="paso in 5"
          :key="paso"
          class="mapa__escala"
          :style="{ background: colorDe(((paso - 1) / 4) ** 2 * maximo) }"
        />
        <span class="mapa__leyenda-titulo">Más</span>
      </div>

      <p class="mapa__nota-pie">
        El sombreado es proporcional al número de contrataciones; pasa el cursor sobre una provincia
        para ver la cifra. Las provincias sin datos se muestran en gris.
      </p>
    </template>
  </div>
</template>

<style scoped>
.mapa {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--e-3);
}

.mapa__lienzo {
  width: 100%;
  height: auto;
  max-height: 460px;
  overflow: visible;
}

.provincia {
  stroke: var(--mapa-borde);
  stroke-width: 1.1;
  stroke-linejoin: round;
  cursor: pointer;
  transition:
    fill var(--normal) var(--curva),
    stroke var(--rapido) var(--curva),
    stroke-width var(--rapido) var(--curva),
    opacity var(--normal) var(--curva);
}

.provincia:hover,
.provincia--resaltada {
  stroke: var(--acento);
  stroke-width: 1.8;
}

.provincia:focus-visible {
  outline: none;
  stroke: var(--acento);
  stroke-width: 2.4;
}

/* La provincia seleccionada se marca en el borde y sube ligeramente de grosor. Un cambio solo de
   color no bastaría: hay quien no distingue bien los tonos azules. */
.provincia--seleccionada {
  stroke: var(--acento-fuerte);
  stroke-width: 2.6;
  filter: drop-shadow(0 2px 6px color-mix(in srgb, var(--acento) 45%, transparent));
}

.provincia--vacia {
  fill: var(--mapa-tierra);
  opacity: 0.75;
}

.mapa__recuadro {
  fill: none;
  stroke: var(--borde-fuerte);
  stroke-width: 1;
  stroke-dasharray: 3 3;
  rx: 4;
}

.mapa__etiqueta-islas {
  fill: var(--texto-tenue);
  font-size: 8px;
  font-weight: 600;
}

.mapa__nota {
  fill: var(--texto-tenue);
  font-size: 10px;
  font-weight: 600;
}

.mapa__ficha {
  position: absolute;
  top: 0;
  right: 0;
  display: grid;
  justify-items: end;
  gap: 1px;
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  background: var(--superficie);
  border: 1px solid var(--borde);
  box-shadow: var(--sombra-2);
  pointer-events: none;
  font-size: var(--t-sm);
}

.mapa__ficha strong {
  font-weight: 650;
}

.mapa__ficha span {
  font-size: var(--t-lg);
  font-weight: 700;
  color: var(--acento);
}

.mapa__ficha small {
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.mapa__leyenda {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.mapa__leyenda-titulo {
  padding: 0 var(--e-1);
}

.mapa__escala {
  width: 26px;
  height: 10px;
  border-radius: 2px;
  border: 1px solid var(--borde);
}

.mapa__nota-pie {
  max-width: 46ch;
  text-align: center;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.5;
}

.mapa__cargando {
  width: 100%;
}

.mapa__esqueleto {
  display: block;
  width: 100%;
  height: 340px;
  border-radius: var(--r-3);
}

.mapa__error {
  padding: var(--e-4);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.fundido-enter-active,
.fundido-leave-active {
  transition: opacity var(--rapido) var(--curva);
}

.fundido-enter-from,
.fundido-leave-to {
  opacity: 0;
}

@media (max-width: 639px) {
  .mapa__lienzo {
    max-height: 380px;
  }

  .mapa__ficha {
    position: static;
    justify-items: center;
    width: 100%;
    pointer-events: auto;
  }
}
</style>
