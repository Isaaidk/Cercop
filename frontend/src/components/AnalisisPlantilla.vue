<script setup>
/**
 * Dónde van a entrar los datos en la plantilla de la empresa.
 *
 * Existe porque el reparto no se puede deducir mirando el archivo: el sistema busca en cada hoja su
 * fila de títulos —que no tiene por qué ser la primera—, coloca cada dato bajo **su** columna y
 * manda cada familia a la hoja que la empresa le dedicó. Cuando alguien pregunta «¿por qué mis datos
 * no caen donde esperaba?», la respuesta está siempre en el archivo, y esto la enseña.
 *
 * Se calcula **a petición**: abrir el libro entero cada vez que se entra en la pestaña haría lenta
 * una pantalla que casi siempre se mira para ver una fecha.
 */
import { computed, ref } from 'vue'

import { api } from '@/api/endpoints'

const props = defineProps({
  /** Para poner el nombre de la columna y no su clave interna. */
  catalogo: { type: Array, default: () => [] },
})

const informe = ref(null)
const analizando = ref(false)
const error = ref('')

/** Clave interna → nombre que se lee en la pantalla. */
const etiquetas = computed(() => {
  const mapa = {}
  for (const grupo of props.catalogo) {
    for (const columna of grupo.columnas) mapa[columna.clave] = columna.etiqueta
  }
  return mapa
})

/**
 * Columnas que no están en el catálogo porque no son de la fuente.
 *
 * `ubicacion` la compone el sistema con la provincia y el cantón, y solo existe cuando la plantilla
 * la pide en una sola columna. Sin este nombre, el informe enseñaría la clave interna y parecería
 * un error de la aplicación.
 */
const COLUMNAS_DE_PLANTILLA = { ubicacion: 'Provincia · cantón' }

const FAMILIAS = { infimas: 'Ínfimas cuantías', ofertas: 'Ofertas' }

function nombreDeColumna(clave) {
  return etiquetas.value[clave] || COLUMNAS_DE_PLANTILLA[clave] || clave
}

function nombreDeFamilia(clave) {
  return FAMILIAS[clave] || clave
}

async function analizar() {
  if (analizando.value) return

  analizando.value = true
  error.value = ''
  try {
    informe.value = await api.analizarPlantilla()
  } catch (fallo) {
    error.value = fallo.message
    informe.value = null
  } finally {
    analizando.value = false
  }
}
</script>

<template>
  <section class="tarjeta aparece">
    <header class="tarjeta__cabecera">
      <div>
        <p class="tarjeta__titulo">Dónde entran los datos</p>
        <p class="tarjeta__pista">
          Comprueba qué hojas de tu plantilla reciben la información y bajo qué títulos
        </p>
      </div>
    </header>

    <div class="tarjeta__cuerpo analisis">
      <div class="analisis__acciones">
        <button
          type="button"
          class="boton boton--secundario boton--pequeno"
          :disabled="analizando"
          @click="analizar"
        >
          <span v-if="analizando" class="girador" aria-hidden="true" />
          {{ analizando ? 'Leyendo la plantilla…' : 'Comprobar mi plantilla' }}
        </button>
        <span class="analisis__nota">Se lee el archivo, no se modifica nada.</span>
      </div>

      <p v-if="error" class="tabla__error" role="alert">{{ error }}</p>

      <template v-else-if="informe">
        <p v-if="!informe.hay_plantilla" class="analisis__vacio">
          No hay ninguna plantilla subida: las exportaciones salen con el libro del sistema, con una
          hoja por familia.
        </p>

        <template v-else>
          <p class="analisis__resumen">
            Los datos de <strong>ínfimas cuantías</strong> entran en la hoja
            <code>{{ informe.destinos.infimas }}</code> y los de <strong>ofertas</strong> en
            <code>{{ informe.destinos.ofertas }}</code>.
          </p>

          <p v-if="informe.familias_sin_hoja_propia.length" class="analisis__aviso" role="status">
            Tu plantilla no tiene una hoja propia para
            <strong>{{ informe.familias_sin_hoja_propia.map(nombreDeFamilia).join(' ni ') }}</strong
            >, así que esos datos van a la hoja de datos con su rótulo delante. Para separarlos,
            añade una hoja cuyo nombre empiece por <code>ÍNFIMAS</code> o <code>OFERTAS</code> y
            vuelve a subir la plantilla.
          </p>

          <div class="analisis__tabla">
            <table>
              <thead>
                <tr>
                  <th scope="col">Hoja</th>
                  <th scope="col">Recibe</th>
                  <th scope="col">Títulos en la fila</th>
                  <th scope="col">Datos desde la fila</th>
                  <th scope="col">Columnas que reconoces</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="hoja in informe.hojas" :key="hoja.hoja">
                  <td>
                    <code>{{ hoja.hoja }}</code>
                  </td>
                  <td>
                    <template v-if="hoja.recibe.length">
                      {{ hoja.recibe.map(nombreDeFamilia).join(' y ') }}
                    </template>
                    <span v-else class="analisis__tenue">nada</span>
                  </td>
                  <td>
                    <template v-if="hoja.fila_de_encabezado">
                      {{ hoja.fila_de_encabezado }}
                    </template>
                    <span v-else class="analisis__tenue">no se reconocen</span>
                  </td>
                  <td>{{ hoja.primera_fila_de_datos }}</td>
                  <td>
                    <template v-if="hoja.columnas_reconocidas.length">
                      {{ hoja.columnas_reconocidas.map((c) => nombreDeColumna(c.clave)).join(', ') }}
                    </template>
                    <span v-else class="analisis__tenue">
                      ninguna: se escribirá la cabecera del sistema
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>

<style scoped>
.analisis {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.analisis__acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
}

.analisis__nota,
.analisis__tenue {
  font-size: 0.85rem;
  color: var(--texto-tenue, #6b7280);
}

.analisis__resumen,
.analisis__aviso,
.analisis__vacio {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.5;
}

.analisis__aviso {
  padding: 0.7rem 0.9rem;
  border-radius: 0.6rem;
  border: 1px dashed var(--aviso, #b45309);
  color: var(--aviso, #b45309);
}

.analisis__vacio {
  color: var(--texto-tenue, #6b7280);
}

.analisis__tabla {
  overflow-x: auto;
}

.analisis__tabla table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.analisis__tabla th,
.analisis__tabla td {
  padding: 0.45rem 0.6rem;
  text-align: left;
  vertical-align: top;
  border-bottom: 1px solid var(--borde, #e5e7eb);
}

.analisis__tabla th {
  font-size: 0.72rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--texto-tenue, #6b7280);
}

.analisis__tabla code,
.analisis__resumen code {
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
  background: var(--superficie-tenue, #f3f4f6);
}
</style>
