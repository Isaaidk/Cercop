<script setup>
/**
 * Panel lateral de filtros.
 *
 * Contiene lo que se puede acotar: palabras clave, provincia, estado, fechas y orden. Todo lo que se
 * cambia aquí afecta a la vez a la tabla, a las gráficas y al mapa, porque los tres leen los mismos
 * filtros del almacén. Ese es el motivo de que los filtros no vivan en cada componente.
 *
 * La provincia se puede elegir aquí **o** pulsando el mapa: los dos caminos escriben el mismo filtro.
 * Elegirla solo desde el mapa dejaba sin filtrar a quien no lo usara, que es la mayoría en escritorio.
 * El cantón, que solo se puede elegir en el mapa, sigue apareciendo como ficha quitadera.
 *
 * Rediseño 2026-11: a la vista solo lo que se usa todos los días —qué busco, en qué provincia y si
 * aún admite proformas—; el CPC, la descripción, el NIC, la fuente, las fechas, el orden y el tamaño
 * de página van en «Más filtros», que se abre solo si alguno de ellos está puesto. Así quien llega
 * por primera vez ve tres preguntas y no once controles, y quien ya filtró por CPC no lo pierde.
 */
import { computed, ref, watch } from 'vue'

import GestorPalabrasClave from '@/components/GestorPalabrasClave.vue'
import GestorPalabrasCpc from '@/components/GestorPalabrasCpc.vue'
import GestorDescripcionProducto from '@/components/GestorDescripcionProducto.vue'
import SelectorProvincias from '@/components/SelectorProvincias.vue'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { numero } from '@/utils/formato'

const estado = filtros.estado

/** Los estados que existen de verdad en los datos, no una lista inventada. */
const estados = computed(() => datos.estado.catalogos.estado || [])
const fuentes = computed(() => datos.estado.catalogos.fuente || [])

function limpiarFecha(campo) {
  filtros.actualizar({ [campo]: null })
}

/**
 * Texto del botón de aplicar.
 *
 * Dice **cuántos** cambios hay pendientes en lugar de un «Aplicar» seco, porque un botón que a veces no
 * hace nada parece roto. Con el número, se entiende que hay algo esperando y cuánto es.
 */
const etiquetaAplicar = computed(() => {
  const pendientes = filtros.pendientes.value
  if (!pendientes) return 'Filtros aplicados'
  return pendientes === 1 ? 'Aplicar 1 cambio' : `Aplicar ${pendientes} cambios`
})

/**
 * Cuántos de los filtros de «Más filtros» están puestos.
 *
 * Sirve para dos cosas: abrir el grupo si hay alguno —un filtro activo escondido es un filtro que
 * nadie entiende por qué no devuelve nada— y decir el número en el propio título del grupo.
 */
const masFiltrosActivos = computed(
  () =>
    [
      estado.cpc?.length,
      estado.descripcion?.length,
      estado.codigo,
      estado.fuente,
      estado.desde || estado.hasta,
      estado.soloNuevos,
      estado.orden && estado.orden !== 'recientes',
    ].filter(Boolean).length,
)

/**
 * Si «Más filtros» está desplegado. Se abre solo cuando aparece un filtro suyo —por ejemplo, al
 * cargar una búsqueda guardada con CPC— pero **nunca se cierra solo**: si se cerrara al quitar el
 * último término, el grupo se plegaría en la cara de quien lo está editando.
 */
const masAbierto = ref(masFiltrosActivos.value > 0)
watch(masFiltrosActivos, (cuantos) => {
  if (cuantos > 0) masAbierto.value = true
})

const pistaAplicar = computed(() =>
  filtros.hayCambiosSinAplicar.value
    ? 'La tabla, las gráficas y el mapa se actualizan al aplicar.'
    : 'Lo que ves corresponde a los filtros puestos.',
)
</script>

<template>
  <aside class="filtros" aria-label="Filtros de búsqueda">
    <!--
      La barra de aplicar, arriba del todo del panel de filtros y siempre a la vista.

      Es la pieza que cambia el comportamiento del panel entero: hasta ahora, cada gesto sobre un
      control lanzaba una consulta, y las gráficas y el mapa se rehacían en cada una. Marcar veinte
      palabras clave eran veinte recargas seguidas y la pantalla no daba tiempo a leerla.

      Ahora los controles escriben en un borrador y esto es lo único que consulta. Se coloca arriba y
      no al final para que esté a la vista después de escribir una fecha, que es cuando se busca.
    -->
    <div
      class="filtros__aplicar"
      :class="{ 'filtros__aplicar--pendiente': filtros.hayCambiosSinAplicar.value }"
    >
      <button
        type="button"
        class="boton filtros__aplicar-boton"
        :class="filtros.hayCambiosSinAplicar.value ? 'boton--principal' : 'boton--secundario'"
        :disabled="!filtros.hayCambiosSinAplicar.value"
        @click="filtros.aplicar()"
      >
        {{ etiquetaAplicar }}
      </button>
      <p class="filtros__aplicar-pista" role="status">{{ pistaAplicar }}</p>
    </div>
    <!-- 1. Qué busco: las palabras clave. Es el filtro de todos los días. -->
    <details class="grupo" open>
      <summary>Buscar</summary>
      <div class="filtros__bloque">
        <GestorPalabrasClave />
      </div>
    </details>

    <!--
      2. Dónde. La provincia se elige aquí o pulsando el mapa: los dos caminos escriben el mismo
      filtro. Antes solo existía el mapa, así que quien no lo usara no podía acotar por provincia.

      Se elige con **casillas** y no con un desplegable: con veinticuatro opciones una lista de
      casillas se lee de un vistazo —se ve lo que está marcado y lo que no sin abrir nada—. El filtro
      sigue siendo la **lista** de provincias y la lista vacía no filtra, igual que en el mapa.
    -->
    <details class="grupo" open>
      <summary>
        Provincia
        <span v-if="estado.provincias.length" class="grupo__cuenta">{{ estado.provincias.length }}</span>
      </summary>
      <div class="filtros__bloque">
        <SelectorProvincias
          :seleccionadas="estado.provincias"
          @cambiar="filtros.fijarProvincias"
        />
      </div>
    </details>

    <!-- 3. Estado y plazo: si la contratación sigue viva y si todavía admite proformas. -->
    <details class="grupo" open>
      <summary>Estado y plazo</summary>
      <div class="filtros__bloque">
        <label class="campo">
          <span class="campo__etiqueta">Estado de la contratación</span>
          <select
            class="seleccion"
            :value="estado.estadoRegistro || ''"
            @change="filtros.actualizar({ estadoRegistro: $event.target.value || null })"
          >
            <option value="">Todos los estados</option>
            <option v-for="valor in estados" :key="valor" :value="valor">{{ valor }}</option>
          </select>
        </label>

        <!--
          Se filtra en el servidor y no aquí: la tabla está paginada, así que esconder lo vencido de
          la página visible dejaría las siguientes llenas de filas sin plazo y los totales dirían otra
          cosa.
        -->
        <label class="interruptor">
          <input
            type="checkbox"
            :checked="estado.soloConPlazo"
            class="interruptor__control"
            @change="filtros.actualizar({ soloConPlazo: $event.target.checked })"
          />
          <span class="interruptor__pista">Solo las que aún admiten proformas</span>
        </label>
      </div>
    </details>

    <!-- 4. Todo lo demás, plegado. Se abre solo si alguno de sus filtros está puesto. -->
    <details class="grupo" :open="masAbierto" @toggle="masAbierto = $event.target.open">
      <summary>
        Más filtros
        <span v-if="masFiltrosActivos" class="grupo__cuenta">{{ masFiltrosActivos }}</span>
      </summary>

      <!--
        Búsqueda por CPC: el mismo gestor que las palabras clave, pero en la clasificación. Una
        palabra clave es una suscripción que el worker va a buscar al SERCOP, y un término de CPC es
        solo un criterio sobre lo que ya está ingestado. El componente lo explica en pantalla.
      -->
      <div class="filtros__bloque">
        <GestorPalabrasCpc />
      </div>

      <!--
        La descripción del producto: lo más fino de los tres buscadores. Las palabras clave buscan en
        toda la convocatoria, el CPC en la clasificación normalizada y esto solo en el objeto.
      -->
      <div class="filtros__bloque">
        <GestorDescripcionProducto />
      </div>

      <!--
        Búsqueda por NIC: el código que identifica una necesidad de contratación —el
        «NIC-1768120280001-2022-00003» de la ficha—. Se compara por fragmento y no por igualdad a
        propósito: casi nadie recuerda el código entero, y buscar por los últimos dígitos o por el año
        es lo que se hace de verdad.
      -->
      <div class="filtros__bloque">
        <label class="campo">
          <span class="campo__etiqueta">NIC de la ínfima cuantía</span>
          <input
            class="entrada"
            type="search"
            placeholder="NIC-1768120280001-2022-00003"
            :value="estado.codigo || ''"
            @input="filtros.actualizar({ codigo: $event.target.value || null })"
          />
        </label>
        <p class="filtros__ayuda">Vale un fragmento: el año o los últimos dígitos.</p>
      </div>

      <div class="filtros__bloque">
        <p class="campo__etiqueta">Fecha de publicación</p>
        <div class="filtros__fechas">
          <label class="campo">
            <span class="filtros__fecha-etiqueta">Desde</span>
            <input
              class="entrada"
              type="date"
              :value="estado.desde || ''"
              @change="filtros.actualizar({ desde: $event.target.value || null })"
            />
          </label>
          <label class="campo">
            <span class="filtros__fecha-etiqueta">Hasta</span>
            <input
              class="entrada"
              type="date"
              :value="estado.hasta || ''"
              @change="filtros.actualizar({ hasta: $event.target.value || null })"
            />
          </label>
        </div>
        <div v-if="estado.desde || estado.hasta" class="filtros__fechas-acciones">
          <button type="button" class="boton boton--fantasma boton--pequeno" @click="limpiarFecha('desde'); limpiarFecha('hasta')">
            Quitar las fechas
          </button>
        </div>
      </div>

      <div class="filtros__bloque">
        <label class="campo">
          <span class="campo__etiqueta">Fuente</span>
          <select
            class="seleccion"
            :value="estado.fuente || ''"
            @change="filtros.elegirFuente($event.target.value || null)"
          >
            <option value="">Todas las fuentes</option>
            <option v-for="valor in fuentes" :key="valor" :value="valor">{{ valor }}</option>
          </select>
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Ordenar por</span>
          <select
            class="seleccion"
            :value="estado.orden"
            @change="filtros.actualizar({ orden: $event.target.value })"
          >
            <option value="recientes">Más recientes primero</option>
            <option value="antiguos">Más antiguas primero</option>
            <option value="nuevos">Detectadas hace poco</option>
          </select>
        </label>

        <label class="interruptor">
          <input
            type="checkbox"
            :checked="estado.soloNuevos"
            class="interruptor__control"
            @change="filtros.actualizar({ soloNuevos: $event.target.checked })"
          />
          <span class="interruptor__pista">Solo lo detectado en la última ingesta</span>
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Tamaño de página</span>
          <select
            class="seleccion"
            :value="estado.tamano"
            @change="filtros.cambiarTamano(Number($event.target.value))"
          >
            <option :value="25">25 por página</option>
            <option :value="50">50 por página</option>
            <option :value="100">100 por página</option>
          </select>
        </label>
      </div>
    </details>

    <div v-if="filtros.hayFiltros.value" class="filtros__resumen">
      <p>
        <strong class="numeros">{{ numero(datos.estado.total) }}</strong>
        contrataciones con los filtros puestos
      </p>
      <button type="button" class="boton boton--secundario boton--pequeno" @click="filtros.limpiarTodo()">
        Limpiar todos los filtros
      </button>
    </div>
  </aside>
</template>

<style scoped>
.filtros {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

/*
 * La barra de aplicar.
 *
 * Se queda pegada arriba al desplazar la columna de filtros: si se fuera con el resto, después de
 * bajar hasta las fechas habría que volver a subir para aplicarlas, que es justo el momento en que
 * se necesita.
 */
.filtros__aplicar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  padding: var(--e-2);
  margin: calc(var(--e-2) * -1);
  border: 1px solid transparent;
  border-radius: var(--r-2);
  background: var(--superficie);
  transition: border-color var(--rapido) var(--curva), background-color var(--rapido) var(--curva);
}

/* Solo se enmarca cuando hay algo que aplicar: si estuviera siempre destacada, dejaría de avisar. */
.filtros__aplicar--pendiente {
  border-color: var(--acento-suave);
  background: var(--acento-tenue);
}

.filtros__aplicar-boton {
  width: 100%;
}

.filtros__aplicar-pista {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.4;
}

.filtros__bloque {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.filtros__fichas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.ficha {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.3rem 0.55rem;
  border: 1px solid var(--acento);
  border-radius: var(--r-redondo);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  font-size: var(--t-sm);
  font-weight: 600;
  cursor: pointer;
  transition: background-color var(--rapido) var(--curva);
}

.ficha:hover {
  background: var(--acento-suave);
}

.ficha__quitar {
  font-size: 0.85em;
  opacity: 0.7;
}

.filtros__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.filtros__fechas {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-2);
}

.filtros__fecha-etiqueta {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.filtros__fechas-acciones {
  display: flex;
}

.interruptor {
  display: flex;
  align-items: flex-start;
  gap: var(--e-2);
  cursor: pointer;
}

.interruptor__control {
  margin-top: 3px;
  accent-color: var(--acento);
  width: 16px;
  height: 16px;
  flex: none;
}

.interruptor__pista {
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.filtros__resumen {
  margin-top: var(--e-2);
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-3);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  border: 1px solid var(--borde);
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.filtros__resumen strong {
  color: var(--texto);
  font-size: var(--t-md);
}

@media (max-width: 639px) {
  .filtros__fechas {
    grid-template-columns: 1fr;
  }
}

/* Grupos plegables: «Buscar», «Provincia», «Estado y plazo» y «Más filtros». Lo que se usa todos
   los días está abierto; se separan con una raya fina y espacio, no con cajas dentro de la caja. */
.grupo {
  border-top: 1px solid var(--borde);
}
.grupo > summary {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: var(--e-3) 0;
  font-size: var(--t-sm);
  font-weight: 700;
  cursor: pointer;
  list-style: none;
}
.grupo > summary::-webkit-details-marker { display: none; }
.grupo > summary::after { content: '▾'; margin-left: auto; color: var(--texto-tenue); transition: transform var(--rapido); }
.grupo:not([open]) > summary::after { transform: rotate(-90deg); }
.grupo > .filtros__bloque { padding: 0 0 var(--e-4); }
.grupo > .filtros__bloque + .filtros__bloque { padding-top: var(--e-2); }
.grupo .separador { display: none; }
.grupo__cuenta { padding: 0 0.45rem; border-radius: var(--r-redondo); background: var(--acento-suave); color: var(--acento-fuerte); font-size: var(--t-xs); }
</style>
