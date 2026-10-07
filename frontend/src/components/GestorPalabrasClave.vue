<script setup>
/**
 * Selector de palabras clave: agregar, quitar y **combinar varias a la vez**.
 *
 * Es el centro del panel. Lo que se puede hacer aquí:
 *
 * - **Elegir varias palabras a la vez** y decidir si se exigen todas o basta con una. La diferencia
 *   es grande: buscar «obras» y «viales» con «todas» devuelve lo que menciona las dos, y con
 *   «cualquiera» devuelve lo que menciona alguna. **El modo por defecto es «cualquiera»**, porque
 *   marcar varias casillas se entiende como «quiero ver todo esto», y con «todas» lo habitual es
 *   que no quede nada. La interfaz dice cuál está activa en lugar de dejarlo a la memoria.
 * - **Agregar una palabra nueva** sin salir del panel. La palabra se guarda en el catálogo del
 *   negocio y la búsqueda se hace **contra el histórico ya descargado**, que es una consulta a la
 *   base y no una llamada al SERCOP: el resultado sale al instante. No se muestra ningún estado de
 *   espera porque, para el listado de ínfimas cuantías, no hay nada que esperar.
 * - **Quitar una palabra de la selección** sin borrarla del catálogo, y **darla de baja** con su ✕.
 *   Son dos cosas distintas: dejar de buscar por ella hoy no es lo mismo que dejar de seguirla. La
 *   baja es real —desactiva la suscripción en el servidor—, así que volver a agregarla la encola
 *   otra vez en lugar de contestar que «ya se consultó hace poco».
 */
import { computed, ref } from 'vue'

import { filtros } from '@/stores/filtros'

const nueva = ref('')
const agregando = ref(false)
const error = ref('')
const aviso = ref('')
const mostrandoCampo = ref(false)
const quitando = ref(null)

const lote = ref('')
const mostrandoLote = ref(false)
const agregandoLote = ref(false)

const estado = filtros.estado
const seleccionadas = computed(() => new Set(estado.seleccionadas))

const longitudMinima = 3
const puedeAgregar = computed(() => nueva.value.trim().length >= longitudMinima && !agregando.value)

async function agregar() {
  if (!puedeAgregar.value) return

  agregando.value = true
  error.value = ''
  aviso.value = ''
  try {
    const resultado = await filtros.agregarPalabra(nueva.value)
    aviso.value = resultado?.avisos?.[0] || 'Palabra clave agregada.'
    nueva.value = ''
    mostrandoCampo.value = false
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    agregando.value = false
  }
}

function cancelar() {
  mostrandoCampo.value = false
  nueva.value = ''
  error.value = ''
}

/**
 * Da de baja la palabra clave del negocio.
 *
 * Es la operación que **no existía**: el panel podía deseleccionar una palabra —dejar de filtrar por
 * ella— pero no darla de baja, así que la suscripción seguía activa y volver a agregarla contestaba
 * «ya se consultó hace poco», que se lee como «ya estaba puesta».
 *
 * Se espera la respuesta del servidor antes de tocar la lista: así, volver a agregarla de inmediato
 * la encola de verdad en vez de encontrarla todavía activa.
 */
async function darDeBaja(palabra) {
  error.value = ''
  aviso.value = ''
  quitando.value = palabra.termino_id
  try {
    await filtros.quitarPalabraDefinitiva(palabra.termino_id)
    aviso.value = `«${palabra.texto}» ya no se sigue. Si la vuelves a agregar, se buscará otra vez.`
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    quitando.value = null
  }
}

/**
 * Las palabras que se detectan en el recuadro, sin repetir y sin las que no sirven.
 *
 * Se separa por comas, punto y coma y saltos de línea porque son los tres separadores que aparecen al
 * copiar de una hoja de cálculo. Se descartan las de menos de tres letras **en el contador**, para que
 * el número que ve el usuario antes de pulsar coincida con el que se va a guardar; el servidor aplica
 * la misma regla por su cuenta.
 */
const palabrasDelLote = computed(() => {
  const partes = String(lote.value || '')
    .split(/[,;\n]/)
    .map((parte) => parte.trim().toLowerCase())
    .filter((parte) => parte.length >= longitudMinima)
  return [...new Set(partes)]
})

const cuantasDelLote = computed(() => palabrasDelLote.value.length)

/**
 * Agrega la lista entera en **una sola** petición.
 *
 * Una por una serían treinta peticiones encadenadas y, como cada alta abre su conexión con la base,
 * la espera pasaría del minuto. El servidor las crea todas en una transacción.
 */
async function agregarLote() {
  if (!cuantasDelLote.value || agregandoLote.value) return

  agregandoLote.value = true
  error.value = ''
  aviso.value = ''
  try {
    const resultado = await filtros.agregarPalabras(lote.value)
    const total = (resultado?.terminos || []).length
    const descartadas = resultado?.descartadas || 0
    aviso.value = [
      `${total} ${total === 1 ? 'palabra agregada' : 'palabras agregadas'}.`,
      descartadas
        ? `Se descartaron ${descartadas} por tener menos de ${longitudMinima} letras.`
        : '',
      'Pulsa «Aplicar» para buscarlas.',
    ]
      .filter(Boolean)
      .join(' ')
    lote.value = ''
    mostrandoLote.value = false
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    agregandoLote.value = false
  }
}

function cancelarLote() {
  mostrandoLote.value = false
  lote.value = ''
  error.value = ''
}
</script>

<template>
  <div class="palabras">
    <div class="palabras__cabecera">
      <p class="campo__etiqueta">Palabras clave</p>
      <div class="palabras__modo" role="group" aria-label="Cómo combinar las palabras seleccionadas">
        <button
          type="button"
          class="palabras__modo-boton"
          :class="{ 'palabras__modo-boton--activo': estado.modo === 'todas' }"
          :aria-pressed="estado.modo === 'todas'"
          @click="filtros.actualizar({ modo: 'todas' })"
        >
          Todas
        </button>
        <button
          type="button"
          class="palabras__modo-boton"
          :class="{ 'palabras__modo-boton--activo': estado.modo === 'cualquiera' }"
          :aria-pressed="estado.modo === 'cualquiera'"
          @click="filtros.actualizar({ modo: 'cualquiera' })"
        >
          Cualquiera
        </button>
      </div>
    </div>

    <p class="palabras__ayuda">
      {{
        estado.modo === 'todas'
          ? 'Se muestran las contrataciones que mencionan todas las palabras seleccionadas.'
          : 'Se muestran las contrataciones que mencionan al menos una de las palabras seleccionadas. Los totales se suman.'
      }}
    </p>

    <div v-if="estado.cargandoPalabras" class="palabras__lista">
      <span class="esqueleto palabras__esqueleto" />
      <span class="esqueleto palabras__esqueleto" />
      <span class="esqueleto palabras__esqueleto corto" />
    </div>

    <p v-else-if="!estado.palabras.length" class="palabras__vacio">
      Todavía no hay palabras clave.
      <button type="button" class="enlace-inline" @click="mostrandoCampo = true">
        Agrega la primera
      </button>
      para empezar a seguir contrataciones.
    </p>

    <ul v-else class="palabras__lista">
      <li v-for="palabra in estado.palabras" :key="palabra.termino_id" class="palabras__item">
        <button
          type="button"
          class="chip"
          :class="{ 'chip--activo': seleccionadas.has(palabra.texto) }"
          :aria-pressed="seleccionadas.has(palabra.texto)"
          @click="filtros.alternarPalabra(palabra.texto)"
        >
          <span class="chip__marca" aria-hidden="true">{{ seleccionadas.has(palabra.texto) ? '✓' : '+' }}</span>
          <span class="chip__texto">{{ palabra.texto }}</span>
          <!--
            Aquí había una etiqueta «en cola» que marcaba las palabras cuya consulta aún no había
            llegado al SERCOP. Se quitó porque confundía más de lo que informaba: el listado de
            ínfimas cuantías se descarga **entero** en cada ciclo, así que buscar por cualquier
            palabra encuentra ya lo que hay, y la etiqueta daba a entender que la búsqueda estaba
            pendiente cuando el resultado que se veía era el definitivo.
          -->
        </button>
        <!--
          La baja va en su propio botón y **separada** del chip: uno selecciona y el otro deja de
          seguir la palabra. Pegados, pulsar «quitar» cuando se quería «seleccionar» sería un
          accidente de un píxel, y la baja no se deshace sola.
        -->
        <button
          type="button"
          class="palabras__baja"
          :aria-label="`Dar de baja la palabra clave ${palabra.texto}`"
          :title="`Dejar de seguir «${palabra.texto}»`"
          :disabled="quitando === palabra.termino_id"
          @click="darDeBaja(palabra)"
        >
          <span aria-hidden="true">✕</span>
        </button>
      </li>
    </ul>

    <div class="palabras__acciones">
      <button v-if="estado.palabras.length" type="button" class="boton boton--secundario boton--pequeno" @click="filtros.seleccionarTodas()">
        Seleccionar todas
      </button>
      <button v-if="estado.seleccionadas.length" type="button" class="boton boton--fantasma boton--pequeno" @click="filtros.limpiarPalabras()">
        Ninguna
      </button>
    </div>

    <!-- El botón de agregar, tal y como se pidió: siempre a la vista dentro del filtro. -->
    <div v-if="!mostrandoCampo && !mostrandoLote" class="palabras__nueva palabras__nueva--dual">
      <button type="button" class="boton boton--secundario palabras__nuevo-boton" @click="mostrandoCampo = true">
        <span aria-hidden="true">＋</span> Agregar palabra clave
      </button>
      <button type="button" class="boton boton--secundario palabras__nuevo-boton" @click="mostrandoLote = true">
        <span aria-hidden="true">≡</span> Pegar una lista
      </button>
    </div>

    <form v-else-if="mostrandoCampo" class="palabras__nueva" @submit.prevent="agregar">
      <label class="solo-lectores" for="nueva-palabra">Nueva palabra clave</label>
      <input
        id="nueva-palabra"
        v-model="nueva"
        class="entrada"
        type="text"
        autofocus
        :placeholder="`Mínimo ${longitudMinima} caracteres`"
        @keydown.esc="cancelar"
      />
      <div class="palabras__nueva-acciones">
        <button type="submit" class="boton boton--principal boton--pequeno" :disabled="!puedeAgregar">
          <span v-if="agregando" class="girador" aria-hidden="true" />
          {{ agregando ? 'Agregando…' : 'Agregar' }}
        </button>
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="cancelar">
          Cancelar
        </button>
      </div>
    </form>

    <!--
      El recuadro para pegar una lista. Es el uso real: nadie escribe veinte temas de uno en uno, los
      copia de otro sitio. El contador dice cuántas se van a guardar antes de pulsar, para que el
      resultado no sorprenda, y avisa de las que se descartan por cortas.
    -->
    <form v-else class="palabras__nueva" @submit.prevent="agregarLote">
      <label class="campo__etiqueta" for="lote-palabras">Palabras separadas por comas</label>
      <textarea
        id="lote-palabras"
        v-model="lote"
        class="entrada palabras__lote"
        rows="4"
        autofocus
        placeholder="produccion, cultura, exposicion, espectaculo, concierto…"
        @keydown.esc="cancelarLote"
      />
      <p class="palabras__ayuda">
        Se separan por comas, punto y coma o saltos de línea.
        <template v-if="cuantasDelLote">
          Se van a agregar <strong class="numeros">{{ cuantasDelLote }}</strong>
          {{ cuantasDelLote === 1 ? 'palabra' : 'palabras' }}.
        </template>
      </p>
      <div class="palabras__nueva-acciones">
        <button
          type="submit"
          class="boton boton--principal boton--pequeno"
          :disabled="!cuantasDelLote || agregandoLote"
        >
          <span v-if="agregandoLote" class="girador" aria-hidden="true" />
          {{ agregandoLote ? 'Agregando…' : `Agregar ${cuantasDelLote || ''}`.trim() }}
        </button>
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="cancelarLote">
          Cancelar
        </button>
      </div>
    </form>

    <p v-if="error" class="palabras__error" role="alert">{{ error }}</p>
    <p v-else-if="aviso" class="palabras__aviso" role="status">{{ aviso }}</p>
  </div>
</template>

<style scoped>
.palabras {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.palabras__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
}

.palabras__modo {
  display: flex;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  overflow: hidden;
}

.palabras__modo-boton {
  padding: 0.2rem 0.6rem;
  border: 0;
  background: transparent;
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-suave);
  cursor: pointer;
  transition: background-color var(--rapido) var(--curva), color var(--rapido) var(--curva);
}

.palabras__modo-boton:hover {
  background: var(--superficie-3);
}

.palabras__modo-boton--activo {
  background: var(--acento);
  color: #fff;
}

.palabras__ayuda {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.palabras__lista {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  list-style: none;
  padding: 0;
  margin: var(--e-1) 0;
}

/* El chip y su botón de baja viajan juntos: la ficha es una fila. */
.palabras__item {
  display: inline-flex;
  align-items: stretch;
  gap: var(--e-1);
}

/*
 * La baja, sobria en reposo y roja solo al pasar por encima: no es un gesto frecuente y no debe
 * invitar a pulsarla por error al seleccionar. El color aparece cuando la intención ya es clara.
 */
.palabras__baja {
  padding: 0 0.5rem;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: transparent;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  cursor: pointer;
  transition: color var(--rapido) var(--curva), border-color var(--rapido) var(--curva),
    background-color var(--rapido) var(--curva);
}

.palabras__baja:hover:not(:disabled) {
  border-color: var(--error);
  color: var(--error);
  background: var(--error-suave);
}

.palabras__baja:disabled {
  opacity: 0.5;
  cursor: progress;
}

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

.chip--activo {
  background: var(--acento);
  border-color: var(--acento);
  color: #fff;
}

.chip__marca {
  font-weight: 700;
  font-size: 0.75em;
  opacity: 0.85;
}

.chip__texto {
  font-weight: 550;
}

.palabras__acciones {
  display: flex;
  gap: var(--e-2);
}

.palabras__nueva {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin-top: var(--e-1);
}

/* Los dos botones de alta, uno al lado del otro: individual y en bloque. */
.palabras__nueva--dual {
  flex-direction: row;
  gap: var(--e-2);
}

.palabras__nueva--dual .palabras__nuevo-boton {
  flex: 1 1 0;
  min-width: 0;
}

.palabras__lote {
  font-family: inherit;
  font-size: var(--t-sm);
  line-height: 1.5;
  resize: vertical;
  min-height: 6.5rem;
}

.palabras__nuevo-boton {
  width: 100%;
  border-style: dashed;
}

.palabras__nueva-acciones {
  display: flex;
  gap: var(--e-2);
}

.palabras__error,
.palabras__aviso {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  font-size: var(--t-xs);
  line-height: 1.45;
}

.palabras__error {
  background: var(--error-suave);
  color: var(--error);
}

.palabras__aviso {
  background: var(--info-suave);
  color: var(--info);
}

.palabras__vacio {
  padding: var(--e-3);
  border: 1px dashed var(--borde-fuerte);
  border-radius: var(--r-2);
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  line-height: 1.5;
}

.enlace-inline {
  border: 0;
  padding: 0;
  background: none;
  color: var(--acento);
  text-decoration: underline;
  cursor: pointer;
  font-size: inherit;
}

.palabras__esqueleto {
  display: inline-block;
  width: 84px;
  height: 26px;
  border-radius: var(--r-redondo);
}

.palabras__esqueleto.corto {
  width: 62px;
}

.girador {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}
</style>
