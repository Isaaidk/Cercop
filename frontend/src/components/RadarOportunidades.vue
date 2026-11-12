<script setup>
/**
 * «Oportunidades para ti»: procesos vigentes que se parecen a lo que vende la empresa, y las
 * alertas para enterarse de los nuevos.
 *
 * El cliente dijo que esta parte «no se entiende qué hace». Por eso la pantalla abre con una frase
 * que lo dice y se parte en cuatro pestañas con nombres de lo que el usuario quiere hacer:
 * Recomendadas (mirar), Mis alertas (que me avisen), Avisos (lo que llegó) y Búsquedas guardadas
 * (volver a una búsqueda). Quien viene a ver oportunidades no baja por formularios para llegarles.
 *
 * Eventos:
 * - `preparar(fila)`: abrir «Preparar oferta» con el proceso. Lo emiten las recomendadas y los avisos.
 * - `usar-busqueda(parametros)`: aplicar una búsqueda guardada en «Buscar oportunidades».
 * - `ir-perfil` (opcional): llevar al perfil de la empresa cuando el radar no tiene con qué comparar.
 *   Si el padre no lo escucha, el botón no se muestra y se indica en texto dónde está el perfil:
 *   un botón que no hace nada es peor que ninguno.
 *
 * La puntuación no es una probabilidad de ganar: mide parecido con el perfil. Por eso se enseña
 * como un número discreto con la palabra «coincidencia» y sin semáforo de colores, que haría leer
 * el verde como «vas a ganar».
 */
import { computed, getCurrentInstance, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import ConstructorAlerta from '@/components/ConstructorAlerta.vue'
import { filtros } from '@/stores/filtros'
import { fechaCorta, haceCuanto } from '@/utils/formato'
import { perfilComercial, resumirAlerta, usd } from '@/utils/oportunidades'

const emit = defineEmits(['usar-busqueda', 'preparar', 'ir-perfil'])

// Si el padre escucha `ir-perfil`, Vue deja el manejador en las props del vnode como `onIrPerfil`.
const escuchanPerfil = Boolean(getCurrentInstance()?.vnode.props?.onIrPerfil)

const radar = ref(null)
const avisos = ref([])
const alertas = ref([])
const busquedas = ref([])
const perfil = ref(null)
const cargando = ref(true)
const error = ref('')
const aviso = ref('')
const seccion = ref('recomendadas')

// El constructor se abre solo cuando se pide: la lista de alertas es lo primero que se ve.
const construyendo = ref(false)
const semilla = ref(null)
const nombreBusqueda = ref('')
const marcandoTodos = ref(false)

const oportunidades = computed(() => radar.value?.oportunidades || [])
const sinLeer = computed(() => avisos.value.filter((item) => !item.leido_en).length)

// El radar responde con `motivo` y sin oportunidades cuando el perfil no dice qué vende la empresa.
const perfilIncompleto = computed(
  () => Boolean(radar.value?.motivo) && !oportunidades.value.length,
)

const SECCIONES = computed(() => [
  { id: 'recomendadas', etiqueta: 'Recomendadas', cuenta: oportunidades.value.length, resaltar: false },
  { id: 'alertas', etiqueta: 'Mis alertas', cuenta: alertas.value.length, resaltar: false },
  { id: 'avisos', etiqueta: 'Avisos', cuenta: sinLeer.value, resaltar: sinLeer.value > 0 },
  { id: 'busquedas', etiqueta: 'Búsquedas guardadas', cuenta: busquedas.value.length, resaltar: false },
])

// Los avisos sin leer van primero; dentro de cada grupo, lo más reciente arriba.
const avisosOrdenados = computed(() =>
  [...avisos.value].sort((a, b) => {
    if (!a.leido_en !== !b.leido_en) return a.leido_en ? 1 : -1
    return String(b.creado_en || '').localeCompare(String(a.creado_en || ''))
  }),
)

const nombresAlerta = computed(() => Object.fromEntries(alertas.value.map((a) => [a.id, a.nombre])))

const FRECUENCIAS = { inmediata: 'Al instante', diaria: 'Diaria', semanal: 'Semanal' }

function avisosDe(alertaId) {
  return avisos.value.filter((item) => item.alerta_id === alertaId).length
}

function lugar(fila) {
  return [fila.canton, fila.provincia].filter(Boolean).join(', ')
}

/** Los motivos como una línea corta: los tres factores que más suman, sin barras ni colores. */
function motivos(fila) {
  return (fila.compatibilidad?.factores || [])
    .filter((f) => f.puntos > 0)
    .sort((a, b) => b.puntos - a.puntos)
    .slice(0, 3)
    .map((f) => f.motivo)
}

/** El aviso trae «72/100. Coincide con…»; el número ya se muestra aparte. */
function detalleAviso(item) {
  return String(item.detalle || '').replace(/^\s*\d+\/100\.\s*/, '')
}

function abrirConstructor(desde = null) {
  semilla.value = desde
  construyendo.value = true
  seccion.value = 'alertas'
}

async function alCrearAlerta(nombre) {
  construyendo.value = false
  semilla.value = null
  aviso.value = `Alerta «${nombre}» creada. Cuando aparezca un proceso que la cumpla, lo verás en «Avisos».`
  await cargar()
}

async function cargar() {
  error.value = ''
  try {
    const [resultado, bandeja, propias, guardadas] = await Promise.all([
      api.verRadar(),
      api.listarAvisos(),
      api.listarAlertas(),
      api.listarBusquedas(),
    ])
    radar.value = resultado
    avisos.value = bandeja.avisos || []
    alertas.value = propias.alertas || []
    busquedas.value = guardadas.busquedas || []
    // Solo si el radar no tiene con qué comparar se lee el perfil, para decir qué le falta.
    if (perfilIncompleto.value && !perfil.value) await cargarPerfil()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

async function cargarPerfil() {
  const [ficha, claves] = await Promise.allSettled([api.verPerfil(), api.listarCpc()])
  perfil.value = perfilComercial(
    ficha.status === 'fulfilled' ? ficha.value : null,
    claves.status === 'fulfilled' ? claves.value?.claves : null,
  )
}

const faltantes = computed(() => {
  const p = perfil.value
  return [
    { id: 'cpc', texto: 'Códigos CPC de lo que vendes', listo: Boolean(p?.cpc.length) },
    { id: 'productos', texto: 'Productos o servicios que ofreces', listo: Boolean(p?.productos.length) },
    { id: 'palabras', texto: 'Palabras clave de tu rubro', listo: Boolean(p?.palabras.length) },
  ]
})

async function guardarBusqueda() {
  error.value = ''
  try {
    await api.guardarBusqueda(nombreBusqueda.value, { ...filtros.parametros.value })
    nombreBusqueda.value = ''
    aviso.value = 'Búsqueda guardada.'
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  }
}

function usar(busqueda) {
  emit('usar-busqueda', busqueda.parametros || {})
}

/** Se marca en pantalla al momento y se avisa al servidor; si falla, se recarga lo real. */
async function leer(item) {
  if (item.leido_en) return
  item.leido_en = new Date().toISOString()
  try {
    await api.leerAviso(item.id)
  } catch (fallo) {
    error.value = fallo.message
    await cargar()
  }
}

// No hay un endpoint para «todos»: se marca cada uno con la llamada que ya existe.
async function leerTodos() {
  marcandoTodos.value = true
  error.value = ''
  const pendientes = avisos.value.filter((item) => !item.leido_en)
  const resultados = await Promise.allSettled(pendientes.map((item) => api.leerAviso(item.id)))
  if (resultados.some((r) => r.status === 'rejected')) {
    error.value = 'Algunos avisos no se pudieron marcar. Inténtalo de nuevo.'
  }
  marcandoTodos.value = false
  await cargar()
}

function prepararDesdeAviso(item) {
  leer(item)
  emit('preparar', { codigo: item.codigo })
}

async function quitar(llamada) {
  error.value = ''
  try {
    await llamada()
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  }
}

onMounted(cargar)
</script>

<template>
  <div class="radar">
    <header class="radar__cabecera">
      <h2>Oportunidades para ti</h2>
      <p>Procesos vigentes que se parecen a lo que vende tu empresa, y alertas para enterarte de los nuevos.</p>
    </header>

    <p v-if="error" class="radar__mensaje radar__mensaje--error" role="alert">{{ error }}</p>
    <p v-if="aviso" class="radar__mensaje" role="status">
      {{ aviso }}
      <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Cerrar mensaje" @click="aviso = ''">
        ×
      </button>
    </p>

    <nav class="radar__pestanas" role="tablist" aria-label="Secciones de oportunidades">
      <button
        v-for="opcion in SECCIONES"
        :key="opcion.id"
        type="button"
        role="tab"
        class="radar__pestana"
        :class="{ 'radar__pestana--activa': seccion === opcion.id }"
        :aria-selected="seccion === opcion.id"
        @click="seccion = opcion.id"
      >
        {{ opcion.etiqueta }}
        <span
          v-if="opcion.cuenta"
          class="radar__cuenta numeros"
          :class="{ 'radar__cuenta--resaltada': opcion.resaltar }"
          :aria-label="opcion.resaltar ? `${opcion.cuenta} sin leer` : undefined"
        >
          {{ opcion.cuenta }}
        </span>
      </button>
    </nav>

    <!-- Cargando -->
    <div v-if="cargando" class="radar__lista" aria-busy="true" aria-label="Cargando oportunidades">
      <div v-for="n in 3" :key="n" class="esqueleto radar__esqueleto" />
    </div>

    <!-- Recomendadas -->
    <section v-else-if="seccion === 'recomendadas'" class="radar__lista" aria-label="Recomendadas">
      <!-- Perfil sin datos: el radar no tiene con qué comparar. Se dice qué falta y dónde ponerlo. -->
      <div v-if="perfilIncompleto" class="vacio">
        <h3>Cuéntanos qué vende tu empresa</h3>
        <p>
          Para recomendarte procesos, comparamos cada uno con tu perfil. Ahora mismo no tiene con qué
          comparar. Completa al menos una de estas tres cosas:
        </p>
        <ul class="vacio__lista">
          <li v-for="item in faltantes" :key="item.id" :class="{ 'vacio__item--listo': item.listo }">
            <span class="vacio__marca" aria-hidden="true">{{ item.listo ? '✓' : '○' }}</span>
            {{ item.texto }}
            <span class="solo-lectores">{{ item.listo ? '(ya está)' : '(falta)' }}</span>
          </li>
        </ul>
        <div class="vacio__acciones">
          <button v-if="escuchanPerfil" type="button" class="boton boton--principal" @click="emit('ir-perfil')">
            Completar mi perfil
          </button>
          <p v-else class="radar__nota">Lo encuentras en «Mi empresa › Perfil».</p>
          <button type="button" class="boton boton--secundario" @click="abrirConstructor()">
            Mientras tanto, crear una alerta
          </button>
        </div>
      </div>

      <template v-else>
        <div class="radar__barra">
          <p class="radar__nota">
            {{ oportunidades.length
              ? `${oportunidades.length} procesos vigentes, del más parecido a tu perfil al menos parecido.`
              : '' }}
          </p>
          <details v-if="radar?.aviso" class="ayuda">
            <summary>¿Qué es la coincidencia?</summary>
            <p>{{ radar.aviso }}</p>
          </details>
        </div>

        <article v-for="fila in oportunidades" :key="fila.id" class="oportunidad">
          <div class="oportunidad__cuerpo">
            <h3>{{ fila.objeto || 'Sin objeto publicado' }}</h3>
            <p class="oportunidad__meta">
              <span v-if="fila.entidad">{{ fila.entidad }}</span>
              <span v-if="lugar(fila)">{{ lugar(fila) }}</span>
              <span v-if="usd(fila.presupuesto) !== '—'" class="numeros">{{ usd(fila.presupuesto) }}</span>
              <span v-if="fila.fecha_publicacion">Publicado {{ fechaCorta(fila.fecha_publicacion) }}</span>
            </p>
            <p v-if="motivos(fila).length" class="oportunidad__motivos">
              <span class="solo-lectores">Por qué se parece: </span>{{ motivos(fila).join(' · ') }}
            </p>
            <details class="oportunidad__detalle">
              <summary>Cómo se calculó</summary>
              <ul>
                <li v-for="factor in fila.compatibilidad.factores" :key="factor.codigo">
                  <span class="numeros oportunidad__puntos">{{ factor.puntos }}/{{ factor.de }}</span>
                  {{ factor.motivo }}
                </li>
              </ul>
            </details>
          </div>
          <div class="oportunidad__lado">
            <p class="oportunidad__nota">
              <strong class="numeros">{{ fila.compatibilidad.puntos }}</strong>
              <span>coincidencia</span>
            </p>
            <p class="oportunidad__codigo numeros">{{ fila.codigo }}</p>
            <button class="boton boton--principal boton--pequeno" type="button" @click="emit('preparar', fila)">
              Preparar oferta
            </button>
          </div>
        </article>

        <div v-if="radar && !oportunidades.length" class="vacio">
          <h3>Hoy no hay procesos vigentes parecidos a tu perfil</h3>
          <p>Crea una alerta y te avisaremos cuando se publique uno.</p>
          <div class="vacio__acciones">
            <button type="button" class="boton boton--principal" @click="abrirConstructor()">Crear una alerta</button>
          </div>
        </div>
      </template>
    </section>

    <!-- Mis alertas -->
    <section v-else-if="seccion === 'alertas'" class="radar__lista" aria-label="Mis alertas">
      <ConstructorAlerta
        v-if="construyendo"
        :key="semilla?.id || 'nueva'"
        :semilla="semilla"
        @creada="alCrearAlerta"
        @cancelar="construyendo = false"
      />

      <template v-else>
        <div v-if="alertas.length" class="radar__barra">
          <p class="radar__nota">Te avisamos en «Avisos» cuando aparece un proceso que cumple cada alerta.</p>
          <button type="button" class="boton boton--principal" @click="abrirConstructor()">Nueva alerta</button>
        </div>

        <article v-for="item in alertas" :key="item.id" class="alerta">
          <div class="alerta__cuerpo">
            <h3>
              {{ item.nombre }}
              <span class="etiqueta">{{ FRECUENCIAS[item.frecuencia] || item.frecuencia }}</span>
            </h3>
            <p class="alerta__frase">{{ resumirAlerta(item) }}</p>
            <p class="radar__nota">
              {{ avisosDe(item.id) ? `${avisosDe(item.id)} avisos recibidos` : 'Sin avisos todavía' }}
            </p>
          </div>
          <div class="alerta__acciones">
            <button
              v-if="avisosDe(item.id)"
              type="button"
              class="boton boton--secundario boton--pequeno"
              @click="seccion = 'avisos'"
            >
              Ver avisos
            </button>
            <button type="button" class="boton boton--fantasma boton--pequeno" @click="abrirConstructor(item)">
              Duplicar y ajustar
            </button>
            <button type="button" class="boton boton--peligro boton--pequeno" @click="quitar(() => api.quitarAlerta(item.id))">
              Quitar
            </button>
          </div>
        </article>

        <div v-if="!alertas.length" class="vacio">
          <h3>Aún no tienes alertas</h3>
          <p>Elige palabras o códigos CPC y te avisaremos cuando se publique un proceso que los cumpla.</p>
          <div class="vacio__acciones">
            <button type="button" class="boton boton--principal" @click="abrirConstructor()">
              Crear mi primera alerta
            </button>
          </div>
        </div>
      </template>
    </section>

    <!-- Avisos -->
    <section v-else-if="seccion === 'avisos'" class="radar__lista" aria-label="Avisos">
      <div v-if="avisos.length" class="radar__barra">
        <p class="radar__nota">
          {{ sinLeer ? `${sinLeer} sin leer de ${avisos.length}.` : 'Todo leído.' }}
        </p>
        <button
          v-if="sinLeer > 1"
          type="button"
          class="boton boton--fantasma boton--pequeno"
          :disabled="marcandoTodos"
          @click="leerTodos"
        >
          {{ marcandoTodos ? 'Marcando…' : 'Marcar todos como leídos' }}
        </button>
      </div>

      <ul v-if="avisos.length" class="avisos">
        <li v-for="item in avisosOrdenados" :key="item.id" class="aviso" :class="{ 'aviso--leido': item.leido_en }">
          <span class="aviso__punto" aria-hidden="true" />
          <div class="aviso__cuerpo">
            <p class="aviso__titulo">
              <span v-if="!item.leido_en" class="solo-lectores">Sin leer: </span>{{ item.titulo }}
            </p>
            <p class="aviso__meta">
              <span v-if="item.puntuacion" class="numeros">{{ item.puntuacion }} coincidencia</span>
              <span v-if="nombresAlerta[item.alerta_id]">Alerta «{{ nombresAlerta[item.alerta_id] }}»</span>
              <span v-if="item.creado_en">{{ haceCuanto(item.creado_en) }}</span>
            </p>
            <p v-if="detalleAviso(item)" class="aviso__detalle">{{ detalleAviso(item) }}</p>
          </div>
          <div class="aviso__acciones">
            <!-- Del aviso directo a la proforma: abre «Preparar oferta» con el proceso ya cargado. -->
            <button
              v-if="item.codigo"
              type="button"
              class="boton boton--principal boton--pequeno"
              @click="prepararDesdeAviso(item)"
            >
              Preparar proforma
            </button>
            <button
              v-if="!item.leido_en"
              type="button"
              class="boton boton--fantasma boton--pequeno"
              @click="leer(item)"
            >
              Marcar leído
            </button>
          </div>
        </li>
      </ul>
      <div v-else class="vacio">
        <h3>No hay avisos</h3>
        <p>Cuando se publique un proceso que cumpla una de tus alertas, aparecerá aquí.</p>
        <div class="vacio__acciones">
          <button type="button" class="boton boton--secundario" @click="seccion = 'alertas'">Ver mis alertas</button>
        </div>
      </div>
    </section>

    <!-- Búsquedas guardadas -->
    <section v-else class="radar__lista" aria-label="Búsquedas guardadas">
      <p class="radar__nota">Filtros de «Buscar oportunidades» que guardaste para volver a usarlos con un clic.</p>
      <ul v-if="busquedas.length" class="avisos">
        <li v-for="item in busquedas" :key="item.id" class="aviso aviso--simple">
          <div class="aviso__cuerpo">
            <p class="aviso__titulo">{{ item.nombre }}</p>
          </div>
          <div class="aviso__acciones">
            <button type="button" class="boton boton--secundario boton--pequeno" @click="usar(item)">Usar</button>
            <button
              type="button"
              class="boton boton--peligro boton--pequeno"
              @click="quitar(() => api.quitarBusqueda(item.id))"
            >
              Quitar
            </button>
          </div>
        </li>
      </ul>
      <p v-else class="radar__nota">Aún no tienes búsquedas guardadas.</p>

      <form class="guardar" @submit.prevent="guardarBusqueda">
        <h3>Guardar los filtros actuales</h3>
        <p class="radar__nota">
          {{ filtros.hayFiltros.value
            ? 'Se guardan los filtros que dejaste puestos en «Buscar oportunidades».'
            : 'Ahora no hay filtros puestos. Ponlos primero en «Buscar oportunidades» y vuelve aquí.' }}
        </p>
        <div class="guardar__fila">
          <label class="campo guardar__campo">
            <span class="campo__etiqueta">Nombre</span>
            <input v-model="nombreBusqueda" class="entrada" placeholder="Ej. Pichincha vigente" required minlength="2" />
          </label>
          <button class="boton boton--principal" type="submit">Guardar búsqueda</button>
        </div>
      </form>
    </section>
  </div>
</template>

<style scoped>
.radar {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
}

.radar__cabecera h2 {
  font-size: var(--t-xl);
}

.radar__cabecera p {
  margin-top: var(--e-1);
  color: var(--texto-suave);
  font-size: var(--t-md);
}

.radar__nota {
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.radar__mensaje {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-2) var(--e-2) var(--e-2) var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  font-size: var(--t-sm);
}

.radar__mensaje--error {
  padding: var(--e-3) var(--e-4);
  border-color: transparent;
  background: var(--error-suave);
  color: var(--error);
}

.radar__pestanas {
  display: flex;
  gap: var(--e-1);
  overflow-x: auto;
  border-bottom: 1px solid var(--borde);
  scrollbar-width: none;
}

.radar__pestana {
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

.radar__pestana:hover {
  color: var(--texto);
}

.radar__pestana--activa {
  border-bottom-color: var(--acento);
  color: var(--texto);
}

.radar__cuenta {
  min-width: 1.4rem;
  padding: 0 0.4rem;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto-suave);
  font-size: var(--t-xs);
  font-weight: 650;
  text-align: center;
}

.radar__cuenta--resaltada {
  background: var(--acento);
  color: #fff;
}

.radar__lista {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.radar__esqueleto {
  height: 6.5rem;
  border-radius: var(--r-3);
}

.radar__barra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--e-2) var(--e-4);
}

/* --- Estado vacío guiado --- */
.vacio {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--e-3);
  padding: var(--e-6) var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.vacio h3 {
  font-size: var(--t-lg);
}

.vacio p {
  max-width: 38rem;
  color: var(--texto-suave);
}

.vacio__lista {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.vacio__lista li {
  display: flex;
  align-items: center;
  gap: var(--e-2);
}

.vacio__marca {
  width: 1.2rem;
  color: var(--texto-tenue);
  text-align: center;
}

.vacio__item--listo {
  color: var(--texto-suave);
}

.vacio__item--listo .vacio__marca {
  color: var(--ok);
}

.vacio__acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-3);
  margin-top: var(--e-2);
}

/* --- Tarjeta de oportunidad --- */
.oportunidad {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--e-5);
  padding: var(--e-4) var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  transition: box-shadow var(--normal) var(--curva);
}

.oportunidad:hover {
  box-shadow: var(--sombra-2);
}

.oportunidad__cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  min-width: 0;
}

.oportunidad h3 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.4;
}

.oportunidad__meta,
.aviso__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1) var(--e-3);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.oportunidad__motivos {
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.oportunidad__detalle summary {
  width: fit-content;
  cursor: pointer;
  color: var(--acento-fuerte);
  font-size: var(--t-xs);
  font-weight: 600;
}

.oportunidad__detalle ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: var(--e-2) 0 0;
  padding: 0;
  list-style: none;
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.oportunidad__puntos {
  display: inline-block;
  min-width: 3rem;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.oportunidad__lado {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--e-2);
}

.oportunidad__nota {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  line-height: 1.1;
}

.oportunidad__nota strong {
  font-size: var(--t-xl);
  font-weight: 650;
  color: var(--texto);
}

.oportunidad__nota span,
.oportunidad__codigo {
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

/* --- Alertas --- */
.alerta {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.alerta__cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  min-width: 0;
}

.alerta__cuerpo h3 {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-md);
  font-weight: 600;
}

.alerta__frase {
  color: var(--texto);
  font-size: var(--t-sm);
}

.alerta__acciones,
.aviso__acciones {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--e-2);
  flex: none;
}

/* --- Avisos y búsquedas --- */
.avisos {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.aviso {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
}

.aviso--simple {
  grid-template-columns: minmax(0, 1fr) auto;
}

.aviso + .aviso {
  border-top: 1px solid var(--borde);
}

.aviso__punto {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--acento);
}

.aviso--leido .aviso__punto {
  background: transparent;
}

.aviso--leido .aviso__titulo {
  font-weight: 450;
  color: var(--texto-suave);
}

.aviso__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.aviso__titulo {
  font-weight: 600;
  overflow-wrap: anywhere;
}

.aviso__meta {
  font-size: var(--t-xs);
}

.aviso__detalle {
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.guardar {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin-top: var(--e-4);
}

.guardar h3 {
  font-size: var(--t-md);
}

.guardar__fila {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--e-3);
}

.guardar__campo {
  flex: 1 1 16rem;
  max-width: 24rem;
}

@media (max-width: 640px) {
  .radar {
    gap: var(--e-4);
  }

  .oportunidad,
  .alerta {
    grid-template-columns: 1fr;
    flex-direction: column;
    padding: var(--e-4);
    gap: var(--e-3);
  }

  .alerta {
    align-items: stretch;
  }

  .oportunidad__lado {
    flex-direction: row;
    align-items: center;
  }

  .oportunidad__nota {
    flex-direction: row;
    align-items: baseline;
    gap: var(--e-1);
  }

  .oportunidad__nota strong {
    font-size: var(--t-lg);
  }

  .oportunidad__codigo {
    flex: 1;
  }

  .aviso {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .aviso--simple {
    grid-template-columns: minmax(0, 1fr);
  }

  .aviso__acciones,
  .alerta__acciones {
    grid-column: 1 / -1;
    justify-content: flex-start;
  }

  .vacio {
    padding: var(--e-5) var(--e-4);
  }

  .guardar__campo {
    max-width: none;
  }
}
</style>
