<script setup>
/**
 * La plantilla de Excel de la empresa.
 *
 * Aquí se sube el libro `.xlsx` con el logo y los estilos de la empresa, y las exportaciones pasan a
 * salir con ese diseño en lugar del genérico. Una por empresa: volver a subir reemplaza la anterior.
 *
 * Tres cosas que la interfaz tiene que dejar claras, porque no se deducen del archivo:
 *
 * 1. **Dónde van los datos.** En una hoja llamada «Datos». Si no existe, se crea. Quien prepare la
 *    plantilla tiene que saberlo antes de subirla, no descubrirlo después de un archivo mal formado.
 * 2. **Que las macros no valen.** No es una limitación caprichosa: los Excel que genera el sistema se
 *    mandan a otras personas, y repartir un libro con macros es repartir código ejecutable. Se dice
 *    antes de que alguien pierda el tiempo preparando un `.xlsm`.
 * 3. **Qué pasa si no hay plantilla.** Nada: las exportaciones siguen saliendo, con el libro de
 *    siempre. Quitar la plantilla no rompe ninguna funcionalidad.
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import AnalisisPlantilla from '@/components/AnalisisPlantilla.vue'
import ColumnasExcel from '@/components/ColumnasExcel.vue'
import { bytesLegibles } from '@/utils/formato'

const cargando = ref(true)
const ocupado = ref(false)
const error = ref('')
const aviso = ref('')

const estado = ref({ tiene_plantilla: false, plantilla: null, hoja_de_datos: 'Datos' })
const seleccionado = ref(null)

const entrada = ref(null)

const hayPlantilla = computed(() => estado.value.tiene_plantilla)

const fecha = computed(() => {
  const cuando = estado.value.plantilla?.actualizado_en
  if (!cuando) return '—'
  return new Date(cuando).toLocaleString('es-EC', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
})

async function cargar() {
  cargando.value = true
  error.value = ''
  try {
    estado.value = await api.verPlantilla()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

function elegir(evento) {
  seleccionado.value = evento.target.files?.[0] || null
  error.value = ''
  aviso.value = ''
}

async function subir() {
  if (!seleccionado.value || ocupado.value) return

  ocupado.value = true
  error.value = ''
  aviso.value = ''
  try {
    const respuesta = await api.subirPlantilla(seleccionado.value)
    estado.value = { ...estado.value, tiene_plantilla: true, plantilla: respuesta.plantilla }
    aviso.value = `Plantilla actualizada con «${respuesta.plantilla.nombre_archivo}». Las exportaciones ya salen con tu diseño.`
    limpiarSeleccion()
  } catch (fallo) {
    // El servidor explica **qué** pasa con el archivo —tamaño, formato, macros—, así que su mensaje
    // se muestra tal cual: sustituirlo por uno genérico obligaría a adivinar el motivo.
    error.value = fallo.message
  } finally {
    ocupado.value = false
  }
}

async function quitar() {
  if (ocupado.value) return

  ocupado.value = true
  error.value = ''
  aviso.value = ''
  try {
    await api.quitarPlantilla()
    estado.value = { ...estado.value, tiene_plantilla: false, plantilla: null }
    aviso.value = 'Se quitó la plantilla. Las exportaciones vuelven al libro de siempre.'
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = false
  }
}

function limpiarSeleccion() {
  seleccionado.value = null
  if (entrada.value) entrada.value.value = ''
}

/**
 * Recoge lo que el servidor acabó guardando.
 *
 * Se toma de la respuesta y no de lo que se envió porque es el servidor quien decide: una lista
 * vacía significa «todas», y pintar lo que se mandó dejaría la pantalla diciendo algo distinto de
 * lo que van a llevar las exportaciones.
 */
function alGuardarColumnas(columnas) {
  estado.value = { ...estado.value, columnas_elegidas: columnas }
}

onMounted(cargar)
</script>

<template>
  <div class="plantilla__pila">
    <section class="tarjeta aparece">
      <header class="tarjeta__cabecera">
        <div>
          <p class="tarjeta__titulo">Plantilla de Excel</p>
          <p class="tarjeta__pista">
            El diseño con el que salen las exportaciones de tu empresa
          </p>
        </div>
      </header>

    <div class="tarjeta__cuerpo plantilla">
      <div v-if="cargando" class="tabla__cargando">
        <span class="esqueleto tabla__fila-esqueleto" />
      </div>

      <template v-else>
        <div v-if="hayPlantilla" class="plantilla__actual">
          <span class="plantilla__icono" aria-hidden="true">⬓</span>
          <div>
            <p class="plantilla__nombre">{{ estado.plantilla.nombre_archivo }}</p>
            <p class="plantilla__meta">
              {{ bytesLegibles(estado.plantilla.tamano_bytes) }} · subida el {{ fecha }}
            </p>
          </div>
        </div>
        <div v-else class="plantilla__vacia">
          <p>
            <strong>No hay ninguna plantilla subida.</strong>
            Las exportaciones salen con el libro genérico del sistema: una hoja por familia, con la
            cabecera que pone el sistema. Sube la tuya para que lleven tu logo y tus estilos.
          </p>
        </div>

        <ol class="plantilla__pasos">
          <li>
            Prepara un libro de Excel con <strong>los títulos de tus columnas</strong> en la fila que
            quieras, entre las diez primeras. Los datos se escriben debajo de cada título, y las
            columnas pueden ir en el orden que tú decidas.
          </li>
          <li>
            Si quieres que las ínfimas cuantías y las ofertas vayan a hojas distintas, dedica una a
            cada familia con un nombre que empiece por <code>ÍNFIMAS</code> y <code>OFERTAS</code>.
            Si no, todo entra en la hoja <code>{{ estado.hoja_de_datos }}</code> —la primera del
            libro, si no existe— con un rótulo delante de cada familia.
          </li>
          <li>
            Deja el resto del libro como quieras: portada, logo, otras hojas. Lo que hay
            <strong>por encima</strong> de tus títulos no se toca; lo de debajo se reemplaza en
            cada descarga.
          </li>
          <li>Guarda el archivo como <strong>Libro de Excel (.xlsx)</strong>, sin macros, y súbelo.</li>
        </ol>

        <div class="plantilla__acciones">
          <input
            ref="entrada"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            class="plantilla__entrada"
            :disabled="ocupado"
            @change="elegir"
          />
          <button
            type="button"
            class="boton boton--secundario boton--pequeno"
            :disabled="!seleccionado || ocupado"
            @click="subir"
          >
            <span v-if="ocupado" class="girador" aria-hidden="true" />
            {{ hayPlantilla ? 'Reemplazar la plantilla' : 'Subir la plantilla' }}
          </button>
          <button
            v-if="hayPlantilla"
            type="button"
            class="boton boton--fantasma boton--pequeno"
            :disabled="ocupado"
            @click="quitar"
          >
            Quitar
          </button>
        </div>

        <p class="plantilla__nota">
          Los datos se escriben <strong>debajo de tus títulos</strong>: los que el sistema no
          reconozca se quedan como estén, y si no reconoce ninguno escribe su propia cabecera al
          final para no poner un dato bajo un título que no le corresponde. Pulsa «Comprobar mi
          plantilla» para ver qué se reconoce antes de descargar nada.
        </p>

        <p v-if="error" class="tabla__error" role="alert">{{ error }}</p>
        <p v-else-if="aviso" class="tabla__exportacion" role="status">{{ aviso }}</p>
      </template>
    </div>
    </section>

    <ColumnasExcel
      :catalogo="estado.columnas_disponibles || []"
      :elegidas="estado.columnas_elegidas"
      @guardado="alGuardarColumnas"
    />

    <AnalisisPlantilla :catalogo="estado.columnas_disponibles || []" />
  </div>
</template>

<style scoped>
.plantilla__pila {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.plantilla {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  max-width: 62ch;
}

.plantilla__actual {
  display: flex;
  align-items: center;
  gap: 0.85rem;
}

.plantilla__icono {
  font-size: 1.6rem;
  line-height: 1;
  color: var(--acento, #2563eb);
}

.plantilla__nombre {
  margin: 0;
  font-weight: 600;
}

.plantilla__meta {
  margin: 0.15rem 0 0;
  font-size: 0.85rem;
  color: var(--texto-tenue, #6b7280);
}

.plantilla__vacia {
  padding: 0.85rem 1rem;
  border-radius: 0.6rem;
  border: 1px dashed var(--borde, #d1d5db);
}

.plantilla__vacia p {
  margin: 0;
}

.plantilla__pasos {
  margin: 0;
  padding-left: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.9rem;
}

.plantilla__pasos code {
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
  background: var(--superficie-tenue, #f3f4f6);
}

.plantilla__acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}

.plantilla__entrada {
  flex: 1 1 16rem;
  font-size: 0.85rem;
}

.plantilla__nota {
  margin: 0;
  font-size: 0.85rem;
  color: var(--texto-tenue, #6b7280);
}
</style>
