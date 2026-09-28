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

import Paginacion from '@/components/Paginacion.vue'
import { api } from '@/api/endpoints'
import { datos } from '@/stores/datos'
import { decimal, fechaCorta, recortar, sinEtiquetas } from '@/utils/formato'
import { separarProvincia } from '@/utils/provincias'

const FILAS_POR_PAGINA = 25
const LONGITUD_MINIMA = 3
const FUENTE_PREDETERMINADA = 'OCDS'

const criterios = reactive({
  palabras: '',
  entidad: '',
  tipo_proceso: '',
  tipo_necesidad: '',
  estado: '',
  codigo: '',
  desde: '',
  hasta: '',
  fuente: FUENTE_PREDETERMINADA,
})

/** Lo que está consultado. Es lo que viaja al servidor; `criterios` es solo lo que se está tecleando. */
const aplicados = ref({ ...criterios })

const filas = ref([])
const total = ref(0)
const paginas = ref(0)
const pagina = ref(1)
const cargando = ref(false)
const error = ref('')

const desplegado = ref(null)

/** Igual que en la tabla de registros: un interruptor, no una lista de claves abiertas. */
const todosDesplegados = ref(false)

const catalogo = computed(() => datos.estado.catalogos)

const fuentes = computed(() => catalogo.value.fuente || [])

/**
 * Las palabras tecleadas, ya separadas y sin repetir.
 *
 * Se cuentan las de tres letras o más porque son las únicas que el servidor va a tener en cuenta; un
 * contador que incluyera las cortas prometería una búsqueda que no se va a hacer.
 */
const palabras = computed(() => {
  const partes = String(criterios.palabras || '')
    .split(/[,;\n]/)
    .map((parte) => parte.trim().toLowerCase())
    .filter((parte) => parte.length >= LONGITUD_MINIMA)
  return [...new Set(partes)]
})

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
  if (aplicados.value.estado) salida.estado = aplicados.value.estado
  if (aplicados.value.codigo.trim()) salida.codigo = aplicados.value.codigo.trim()
  if (aplicados.value.desde) salida.desde = aplicados.value.desde
  if (aplicados.value.hasta) salida.hasta = aplicados.value.hasta
  const terminos = palabras.value
  if (terminos.length) salida.termino = terminos
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
  aplicados.value = { ...criterios }
  pagina.value = 1
  desplegado.value = null
  todosDesplegados.value = false
  return consultar()
}

function limpiar() {
  criterios.palabras = ''
  criterios.entidad = ''
  criterios.tipo_proceso = ''
  criterios.tipo_necesidad = ''
  criterios.estado = ''
  criterios.codigo = ''
  criterios.desde = ''
  criterios.hasta = ''
  criterios.fuente = FUENTE_PREDETERMINADA
  return aplicar()
}

function irAPagina(destino) {
  pagina.value = destino
  desplegado.value = null
  todosDesplegados.value = false
  return consultar()
}

function estaDesplegada(fila) {
  return todosDesplegados.value || desplegado.value === fila.id
}

function alternarTodo() {
  todosDesplegados.value = !todosDesplegados.value
  desplegado.value = null
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

/**
 * Los campos del detalle, con nombre legible.
 *
 * Se listan en un orden fijo y no volcando el registro entero: el registro trae claves internas
 * —`id`, `fuente`, `clave_natural`— que no significan nada para quien lee y que además ocuparían
 * media pantalla antes de llegar a lo que sí importa.
 */
const CAMPOS_DETALLE = [
  ['ocid', 'OCID'],
  ['codigo', 'Código del proceso'],
  ['entidad', 'Entidad contratante'],
  ['objeto_compra', 'Objeto del proceso'],
  ['tipo_proceso', 'Tipo de contratación'],
  ['tipo_necesidad', 'Tipo de compra'],
  ['estado', 'Estado del proceso'],
  ['provincia', 'Provincia'],
  ['canton', 'Cantón'],
  ['presupuesto', 'Presupuesto referencial'],
  ['monto', 'Monto'],
  ['metodo', 'Método de contratación'],
  ['proveedor', 'Proveedor adjudicado'],
  ['fecha_publicacion', 'Fecha de publicación'],
]

function detalle(fila) {
  return CAMPOS_DETALLE.map(([clave, etiqueta]) => {
    const valor = fila[clave]
    if (valor === null || valor === undefined || valor === '') return null
    return { clave, etiqueta, valor: sinEtiquetas(String(valor)) }
  }).filter(Boolean)
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
        <label class="campo__etiqueta" for="of-estado">Estado del proceso</label>
        <select id="of-estado" v-model="criterios.estado" class="entrada">
          <option value="">Todos los estados</option>
          <option v-for="valor in catalogo.estado || []" :key="valor" :value="valor">
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
      Con la fuente <strong>OCDS</strong> la columna «Estado del proceso» sale vacía, porque los datos
      abiertos no publican ese campo; con <strong>NCO</strong> sí aparece.
    </p>

    <div v-if="filas.length" class="ofertas__barra">
      <p class="ofertas__resumen">
        <strong class="numeros">{{ total }}</strong>
        {{ total === 1 ? 'proceso' : 'procesos' }} con los criterios puestos.
      </p>
      <button type="button" class="boton boton--secundario boton--pequeno" @click="alternarTodo">
        <span aria-hidden="true">{{ todosDesplegados ? '⌃' : '⌄' }}</span>
        {{ todosDesplegados ? 'Contraer todo' : 'Desplegar todo' }}
      </button>
    </div>

    <div v-if="filas.length" class="ofertas__marco">
      <table class="ofertas__tabla">
        <thead>
          <tr>
            <th scope="col">Código</th>
            <th scope="col">Entidad contratante</th>
            <th scope="col">Objeto del proceso</th>
            <th scope="col">Estado del proceso</th>
            <th scope="col">Provincia / Cantón</th>
            <th scope="col" class="ofertas__numero">Presupuesto referencial total (sin iva)</th>
            <th scope="col">Fecha de publicación</th>
            <th scope="col">Opciones</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="fila in filas" :key="fila.id">
            <tr class="ofertas__fila">
              <td class="ofertas__codigo numeros" :title="fila.codigo">{{ fila.codigo || '—' }}</td>
              <td :title="fila.entidad">{{ recortar(fila.entidad || '—', 42) }}</td>
              <td class="ofertas__objeto" :title="sinEtiquetas(fila.objeto_compra || '')">
                {{ recortar(sinEtiquetas(fila.objeto_compra || '—'), 90) }}
              </td>
              <td>
                <span v-if="fila.estado" class="ofertas__insignia">{{ fila.estado }}</span>
                <span v-else class="ofertas__vacio" title="Los datos abiertos no publican este campo">
                  —
                </span>
              </td>
              <td>{{ lugar(fila) }}</td>
              <td class="ofertas__numero numeros">{{ presupuesto(fila) }}</td>
              <td class="numeros">{{ fechaCorta(fila.fecha_publicacion) }}</td>
              <td>
                <button
                  type="button"
                  class="boton boton--fantasma boton--pequeno"
                  :aria-expanded="estaDesplegada(fila)"
                  @click="desplegado = estaDesplegada(fila) ? null : fila.id"
                >
                  {{ estaDesplegada(fila) ? 'Ocultar' : 'Ver detalle' }}
                </button>
              </td>
            </tr>
            <tr v-if="estaDesplegada(fila)" class="ofertas__detalle">
              <td colspan="8">
                <dl class="ofertas__campos">
                  <div v-for="campo in detalle(fila)" :key="campo.clave" class="ofertas__campo">
                    <dt>{{ campo.etiqueta }}</dt>
                    <dd>{{ campo.valor }}</dd>
                  </div>
                </dl>
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

.ofertas__detalle td {
  padding: var(--e-3);
  background: var(--c-fondo);
}

.ofertas__campos {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
  gap: var(--e-2);
  margin: 0;
}

.ofertas__campo dt {
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--c-texto-suave);
  text-transform: capitalize;
}

.ofertas__campo dd {
  margin: 0.1rem 0 0;
  font-size: var(--t-sm);
  word-break: break-word;
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
