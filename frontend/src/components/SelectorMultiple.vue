<script setup>
/**
 * Un desplegable de selección múltiple: se abre, se marcan varias casillas y se cierra.
 *
 * Por qué un desplegable y no la lista de casillas que usan las provincias
 * ----------------------------------------------------------------------
 * Por espacio. Las provincias son veinticuatro y caben de un vistazo; los tipos de contratación son
 * diecinueve **hoy** y el catálogo de la fuente puede crecer, y en la pestaña de ofertas conviven con
 * otros doce campos. Una lista de casillas siempre abierta ocuparía media pantalla para un filtro que
 * casi nunca se toca, mientras que el desplegable ocupa una línea y enseña lo elegido en la propia
 * etiqueta.
 *
 * Por qué casillas dentro y no un desplegable normal
 * -------------------------------------------------
 * Porque el `<select multiple>` nativo no sirve para esto: en la mayoría de navegadores de escritorio
 * hay que mantener pulsado `Ctrl` para marcar un segundo valor —algo que casi nadie descubre— y en
 * móvil directamente no existe. Las casillas se marcan una detrás de otra sin saber nada de teclado.
 *
 * Qué se cierra solo
 * ------------------
 * El panel se cierra al pulsar fuera y con `Escape`. Sin lo primero quedaba abierto tapando la tabla
 * hasta que se volviera a pulsar el botón, que es lo que hace que un desplegable se sienta atascado.
 *
 * La selección vive en quien lo usa: aquí solo se avisa de lo que cambia. Se guarda una copia local
 * para que dos clics seguidos no lean la misma lista vieja —marcar dos casillas de corrido perdía la
 * primera— y el `watch` mantiene el espejo cuando la selección cambia por otro camino.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  /** Texto de la etiqueta. */
  etiqueta: { type: String, required: true },
  /** Los valores que se pueden marcar, en el orden en que se ofrecen. */
  opciones: { type: Array, default: () => [] },
  /** Los valores marcados. */
  seleccionadas: { type: Array, default: () => [] },
  /** Cómo se nombra un valor en la frase del resumen, en singular y en plural. */
  singular: { type: String, default: 'valor' },
  plural: { type: String, default: 'valores' },
  /** Una línea explicando qué filtra este campo. */
  ayuda: { type: String, default: '' },
  /** Se enseña el buscador a partir de esta cantidad de opciones. */
  minimoParaBuscar: { type: Number, default: 8 },
})

const emit = defineEmits(['cambiar'])

const abierto = ref(false)
const busqueda = ref('')
const raiz = ref(null)

const marcadas = ref(new Set(props.seleccionadas))

watch(
  () => props.seleccionadas,
  (nuevas) => {
    marcadas.value = new Set(nuevas)
  },
  { deep: true },
)

const conBuscador = computed(() => props.opciones.length >= props.minimoParaBuscar)

/** Sin tildes y en minúsculas, como se comparan los textos en todo el panel. */
function normalizar(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
}

const visibles = computed(() => {
  const filtro = normalizar(busqueda.value)
  if (!filtro) return props.opciones
  return props.opciones.filter((opcion) => normalizar(opcion).includes(filtro))
})

const todasMarcadas = computed(
  () => marcadas.value.size > 0 && marcadas.value.size === props.opciones.length,
)

/** El resumen del botón: «Todos», «Licitación» o «3 tipos». */
const resumen = computed(() => {
  const cuantas = marcadas.value.size
  if (!cuantas) return `Todos los ${props.plural}`
  if (cuantas === 1) return [...marcadas.value][0]
  return `${cuantas} ${props.plural}`
})

function alternar(opcion) {
  const siguientes = new Set(marcadas.value)
  if (siguientes.has(opcion)) siguientes.delete(opcion)
  else siguientes.add(opcion)
  fijar([...siguientes])
}

function marcarTodas() {
  fijar(todasMarcadas.value ? [] : props.opciones)
}

function limpiar() {
  busqueda.value = ''
  fijar([])
}

/**
 * Escribe la selección en los dos sitios: en la copia local y en quien lo usa.
 *
 * Ordenada, para que la clave de caché no dependa del orden en que se marcaron las casillas.
 */
function fijar(valores) {
  const ordenados = [...new Set(valores)].sort()
  marcadas.value = new Set(ordenados)
  emit('cambiar', ordenados)
}

function alternarPanel() {
  abierto.value = !abierto.value
  if (!abierto.value) busqueda.value = ''
}

/**
 * Cierra al pulsar fuera.
 *
 * Se escucha en el documento y no en un velo: sin esto, pulsar en la tabla de detrás tendría que
 * cerrar el panel y además hacer su trabajo, y un velo se comería el primer clic.
 */
function alPulsarFuera(evento) {
  if (!abierto.value) return
  if (raiz.value && !raiz.value.contains(evento.target)) abierto.value = false
}

function alPulsarTecla(evento) {
  if (evento.key === 'Escape' && abierto.value) {
    abierto.value = false
    busqueda.value = ''
  }
}

onMounted(() => {
  document.addEventListener('click', alPulsarFuera)
  document.addEventListener('keydown', alPulsarTecla)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', alPulsarFuera)
  document.removeEventListener('keydown', alPulsarTecla)
})
</script>

<template>
  <div ref="raiz" class="multiple">
    <span class="campo__etiqueta" :id="`etiqueta-${etiqueta}`">{{ etiqueta }}</span>

    <button
      type="button"
      class="multiple__boton"
      :class="{ 'multiple__boton--con-marca': marcadas.size > 0 }"
      :aria-expanded="abierto"
      aria-haspopup="listbox"
      :aria-labelledby="`etiqueta-${etiqueta}`"
      @click="alternarPanel"
    >
      <span class="multiple__resumen" :title="[...marcadas].sort().join(', ')">{{ resumen }}</span>
      <span class="multiple__flecha" :class="{ 'multiple__flecha--arriba': abierto }" aria-hidden="true">▾</span>
    </button>

    <p v-if="ayuda && !abierto" class="multiple__ayuda">{{ ayuda }}</p>

    <div v-if="abierto" class="multiple__panel">
      <div class="multiple__cabecera">
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="marcarTodas()">
          {{ todasMarcadas ? 'Desmarcar todo' : 'Marcar todo' }}
        </button>
        <button
          type="button"
          class="boton boton--fantasma boton--pequeno"
          :disabled="!marcadas.size"
          @click="limpiar()"
        >
          Limpiar
        </button>
      </div>

      <input
        v-if="conBuscador"
        v-model="busqueda"
        class="entrada multiple__buscar"
        type="search"
        :placeholder="`Buscar ${singular}…`"
        :aria-label="`Buscar ${singular} en la lista`"
      />

      <!--
        Un grupo de casillas y no una lista de opciones: las casillas nativas ya anuncian su estado y
        se marcan con la barra espaciadora, y envolverlas en `role="option"` diría dos cosas distintas
        de lo mismo.
      -->
      <ul class="multiple__lista" role="group" :aria-label="etiqueta">
        <li v-for="opcion in visibles" :key="opcion">
          <label
            class="multiple__opcion"
            :class="{ 'multiple__opcion--marcada': marcadas.has(opcion) }"
          >
            <input
              type="checkbox"
              :checked="marcadas.has(opcion)"
              @change="alternar(opcion)"
            />
            <span>{{ opcion }}</span>
          </label>
        </li>
      </ul>

      <p v-if="!visibles.length" class="multiple__vacio">Ninguno se llama así.</p>

      <p v-if="marcadas.size" class="multiple__pie">
        {{ marcadas.size }}
        {{ marcadas.size === 1 ? singular + ' marcado' : plural + ' marcados' }}. Se suman entre sí.
      </p>
    </div>
  </div>
</template>

<style scoped>
.multiple {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.multiple__boton {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
  width: 100%;
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
  font: inherit;
  font-size: var(--t-sm);
  color: var(--texto-suave);
  text-align: left;
  cursor: pointer;
}

.multiple__boton:hover {
  border-color: var(--borde-fuerte);
}

.multiple__boton:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 1px;
}

/* Con algo marcado el borde y el texto cambian de color: es la señal de que este filtro está
   puesto, sin tener que abrir el desplegable para comprobarlo. */
.multiple__boton--con-marca {
  border-color: var(--acento);
  color: var(--texto);
  font-weight: 600;
}

.multiple__resumen {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.multiple__flecha {
  flex: none;
  font-size: 0.7em;
  transition: transform var(--normal) var(--curva);
}

.multiple__flecha--arriba {
  transform: rotate(180deg);
}

.multiple__ayuda {
  margin: 0;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

/*
 * El panel flota sobre lo de abajo en lugar de empujarlo: dentro de la rejilla de filtros, abierto
 * en línea desplazaría media pantalla cada vez que se abre.
 */
.multiple__panel {
  position: absolute;
  z-index: 30;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 0.25rem;
  padding: var(--e-2);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  background: var(--superficie);
  box-shadow: var(--sombra-3);
}

.multiple__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
  margin-bottom: var(--e-2);
}

.multiple__buscar {
  width: 100%;
  margin-bottom: var(--e-2);
}

.multiple__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 15rem;
  overflow-y: auto;
}

.multiple__opcion {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.2rem 0.3rem;
  border-radius: var(--r-1);
  font-size: var(--t-sm);
  cursor: pointer;
}

.multiple__opcion:hover {
  background: var(--superficie-2);
}

.multiple__opcion--marcada {
  color: var(--acento);
  font-weight: 600;
}

.multiple__vacio,
.multiple__pie {
  margin: var(--e-2) 0 0;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}
</style>
