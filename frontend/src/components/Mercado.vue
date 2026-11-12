<script setup>
/**
 * «Precios y competencia»: lo que ya se adjudicó, contado como respuestas a preguntas de negocio.
 *
 * Antes eran seis pestañas con nombres de tabla («Adjudicaciones», «Demanda»…) y listas de puntos,
 * y el cliente no entendía para qué servían. Ahora cada sección es una pregunta que un proveedor se
 * hace antes de ofertar —¿a qué precio se adjudica?, ¿quién me gana?, ¿quién compra?, ¿dónde?— con
 * una frase de ayuda y un único buscador.
 *
 * El buscador es uno solo para todas las preguntas y acepta un CPC o una palabra: si lleva dígitos
 * se envía como `cpc` (el backend lo usa como prefijo) y si no, como `q`. Arranca con el primer CPC
 * del perfil, para que la pantalla abra ya respondiendo sobre lo que vende la empresa y no vacía.
 *
 * Los montos son el total de cada proceso, no un precio por unidad: se repite donde se muestran
 * porque es la confusión más fácil al leer «precio».
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'

import { api } from '@/api/endpoints'
import { fechaCorta, numero } from '@/utils/formato'
import { esCpc, perfilComercial, usd } from '@/utils/oportunidades'

const PREGUNTAS = [
  {
    id: 'precios',
    corta: 'Precios',
    pregunta: '¿A qué precio se adjudica lo que vendo?',
    ayuda: 'Montos adjudicados en procesos parecidos. Es el total de cada proceso, no el precio por unidad.',
  },
  {
    id: 'proveedores',
    corta: 'Competidores',
    pregunta: '¿Quién me gana?',
    ayuda: 'Las empresas que más procesos de esto ganaron, cuántos y por cuánto en total.',
  },
  {
    id: 'entidades',
    corta: 'Compradores',
    pregunta: '¿Qué entidades compran lo mío?',
    ayuda: 'Las instituciones que más publican procesos de esto: a quién conviene ofrecer.',
  },
  {
    id: 'demanda',
    corta: 'Dónde',
    pregunta: '¿Dónde se compra más?',
    ayuda: 'Provincias y cantones con más procesos, y los códigos CPC que más se piden.',
  },
  {
    id: 'comparar',
    corta: 'Comparar',
    pregunta: 'Comparar oportunidades',
    ayuda: 'Elige hasta cuatro procesos adjudicados y míralos lado a lado: monto, entidad, plazos y requisitos.',
  },
]

const seccion = ref('precios')
const busqueda = reactive({ termino: '', anio: '', entidad: '', proveedor: '' })
const sugeridos = ref([])
const error = ref('')
const aviso = ref('')

// Un resultado por pregunta, con la búsqueda que lo produjo: al volver a una pestaña con la misma
// búsqueda no se repite la consulta.
const resultados = reactive({
  precios: { datos: null, clave: '', cargando: false },
  proveedores: { datos: null, clave: '', cargando: false },
  entidades: { datos: null, clave: '', cargando: false },
  demanda: { datos: null, clave: '', cargando: false },
  comparar: { datos: null, clave: '', cargando: false },
})

const seleccion = ref([])
const comparacion = ref(null)
const comparando = ref(false)

const actual = computed(() => PREGUNTAS.find((p) => p.id === seccion.value))
const resultado = computed(() => resultados[seccion.value])
const terminoMostrado = computed(() => busqueda.termino.trim())

const LLAMADAS = {
  precios: (p) => api.preciosMercado(p),
  proveedores: (p) => api.proveedoresMercado(p),
  entidades: (p) => api.entidadesMercado(p),
  demanda: (p) => api.demandaMercado(p),
  // «Comparar» elige entre adjudicaciones; por eso su lista sale de ese endpoint.
  comparar: (p) => api.adjudicaciones(p),
}

function parametros(id) {
  const salida = {}
  const termino = busqueda.termino.trim()
  if (termino) salida[esCpc(termino) ? 'cpc' : 'q'] = termino
  if (busqueda.anio.trim()) salida.anio = busqueda.anio.trim()
  if (id === 'comparar') {
    if (busqueda.entidad.trim()) salida.entidad = busqueda.entidad.trim()
    if (busqueda.proveedor.trim()) salida.proveedor = busqueda.proveedor.trim()
  }
  return salida
}

async function consultar(id = seccion.value, forzar = false) {
  const p = parametros(id)
  const clave = JSON.stringify(p)
  const destino = resultados[id]
  if (!forzar && destino.datos && destino.clave === clave) return
  destino.cargando = true
  error.value = ''
  try {
    const datos = await LLAMADAS[id](p)
    destino.datos = datos
    destino.clave = clave
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    destino.cargando = false
  }
}

function ir(id) {
  seccion.value = id
  consultar(id)
}

function buscar() {
  consultar(seccion.value, true)
}

function usarTermino(termino) {
  busqueda.termino = termino
  consultar(seccion.value, true)
}

/** Desde «¿Dónde se compra más?»: ver a qué precio se adjudica ese CPC. */
function preciosDe(cpc) {
  busqueda.termino = cpc
  ir('precios')
}

// ------------------------------------------------------------------------------- precios

function hayResumen(grupo) {
  return grupo.resumen && Number(grupo.resumen.n) > 0
}

// ------------------------------------------------------------------------------- demanda

const maxProvincia = computed(() => {
  const filas = resultados.demanda.datos?.provincias || []
  return Math.max(1, ...filas.map((fila) => Number(fila.procesos) || 0))
})

function ancho(procesos) {
  return `${Math.max(2, (Number(procesos) / maxProvincia.value) * 100)}%`
}

// ------------------------------------------------------------------------------- comparar

function elegida(id) {
  return seleccion.value.some((item) => item.id === id)
}

function irAlComparador() {
  nextTick(() => document.querySelector('.mercado__comparacion')?.scrollIntoView({ block: 'nearest' }))
}

function agregar(fila) {
  error.value = ''
  if (elegida(fila.id)) {
    irAlComparador()
    return
  }
  if (seleccion.value.length >= 4) {
    aviso.value = 'Se comparan hasta cuatro procesos. Quita uno para agregar otro.'
    irAlComparador()
    return
  }
  seleccion.value = [...seleccion.value, fila]
  aviso.value = seleccion.value.length < 2 ? 'Elige al menos uno más para verlos lado a lado.' : ''
  if (seleccion.value.length >= 2) comparar()
}

function quitar(id) {
  seleccion.value = seleccion.value.filter((item) => item.id !== id)
  comparacion.value = null
  aviso.value =
    seleccion.value.length === 1 ? 'Elige al menos uno más para verlos lado a lado.' : ''
  if (seleccion.value.length >= 2) comparar()
}

async function comparar() {
  if (seleccion.value.length < 2) return
  error.value = ''
  comparando.value = true
  try {
    comparacion.value = await api.compararMercado(seleccion.value.map((fila) => fila.id))
    irAlComparador()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    comparando.value = false
  }
}

const FILAS_COMPARACION = [
  { etiqueta: 'Objeto', valor: (f) => f.objeto || '—' },
  { etiqueta: 'Entidad', valor: (f) => f.entidad || '—' },
  { etiqueta: 'Ubicación', valor: (f) => f.ubicacion || '—' },
  { etiqueta: 'CPC', valor: (f) => (f.cpc || []).join(', ') || '—' },
  { etiqueta: 'Presupuesto', valor: (f) => usd(f.presupuesto), numeros: true },
  { etiqueta: 'Monto adjudicado', valor: (f) => usd(f.monto), numeros: true },
  { etiqueta: 'Tipo', valor: (f) => f.tipo_proceso || '—' },
  { etiqueta: 'Publicación', valor: (f) => fechaCorta(f.fecha_publicacion) },
  { etiqueta: 'Fecha límite', valor: (f) => fechaCorta(f.plazo_proformas_en) },
  { etiqueta: 'Requisitos', valor: (f) => (f.requisitos || []).join(' · ') || '—' },
]

// ------------------------------------------------------------------------------- arranque

async function cargarPerfil() {
  const [ficha, claves] = await Promise.allSettled([api.verPerfil(), api.listarCpc()])
  const leido = perfilComercial(
    ficha.status === 'fulfilled' ? ficha.value : null,
    claves.status === 'fulfilled' ? claves.value?.claves : null,
  )
  // Primero los CPC (son los que mejor filtran), luego productos y palabras; pocos, para no agobiar.
  sugeridos.value = [...new Set([...leido.cpc.slice(0, 5), ...leido.productos, ...leido.palabras])].slice(0, 8)
  if (!busqueda.termino && leido.cpc.length) busqueda.termino = leido.cpc[0]
}

onMounted(async () => {
  await cargarPerfil()
  consultar('precios')
})
</script>

<template>
  <div class="mercado">
    <header class="mercado__cabecera">
      <h2>Precios y competencia</h2>
      <p>Lo que ya se adjudicó, para que ofertes con un precio que gana y sepas contra quién compites.</p>
    </header>

    <nav class="mercado__pestanas" role="tablist" aria-label="Preguntas de mercado">
      <button
        v-for="opcion in PREGUNTAS"
        :key="opcion.id"
        type="button"
        role="tab"
        class="mercado__pestana"
        :class="{ 'mercado__pestana--activa': seccion === opcion.id }"
        :aria-selected="seccion === opcion.id"
        :title="opcion.pregunta"
        @click="ir(opcion.id)"
      >
        {{ opcion.corta }}
        <span v-if="opcion.id === 'comparar' && seleccion.length" class="mercado__cuenta numeros">
          {{ seleccion.length }}
        </span>
      </button>
    </nav>

    <section class="mercado__pregunta" :aria-label="actual.pregunta">
      <div>
        <h3>{{ actual.pregunta }}</h3>
        <p class="mercado__ayuda">{{ actual.ayuda }}</p>
      </div>

      <!-- Un solo buscador para todas las preguntas -->
      <form class="buscador" role="search" @submit.prevent="buscar">
        <label class="campo buscador__termino">
          <span class="campo__etiqueta">Qué vendes (código CPC o palabra)</span>
          <input
            v-model="busqueda.termino"
            class="entrada"
            type="search"
            placeholder="Ej. 87150 o impresoras"
            autocomplete="off"
          />
        </label>
        <label class="campo buscador__anio">
          <span class="campo__etiqueta">Año</span>
          <input v-model="busqueda.anio" class="entrada numeros" inputmode="numeric" maxlength="4" placeholder="Todos" />
        </label>
        <template v-if="seccion === 'comparar'">
          <label class="campo buscador__extra">
            <span class="campo__etiqueta">Entidad</span>
            <input v-model="busqueda.entidad" class="entrada" placeholder="Ej. IESS" />
          </label>
          <label class="campo buscador__extra">
            <span class="campo__etiqueta">Proveedor</span>
            <input v-model="busqueda.proveedor" class="entrada" placeholder="Nombre o razón social" />
          </label>
        </template>
        <button class="boton boton--principal" type="submit" :disabled="resultado.cargando">
          {{ resultado.cargando ? 'Buscando…' : 'Buscar' }}
        </button>
      </form>
      <div v-if="sugeridos.length" class="sugeridos">
        <span class="sugeridos__titulo">De tu perfil:</span>
        <button
          v-for="termino in sugeridos"
          :key="termino"
          type="button"
          class="sugerido"
          :class="{ 'sugerido--activo': termino === terminoMostrado, numeros: esCpc(termino) }"
          :aria-pressed="termino === terminoMostrado"
          @click="usarTermino(termino)"
        >
          {{ esCpc(termino) ? `CPC ${termino}` : termino }}
        </button>
      </div>
    </section>

    <p v-if="error" class="mercado__error" role="alert">{{ error }}</p>

    <div v-if="resultado.cargando && !resultado.datos" class="mercado__cargando" aria-busy="true">
      <div v-for="n in 3" :key="n" class="esqueleto" />
    </div>

    <!-- ¿A qué precio se adjudica lo que vendo? -->
    <section v-else-if="seccion === 'precios'" class="mercado__resultado" :class="{ 'mercado__resultado--cargando': resultado.cargando }">
      <p v-if="resultado.datos?.motivo" class="mercado__vacio">{{ resultado.datos.motivo }}</p>
      <p v-else-if="resultado.datos && !(resultado.datos.grupos || []).length" class="mercado__vacio">
        No encontramos adjudicaciones para «{{ terminoMostrado || 'todo' }}». Prueba con otra palabra o con el
        inicio del código CPC.
      </p>
      <article v-for="grupo in resultado.datos?.grupos || []" :key="grupo.cpc || 'busqueda'" class="bloque">
        <header class="bloque__cabecera">
          <h4>{{ grupo.cpc ? `CPC ${grupo.cpc}` : 'Procesos que coinciden con tu búsqueda' }}</h4>
          <span v-if="hayResumen(grupo)" class="mercado__pista numeros">{{ numero(grupo.resumen.n) }} procesos</span>
        </header>

        <template v-if="hayResumen(grupo)">
          <p class="bloque__respuesta">
            La mitad se adjudicó por menos de <strong class="numeros">{{ usd(grupo.resumen.mediana) }}</strong>.
          </p>
          <dl class="cifras">
            <div>
              <dt>Mediana</dt>
              <dd class="numeros">{{ usd(grupo.resumen.mediana) }}</dd>
            </div>
            <div>
              <dt>Promedio</dt>
              <dd class="numeros">{{ usd(grupo.resumen.promedio) }}</dd>
            </div>
            <div>
              <dt>Más bajo</dt>
              <dd class="numeros">{{ usd(grupo.resumen.minimo) }}</dd>
            </div>
            <div>
              <dt>Más alto</dt>
              <dd class="numeros">{{ usd(grupo.resumen.maximo) }}</dd>
            </div>
          </dl>
        </template>
        <p v-if="grupo.aviso" class="mercado__pista">{{ grupo.aviso }}</p>

        <div class="bloque__tablas">
          <div v-if="(grupo.por_anio || []).length" class="tabla">
            <table>
              <caption>Por año</caption>
              <thead>
                <tr><th scope="col">Año</th><th scope="col" class="num">Promedio</th><th scope="col" class="num">Procesos</th></tr>
              </thead>
              <tbody>
                <tr v-for="punto in grupo.por_anio" :key="punto.nombre">
                  <td class="numeros">{{ punto.nombre }}</td>
                  <td class="num numeros">{{ usd(punto.promedio) }}</td>
                  <td class="num numeros">{{ numero(punto.n) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="(grupo.por_entidad || []).length" class="tabla">
            <table>
              <caption>Por entidad</caption>
              <thead>
                <tr><th scope="col">Entidad</th><th scope="col" class="num">Promedio</th><th scope="col" class="num">Procesos</th></tr>
              </thead>
              <tbody>
                <tr v-for="punto in grupo.por_entidad.slice(0, 10)" :key="punto.nombre">
                  <td>{{ punto.nombre }}</td>
                  <td class="num numeros">{{ usd(punto.promedio) }}</td>
                  <td class="num numeros">{{ numero(punto.n) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <details v-if="(grupo.procesos || []).length" class="bloque__mas">
          <summary>Ver cada proceso ({{ numero(grupo.procesos.length) }})</summary>
          <div class="tabla">
            <table>
              <thead>
                <tr><th scope="col" class="num">Monto</th><th scope="col">Objeto</th><th scope="col">Entidad</th></tr>
              </thead>
              <tbody>
                <tr v-for="proceso in grupo.procesos" :key="proceso.codigo">
                  <td class="num numeros">{{ usd(proceso.monto) }}</td>
                  <td>{{ proceso.objeto || '—' }}</td>
                  <td>{{ proceso.entidad || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </article>
      <p v-if="resultado.datos?.aviso" class="mercado__pista">{{ resultado.datos.aviso }}</p>
    </section>

    <!-- ¿Quién me gana? -->
    <section v-else-if="seccion === 'proveedores'" class="mercado__resultado" :class="{ 'mercado__resultado--cargando': resultado.cargando }">
      <p v-if="resultado.datos?.motivo" class="mercado__vacio">{{ resultado.datos.motivo }}</p>
      <p v-else-if="resultado.datos && !(resultado.datos.filas || []).length" class="mercado__vacio">
        No hay proveedores adjudicados para «{{ terminoMostrado || 'todo' }}».
      </p>
      <div v-else-if="(resultado.datos?.filas || []).length" class="tabla bloque">
        <table>
          <thead>
            <tr>
              <th scope="col">Proveedor</th>
              <th scope="col" class="num">Procesos ganados</th>
              <th scope="col" class="num">Monto adjudicado</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in resultado.datos.filas" :key="fila.nombre">
              <td>
                <strong>{{ fila.nombre }}</strong>
                <small v-if="(fila.entidades || []).length">Le compran: {{ fila.entidades.slice(0, 3).join(' · ') }}</small>
                <small v-if="(fila.evolucion || []).length" class="numeros">
                  Por año: {{ fila.evolucion.map((p) => `${p.anio} (${numero(p.n)})`).join(', ') }}
                </small>
              </td>
              <td class="num numeros">
                {{ numero(fila.procesos) }}
                <small v-if="fila.adjudicaciones != null && fila.adjudicaciones !== fila.procesos">
                  {{ numero(fila.adjudicaciones) }} con monto
                </small>
              </td>
              <td class="num numeros">{{ usd(fila.monto) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ¿Qué entidades compran lo mío? -->
    <section v-else-if="seccion === 'entidades'" class="mercado__resultado" :class="{ 'mercado__resultado--cargando': resultado.cargando }">
      <p v-if="resultado.datos?.motivo" class="mercado__vacio">{{ resultado.datos.motivo }}</p>
      <p v-else-if="resultado.datos && !(resultado.datos.filas || []).length" class="mercado__vacio">
        Ninguna entidad publicó procesos de «{{ terminoMostrado || 'todo' }}».
      </p>
      <div v-else-if="(resultado.datos?.filas || []).length" class="tabla bloque">
        <table>
          <thead>
            <tr>
              <th scope="col">Entidad</th>
              <th scope="col" class="num">Procesos</th>
              <th scope="col" class="num">Publicado</th>
              <th scope="col" class="num">Adjudicado</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in resultado.datos.filas" :key="fila.nombre">
              <td>
                <strong>{{ fila.nombre }}</strong>
                <small v-if="(fila.provincias || []).length">{{ fila.provincias.join(', ') }}</small>
                <small v-if="(fila.proveedores || []).length">Le venden: {{ fila.proveedores.slice(0, 3).join(' · ') }}</small>
              </td>
              <td class="num numeros">{{ numero(fila.procesos) }}</td>
              <td class="num numeros">{{ usd(fila.publicado) }}</td>
              <td class="num numeros">{{ usd(fila.adjudicado) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ¿Dónde se compra más? -->
    <section v-else-if="seccion === 'demanda'" class="mercado__resultado" :class="{ 'mercado__resultado--cargando': resultado.cargando }">
      <p v-if="resultado.datos?.motivo" class="mercado__vacio">{{ resultado.datos.motivo }}</p>
      <template v-else-if="resultado.datos">
        <article class="bloque">
          <h4>Provincias</h4>
          <p v-if="!(resultado.datos.provincias || []).length" class="mercado__vacio">No hay procesos para este filtro.</p>
          <ul class="barras">
            <li v-for="fila in resultado.datos.provincias || []" :key="fila.nombre">
              <span class="barras__nombre">{{ fila.nombre }}</span>
              <span class="barras__pista" aria-hidden="true">
                <span class="barras__barra" :style="{ width: ancho(fila.procesos) }" />
              </span>
              <span class="barras__dato numeros">{{ numero(fila.procesos) }} · {{ usd(fila.monto) }}</span>
            </li>
          </ul>
        </article>

        <div class="bloque__tablas">
          <article class="bloque">
            <h4>Cantones</h4>
            <p v-if="!(resultado.datos.cantones || []).length" class="mercado__vacio">
              No hay cantón publicado para este filtro.
            </p>
            <div v-else class="tabla">
              <table>
                <thead>
                  <tr><th scope="col">Cantón</th><th scope="col" class="num">Procesos</th><th scope="col" class="num">Monto</th></tr>
                </thead>
                <tbody>
                  <tr v-for="fila in resultado.datos.cantones.slice(0, 15)" :key="fila.provincia + fila.nombre">
                    <td>{{ fila.nombre }} <small>{{ fila.provincia }}</small></td>
                    <td class="num numeros">{{ numero(fila.procesos) }}</td>
                    <td class="num numeros">{{ usd(fila.monto) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>

          <article v-if="(resultado.datos.categorias || []).length" class="bloque">
            <h4>Lo que más se pide (CPC)</h4>
            <div class="tabla">
              <table>
                <thead>
                  <tr><th scope="col">CPC</th><th scope="col" class="num">Procesos</th><th scope="col"><span class="solo-lectores">Acción</span></th></tr>
                </thead>
                <tbody>
                  <tr v-for="fila in resultado.datos.categorias.slice(0, 15)" :key="fila.nombre">
                    <td class="numeros">{{ fila.nombre }}</td>
                    <td class="num numeros">{{ numero(fila.procesos) }}</td>
                    <td class="num">
                      <button type="button" class="boton boton--fantasma boton--pequeno" @click="preciosDe(fila.nombre)">
                        Ver precios
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </div>
      </template>
    </section>

    <!-- Comparar oportunidades -->
    <section v-else class="mercado__resultado" :class="{ 'mercado__resultado--cargando': resultado.cargando }">
      <div class="mercado__comparacion bloque">
        <header class="bloque__cabecera">
          <h4>Tu selección <span class="mercado__pista numeros">{{ seleccion.length }} de 4</span></h4>
          <button
            class="boton boton--principal boton--pequeno"
            type="button"
            :disabled="seleccion.length < 2 || comparando"
            @click="comparar"
          >
            {{ comparando ? 'Comparando…' : 'Ver lado a lado' }}
          </button>
        </header>
        <p v-if="!seleccion.length" class="mercado__pista">
          Todavía no elegiste ninguno. Usa «Agregar» en la lista de abajo.
        </p>
        <p v-if="aviso" class="mercado__pista" role="status">{{ aviso }}</p>
        <ul v-if="seleccion.length" class="elegidos">
          <li v-for="fila in seleccion" :key="fila.id">
            <span>{{ fila.objeto || fila.codigo }}</span>
            <button type="button" class="boton boton--fantasma boton--pequeno" @click="quitar(fila.id)">Quitar</button>
          </li>
        </ul>

        <div v-if="comparacion?.filas?.length" class="tabla">
          <table class="tabla--comparar">
            <thead>
              <tr>
                <th scope="col"><span class="solo-lectores">Campo</span></th>
                <th v-for="fila in comparacion.filas" :key="fila.id" scope="col" class="numeros">{{ fila.codigo }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="campo in FILAS_COMPARACION" :key="campo.etiqueta">
                <th scope="row">{{ campo.etiqueta }}</th>
                <td v-for="fila in comparacion.filas" :key="fila.id" :class="{ numeros: campo.numeros }">
                  {{ campo.valor(fila) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <p v-if="resultado.datos?.motivo" class="mercado__vacio">{{ resultado.datos.motivo }}</p>
      <p v-else-if="resultado.datos && !(resultado.datos.filas || []).length" class="mercado__vacio">
        Ninguna adjudicación coincide con la búsqueda.
      </p>
      <div v-else-if="(resultado.datos?.filas || []).length" class="tabla bloque">
        <table>
          <caption>Adjudicaciones</caption>
          <thead>
            <tr>
              <th scope="col">Proceso</th>
              <th scope="col">Ganó</th>
              <th scope="col" class="num">Monto</th>
              <th scope="col"><span class="solo-lectores">Acción</span></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="fila in resultado.datos.filas" :key="fila.id">
              <td>
                <strong>{{ fila.objeto || 'Sin objeto publicado' }}</strong>
                <small>
                  {{ [fila.entidad, [fila.canton, fila.provincia].filter(Boolean).join(', '), fechaCorta(fila.fecha_publicacion)]
                    .filter((x) => x && x !== '—')
                    .join(' · ') }}
                </small>
              </td>
              <td>{{ fila.proveedor || '—' }}</td>
              <td class="num numeros">{{ usd(fila.monto) }}</td>
              <td class="num">
                <button
                  type="button"
                  class="boton boton--pequeno"
                  :class="elegida(fila.id) ? 'boton--fantasma' : 'boton--secundario'"
                  :aria-pressed="elegida(fila.id)"
                  @click="elegida(fila.id) ? quitar(fila.id) : agregar(fila)"
                >
                  {{ elegida(fila.id) ? 'Quitar' : 'Agregar' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.mercado {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
}

.mercado__cabecera h2 {
  font-size: var(--t-xl);
}

.mercado__cabecera p {
  margin-top: var(--e-1);
  color: var(--texto-suave);
  font-size: var(--t-md);
}

.mercado__pestanas {
  display: flex;
  gap: var(--e-1);
  overflow-x: auto;
  border-bottom: 1px solid var(--borde);
  scrollbar-width: none;
}

.mercado__pestana {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.6rem 0.9rem;
  margin-bottom: -1px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: none;
  color: var(--texto-suave);
  font-size: var(--t-base);
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
}

.mercado__pestana:hover {
  color: var(--texto);
}

.mercado__pestana--activa {
  border-bottom-color: var(--acento);
  color: var(--texto);
}

.mercado__cuenta {
  min-width: 1.4rem;
  padding: 0 0.4rem;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto-suave);
  font-size: var(--t-xs);
  text-align: center;
}

.mercado__pregunta {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.mercado__pregunta h3 {
  font-size: var(--t-lg);
}

.mercado__ayuda {
  margin-top: var(--e-1);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.buscador {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--e-3);
}

.buscador__termino {
  flex: 2 1 16rem;
}

.buscador__anio {
  flex: 0 1 7rem;
}

.buscador__extra {
  flex: 1 1 10rem;
}

.sugeridos {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1);
  margin-top: calc(var(--e-2) * -1);
}

.sugeridos__titulo {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.sugerido {
  padding: 2px 10px;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: transparent;
  color: var(--texto-suave);
  font-size: var(--t-xs);
  cursor: pointer;
  transition:
    border-color var(--rapido),
    color var(--rapido);
}

.sugerido:hover {
  border-color: var(--acento);
  color: var(--acento-fuerte);
}

.sugerido--activo {
  border-color: var(--acento);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
}

.mercado__error {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.mercado__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.mercado__cargando .esqueleto {
  height: 4.5rem;
  border-radius: var(--r-3);
}

.mercado__resultado {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  transition: opacity var(--rapido);
}

.mercado__resultado--cargando {
  opacity: 0.55;
}

.mercado__vacio {
  padding: var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.mercado__pista {
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  font-weight: 500;
}

/* --- Bloques de resultado --- */
.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4) var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.bloque h4 {
  display: flex;
  align-items: baseline;
  gap: var(--e-2);
  font-size: var(--t-md);
  font-weight: 650;
}

.bloque__cabecera {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.bloque__respuesta {
  font-size: var(--t-md);
}

.bloque__tablas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
  gap: var(--e-4);
}

.bloque__mas summary {
  width: fit-content;
  cursor: pointer;
  color: var(--acento-fuerte);
  font-size: var(--t-sm);
  font-weight: 600;
}

.bloque__mas[open] summary {
  margin-bottom: var(--e-2);
}

.cifras {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--e-3);
  margin: 0;
}

.cifras div {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--e-3);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

.cifras dt {
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

.cifras dd {
  margin: 0;
  font-size: var(--t-lg);
  font-weight: 650;
}

/* --- Tablas sobrias: sin rayado de cebra, líneas finas y cifras alineadas a la derecha --- */
.tabla {
  overflow-x: auto;
}

.tabla table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.tabla caption {
  padding-bottom: var(--e-2);
  text-align: left;
  font-size: var(--t-sm);
  font-weight: 650;
  color: var(--texto);
}

.tabla th,
.tabla td {
  padding: var(--e-2) var(--e-3);
  border-bottom: 1px solid var(--borde);
  text-align: left;
  vertical-align: top;
}

.tabla th {
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-suave);
}

.tabla tbody tr:last-child td,
.tabla tbody tr:last-child th {
  border-bottom: 0;
}

.tabla td strong {
  display: block;
  font-weight: 600;
}

.tabla td small {
  display: block;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.tabla .num {
  text-align: right;
  white-space: nowrap;
}

.tabla--comparar th[scope='row'] {
  width: 9rem;
  white-space: nowrap;
}

.tabla--comparar td {
  min-width: 11rem;
}

/* --- Barras de provincias: un solo color, el de la primera serie --- */
.barras {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.barras li {
  display: grid;
  grid-template-columns: 10rem minmax(0, 1fr) auto;
  gap: var(--e-3);
  align-items: center;
  font-size: var(--t-sm);
}

.barras__pista {
  height: 8px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  overflow: hidden;
}

.barras__barra {
  display: block;
  height: 100%;
  border-radius: var(--r-redondo);
  background: var(--serie-1);
}

.barras__dato {
  color: var(--texto-suave);
  font-size: var(--t-xs);
  white-space: nowrap;
}

.elegidos {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}

.elegidos li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-2) 0;
  font-size: var(--t-sm);
}

.elegidos li + li {
  border-top: 1px solid var(--borde);
}

@media (max-width: 640px) {
  .mercado {
    gap: var(--e-4);
  }

  .bloque {
    padding: var(--e-4);
  }

  .cifras {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .buscador .boton {
    flex: 1 1 100%;
  }

  .barras li {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .barras__pista {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .bloque__tablas {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
