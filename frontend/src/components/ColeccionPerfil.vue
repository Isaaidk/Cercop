<script setup>
/**
 * Una lista del perfil (contactos, productos, cobertura…) con su formulario de alta.
 *
 * Es presentacional: no habla con la API. Avisa con `agregar` y `quitar` y quien lo usa decide qué
 * hacer. Cada campo se describe con `{ clave, etiqueta, tipo, opciones, requerido, ancho }` para
 * que añadir una colección no obligue a escribir otro formulario.
 *
 * Está pensada también para personas mayores: los botones dicen lo que hacen («Agregar», «Quitar»)
 * en vez de un «+» o una «×», y quitar pide confirmar en el mismo sitio, porque un toque de más con
 * el dedo borraba una fila sin vuelta atrás.
 */
import { computed, reactive, ref, watch } from 'vue'

const props = defineProps({
  titulo: { type: String, required: true },
  ayuda: { type: String, default: '' },
  vacio: { type: String, default: 'Todavía no hay nada.' },
  filas: { type: Array, default: () => [] },
  campos: { type: Array, required: true },
  resumen: { type: Function, required: true },
  detalle: { type: Function, default: null },
  puedeEditar: { type: Boolean, default: true },
  ocupado: { type: Boolean, default: false },
})
const emit = defineEmits(['agregar', 'quitar'])

const valoresIniciales = () =>
  Object.fromEntries(props.campos.map((campo) => [campo.clave, campo.inicial ?? '']))
const nuevo = reactive(valoresIniciales())
const abierto = ref(false)
const porQuitar = ref(null)

const completo = computed(() =>
  props.campos.every((campo) => !campo.requerido || String(nuevo[campo.clave] ?? '').trim()),
)

function agregar() {
  if (!completo.value) return
  const fila = {}
  for (const campo of props.campos) {
    const valor = nuevo[campo.clave]
    if (valor === '' || valor == null) continue
    fila[campo.clave] = campo.tipo === 'number' ? Number(valor) : valor
  }
  emit('agregar', fila)
  Object.assign(nuevo, valoresIniciales())
}

function cancelar() {
  Object.assign(nuevo, valoresIniciales())
  abierto.value = false
}

function confirmarQuitar(id) {
  porQuitar.value = null
  emit('quitar', id)
}

// Al agregarse una fila el formulario se cierra solo: la lista de arriba confirma que entró.
watch(
  () => props.filas.length,
  () => (abierto.value = false),
)
</script>

<template>
  <div class="coleccion">
    <header class="coleccion__cabecera">
      <div>
        <h4>
          {{ titulo }}
          <span class="coleccion__cuenta">{{ filas.length }}</span>
        </h4>
        <p v-if="ayuda" class="coleccion__ayuda">{{ ayuda }}</p>
      </div>
      <button
        v-if="puedeEditar && !abierto"
        class="boton boton--secundario coleccion__boton"
        type="button"
        :aria-expanded="abierto"
        @click="abierto = true"
      >
        Agregar
      </button>
    </header>

    <form v-if="abierto" class="coleccion__alta" @submit.prevent="agregar">
      <label
        v-for="campo in campos"
        :key="campo.clave"
        class="coleccion__campo"
        :class="{ 'coleccion__campo--ancho': campo.ancho }"
      >
        <span>{{ campo.etiqueta }}<small v-if="campo.requerido"> (obligatorio)</small></span>
        <select v-if="campo.tipo === 'select'" v-model="nuevo[campo.clave]">
          <option v-if="!campo.requerido" value="">Sin indicar</option>
          <option v-for="opcion in campo.opciones" :key="opcion.valor" :value="opcion.valor">
            {{ opcion.etiqueta }}
          </option>
        </select>
        <span v-else-if="campo.tipo === 'check'" class="coleccion__check">
          <input v-model="nuevo[campo.clave]" type="checkbox" />
          {{ campo.texto || 'Sí' }}
        </span>
        <input
          v-else
          v-model="nuevo[campo.clave]"
          :type="campo.tipo === 'number' ? 'number' : 'text'"
          :min="campo.tipo === 'number' ? 0 : undefined"
          :placeholder="campo.pista || ''"
          :required="campo.requerido"
        />
      </label>
      <div class="coleccion__acciones">
        <button class="boton boton--principal coleccion__boton" type="submit" :disabled="!completo || ocupado">
          {{ ocupado ? 'Guardando…' : 'Guardar' }}
        </button>
        <button class="boton boton--secundario coleccion__boton" type="button" @click="cancelar">Cancelar</button>
      </div>
    </form>

    <ul v-if="filas.length" class="coleccion__lista">
      <li v-for="fila in filas" :key="fila.id" class="coleccion__fila">
        <div class="coleccion__texto">
          <strong>{{ resumen(fila) }}</strong>
          <small v-if="detalle && detalle(fila)">{{ detalle(fila) }}</small>
        </div>
        <div v-if="puedeEditar" class="coleccion__quitar">
          <template v-if="porQuitar === fila.id">
            <span class="coleccion__pregunta">¿Quitar?</span>
            <button class="boton boton--peligro coleccion__boton" type="button" @click="confirmarQuitar(fila.id)">
              Sí, quitar
            </button>
            <button class="boton boton--secundario coleccion__boton" type="button" @click="porQuitar = null">No</button>
          </template>
          <button
            v-else
            class="boton boton--secundario coleccion__boton"
            type="button"
            :aria-label="`Quitar ${resumen(fila)}`"
            @click="porQuitar = fila.id"
          >
            Quitar
          </button>
        </div>
      </li>
    </ul>
    <p v-else class="coleccion__vacio">{{ vacio }}</p>
  </div>
</template>

<style scoped>
.coleccion { display: flex; flex-direction: column; gap: var(--e-3); font-size: 1rem; }
.coleccion__cabecera { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: var(--e-3); }
.coleccion__cabecera h4 { font-size: var(--t-lg); font-weight: 700; display: flex; align-items: center; gap: var(--e-2); }
.coleccion__cuenta { padding: 0 0.55rem; border-radius: var(--r-redondo); background: var(--superficie-3); color: var(--texto); font-size: 1rem; font-weight: 600; }
.coleccion__ayuda { color: var(--texto-suave); font-size: 1rem; margin-top: 2px; }
.coleccion__boton { min-height: 44px; padding: 0.55rem 1.1rem; font-size: 1rem; font-weight: 650; }
.coleccion__alta { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: var(--e-4); padding: var(--e-4); border: 1px solid var(--borde-fuerte); border-radius: var(--r-3); background: var(--superficie-2); }
.coleccion__campo { display: flex; flex-direction: column; gap: var(--e-1); font-size: 1rem; font-weight: 650; color: var(--texto); }
.coleccion__campo small { font-weight: 400; color: var(--texto-suave); font-size: 1rem; }
.coleccion__campo--ancho { grid-column: 1 / -1; }
.coleccion__campo input:not([type='checkbox']), .coleccion__campo select { min-height: 48px; padding: 0.6rem 0.8rem; border: 1px solid var(--borde-fuerte); border-radius: var(--r-2); background: var(--superficie); color: var(--texto); font: inherit; font-weight: 400; font-size: var(--t-lg); }
.coleccion__campo input:focus-visible, .coleccion__campo select:focus-visible { outline: 3px solid var(--acento); outline-offset: 1px; }
.coleccion__check { display: flex; align-items: center; gap: var(--e-2); min-height: 48px; font-weight: 400; }
.coleccion__check input { width: 1.4rem; height: 1.4rem; }
.coleccion__acciones { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: var(--e-3); }
.coleccion__lista { display: flex; flex-direction: column; gap: var(--e-2); list-style: none; padding: 0; margin: 0; }
.coleccion__fila { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--e-3); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde-fuerte); border-radius: var(--r-2); background: var(--superficie); }
.coleccion__texto { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1 1 14rem; }
.coleccion__texto strong { font-size: var(--t-lg); font-weight: 600; overflow-wrap: anywhere; }
.coleccion__texto small { color: var(--texto-suave); font-size: 1rem; overflow-wrap: anywhere; }
.coleccion__quitar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--e-2); }
.coleccion__pregunta { font-weight: 650; }
.coleccion__vacio { padding: var(--e-3) var(--e-4); border: 1px dashed var(--borde-fuerte); border-radius: var(--r-2); color: var(--texto-suave); font-size: 1rem; }
@media (max-width: 640px) {
  .coleccion__boton { flex: 1 1 auto; }
}
</style>
