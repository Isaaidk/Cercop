<script setup>
/**
 * Búsqueda por CPC: añadir términos de uno en uno o pegando una lista.
 *
 * Es el mismo gesto que el gestor de palabras clave —individual, en bloque, y quitar— porque es el
 * mismo uso: una lista de clasificaciones se copia de otro sitio, no se teclea veinte veces. Pero
 * hay una diferencia que conviene tener clara al leerlo: **esto no llama a nadie**.
 *
 * Una palabra clave es una suscripción: se guarda en el catálogo del negocio y el worker la busca
 * en el SERCOP. Un término de CPC es solo un criterio de búsqueda sobre lo que ya está ingestado, así
 * que no hay catálogo, ni ingesta, ni espera: la lista entra de golpe y el filtro se aplica al pulsar
 * «Aplicar», como cualquier otro criterio.
 *
 * El modo —«todas» o «cualquiera»— **no se repite aquí**. Es el mismo interruptor que el de las
 * palabras clave, y un segundo control para el mismo valor es la forma más fácil de que la pantalla
 * diga una cosa mientras la consulta hace otra.
 */
import { computed, ref } from 'vue'

import { filtros } from '@/stores/filtros'
import { LONGITUD_MINIMA_TERMINO, terminosDeLista } from '@/utils/terminos'

const estado = filtros.estado

const nuevo = ref('')
const lote = ref('')
const mostrandoCampo = ref(false)
const mostrandoLote = ref(false)
const error = ref('')
const aviso = ref('')
const guardando = ref(false)

const puedeAgregar = computed(() => nuevo.value.trim().length >= LONGITUD_MINIMA_TERMINO)

/**
 * «Todas» con más de una clasificación solo puede devolver cero.
 *
 * El modo exige que el CPC de un registro contenga **todos** los términos a la vez, y las
 * clasificaciones de esta lista son alternativas —«evento», «produccion», «962200561»—: ninguna
 * necesidad está clasificada en varias a la vez. La tabla queda vacía y lo que se lee es que el
 * filtro está roto. Se avisa antes de pulsar, en lugar de dejar que se descubra contando filas.
 */
const avisoModoTodas = computed(() => estado.modo === 'todas' && estado.cpc.length > 1)

/** Lo que se detecta en el recuadro, sin repetir y sin las de menos de tres letras. */
const delLote = computed(() => terminosDeLista(lote.value))

async function agregar() {
  if (!puedeAgregar.value || guardando.value) return
  const texto = nuevo.value.trim()
  guardando.value = true
  error.value = ''
  aviso.value = ''
  try {
    const resultado = await filtros.agregarCpc(texto)
    if (!resultado.agregado) {
      error.value =
        resultado.motivo === 'corta'
          ? `«${texto}» tiene menos de ${LONGITUD_MINIMA_TERMINO} letras.`
          : `«${texto}» ya está en la lista de CPC.`
      return
    }
    aviso.value = 'Término guardado. La tabla ya lo está buscando.'
    nuevo.value = ''
    mostrandoCampo.value = false
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    guardando.value = false
  }
}

async function agregarLote() {
  if (!delLote.value.terminos.length || guardando.value) return
  guardando.value = true
  error.value = ''
  aviso.value = ''
  try {
    const { agregadas, repetidas, cortas } = await filtros.agregarVariasCpc(lote.value)
    aviso.value = [
      `${agregadas.length} ${agregadas.length === 1 ? 'término guardado' : 'términos guardados'}.`,
      cortas ? `Se descartaron ${cortas} por tener menos de ${LONGITUD_MINIMA_TERMINO} letras.` : '',
      repetidas ? `${repetidas} ya ${repetidas === 1 ? 'estaba' : 'estaban'} en la lista.` : '',
      'La tabla ya los está buscando.',
    ]
      .filter(Boolean)
      .join(' ')
    lote.value = ''
    mostrandoLote.value = false
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    guardando.value = false
  }
}

function cancelarCampo() {
  mostrandoCampo.value = false
  nuevo.value = ''
  error.value = ''
}

function cancelarLote() {
  mostrandoLote.value = false
  lote.value = ''
  error.value = ''
}

/** Quitar un término lo borra de la lista guardada, no solo de la pantalla. */
async function quitar(texto) {
  error.value = ''
  try {
    await filtros.quitarCpc(texto)
  } catch (fallo) {
    error.value = fallo.message
  }
}

async function vaciar() {
  error.value = ''
  try {
    await filtros.limpiarCpc()
    aviso.value = ''
  } catch (fallo) {
    error.value = fallo.message
  }
}

async function usarPalabrasClave() {
  error.value = ''
  try {
    const resultado = await filtros.agregarVariasCpc(estado.seleccionadas.join(','))
    aviso.value = `${resultado.agregadas.length} ${resultado.agregadas.length === 1 ? 'término copiado' : 'términos copiados'} de las palabras clave marcadas. La tabla ya los está buscando.`
  } catch (fallo) {
    error.value = fallo.message
  }
}
</script>

<template>
  <div class="cpc">
    <p class="campo__etiqueta">Buscar por CPC</p>

    <p class="cpc__ayuda">
      Busca en el <strong>código y el nombre estándar</strong> del CPC de cada ítem, no en la
      descripción que escribe la entidad. Sirve para lo mismo que una palabra clave, pero sin traer
      lo que solo menciona el término de pasada.
      {{
        estado.modo === 'todas'
          ? ' Con «Todas» se exigen todos los términos añadidos aquí.'
          : ' Con «Cualquiera» basta con que aparezca uno de los términos añadidos aquí.'
      }}
    </p>

    <!--
      «Solo CPC»: con el interruptor activo, buscar por clasificación **no** exige además las palabras
      clave marcadas en el gestor de arriba.

      Es lo que quiere quien pega un código y espera ver todo lo clasificado así. Sin él, el servidor
      suma los dos criterios y las palabras clave de fondo recortan el resultado, de modo que el
      código parece no encontrar necesidades que sí existen.
    -->
    <label class="cpc__interruptor">
      <input
        type="checkbox"
        class="cpc__interruptor-control"
        :checked="estado.cpcSolo"
        @change="filtros.actualizar({ cpcSolo: $event.target.checked })"
      />
      <span>
        Buscar <strong>solo por CPC</strong>, sin exigir además las palabras clave marcadas.
      </span>
    </label>

    <p v-if="estado.cpcSolo && !estado.cpc.length" class="cpc__ayuda" role="status">
      No hay ningún término en la lista de CPC, así que «solo CPC» todavía no cambia nada.
    </p>

    <!--
      La trampa del modo «Todas» se avisa **antes** de pulsar, no después de ver la tabla vacía. Ver
      `avisoModoTodas`. No bloquea el botón: quien tenga un solo término quiere ese modo, y quien
      tenga dos muy parecidos puede querer la intersección de verdad.
    -->
    <p v-if="avisoModoTodas" class="cpc__aviso-modo" role="alert">
      Con «Todas» haría falta que el CPC de una misma necesidad contuviera los
      {{ estado.cpc.length }} términos a la vez, y estas clasificaciones son alternativas: ninguna
      coincide con otra. El resultado va a ser vacío. Cambia a «Cualquiera», o deja un solo término.
    </p>

    <ul v-if="estado.cpc.length" class="cpc__lista">
      <li v-for="termino in estado.cpc" :key="termino">
        <button
          type="button"
          class="chip"
          :aria-label="`Quitar ${termino} de la lista de CPC`"
          @click="quitar(termino)"
        >
          <span class="chip__marca" aria-hidden="true">⌗</span>
          <span class="chip__texto">{{ termino }}</span>
          <span class="chip__quitar" aria-hidden="true">✕</span>
        </button>
      </li>
    </ul>

    <p v-else-if="estado.cargandoCpc" class="cpc__vacio">Cargando la lista…</p>

    <p v-else class="cpc__vacio">
      La lista está vacía: el filtro por CPC no está en uso.
    </p>

    <div class="cpc__acciones">
      <button
        v-if="estado.cpc.length"
        type="button"
        class="boton boton--fantasma boton--pequeno"
        @click="vaciar()"
      >
        Vaciar la lista
      </button>
      <!--
        Copiar las palabras clave marcadas evita el paso que sobra: quien vigila «lavado» quiere
        buscarlo por su clasificación, y volver a escribirlo a mano es trabajo repetido. Se guardan
        en la lista del equipo, así que valen también para el compañero.
      -->
      <button
        v-if="estado.seleccionadas.length"
        type="button"
        class="boton boton--fantasma boton--pequeno"
        :disabled="guardando"
        @click="usarPalabrasClave()"
      >
        Copiar las {{ estado.seleccionadas.length }} palabras clave
      </button>
    </div>

    <div v-if="!mostrandoCampo && !mostrandoLote" class="cpc__nueva cpc__nueva--dual">
      <button
        type="button"
        class="boton boton--secundario boton--pequeno cpc__nuevo-boton"
        @click="mostrandoCampo = true"
      >
        <span aria-hidden="true">＋</span> Añadir término
      </button>
      <button
        type="button"
        class="boton boton--secundario boton--pequeno cpc__nuevo-boton"
        @click="mostrandoLote = true"
      >
        <span aria-hidden="true">≡</span> Pegar una lista
      </button>
    </div>

    <form v-else-if="mostrandoCampo" class="cpc__nueva" @submit.prevent="agregar">
      <label class="solo-lectores" for="nuevo-cpc">Palabra o código del CPC</label>
      <input
        id="nuevo-cpc"
        v-model="nuevo"
        class="entrada"
        type="text"
        autofocus
        :placeholder="`lavado, 871410032… (mínimo ${LONGITUD_MINIMA_TERMINO} letras)`"
        @keydown.esc="cancelarCampo"
      />
      <div class="cpc__nueva-acciones">
        <button type="submit" class="boton boton--principal boton--pequeno" :disabled="!puedeAgregar || guardando">
          {{ guardando ? 'Guardando…' : 'Añadir' }}
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
    <form v-else class="cpc__nueva" @submit.prevent="agregarLote">
      <label class="campo__etiqueta" for="lote-cpc">Términos separados por comas</label>
      <textarea
        id="lote-cpc"
        v-model="lote"
        class="entrada cpc__lote"
        rows="4"
        autofocus
        placeholder="lavado, engrasado, 871410032, aseo…"
        @keydown.esc="cancelarLote"
      />
      <p class="cpc__ayuda">
        Se separan por comas, punto y coma o saltos de línea.
        <template v-if="delLote.terminos.length">
          Se van a añadir <strong class="numeros">{{ delLote.terminos.length }}</strong>
          {{ delLote.terminos.length === 1 ? 'término' : 'términos' }}.
        </template>
        <template v-if="delLote.cortas">
          Se descartarán {{ delLote.cortas }} por tener menos de {{ LONGITUD_MINIMA_TERMINO }} letras.
        </template>
      </p>
      <div class="cpc__nueva-acciones">
        <button
          type="submit"
          class="boton boton--principal boton--pequeno"
          :disabled="!delLote.terminos.length || guardando"
        >
          {{ guardando ? 'Guardando…' : delLote.terminos.length ? `Añadir ${delLote.terminos.length}` : 'Añadir' }}
        </button>
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="cancelarLote">
          Cancelar
        </button>
      </div>
    </form>

    <p v-if="estado.errorCpcLista" class="cpc__error" role="alert">
      No se pudo cargar la lista guardada: {{ estado.errorCpcLista }}
    </p>
    <p v-if="error" class="cpc__error" role="alert">{{ error }}</p>
    <p v-else-if="aviso" class="cpc__aviso" role="status">{{ aviso }}</p>
  </div>
</template>

<style scoped>
.cpc {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.cpc__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

/*
 * El interruptor de «solo CPC»: mismo tamaño y contraste que la ayuda que tiene al lado, porque es
 * una decisión sobre el filtro y no una acción. En reposo no llama la atención; se entiende leyendo.
 */
.cpc__interruptor {
  display: flex;
  align-items: flex-start;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-suave);
  cursor: pointer;
}

.cpc__interruptor-control {
  margin-top: 2px;
  width: 15px;
  height: 15px;
  flex: none;
  accent-color: var(--acento);
}

.cpc__vacio {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.cpc__lista {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  list-style: none;
  padding: 0;
  margin: var(--e-1) 0;
}

/* Las mismas fichas que las palabras clave: son la misma idea y tienen que leerse igual. */
.chip {
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
    color var(--rapido) var(--curva),
    transform var(--rapido) var(--curva);
}

.chip:hover {
  border-color: var(--acento);
  color: var(--texto);
}

.chip:active {
  transform: scale(0.97);
}

.chip__marca {
  font-weight: 700;
  opacity: 0.85;
}

.chip__texto {
  font-weight: 550;
}

.chip__quitar {
  font-size: 0.75em;
  opacity: 0.75;
}

.cpc__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.cpc__nueva {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin-top: var(--e-1);
}

/* Los dos botones de alta, uno al lado del otro: individual y en bloque. */
.cpc__nueva--dual {
  flex-direction: row;
  flex-wrap: wrap;
  gap: var(--e-2);
}

/*
 * `max-content` como ancho mínimo, y no cero: cada botón mide al menos lo que mide su texto, y
 * cuando los dos juntos no caben el segundo **baja a la línea siguiente**. Sin esto, en una columna
 * estrecha los dos botones empujaban el ancho del contenido por encima de la columna y era la
 * columna entera la que se iba de lado: aparecía una barra horizontal en el panel de filtros y las
 * líneas de texto quedaban cortadas por la derecha.
 */
.cpc__nueva--dual .cpc__nuevo-boton {
  flex: 1 1 auto;
  min-width: max-content;
}

.cpc__nueva-acciones {
  display: flex;
  gap: var(--e-2);
}

.cpc__lote {
  font-family: inherit;
  font-size: var(--t-sm);
  resize: vertical;
}

.cpc__error {
  font-size: var(--t-xs);
  color: var(--error);
}

.cpc__aviso {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

/*
  El aviso del modo «Todas». Se pinta como advertencia y no como error: nada ha fallado todavía, y
  el color de error delante de una lista recién guardada daría a entender que se guardó mal.
*/
.cpc__aviso-modo {
  padding: var(--e-2);
  border-left: 3px solid var(--aviso);
  border-radius: var(--r-1);
  background: var(--aviso-suave);
  color: var(--aviso);
  font-size: var(--t-xs);
}
</style>
