<script setup>
/**
 * Búsqueda por la **descripción del producto**.
 *
 * Qué se puede escribir aquí: una frase o unas palabras que se buscan en el **objeto de compra** de
 * cada necesidad, y solo ahí. Es lo que distingue este campo del de las palabras clave: allí el
 * término se busca en todo el texto de la convocatoria —el código, la entidad, la provincia, los
 * tipos de proceso—, así que aparece todo lo que lo menciona de pasada; aquí se responde a «qué se
 * está comprando». Quien busca «computadoras» quiere computadoras, no una capacitación sobre
 * computación.
 *
 * El modo —«todas» o «cualquiera»— **no se repite aquí**: es el mismo interruptor que el de las
 * palabras clave, y un segundo control para el mismo valor es la forma más fácil de que la pantalla
 * diga una cosa mientras la consulta hace otra. Con la lista vacía, el campo no filtra nada.
 *
 * Se añade de una en una o **pegando una lista**, como en el CPC y en las palabras clave: es el mismo
 * gesto porque es el mismo uso. Una lista de productos —«computadoras, impresoras, tóner»— se copia
 * de otro sitio, no se teclea palabra por palabra, y obligar a repetir el campo tres veces para tres
 * términos es trabajo de más.
 *
 * Lo que se añade queda en el **borrador**: se aplica con el botón de filtros, que además dice cuántos
 * cambios hay pendientes. No se consulta al teclear, y por eso este criterio sí se guarda en la caché
 * del servidor —a diferencia de la búsqueda libre—: describe lo que esa empresa compra siempre.
 */
import { computed, ref } from 'vue'

import { filtros } from '@/stores/filtros'
import { LONGITUD_MINIMA_TERMINO, terminosDeLista } from '@/utils/terminos'

// El mismo mínimo que aplican las palabras clave y que exige la fuente oficial para aceptar una
// búsqueda. El servidor lo comprueba por su cuenta; aquí solo se explica antes de pulsar.
const MINIMO = LONGITUD_MINIMA_TERMINO

const estado = filtros.estado
const texto = ref('')
const lote = ref('')
const mostrandoCampo = ref(false)
const mostrandoLote = ref(false)
const error = ref('')
const aviso = ref('')

const puedeAgregar = computed(() => texto.value.trim().length >= MINIMO)

/** Lo que se detecta en el recuadro, sin repetir y sin las de menos de tres letras. */
const delLote = computed(() => terminosDeLista(lote.value))

function agregar() {
  if (!puedeAgregar.value) return
  const limpio = texto.value.trim()
  const motivo = filtros.agregarDescripcion(limpio)

  if (motivo === 'corta') {
    error.value = `«${limpio}» tiene menos de ${MINIMO} letras.`
    return
  }
  if (motivo === 'repetida') {
    error.value = `«${limpio}» ya está en la lista.`
    return
  }
  error.value = ''
  texto.value = ''
}

/**
 * Añade la lista entera de una vez.
 *
 * El resumen dice lo que pasó de verdad —cuántas entraron, cuántas ya estaban y cuántas se
 * descartaron por cortas— en lugar de un «listo» que deja sin saber por qué la lista no tiene las
 * siete que se pegaron.
 *
 * El campo de una en una **se queda abierto** después de añadir, al contrario que en el CPC: allí
 * cada término viaja al servidor y cerrar el campo confirma que se guardó, y aquí la lista vive en el
 * borrador y lo normal es escribir dos o tres seguidos.
 */
function agregarLote() {
  if (!delLote.value.terminos.length) return
  const { agregadas, repetidas, cortas } = filtros.agregarVariasDescripcion(lote.value)
  aviso.value = [
    `${agregadas.length} ${agregadas.length === 1 ? 'descripción añadida' : 'descripciones añadidas'}.`,
    cortas ? `Se descartaron ${cortas} por tener menos de ${MINIMO} letras.` : '',
    repetidas ? `${repetidas} ya ${repetidas === 1 ? 'estaba' : 'estaban'} en la lista.` : '',
  ]
    .filter(Boolean)
    .join(' ')
  error.value = ''
  lote.value = ''
  mostrandoLote.value = false
}

function cancelarCampo() {
  mostrandoCampo.value = false
  texto.value = ''
  error.value = ''
}

function cancelarLote() {
  mostrandoLote.value = false
  lote.value = ''
  error.value = ''
}

function quitar(termino) {
  error.value = ''
  aviso.value = ''
  filtros.quitarDescripcion(termino)
}
</script>

<template>
  <div class="descripcion">
    <label class="campo__etiqueta" for="descripcion-producto">Descripción del producto</label>

    <p class="descripcion__ayuda">
      Busca en el <strong>objeto de compra</strong> —lo que la entidad dice que va a comprar— y no en
      el resto de la convocatoria. Sirve para lo mismo que una palabra clave, pero sin traer lo que
      solo menciona el término de pasada.
      {{
        estado.modo === 'todas'
          ? ' Con «Todas» se exigen todas las palabras de la frase.'
          : ' Con «Cualquiera» basta con que aparezca alguna palabra de la frase.'
      }}
    </p>

    <form v-if="mostrandoCampo" class="descripcion__nueva" @submit.prevent="agregar">
      <label class="solo-lectores" for="descripcion-producto">Descripción del producto</label>
      <input
        id="descripcion-producto"
        v-model="texto"
        class="entrada"
        type="text"
        autofocus
        :placeholder="`equipo de computo, sillas… (mínimo ${MINIMO} letras)`"
        @keydown.esc="cancelarCampo"
      />
      <div class="descripcion__acciones">
        <button
          type="submit"
          class="boton boton--principal boton--pequeno"
          :disabled="!puedeAgregar"
        >
          Añadir
        </button>
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="cancelarCampo">
          Cancelar
        </button>
      </div>
    </form>

    <!--
      El recuadro para pegar una lista. El contador dice cuántos términos se van a añadir antes de
      pulsar, para que el resultado no sorprenda, y avisa de los que se descartan por cortos.
    -->
    <form v-else-if="mostrandoLote" class="descripcion__nueva" @submit.prevent="agregarLote">
      <label class="campo__etiqueta" for="lote-descripcion">Descripciones separadas por comas</label>
      <textarea
        id="lote-descripcion"
        v-model="lote"
        class="entrada descripcion__lote"
        rows="4"
        autofocus
        placeholder="equipo de computo, sillas, papel bond…"
        @keydown.esc="cancelarLote"
      />
      <p class="descripcion__ayuda">
        Se separan por comas, punto y coma o saltos de línea.
        <template v-if="delLote.terminos.length">
          Se van a añadir <strong class="numeros">{{ delLote.terminos.length }}</strong>
          {{ delLote.terminos.length === 1 ? 'descripción' : 'descripciones' }}.
        </template>
        <template v-if="delLote.cortas">
          Se descartarán {{ delLote.cortas }} por tener menos de {{ MINIMO }} letras.
        </template>
      </p>
      <div class="descripcion__acciones">
        <button
          type="submit"
          class="boton boton--principal boton--pequeno"
          :disabled="!delLote.terminos.length"
        >
          {{ delLote.terminos.length ? `Añadir ${delLote.terminos.length}` : 'Añadir' }}
        </button>
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="cancelarLote">
          Cancelar
        </button>
      </div>
    </form>

    <div v-else class="descripcion__acciones">
      <button
        type="button"
        class="boton boton--secundario boton--pequeno"
        @click="mostrandoCampo = true"
      >
        <span aria-hidden="true">＋</span> Añadir
      </button>
      <button
        type="button"
        class="boton boton--secundario boton--pequeno"
        @click="mostrandoLote = true"
      >
        <span aria-hidden="true">≡</span> Pegar una lista
      </button>
    </div>

    <ul v-if="estado.descripcion.length" class="descripcion__lista">
      <li v-for="termino in estado.descripcion" :key="termino">
        <button
          type="button"
          class="descripcion__chip"
          :aria-label="`Quitar ${termino} de la descripción`"
          @click="quitar(termino)"
        >
          <span class="descripcion__chip-texto">{{ termino }}</span>
          <span aria-hidden="true">✕</span>
        </button>
      </li>
    </ul>

    <p v-else class="descripcion__vacio">
      Sin descripción: el filtro no está en uso.
    </p>

    <p v-if="estado.descripcion.length && estado.modo === 'todas'" class="descripcion__ayuda">
      Con «Todas», la necesidad tiene que mencionar
      <strong>todas las palabras</strong> de la frase en su objeto de compra. Si la búsqueda no
      devuelve nada, prueba a quitarlas para dejar una sola.
    </p>

    <p v-if="error" class="descripcion__error" role="alert">{{ error }}</p>
    <p v-else-if="aviso" class="descripcion__aviso" role="status">{{ aviso }}</p>
  </div>
</template>

<style scoped>
.descripcion {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.descripcion__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.descripcion__nueva {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.descripcion__nueva .entrada {
  flex: 1 1 auto;
  min-width: 0;
}

/*
 * Las acciones envuelven en lugar de desbordar: dos botones en una columna de 300 píxeles caben
 * justos, y cuando no caben se apilan en vez de empujar el ancho del panel —que es lo que hacía
 * aparecer la barra horizontal de la columna de filtros—.
 */
.descripcion__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

/* Cada botón mide lo que mide su texto, para que envuelva en lugar de empujar el ancho. */
.descripcion__acciones .boton {
  min-width: max-content;
}

.descripcion__lote {
  resize: vertical;
  min-height: 5rem;
  font-family: inherit;
}

.descripcion__lista {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  list-style: none;
  padding: 0;
  margin: var(--e-1) 0;
}

/* Las mismas fichas que las palabras clave y el CPC: es la misma idea y se lee igual. */
.descripcion__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.3rem 0.6rem;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-sm);
  color: var(--texto-suave);
  cursor: pointer;
  transition:
    background-color var(--rapido) var(--curva),
    border-color var(--rapido) var(--curva),
    color var(--rapido) var(--curva);
}

.descripcion__chip:hover {
  border-color: var(--acento);
  color: var(--texto);
}

.descripcion__chip-texto {
  font-weight: 550;
}

.descripcion__vacio {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.descripcion__error {
  font-size: var(--t-xs);
  color: var(--error);
}

.descripcion__aviso {
  font-size: var(--t-xs);
  color: var(--ok);
  line-height: 1.45;
}
</style>
