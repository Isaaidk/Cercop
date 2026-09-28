<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Bar, Doughnut, Pie } from 'vue-chartjs'
import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  Tooltip,
} from 'chart.js'
import { obtenerEstadisticas, urlExportarNecesidades } from '../services/api'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend)

const PALETA = [
  '#0b4f9e', '#12813f', '#c2410c', '#7c3aed', '#0e7490', '#b45309',
  '#be123c', '#4d7c0f', '#1d4ed8', '#a16207', '#0891b2', '#9333ea',
  '#dc2626', '#65a30d', '#0f766e', '#9d174d', '#2563eb', '#ea580c',
  '#4b5563', '#0369a1',
]

const filtros = reactive({
  q: '',
  modo: 'todas',
  provincia: '',
  canton: '',
  estado: '',
  tipo: '',
  fecha_desde: '',
  fecha_hasta: '',
  top: 12,
})

const estadisticas = ref({
  total: 0,
  cantones_distintos: 0,
  provincias_distintas: 0,
  por_vencer_24h: 0,
  por_canton: [],
  por_provincia: [],
  por_estado: [],
  por_tipo: [],
  por_dia: [],
  vencimientos: [],
})

const catalogo = ref({ provincias: [], estados: [], tipos: [], cantones: [] })
const cargando = ref(false)
const error = ref('')
let temporizador = null

const OPCIONES_BASE = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'right',
      labels: { boxWidth: 12, font: { size: 11 } },
    },
    tooltip: {
      callbacks: {
        label: (contexto) => {
          const valor = contexto.parsed?.y ?? contexto.parsed
          const total = contexto.dataset.data.reduce((suma, item) => suma + item, 0) || 1
          const porcentaje = ((valor * 100) / total).toFixed(1)
          return ` ${valor.toLocaleString('es-EC')} (${porcentaje} %)`
        },
      },
    },
  },
}

const opcionesPie = { ...OPCIONES_BASE }
const opcionesBarra = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: { legend: { display: false } },
  scales: {
    y: { beginAtZero: true, ticks: { precision: 0 } },
    x: { ticks: { autoSkip: false, maxRotation: 60, minRotation: 30, font: { size: 10 } } },
  },
}

const color = (indice) => PALETA[indice % PALETA.length]

/** Convierte las filas {etiqueta,total} en un dataset de pastel. */
const aPastel = (filas) => ({
  labels: filas.map((fila) => fila.etiqueta),
  datasets: [
    {
      data: filas.map((fila) => fila.total),
      backgroundColor: filas.map((_, indice) => color(indice)),
      borderColor: '#ffffff',
      borderWidth: 2,
    },
  ],
})

const datosCantones = computed(() => aPastel(estadisticas.value.por_canton || []))
const datosProvincias = computed(() => aPastel(estadisticas.value.por_provincia || []))
const datosEstado = computed(() => aPastel(estadisticas.value.por_estado || []))
const datosTipo = computed(() => aPastel(estadisticas.value.por_tipo || []))

const datosDias = computed(() => ({
  labels: (estadisticas.value.por_dia || []).map((fila) => fila.fecha.slice(5)),
  datasets: [
    {
      label: 'Necesidades publicadas',
      data: (estadisticas.value.por_dia || []).map((fila) => fila.total),
      backgroundColor: '#0b4f9e',
      borderRadius: 5,
    },
  ],
}))

const COLORES_VENCIMIENTO = {
  'Vence en 24 h': '#dc2626',
  '1 a 3 días': '#ea580c',
  '3 a 7 días': '#a16207',
  '1 a 2 semanas': '#0e7490',
  'Más de 2 semanas': '#12813f',
  'Plazo vencido': '#4b5563',
}

const datosVencimientos = computed(() => ({
  labels: (estadisticas.value.vencimientos || []).map((fila) => fila.etiqueta),
  datasets: [
    {
      label: 'Necesidades',
      data: (estadisticas.value.vencimientos || []).map((fila) => fila.total),
      backgroundColor: (estadisticas.value.vencimientos || []).map(
        (fila) => COLORES_VENCIMIENTO[fila.etiqueta] || '#0b4f9e'
      ),
      borderRadius: 5,
    },
  ],
}))

const hayDatos = computed(() => (estadisticas.value.total || 0) > 0)

const cargar = async () => {
  cargando.value = true
  error.value = ''
  try {
    const respuesta = await obtenerEstadisticas(filtros)
    estadisticas.value = respuesta
    if (!catalogo.value.provincias.length) {
      catalogo.value = {
        provincias: (respuesta.por_provincia || []).map((fila) => fila.etiqueta),
        cantones: (respuesta.por_canton || []).map((fila) => fila.etiqueta),
        estados: (respuesta.por_estado || []).map((fila) => fila.etiqueta),
        tipos: (respuesta.por_tipo || []).map((fila) => fila.etiqueta),
      }
    }
  } catch (excepcion) {
    error.value =
      excepcion?.response?.data?.detail ||
      'No se pudieron obtener los datos para las gráficas. Verifique el backend.'
  } finally {
    cargando.value = false
  }
}

watch(
  filtros,
  () => {
    clearTimeout(temporizador)
    temporizador = setTimeout(cargar, 350)
  },
  { deep: true }
)

const limpiar = () => {
  Object.assign(filtros, {
    q: '',
    modo: 'todas',
    provincia: '',
    canton: '',
    estado: '',
    tipo: '',
    fecha_desde: '',
    fecha_hasta: '',
    top: 12,
  })
}

const exportar = () =>
  window.open(urlExportarNecesidades({ ...filtros, orden: 'fecha_publicacion', dir: 'desc' }), '_blank')

onMounted(cargar)
</script>

<template>
  <section class="panel">
    <h2>Filtros de las gráficas</h2>

    <div class="rejilla-filtros">
      <div class="campo ancho">
        <label>Palabras clave (separe con comas)</label>
        <input type="text" v-model="filtros.q" placeholder="Ej: mantenimiento, medicamentos" />
      </div>

      <div class="campo">
        <label>Coincidencia</label>
        <select v-model="filtros.modo">
          <option value="todas">Contiene todas las palabras</option>
          <option value="cualquiera">Contiene alguna palabra</option>
        </select>
      </div>

      <div class="campo">
        <label>Provincia</label>
        <input type="text" v-model="filtros.provincia" placeholder="Ej: PICHINCHA" list="prov-graf" />
        <datalist id="prov-graf">
          <option v-for="provincia in catalogo.provincias" :key="provincia" :value="provincia" />
        </datalist>
      </div>

      <div class="campo">
        <label>Cantón</label>
        <input type="text" v-model="filtros.canton" placeholder="Ej: QUITO" />
      </div>

      <div class="campo">
        <label>Estado de la necesidad</label>
        <select v-model="filtros.estado">
          <option value="">Todos los estados</option>
          <option v-for="estado in catalogo.estados" :key="estado" :value="estado">{{ estado }}</option>
        </select>
      </div>

      <div class="campo">
        <label>Tipo de necesidad</label>
        <select v-model="filtros.tipo">
          <option value="">Todos los tipos</option>
          <option v-for="tipo in catalogo.tipos" :key="tipo" :value="tipo">{{ tipo }}</option>
        </select>
      </div>

      <div class="campo">
        <label>Publicadas desde</label>
        <input type="date" v-model="filtros.fecha_desde" />
      </div>

      <div class="campo">
        <label>Publicadas hasta</label>
        <input type="date" v-model="filtros.fecha_hasta" />
      </div>

      <div class="campo">
        <label>Cantones a mostrar</label>
        <input type="number" min="3" max="40" v-model.number="filtros.top" />
      </div>
    </div>

    <div class="acciones">
      <button class="btn" @click="limpiar" :disabled="cargando">Limpiar filtros</button>
      <button class="btn verde" @click="exportar">⬇️ Exportar datos</button>
      <span class="nota" v-if="estadisticas.actualizado">
        Datos al {{ estadisticas.actualizado }}
      </span>
      <span class="nota" v-if="cargando">Actualizando gráficas…</span>
    </div>

    <p v-if="error" class="mensaje error">{{ error }}</p>
  </section>

  <section class="tarjetas">
    <div class="tarjeta">
      <span class="titulo">Necesidades</span>
      <strong>{{ (estadisticas.total || 0).toLocaleString('es-EC') }}</strong>
      <span class="detalle">según los filtros</span>
    </div>
    <div class="tarjeta">
      <span class="titulo">Cantones</span>
      <strong>{{ (estadisticas.cantones_distintos || 0).toLocaleString('es-EC') }}</strong>
      <span class="detalle">con necesidades</span>
    </div>
    <div class="tarjeta">
      <span class="titulo">Provincias</span>
      <strong>{{ (estadisticas.provincias_distintas || 0).toLocaleString('es-EC') }}</strong>
      <span class="detalle">con necesidades</span>
    </div>
    <div class="tarjeta alerta">
      <span class="titulo">Proformas que vencen en 24 h</span>
      <strong>{{ (estadisticas.por_vencer_24h || 0).toLocaleString('es-EC') }}</strong>
      <span class="detalle">requieren atención inmediata</span>
    </div>
  </section>

  <section class="graficas" v-if="hayDatos">
    <div class="grafica ancha">
      <h3>
        Ínfimas Cuantías por cantón
        <small>Top {{ estadisticas.top || filtros.top }} cantones y agrupación del resto</small>
      </h3>
      <div class="lienzo alto">
        <Pie :data="datosCantones" :options="opcionesPie" />
      </div>
    </div>

    <div class="grafica">
      <h3>
        Por provincia
        <small>Distribución geográfica</small>
      </h3>
      <div class="lienzo">
        <Pie :data="datosProvincias" :options="opcionesPie" />
      </div>
    </div>

    <div class="grafica">
      <h3>
        Estado de la necesidad
        <small>En Curso / Finalizada</small>
      </h3>
      <div class="lienzo">
        <Doughnut :data="datosEstado" :options="opcionesPie" />
      </div>
    </div>

    <div class="grafica">
      <h3>
        Tipo de necesidad
        <small>Ínfimas Cuantías / Contratación</small>
      </h3>
      <div class="lienzo">
        <Doughnut :data="datosTipo" :options="opcionesPie" />
      </div>
    </div>

    <div class="grafica">
      <h3>
        Vencimiento de proformas
        <small>Días restantes para entregar proformas</small>
      </h3>
      <div class="lienzo">
        <Bar :data="datosVencimientos" :options="opcionesBarra" />
      </div>
    </div>

    <div class="grafica ancha">
      <h3>
        Publicaciones por día
        <small>Últimos {{ estadisticas.dias_serie || 30 }} días</small>
      </h3>
      <div class="lienzo">
        <Bar :data="datosDias" :options="opcionesBarra" />
      </div>
    </div>
  </section>

  <section class="panel" v-else-if="!cargando && !error">
    <p class="vacio">No hay necesidades que coincidan con los filtros seleccionados.</p>
  </section>
</template>

<style scoped>
.panel {
  background: #fff;
  border-radius: 14px;
  box-shadow: var(--sombra);
  padding: 20px 22px;
  margin-bottom: 20px;
}

.panel h2 {
  font-size: 1.05em;
  color: var(--azul-oscuro);
  margin-bottom: 14px;
}

.rejilla-filtros {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 14px;
}

.campo {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.campo.ancho {
  grid-column: span 2;
}

.campo label {
  font-size: 0.82em;
  font-weight: 600;
  color: var(--gris-700);
}

input,
select {
  padding: 9px 11px;
  border: 1px solid var(--gris-200);
  border-radius: 8px;
  font-size: 0.92em;
  background: #fff;
  color: inherit;
  width: 100%;
}

.acciones {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 16px;
}

.btn {
  padding: 10px 18px;
  border: 1px solid var(--gris-200);
  background: #fff;
  border-radius: 9px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9em;
}

.btn:hover:not(:disabled) {
  border-color: var(--azul);
  color: var(--azul);
}

.btn.verde {
  background: var(--verde);
  border-color: var(--verde);
  color: #fff;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.nota {
  font-size: 0.8em;
  color: var(--gris-400);
}

.mensaje {
  margin: 14px 0 0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 0.88em;
}

.mensaje.error {
  background: var(--rojo-claro);
  color: var(--rojo);
  border-left: 4px solid var(--rojo);
}

.tarjetas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
}

.tarjeta {
  background: #fff;
  border-radius: 14px;
  box-shadow: var(--sombra);
  padding: 18px 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-left: 5px solid var(--azul);
}

.tarjeta.alerta {
  border-left-color: var(--rojo);
}

.tarjeta .titulo {
  font-size: 0.8em;
  font-weight: 700;
  color: var(--gris-700);
  text-transform: uppercase;
  letter-spacing: 0.4px;
}

.tarjeta strong {
  font-size: 1.9em;
  color: var(--azul-oscuro);
  line-height: 1.1;
}

.tarjeta.alerta strong {
  color: var(--rojo);
}

.tarjeta .detalle {
  font-size: 0.78em;
  color: var(--gris-400);
}

.graficas {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 18px;
}

.grafica {
  background: #fff;
  border-radius: 14px;
  box-shadow: var(--sombra);
  padding: 16px 18px 18px;
}

.grafica.ancha {
  grid-column: 1 / -1;
}

.grafica h3 {
  font-size: 0.95em;
  color: var(--azul-oscuro);
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.grafica h3 small {
  font-weight: 500;
  font-size: 0.78em;
  color: var(--gris-400);
}

.lienzo {
  position: relative;
  height: 280px;
}

.lienzo.alto {
  height: 400px;
}

.vacio {
  text-align: center;
  color: var(--gris-400);
  padding: 30px;
  margin: 0;
}

@media (max-width: 720px) {
  .lienzo,
  .lienzo.alto {
    height: 260px;
  }
}
</style>
