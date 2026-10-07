<script setup>
/**
 * Las provincias como casillas, con buscador.
 *
 * Por qué casillas y no el desplegable con fichas que hay en el panel lateral
 * -------------------------------------------------------------------------
 * Porque la pregunta es «¿en qué provincias?» y con 24 opciones una lista de casillas se lee de un
 * vistazo: se ve lo que está marcado y lo que no sin abrir nada. El desplegable que añade y la ficha
 * que quita funciona, pero obliga a abrirlo una vez por provincia y no deja ver la selección entera
 * de golpe.
 *
 * Se conserva la misma lógica que el mapa —el filtro es la **lista** de provincias, y el mapa
 * escribe la misma lista— para que las dos formas de elegir sigan coincidiendo. Con la lista vacía no
 * se filtra por provincia, que es lo que hace el mapa cuando no hay ninguna pulsada.
 *
 * El buscador existe porque veinticuatro casillas ocupan mucho en un móvil y porque casi siempre se
 * sabe cuál se busca; escribe «azu» y queda sola. No filtra por gusto: escribir tres letras es más
 * rápido que recorrer la lista.
 */
import { computed, ref, watch } from 'vue'

import { PROVINCIAS } from '@/utils/provincias'

const props = defineProps({
  /** Códigos de las provincias elegidas. */
  seleccionadas: { type: Array, default: () => [] },
  /** Texto de la etiqueta. */
  etiqueta: { type: String, default: 'Provincias' },
})

const emit = defineEmits(['cambiar'])

const busqueda = ref('')

/**
 * Copia local de lo marcado, sincronizada con la propiedad.
 *
 * Hace falta y no es un capricho: al marcar una casilla, la lista nueva se calcula **aquí** y la
 * propiedad no cambia hasta que el componente se vuelve a pintar, así que dos clics seguidos —un
 * ciudadano marcando Azuay y Bolívar de corrido— leerían los dos la misma lista vieja y el primero
 * se perdería. Se descubrió verificándolo: dos clics en el mismo instante dejaban una sola provincia
 * marcada. Con la copia local cada gesto parte de lo que hay puesto de verdad, y el `watch` mantiene
 * el espejo cuando la selección cambia por otro camino —el mapa escribe el mismo filtro—.
 */
const elegidas = ref(new Set(props.seleccionadas))

watch(
  () => props.seleccionadas,
  (nuevas) => {
    elegidas.value = new Set(nuevas)
  },
  { deep: true },
)
/** Sin tildes y en minúsculas, como se comparan los nombres en todo el panel. */
function normalizar(texto) {
  return String(texto || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim()
}

const visibles = computed(() => {
  const filtro = normalizar(busqueda.value)
  if (!filtro) return PROVINCIAS
  return PROVINCIAS.filter(
    (provincia) =>
      normalizar(provincia.nombre).includes(filtro) || normalizar(provincia.codigo).includes(filtro),
  )
})

const todasMarcadas = computed(
  () => elegidas.value.size > 0 && elegidas.value.size === PROVINCIAS.length,
)

function alternar(codigo) {
  const siguientes = new Set(elegidas.value)
  if (siguientes.has(codigo)) siguientes.delete(codigo)
  else siguientes.add(codigo)
  fijar([...siguientes])
}

function marcarTodas() {
  fijar(todasMarcadas.value ? [] : PROVINCIAS.map((provincia) => provincia.codigo))
}

/** Escribe la selección en los dos sitios: en la copia local y en quien lo usa. */
function fijar(codigos) {
  elegidas.value = new Set(codigos)
  emit('cambiar', [...codigos].sort())
}
</script>

<template>
  <div class="provincias">
    <div class="provincias__cabecera">
      <span class="campo__etiqueta">{{ etiqueta }}</span>
      <button type="button" class="boton boton--fantasma boton--pequeno" @click="marcarTodas()">
        {{ todasMarcadas ? 'Desmarcar todas' : 'Marcar todas' }}
      </button>
    </div>

    <p class="provincias__ayuda">
      {{
        elegidas.size
          ? `${elegidas.size} ${elegidas.size === 1 ? 'provincia' : 'provincias'} marcadas.`
          : 'Sin marcar: se buscan todas.'
      }}
      Se suman entre sí, igual que pulsándolas en el mapa.
    </p>

    <input
      v-model="busqueda"
      class="entrada provincias__buscar"
      type="search"
      placeholder="Buscar provincia…"
      aria-label="Buscar provincia en la lista"
    />

    <ul class="provincias__lista">
      <li v-for="provincia in visibles" :key="provincia.codigo">
        <label class="provincias__opcion" :class="{ 'provincias__opcion--marcada': elegidas.has(provincia.codigo) }">
          <input
            type="checkbox"
            :checked="elegidas.has(provincia.codigo)"
            @change="alternar(provincia.codigo)"
          />
          <span>{{ provincia.nombre }}</span>
        </label>
      </li>
    </ul>

    <p v-if="!visibles.length" class="provincias__vacio">Ninguna provincia se llama así.</p>

    <p v-if="elegidas.size" class="provincias__fichas">
      <button
        v-for="codigo in [...elegidas].sort()"
        :key="codigo"
        type="button"
        class="provincias__ficha"
        :aria-label="`Quitar ${codigo}`"
        @click="alternar(codigo)"
      >
        {{ codigo }} <span aria-hidden="true">✕</span>
      </button>
    </p>
  </div>
</template>

<style scoped>
.provincias {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.provincias__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
}

.provincias__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.provincias__buscar {
  width: 100%;
}

/*
 * Dos columnas en cuanto quepan y una sola en móvil. `auto-fill` con un mínimo de 8rem es lo que
 * hace las dos cosas sin una regla de medios por cada ancho.
 */
.provincias__lista {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr));
  gap: 0.15rem var(--e-2);
  list-style: none;
  margin: 0;
  padding: var(--e-2);
  max-height: 15rem;
  overflow-y: auto;
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

.provincias__opcion {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.15rem 0.25rem;
  border-radius: var(--r-1);
  font-size: var(--t-sm);
  cursor: pointer;
}

.provincias__opcion:hover {
  background: var(--superficie);
}

.provincias__opcion--marcada {
  color: var(--acento);
  font-weight: 600;
}

.provincias__vacio {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.provincias__fichas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  margin: 0;
}

.provincias__ficha {
  display: inline-flex;
  align-items: center;
  gap: var(--e-1);
  padding: 0.2rem 0.55rem;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-xs);
  color: var(--texto-suave);
  cursor: pointer;
}

.provincias__ficha:hover {
  border-color: var(--acento);
  color: var(--texto);
}
</style>
