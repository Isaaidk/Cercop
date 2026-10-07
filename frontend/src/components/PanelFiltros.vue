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
 */
import { computed } from 'vue'

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
    <div class="filtros__bloque">
      <GestorPalabrasClave />
    </div>

    <!--
      Búsqueda por CPC: el mismo gestor que las palabras clave, pero en la clasificación.

      Va pegado a ellas porque se usan juntas, y va separado porque no son lo mismo: una palabra
      clave es una suscripción que el worker va a buscar al SERCOP, y un término de CPC es solo un
      criterio sobre lo que ya está ingestado. El componente lo explica en pantalla.
    -->
    <div class="filtros__bloque">
      <GestorPalabrasCpc />
    </div>

    <!--
      La descripción del producto, debajo del CPC y por el mismo motivo: son los tres sitios donde se
      escribe qué se busca, y se usan juntos.

      Va después del CPC porque es lo más fino de los tres: las palabras clave buscan en toda la
      convocatoria, el CPC en la clasificación normalizada y esto solo en el objeto de compra. De
      arriba abajo, cada uno acota más.
    -->
    <div class="filtros__bloque">
      <GestorDescripcionProducto />
    </div>

    <hr class="separador" />

    <!--
      La provincia se elige aquí o pulsando el mapa: los dos caminos escriben el mismo filtro. Antes
      solo existía el mapa, así que quien no lo usara no podía acotar por provincia.

      Se elige con **casillas** y no con un desplegable que añade y fichas que quitan: la pregunta es
      «¿en qué provincias?», y con veinticuatro opciones una lista de casillas se lee de un vistazo
      —se ve lo que está marcado y lo que no sin abrir nada— mientras que el desplegable obligaba a
      abrirlo una vez por provincia. Lo que no cambia es la lógica: el filtro sigue siendo la
      **lista** de provincias y la lista vacía no filtra, igual que en el mapa.
    -->
    <div class="filtros__bloque">
      <SelectorProvincias
        :seleccionadas="estado.provincias"
        @cambiar="filtros.fijarProvincias"
      />

      <!-- El cantón solo se puede elegir en el mapa: aquí aparece como ficha para poder quitarlo. -->
      <div v-if="estado.canton" class="filtros__fichas">
        <button
          type="button"
          class="ficha"
          :aria-label="`Quitar el filtro del cantón ${estado.canton}`"
          @click="filtros.elegirCanton(estado.canton)"
        >
          <span class="ficha__ciudad" aria-hidden="true">▣</span>
          {{ estado.canton }}
          <span class="ficha__quitar" aria-hidden="true">✕</span>
        </button>
      </div>
    </div>

    <hr class="separador" />

    <!--
      Búsqueda por NIC: el código que identifica una necesidad de contratación —el
      «NIC-1768120280001-2022-00003» de la ficha—. Es el mismo criterio `codigo` del servidor que ya
      usaba el listado de ofertas; aquí se nombra como lo llama quien tiene la ficha delante, que es
      el NIC de la ínfima cuantía.

      Se compara por fragmento y no por igualdad a propósito: el código se copia del portal, pero
      casi nadie lo recuerda entero, y buscar por los últimos dígitos o por el año es lo que se hace
      de verdad. Vive con los demás criterios y por eso pasa por el botón de aplicar.
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
      <p class="filtros__ayuda">
        Vale un fragmento: el año, los últimos dígitos. Déjalo vacío para no filtrar por código.
      </p>
    </div>

    <hr class="separador" />

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
    </div>

    <hr class="separador" />

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

    <hr class="separador" />

    <div class="filtros__bloque">
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

      <!--
        Se filtra en el servidor y no aquí: la tabla está paginada, así que esconder lo vencido de la
        página visible dejaría las siguientes llenas de filas sin plazo y los totales dirían otra cosa.
      -->
      <button
        type="button"
        class="boton boton--secundario boton--pequeno filtros__plazo"
        :aria-pressed="estado.soloConPlazo"
        @click="filtros.actualizar({ soloConPlazo: !estado.soloConPlazo })"
      >
        <span aria-hidden="true">{{ estado.soloConPlazo ? '◉' : '○' }}</span>
        {{ estado.soloConPlazo ? 'Viendo solo las que admiten proformas' : 'Ocultar las de plazo vencido' }}
      </button>
    </div>

    <hr class="separador" />

    <div class="filtros__bloque">
      <p class="campo__etiqueta">Tamaño de página</p>
      <select
        class="seleccion"
        :value="estado.tamano"
        @change="filtros.cambiarTamano(Number($event.target.value))"
      >
        <option :value="25">25 por página</option>
        <option :value="50">50 por página</option>
        <option :value="100">100 por página</option>
      </select>
    </div>

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
  gap: var(--e-4);
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
  border-color: var(--acento);
  background: var(--acento-suave);
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
</style>
