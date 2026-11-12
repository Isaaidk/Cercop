<script setup>
/**
 * Una sección del certificado («Domicilio tributario», «Medios de contacto»…): título grande, una
 * línea debajo, los datos para leer y un botón «Editar».
 *
 * La pantalla se lee por defecto y se edita **de a una sección**. Antes todo el perfil era un
 * formulario abierto con una barra de «cambios sin guardar» abajo: a una persona mayor le costaba
 * saber qué había tocado y si ya estaba guardado. Ahora «Editar» abre solo esta sección con campos
 * grandes y dos salidas claras, «Guardar» o «Cancelar», y el resultado se dice aquí mismo, junto a
 * lo que se cambió, no arriba de la página donde no se ve.
 *
 * `modo="lista"` es para las listas (actividades, contactos…): cada fila se guarda al agregarla, así
 * que no hay nada pendiente y la salida es una sola, «Terminar».
 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  id: { type: String, required: true },
  titulo: { type: String, required: true },
  ayuda: { type: String, default: '' },
  editando: { type: Boolean, default: false },
  guardando: { type: Boolean, default: false },
  modo: { type: String, default: 'campos' },
  puedeEditar: { type: Boolean, default: true },
  /** Frase de éxito o de error de la última acción en esta sección. */
  mensaje: { type: String, default: '' },
  error: { type: String, default: '' },
})
const emit = defineEmits(['editar', 'guardar', 'cancelar'])

const formulario = ref(null)

// Al abrir la edición el cursor va al primer campo: quien usa teclado o lupa no tiene que buscarlo.
watch(
  () => props.editando,
  async (abierta) => {
    if (!abierta) return
    await nextTick()
    formulario.value?.querySelector('input, select, textarea, button')?.focus()
  },
)
</script>

<template>
  <section :id="`perfil-${id}`" class="seccion-cert" :aria-labelledby="`perfil-${id}-titulo`">
    <header class="seccion-cert__cabecera">
      <div>
        <h3 :id="`perfil-${id}-titulo`">{{ titulo }}</h3>
        <p v-if="ayuda" class="seccion-cert__ayuda">{{ ayuda }}</p>
      </div>
      <button
        v-if="puedeEditar && !editando"
        type="button"
        class="boton boton--secundario seccion-cert__editar"
        :aria-label="`Editar ${titulo}`"
        @click="emit('editar')"
      >
        Editar
      </button>
    </header>

    <p v-if="mensaje && !editando" class="seccion-cert__mensaje seccion-cert__mensaje--ok" role="status">
      {{ mensaje }}
    </p>

    <div v-if="!editando" class="seccion-cert__lectura">
      <slot />
    </div>

    <!-- Las listas llevan dentro su propio formulario de alta: un <form> dentro de otro no es válido
         y el «Enter» de uno enviaría el otro, por eso en modo lista el contenedor es un <div>. -->
    <component
      :is="modo === 'campos' ? 'form' : 'div'"
      v-else
      ref="formulario"
      class="seccion-cert__edicion"
      @submit.prevent="emit('guardar')"
    >
      <slot name="edicion" />
      <p v-if="error" class="seccion-cert__mensaje seccion-cert__mensaje--error" role="alert">{{ error }}</p>
      <div class="seccion-cert__acciones">
        <template v-if="modo === 'campos'">
          <button class="boton boton--principal" type="submit" :disabled="guardando">
            {{ guardando ? 'Guardando…' : 'Guardar' }}
          </button>
          <button class="boton boton--secundario" type="button" :disabled="guardando" @click="emit('cancelar')">
            Cancelar
          </button>
        </template>
        <button v-else class="boton boton--principal" type="button" @click="emit('cancelar')">Terminar</button>
      </div>
    </component>
  </section>
</template>

<style scoped>
.seccion-cert { display: flex; flex-direction: column; gap: var(--e-3); scroll-margin-top: 1rem; }
.seccion-cert__cabecera { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: var(--e-3); padding-bottom: var(--e-2); border-bottom: 2px solid var(--texto); }
.seccion-cert__cabecera h3 { font-size: var(--t-xl); font-weight: 700; color: var(--texto); }
.seccion-cert__ayuda { margin-top: var(--e-1); color: var(--texto-suave); font-size: 1rem; }
.seccion-cert__editar { min-height: 48px; min-width: 7rem; padding: 0.6rem 1.25rem; font-size: var(--t-lg); font-weight: 650; }
.seccion-cert__mensaje { padding: var(--e-3) var(--e-4); border-radius: var(--r-2); font-size: 1rem; font-weight: 600; }
.seccion-cert__mensaje--ok { background: var(--ok-suave); color: var(--ok); }
.seccion-cert__mensaje--error { background: var(--error-suave); color: var(--error); }
.seccion-cert__edicion { display: flex; flex-direction: column; gap: var(--e-4); padding: var(--e-5); border: 2px solid var(--acento); border-radius: var(--r-3); background: var(--superficie); }
.seccion-cert__acciones { display: flex; flex-wrap: wrap; gap: var(--e-3); padding-top: var(--e-2); }
.seccion-cert__acciones .boton { min-height: 48px; min-width: 9rem; padding: 0.65rem 1.5rem; font-size: var(--t-lg); font-weight: 650; }
@media (max-width: 640px) {
  .seccion-cert__edicion { padding: var(--e-4); }
  .seccion-cert__acciones .boton, .seccion-cert__editar { flex: 1 1 100%; }
}
</style>
