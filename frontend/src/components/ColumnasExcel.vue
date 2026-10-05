<script setup>
/**
 * Qué columnas llevan las exportaciones de la empresa.
 *
 * Es una lista de casillas y una decisión que vale para **todas** las descargas de la empresa, no
 * solo para la que se esté mirando. Por eso se guarda en el servidor y no en el navegador: el
 * compañero de al lado tiene que bajar el mismo archivo.
 *
 * Dos cosas que la pantalla tiene que dejar claras, porque no se deducen de las casillas:
 *
 * 1. **Sin ninguna casilla marcada salen todas.** Es el estado de partida y el que se recupera con
 *    «Todas»: no hay forma de exportar un archivo sin columnas, y ofrecerla sería ofrecer un botón
 *    que solo puede dar un archivo inservible.
 * 2. **Con plantilla, la columna que se desmarca no desaparece del archivo: se queda vacía.** El
 *    diseño es de la empresa y el sistema no lo toca; lo que se elige es qué se rellena.
 */
import { computed, ref, watch } from 'vue'

import { api } from '@/api/endpoints'

const props = defineProps({
  /** Agrupadas para la pantalla: [{ grupo, columnas: [{ clave, etiqueta }] }]. */
  catalogo: { type: Array, default: () => [] },
  /** Lo que hay guardado, o `null` si nunca se eligió nada —es decir, todas—. */
  elegidas: { type: Array, default: null },
})

const emit = defineEmits(['guardado'])

const guardando = ref(false)
const error = ref('')
const aviso = ref('')

/** Las claves de todas las columnas del catálogo, en el orden en que se muestran. */
const todas = computed(() =>
  props.catalogo.flatMap((grupo) => grupo.columnas.map((columna) => columna.clave)),
)

/**
 * Las casillas marcadas. Arranca con todas: sin selección guardada salen todas.
 *
 * La sincronización mira **las dos cosas** —lo guardado y el catálogo— y no solo lo guardado. El
 * catálogo llega con la respuesta de la plantilla, después del primer pintado: mirando solo lo
 * guardado, la pantalla se quedaría con el catálogo vacío del arranque y todas las casillas
 * aparecerían desmarcadas mientras el servidor no tiene nada excluido.
 */
const marcadas = ref([])

/**
 * Las casillas que corresponden a lo guardado.
 *
 * `null` y la lista vacía significan lo mismo —«todas»— y se tratan igual: el servidor guarda la
 * lista vacía cuando no hay nada excluido, y si aquí se leyera como «ninguna marcada» la pantalla
 * diría justo lo contrario de lo que hacen las exportaciones.
 */
function marcadasDe(elegidas) {
  return elegidas && elegidas.length ? [...elegidas] : [...todas.value]
}

watch([() => props.elegidas, todas], () => {
  marcadas.value = marcadasDe(props.elegidas)
}, { immediate: true })

/**
 * Si hay cambios sin guardar.
 *
 * Se comparan los conjuntos y no el orden: marcar y desmarcar la misma casilla deja el mismo
 * archivo, y el botón no debe quedarse encendido por eso. Tampoco se compara contra la lista tal
 * cual, porque «todas marcadas» y «sin selección» significan lo mismo y tienen que verse igual.
 */
const hayCambios = computed(() => {
  const actual = [...marcadas.value].sort().join()
  const previo = marcadasDe(props.elegidas).sort().join()
  return actual !== previo
})

/**
 * Sin ninguna columna no hay archivo, así que no se puede guardar.
 *
 * No se ofrece «exportar sin columnas» porque el resultado sería un Excel con las filas vacías: un
 * archivo que parece correcto y no dice nada. Quien pelee con esto lo que quiere es una columna
 * menos, no ninguna.
 */
const sinNinguna = computed(() => marcadas.value.length === 0)

function alternar(clave) {
  error.value = ''
  aviso.value = ''
  marcadas.value = marcadas.value.includes(clave)
    ? marcadas.value.filter((marcada) => marcada !== clave)
    : [...marcadas.value, clave]
}

function marcarTodas() {
  error.value = ''
  aviso.value = ''
  marcadas.value = [...todas.value]
}

async function guardar() {
  if (guardando.value) return

  guardando.value = true
  error.value = ''
  aviso.value = ''
  try {
    // Con todas marcadas se guarda la lista vacía, que es como el servidor dice «todas»: así el
    // estado no depende de que el catálogo no cambie, y una columna nueva aparece sola.
    const incluidas = todas.value.filter((clave) => marcadas.value.includes(clave))
    const respuesta = await api.guardarColumnas(
      incluidas.length === todas.value.length ? [] : incluidas,
    )
    emit('guardado', respuesta.columnas_elegidas || [])
    aviso.value =
      incluidas.length === todas.value.length
        ? 'Guardado: las exportaciones llevarán todas las columnas.'
        : `Guardado: las exportaciones llevarán ${incluidas.length} columnas.`
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    guardando.value = false
  }
}
</script>

<template>
  <section class="tarjeta aparece">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">Columnas del Excel</p>
        <p class="tarjeta__pista">
          Lo que se desmarca no se rellena en las exportaciones de tu empresa
        </p>
      </div>
    </header>

    <div class="tarjeta__cuerpo columnas">
      <p class="columnas__nota">
        La selección vale para <strong>todas las descargas de la empresa</strong>. Si no marcas nada,
        el archivo lleva todas las columnas. Con plantilla, una columna desmarcada no desaparece: se
        queda vacía, porque el diseño del archivo es tuyo.
      </p>

      <div v-for="grupo in catalogo" :key="grupo.grupo" class="columnas__grupo">
        <p class="columnas__grupo-titulo">{{ grupo.grupo }}</p>
        <div class="columnas__lista">
          <label v-for="columna in grupo.columnas" :key="columna.clave" class="columnas__opcion">
            <input
              type="checkbox"
              :checked="marcadas.includes(columna.clave)"
              @change="alternar(columna.clave)"
            />
            <span>{{ columna.etiqueta }}</span>
          </label>
        </div>
      </div>

      <div class="columnas__acciones">
        <button
          type="button"
          class="boton boton--principal boton--pequeno"
          :disabled="guardando || !hayCambios || sinNinguna"
          @click="guardar"
        >
          <span v-if="guardando" class="girador" aria-hidden="true" />
          {{ hayCambios ? 'Guardar las columnas' : 'Sin cambios' }}
        </button>
        <button
          type="button"
          class="boton boton--secundario boton--pequeno"
          :disabled="guardando"
          @click="marcarTodas"
        >
          Marcar todas
        </button>
        <span class="columnas__cuenta">{{ marcadas.length }} de {{ todas.length }}</span>
      </div>

      <p v-if="sinNinguna" class="columnas__aviso" role="status">
        Marca al menos una columna: un archivo sin columnas saldría con las filas vacías.
      </p>

      <p v-if="error" class="tabla__error" role="alert">{{ error }}</p>
      <p v-else-if="aviso" class="tabla__exportacion" role="status">{{ aviso }}</p>
    </div>
  </section>
</template>

<style scoped>
.columnas {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 72ch;
}

.columnas__nota {
  margin: 0;
  font-size: 0.88rem;
  color: var(--texto-tenue, #6b7280);
}

.columnas__grupo {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.columnas__grupo-titulo {
  margin: 0;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--texto-tenue, #6b7280);
}

.columnas__lista {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
  gap: 0.3rem 1rem;
}

.columnas__opcion {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
  cursor: pointer;
}

.columnas__acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}

.columnas__cuenta {
  font-size: 0.82rem;
  color: var(--texto-tenue, #6b7280);
}

.columnas__aviso {
  margin: 0;
  font-size: 0.85rem;
  color: var(--aviso, #b45309);
}
</style>
