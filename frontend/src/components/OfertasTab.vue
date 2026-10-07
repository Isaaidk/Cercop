<script setup>
/**
 * Listado de procesos publicados, con la forma del buscador del portal.
 *
 * Por qué es una pestaña aparte y no un filtro más del lateral
 * -----------------------------------------------------------
 * Porque responde a otra pregunta. El lateral acota **las contrataciones que siguen tus palabras
 * clave**; esto reproduce el listado del portal —entidad, tipo, código, fechas— y quien lo usa está
 * buscando un proceso concreto, no vigilando un tema. Mezclarlos habría obligado a que los criterios
 * del portal viajaran en la clave de caché de todas las búsquedas y a que el resumen del panel
 * cambiara al teclear un código de proceso, que no es lo que se espera.
 *
 * Por qué se aplica con un botón
 * ------------------------------
 * Escribir «municipio» son ocho pulsaciones, y sin botón cada una sería una consulta: ocho
 * peticiones, ocho respuestas que llegan en cualquier orden y una tabla parpadeando. Se consulta una
 * vez, cuando los criterios ya son los que se quieren.
 *
 * De dónde salen los datos
 * ------------------------
 * De los datos abiertos del SERCOP (OCDS), que es la misma información que publica el portal en su
 * buscador de procesos. El buscador del portal no se puede consultar desde aquí: su servicio pide un
 * captcha y responde vacío a cualquier petición que no venga de su propia página.
 *
 * La consecuencia visible es una columna: **«Estado del Proceso» no viene en los datos abiertos**, así
 * que con la fuente OCDS sale vacía. Se rellena sola si se cambia la fuente a NCO, que sí lo publica.
 * Se dice aquí y en pantalla en lugar de dejar una columna muda que parezca un fallo.
 */
import { computed, onMounted, reactive, ref } from 'vue'

import CajonDetalleOferta from '@/components/CajonDetalleOferta.vue'
import CampoDeTerminos from '@/components/CampoDeTerminos.vue'
import Paginacion from '@/components/Paginacion.vue'
import SelectorProvincias from '@/components/SelectorProvincias.vue'
import { api } from '@/api/endpoints'
import { datos } from '@/stores/datos'
import { decimal, fechaCorta, recortar, sinEtiquetas } from '@/utils/formato'
import { nombreParaApi, separarProvincia } from '@/utils/provincias'
import { LONGITUD_MINIMA_TERMINO } from '@/utils/terminos'

const FILAS_POR_PAGINA = 25
const FUENTE_PREDETERMINADA = 'OCDS'

/**
 * La fuente que **no** publica el estado de la contratación.
 *
 * Los datos abiertos de los procesos no traen estado —se comprobó: en las 104.316 filas de OCDS la
 * columna está vacía y el filtro devuelve cero—, mientras que la fuente de las ínfimas cuantías sí
 * lo publica. Con esta constante se apaga el control en lugar de ofrecer un filtro que vacía la
 * tabla, que es la peor forma de «tener» una función.
 */
const FUENTE_SIN_ESTADO = 'OCDS'

/**
 * Cómo se combinan varias palabras clave en esta pestaña.
 *
 * Se pide «cualquiera» de forma explícita porque el servidor, si no se le dice otra cosa, combina
 * con «todas»: con dos palabras distintas eso devuelve casi siempre cero, y marcar tres sin ver
 * nada se lee como que el filtro no funciona. Es la misma elección que hace el panel de ínfimas.
 */
const MODO_PALABRAS = 'cualquiera'

const criterios = reactive({
  palabras: '',
  descripcion: [],
  cpc: [],
  modo: MODO_PALABRAS,
  provincias: [],
  estado: '',
  entidad: '',
  tipo_proceso: '',
  tipo_necesidad: '',
  codigo: '',
  desde: '',
  hasta: '',
  fuente: FUENTE_PREDETERMINADA,
})

/**
 * Copia del borrador con las listas clonadas.
 *
 * Un `{...criterios}` a secas compartiría los arreglos entre el borrador y lo aplicado, así que
 * añadir una ficha cambiaría **también** la consulta ya hecha: el botón de aplicar dejaría de tener
 * sentido para esos campos y la pantalla diría que no hay cambios pendientes cuando sí los hay.
 */
function copiarCriterios(origen) {
  return {
    ...origen,
    descripcion: [...origen.descripcion],
    cpc: [...origen.cpc],
    provincias: [...origen.provincias],
  }
}

/** Lo que está consultado. Es lo que viaja al servidor; `criterios` es solo lo que se está tecleando. */
const aplicados = ref(copiarCriterios(criterios))

const filas = ref([])
const total = ref(0)
const paginas = ref(0)
const pagina = ref(1)
const cargando = ref(false)
const error = ref('')

/**
 * La fila cuyo detalle está abierto, si hay alguna.
 *
 * Es **una** y no una lista de claves, como en la tabla de ínfimas: el detalle se enseña en un cajón
 * lateral que ocupa la pantalla, así que dos a la vez no caben y el botón de «desplegar todo» dejó de
 * tener sentido —abrir veinticinco cajones no es algo que se pueda leer—.
 *
 * Se guarda la fila entera y no su identificador porque el cajón la necesita para pintarse, y
 * volver a buscarla en la lista sería una forma de que las dos se separaran.
 */
const abierto = ref(null)

const catalogo = computed(() => datos.estado.catalogos)

const fuentes = computed(() => catalogo.value.fuente || [])

/** Los estados que existen de verdad en los datos, no una lista inventada. */
const estados = computed(() => catalogo.value.estado || [])

/**
 * Las palabras que se pueden buscar en un texto, ya separadas y sin repetir.
 *
 * Se descartan las de tres letras o más cortas porque son las únicas que el servidor va a tener en
 * cuenta; un contador que incluyera las cortas prometería una búsqueda que no se va a hacer.
 */
function terminosDe(texto) {
  const partes = String(texto || '')
    .split(/[,;\n]/)
    .map((parte) => parte.trim().toLowerCase())
    .filter((parte) => parte.length >= LONGITUD_MINIMA_TERMINO)
  return [...new Set(partes)]
}

/** Las palabras tecleadas, para el contador de la ayuda. */
const palabras = computed(() => terminosDe(criterios.palabras))

const hayCambios = computed(
  () =>
    JSON.stringify({ ...criterios }) !== JSON.stringify({ ...aplicados.value }) ||
    pagina.value !== 1,
)

function parametros() {
  const salida = { tamano: FILAS_POR_PAGINA, pagina: pagina.value }
  if (aplicados.value.fuente) salida.fuente = aplicados.value.fuente
  if (aplicados.value.entidad.trim()) salida.entidad = aplicados.value.entidad.trim()
  if (aplicados.value.tipo_proceso) salida.tipo_proceso = aplicados.value.tipo_proceso
  if (aplicados.value.tipo_necesidad) salida.tipo_necesidad = aplicados.value.tipo_necesidad
  if (aplicados.value.codigo.trim()) salida.codigo = aplicados.value.codigo.trim()
  if (aplicados.value.desde) salida.desde = aplicados.value.desde
  if (aplicados.value.hasta) salida.hasta = aplicados.value.hasta
  // Las palabras se leen de **lo aplicado**, no del borrador: todos los demás campos ya salían de
  // `aplicados` y los términos eran el único criterio que no respetaba el botón, de modo que
  // teclear sin pulsar «Buscar» cambiaba en silencio lo que se iba a consultar.
  const terminos = terminosDe(aplicados.value.palabras)
  if (terminos.length) salida.termino = terminos

  // Los tres campos de texto —palabras clave, CPC y descripción del producto— comparten el modo:
  // la pregunta es la misma, cómo se combinan entre sí varias palabras de la misma lista. Se envía
  // en cuanto haya algo con lo que combinarlo.
  const descripcion = aplicados.value.descripcion
  const cpc = aplicados.value.cpc
  if (descripcion.length) salida.descripcion = descripcion
  if (cpc.length) salida.cpc = cpc
  if (terminos.length || descripcion.length || cpc.length) salida.modo = aplicados.value.modo

  // La provincia viaja con el nombre en mayúsculas, como la escribe la fuente; el servidor la
  // reduce a su clave para compararla con la columna.
  if (aplicados.value.provincias.length) {
    salida.provincia = aplicados.value.provincias.map(nombreParaApi)
  }
  // El estado se envía solo si la fuente lo publica. Si se colara con los datos abiertos, la lista
  // saldría vacía y parecería que la búsqueda está rota cuando lo que falta es el dato.
  if (aplicados.value.estado && aplicados.value.fuente !== FUENTE_SIN_ESTADO) {
    salida.estado = aplicados.value.estado
  }
  return salida
}

async function consultar() {
  cargando.value = true
  error.value = ''
  try {
    const respuesta = await api.buscar(parametros())
    filas.value = respuesta.elementos || []
    total.value = respuesta.total || 0
    paginas.value = respuesta.paginas || 0
  } catch (fallo) {
    error.value = fallo.message
    filas.value = []
    total.value = 0
    paginas.value = 0
  } finally {
    cargando.value = false
  }
}

function aplicar() {
  aplicados.value = copiarCriterios(criterios)
  pagina.value = 1
  abierto.value = null
  return consultar()
}

function limpiar() {
  criterios.palabras = ''
  criterios.descripcion = []
  criterios.cpc = []
  criterios.modo = MODO_PALABRAS
  criterios.provincias = []
  criterios.estado = ''
  criterios.entidad = ''
  criterios.tipo_proceso = ''
  criterios.tipo_necesidad = ''
  criterios.codigo = ''
  criterios.desde = ''
  criterios.hasta = ''
  criterios.fuente = FUENTE_PREDETERMINADA
  return aplicar()
}

/*
 * Los términos que se escriben como fichas.
 *
 * El control avisa de lo que se añade y de lo que se quita —no admite repetidos ni palabras de una
 * o dos letras, y lo explica— y aquí solo se escribe en el borrador. Se hace con una función por
 * lista porque cada una vive en su campo, y con `filter`/spread en lugar de mutar el arreglo: así
 * el cambio se ve en la pantalla aunque las dos listas se parezcan.
 */
function agregarDescripcion(termino) {
  criterios.descripcion = [...criterios.descripcion, termino]
}

function quitarDescripcion(termino) {
  criterios.descripcion = criterios.descripcion.filter((valor) => valor !== termino)
}

function agregarCpc(termino) {
  criterios.cpc = [...criterios.cpc, termino]
}

function quitarCpc(termino) {
  criterios.cpc = criterios.cpc.filter((valor) => valor !== termino)
}

function cambiarProvincias(codigos) {
  criterios.provincias = codigos
}

function irAPagina(destino) {
  pagina.value = destino
  abierto.value = null
  return consultar()
}

/** El importe tal y como se pide en la columna: sin IVA, con separador de miles. */
function presupuesto(fila) {
  const valor = fila.presupuesto ?? fila.monto
  if (valor === null || valor === undefined || valor === '') return '—'
  return `$ ${decimal(valor)}`
}

function lugar(fila) {
  const { provincia, canton } = separarProvincia(fila.provincia)
  return [provincia, canton].filter(Boolean).join(' / ') || fila.provincia || '—'
}

onMounted(() => {
  // Los catálogos alimentan los desplegables. Si aún no han llegado, no se espera: el listado se
  // puede consultar igual y los desplegables se rellenan cuando lleguen.
  consultar()
})
</script>

<template>
  <section class="ofertas">
    <header class="ofertas__cabecera">
      <div>
        <p class="ofertas__titulo">Ofertas y procesos publicados</p>
        <p class="ofertas__pista">
          Todos los procesos publicados por las entidades, con los mismos criterios del buscador del
          portal.
        </p>
      </div>
      <span v-if="total" class="ofertas__cuenta numeros">{{ total }}</span>
    </header>

    <form class="ofertas__filtros" @submit.prevent="aplicar">
      <div class="campo campo--ancho">
        <label class="campo__etiqueta" for="of-palabras">Palabras clave</label>
        <input
          id="of-palabras"
          v-model="criterios.palabras"
          class="entrada"
          type="text"
          placeholder="Ej.: mantenimiento, medicamentos, obras"
        />
        <p v-if="palabras.length" class="ofertas__ayuda">
          Se buscarán <strong class="numeros">{{ palabras.length }}</strong>
          {{ palabras.length === 1 ? 'palabra' : 'palabras' }}, separadas por comas.
        </p>
      </div>

      <!--
        Cómo se combinan los términos entre sí. Es **el mismo** interruptor que en el panel lateral y
        por el mismo motivo: la pregunta —¿todas o cualquiera?— es la misma para las palabras clave,
        el CPC y la descripción, y un segundo control para el mismo valor es la forma más fácil de
        que la pantalla diga una cosa mientras la consulta hace otra. Arranca en «cualquiera» porque
        marcar varias cosas se entiende como «quiero ver todo esto», y con «todas» lo normal es no
        ver nada.
      -->
      <div class="campo campo--ancho">
        <div class="ofertas__modo-fila">
          <span class="campo__etiqueta">Combinar los términos</span>
          <div class="ofertas__modo" role="group" aria-label="Cómo combinar los términos buscados">
            <button
              type="button"
              class="ofertas__modo-boton"
              :class="{ 'ofertas__modo-boton--activo': criterios.modo === 'todas' }"
              :aria-pressed="criterios.modo === 'todas'"
              @click="criterios.modo = 'todas'"
            >
              Todas
            </button>
            <button
              type="button"
              class="ofertas__modo-boton"
              :class="{ 'ofertas__modo-boton--activo': criterios.modo === 'cualquiera' }"
              :aria-pressed="criterios.modo === 'cualquiera'"
              @click="criterios.modo = 'cualquiera'"
            >
              Cualquiera
            </button>
          </div>
        </div>
        <p class="ofertas__ayuda">
          {{
            criterios.modo === 'todas'
              ? 'Se exigen todos los términos: el proceso tiene que mencionarlos todos.'
              : 'Basta con que aparezca uno: los resultados de cada término se suman.'
          }}
        </p>
      </div>

      <div class="campo campo--ancho">
        <CampoDeTerminos
          etiqueta="Descripción del producto"
          ayuda="Busca solo en el objeto de compra —lo que la entidad dice que va a comprar— y no en el
            resto de la convocatoria."
          marcador="equipo de computo, sillas…"
          :terminos="criterios.descripcion"
          @agregar="agregarDescripcion"
          @quitar="quitarDescripcion"
        />
      </div>

      <div class="campo campo--ancho">
        <CampoDeTerminos
          etiqueta="Clasificación CPC"
          ayuda="Busca en el código y el nombre estándar de los ítems de la necesidad. Un número de seis
            cifras o más se compara por igualdad contra el código."
          marcador="871410032, o «lavado»"
          :terminos="criterios.cpc"
          @agregar="agregarCpc"
          @quitar="quitarCpc"
        />
      </div>

      <div class="campo campo--ancho">
        <SelectorProvincias
          :seleccionadas="criterios.provincias"
          @cambiar="cambiarProvincias"
        />
      </div>

      <div class="campo campo--ancho">
        <label class="campo__etiqueta" for="of-entidad">Entidad contratante</label>
        <input
          id="of-entidad"
          v-model="criterios.entidad"
          class="entrada"
          type="text"
          placeholder="Parte del nombre, sin importar mayúsculas ni tildes"
        />
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-tipo-proceso">Tipo de contratación</label>
        <select id="of-tipo-proceso" v-model="criterios.tipo_proceso" class="entrada">
          <option value="">Todos los tipos</option>
          <option v-for="valor in catalogo.tipo_proceso || []" :key="valor" :value="valor">
            {{ valor }}
          </option>
        </select>
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-tipo-necesidad">Tipo de compra</label>
        <select id="of-tipo-necesidad" v-model="criterios.tipo_necesidad" class="entrada">
          <option value="">Todos los tipos</option>
          <option v-for="valor in catalogo.tipo_necesidad || []" :key="valor" :value="valor">
            {{ valor }}
          </option>
        </select>
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-codigo">Código del proceso</label>
        <input
          id="of-codigo"
          v-model="criterios.codigo"
          class="entrada"
          type="text"
          placeholder="Parte del código, ej.: 2026-00270"
        />
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-estado">Estado de la contratación</label>
        <select
          id="of-estado"
          v-model="criterios.estado"
          class="entrada"
          :disabled="criterios.fuente === FUENTE_SIN_ESTADO"
        >
          <option value="">Todos los estados</option>
          <option v-for="valor in estados" :key="valor" :value="valor">{{ valor }}</option>
        </select>
        <!--
          Desactivado y explicado, en lugar de disponible y siempre vacío. Se midió antes de
          decidirlo: con la fuente de datos abiertos, elegir un estado devuelve **cero** filas,
          porque esas 104.316 filas no traen el campo. Un control que vacía la tabla sin decir por
          qué se lee como que la búsqueda está rota.
        -->
        <p v-if="criterios.fuente === FUENTE_SIN_ESTADO" class="ofertas__ayuda">
          Los procesos de datos abiertos no publican el estado, así que aquí no se puede filtrar por
          él. Cambia la fuente a NCO para usarlo.
        </p>
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-desde">Publicados desde</label>
        <input id="of-desde" v-model="criterios.desde" class="entrada" type="date" />
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-hasta">Publicados hasta</label>
        <input id="of-hasta" v-model="criterios.hasta" class="entrada" type="date" />
      </div>

      <div class="campo">
        <label class="campo__etiqueta" for="of-fuente">Fuente</label>
        <select id="of-fuente" v-model="criterios.fuente" class="entrada">
          <option value="">Todas las fuentes</option>
          <option v-for="valor in fuentes" :key="valor" :value="valor">{{ valor }}</option>
        </select>
      </div>

      <div class="ofertas__acciones">
        <button type="submit" class="boton boton--principal" :disabled="cargando">
          <span v-if="cargando" class="girador" aria-hidden="true" />
          {{ cargando ? 'Consultando…' : 'Buscar procesos' }}
        </button>
        <button type="button" class="boton boton--fantasma" @click="limpiar">Limpiar filtros</button>
        <span v-if="hayCambios && !cargando" class="ofertas__pendiente">
          Hay criterios sin consultar. Pulsa «Buscar procesos» para verlos.
        </span>
      </div>
    </form>

    <p v-if="error" class="ofertas__error" role="alert">{{ error }}</p>

    <p class="ofertas__nota">
      Los datos vienen de los datos abiertos del SERCOP. El buscador del portal no se puede consultar
      desde aquí —su servicio pide un captcha—, así que el listado se arma con esa misma información.
      El <strong>estado del proceso</strong> no se muestra porque los datos abiertos no lo publican:
      una columna con «—» en todas las filas parece un fallo del sistema y no lo es.
    </p>

    <div v-if="filas.length" class="ofertas__barra">
      <p class="ofertas__resumen">
        <strong class="numeros">{{ total }}</strong>
        {{ total === 1 ? 'proceso' : 'procesos' }} con los criterios puestos.
      </p>
      <p class="ofertas__pista">
        Pulsa <strong>Ver detalle</strong> en cualquier fila: el proceso se abre en un cajón, sin
        desordenar el ancho de la tabla.
      </p>
    </div>

    <div v-if="filas.length" class="ofertas__marco">
      <table class="ofertas__tabla">
        <thead>
          <tr>
            <th scope="col">Código</th>
            <th scope="col">Entidad contratante</th>
            <th scope="col">Objeto del proceso</th>
            <th scope="col">Provincia / Cantón</th>
            <th scope="col" class="ofertas__numero">Presupuesto referencial total (sin iva)</th>
            <th scope="col">Fecha de publicación</th>
            <th scope="col">Opciones</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="fila in filas" :key="fila.id">
            <tr class="ofertas__fila">
              <td class="ofertas__codigo numeros" :title="fila.codigo">
                <!--
                  El código como enlace, igual que en la tabla de ínfimas: cuando la fuente
                  publica la dirección del proceso, el código es la forma más corta de abrirlo. El
                  enlace lo compone el servidor —es el mismo dato para la tabla, el mapa y el
                  Excel— y aquí solo se pinta.
                -->
                <a
                  v-if="fila.enlace_publico"
                  class="codigo--enlace numeros"
                  :href="fila.enlace_publico"
                  target="_blank"
                  rel="noopener noreferrer"
                  :title="`Abrir ${fila.codigo || 'el proceso'} en el portal de la fuente`"
                >
                  {{ fila.codigo || '—' }}
                  <span class="codigo__fuera" aria-hidden="true">↗</span>
                </a>
                <span v-else>{{ fila.codigo || '—' }}</span>
              </td>
              <td :title="fila.entidad">{{ recortar(fila.entidad || '—', 42) }}</td>
              <td class="ofertas__objeto" :title="sinEtiquetas(fila.objeto_compra || '')">
                {{ recortar(sinEtiquetas(fila.objeto_compra || '—'), 90) }}
              </td>
              <td>{{ lugar(fila) }}</td>
              <td class="ofertas__numero numeros">{{ presupuesto(fila) }}</td>
              <td class="numeros">{{ fechaCorta(fila.fecha_publicacion) }}</td>
              <td>
                <button
                  type="button"
                  class="boton boton--secundario boton--pequeno"
                  aria-haspopup="dialog"
                  @click="abierto = fila"
                >
                  Ver detalle
                </button>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <p v-else-if="!cargando" class="ofertas__vacia">
      No hay procesos que cumplan estos criterios. Prueba a quitar alguno o a ampliar las fechas.
    </p>

    <Paginacion
      v-if="paginas > 1"
      :pagina="pagina"
      :paginas="paginas"
      :total="total"
      :tamano="FILAS_POR_PAGINA"
      @cambiar="irAPagina"
    />

    <!--
      El detalle, fuera de la tabla y a un lado. Antes era una fila más con una celda que ocupaba
      las siete columnas, y como la rejilla de campos mide como la tabla y la tabla mide como su
      fila más ancha, abrir un proceso estiraba el ancho por encima de la pantalla y **todo el panel
      se iba de lado**. Fuera de la tabla, el ancho de las columnas no depende de lo que haya
      abierto.

      Va **al final** de la sección y no entre la tabla y el mensaje de vacío: en Vue, `v-else-if`
      tiene que estar pegado a su `v-if`, y meter algo en medio rompe la cadena —el mensaje de «no
      hay procesos» pasaba a pintarse siempre, incluso con la tabla llena—.
    -->
    <CajonDetalleOferta v-if="abierto" :fila="abierto" @cerrar="abierto = null" />
  </section>
</template>

<style scoped>
.ofertas {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.ofertas__cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--e-3);
}

.ofertas__titulo {
  margin: 0;
  font-size: var(--t-lg);
  font-weight: 600;
}

.ofertas__pista {
  margin: 0.15rem 0 0;
  font-size: var(--t-xs);
  color: var(--c-texto-suave);
}

.ofertas__cuenta {
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--c-acento);
}

/* Rejilla de criterios. `auto-fit` con un mínimo razonable deja los campos en una columna en móvil
   sin escribir ninguna consulta de medios. */
.ofertas__filtros {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: var(--e-2);
  padding: var(--e-3);
  border: 1px solid var(--c-borde);
  border-radius: var(--r-md);
  background: var(--c-superficie);
}

.campo--ancho {
  grid-column: span 2;
}

.campo {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.campo__etiqueta {
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--c-texto-suave);
}

.ofertas__acciones {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-2);
}

.ofertas__pendiente {
  font-size: var(--t-xs);
  color: var(--c-acento);
}

.ofertas__ayuda,
.ofertas__nota {
  margin: 0;
  font-size: var(--t-xs);
  color: var(--c-texto-suave);
}

.ofertas__nota {
  line-height: 1.55;
}

.ofertas__error {
  margin: 0;
  padding: var(--e-2);
  border-radius: var(--r-sm);
  background: var(--c-error-suave, rgb(220 38 38 / 12%));
  color: var(--c-error, #b91c1c);
  font-size: var(--t-sm);
}

.ofertas__barra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
}

.ofertas__resumen {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--c-texto-suave);
}

.ofertas__marco {
  overflow-x: auto;
  border: 1px solid var(--c-borde);
  border-radius: var(--r-md);
}

.ofertas__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.ofertas__tabla thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: var(--e-2);
  border-bottom: 1px solid var(--c-borde);
  background: var(--c-superficie);
  font-size: var(--t-xs);
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
}

.ofertas__fila td {
  padding: var(--e-2);
  border-bottom: 1px solid var(--c-borde-suave, var(--c-borde));
  vertical-align: top;
}

.ofertas__fila:hover td {
  background: var(--c-superficie);
}

.ofertas__codigo {
  font-weight: 600;
  white-space: nowrap;
}

.ofertas__objeto {
  min-width: 16rem;
  color: var(--c-texto-suave);
}

.ofertas__numero {
  text-align: right;
  white-space: nowrap;
}

.ofertas__insignia {
  display: inline-block;
  padding: 0.1rem 0.45rem;
  border-radius: 999px;
  background: var(--c-acento-suave, rgb(37 99 235 / 12%));
  color: var(--c-acento);
  font-size: var(--t-xs);
  font-weight: 600;
  white-space: nowrap;
}

.ofertas__vacio {
  color: var(--c-texto-suave);
}

/* El mismo interruptor de dos posiciones que el panel lateral: misma idea, mismo aspecto. */
.ofertas__modo-fila {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
  flex-wrap: wrap;
}

.ofertas__modo {
  display: flex;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  overflow: hidden;
}

.ofertas__modo-boton {
  padding: 0.2rem 0.6rem;
  border: 0;
  background: transparent;
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-suave);
  cursor: pointer;
  transition:
    background-color var(--rapido) var(--curva),
    color var(--rapido) var(--curva);
}

.ofertas__modo-boton:hover {
  background: var(--superficie-3);
}

.ofertas__modo-boton--activo {
  background: var(--acento);
  color: #fff;
}

/*
 * El código como enlace, con el mismo trato que en la tabla de ínfimas.
 *
 * Se subraya solo al pasar por encima: subrayados todos a la vez, una columna entera de enlaces
 * convierte la tabla en una masa de líneas. El color sí va siempre, porque es lo único que avisa de
 * que el código se puede pulsar sin tener que probarlo.
 */
.codigo--enlace {
  color: var(--acento);
  text-decoration: none;
}

.codigo--enlace:hover {
  text-decoration: underline;
}

.codigo--enlace:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
  border-radius: var(--r-1);
}

.codigo__fuera {
  margin-left: 0.25em;
  font-size: 0.85em;
  opacity: 0.75;
}

.ofertas__vacia {
  margin: 0;
  padding: var(--e-4);
  border: 1px dashed var(--c-borde);
  border-radius: var(--r-md);
  color: var(--c-texto-suave);
  font-size: var(--t-sm);
  text-align: center;
}

@media (width <= 720px) {
  .campo--ancho {
    grid-column: 1 / -1;
  }
}
</style>
