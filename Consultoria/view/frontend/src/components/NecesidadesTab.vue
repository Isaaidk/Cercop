<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import EtiquetaEstado from './EtiquetaEstado.vue'
import Paginacion from './Paginacion.vue'
import {
  actualizarNecesidades,
  buscarNecesidades,
  obtenerCatalogo,
  urlExportarNecesidades,
} from '../services/api'

const PALABRAS_RAPIDAS = [
  'medicamentos',
  'mantenimiento',
  'alimentación',
  'construcción',
  'transporte',
  'combustible',
  'aseo',
  'tecnología',
  'seguridad',
  'materiales',
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
  solo_vigentes: false,
  por_vencer_horas: '',
})

const pagina = ref(1)
const porPagina = ref(25)
const orden = ref('fecha_publicacion')
const dir = ref('desc')

const datos = ref([])
const catalogo = ref({ provincias: [], cantones: [], estados: [], tipos: [], total: 0 })
const total = ref(0)
const totalPaginas = ref(1)
const cargando = ref(false)
const actualizando = ref(false)
const error = ref('')
const aviso = ref('')

let temporizador = null

/** Cantones que pertenecen a la provincia seleccionada. */
const cantonesDisponibles = computed(() => {
  const filas = catalogo.value.cantones || []
  const provincia = filtros.provincia
  const filtradas = provincia
    ? filas.filter((fila) => fila.provincia === provincia)
    : filas
  return [...new Set(filtradas.map((fila) => fila.canton))].filter(Boolean).sort()
})

const parametrosConsulta = computed(() => ({
  q: filtros.q,
  modo: filtros.modo,
  provincia: filtros.provincia,
  canton: filtros.canton,
  estado: filtros.estado,
  tipo: filtros.tipo,
  fecha_desde: filtros.fecha_desde,
  fecha_hasta: filtros.fecha_hasta,
  solo_vigentes: filtros.solo_vigentes ? true : '',
  por_vencer_horas: filtros.por_vencer_horas,
  orden: orden.value,
  dir: dir.value,
}))

const buscar = async () => {
  cargando.value = true
  error.value = ''
  try {
    const respuesta = await buscarNecesidades({
      ...parametrosConsulta.value,
      pagina: pagina.value,
      por_pagina: porPagina.value,
    })
    datos.value = respuesta.data || []
    total.value = respuesta.total || 0
    totalPaginas.value = respuesta.total_paginas || 1
    if (respuesta.catalogo) catalogo.value = respuesta.catalogo
  } catch (excepcion) {
    error.value =
      excepcion?.response?.data?.detail ||
      'No se pudo conectar con el backend. Verifique que uvicorn esté ejecutándose en el puerto 8000.'
  } finally {
    cargando.value = false
  }
}

const cargarCatalogo = async () => {
  try {
    catalogo.value = await obtenerCatalogo()
    if (!filtros.tipo && catalogo.value.tipos?.length === 1) {
      filtros.tipo = catalogo.value.tipos[0]
    }
  } catch {
    /* el catálogo se llena con la primera búsqueda */
  }
}

const programarBusqueda = () => {
  clearTimeout(temporizador)
  temporizador = setTimeout(() => {
    pagina.value = 1
    buscar()
  }, 350)
}

watch(filtros, programarBusqueda, { deep: true })

watch([pagina, porPagina], (nuevos, anteriores) => {
  if (nuevos[0] !== anteriores[0] || nuevos[1] !== anteriores[1]) buscar()
})

watch(
  () => filtros.provincia,
  () => {
    // Si la provincia cambia, el cantón anterior puede no existir.
    if (filtros.canton && !cantonesDisponibles.value.includes(filtros.canton)) {
      filtros.canton = ''
    }
  }
)

const ordenarPor = (campo) => {
  if (orden.value === campo) {
    dir.value = dir.value === 'desc' ? 'asc' : 'desc'
  } else {
    orden.value = campo
    dir.value = 'desc'
  }
  pagina.value = 1
  buscar()
}

const indicadorOrden = (campo) => (orden.value === campo ? (dir.value === 'desc' ? '▼' : '▲') : '')

const alternarPalabra = (palabra) => {
  const actuales = filtros.q
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  const indice = actuales.findIndex((item) => item.toLowerCase() === palabra)
  if (indice >= 0) actuales.splice(indice, 1)
  else actuales.push(palabra)
  filtros.q = actuales.join(', ')
}

const palabraActiva = (palabra) =>
  filtros.q
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .includes(palabra)

const limpiarFiltros = () => {
  Object.assign(filtros, {
    q: '',
    modo: 'todas',
    provincia: '',
    canton: '',
    estado: '',
    tipo: '',
    fecha_desde: '',
    fecha_hasta: '',
    solo_vigentes: false,
    por_vencer_horas: '',
  })
  orden.value = 'fecha_publicacion'
  dir.value = 'desc'
  pagina.value = 1
}

const exportar = () => {
  if (!datos.value.length) {
    aviso.value = 'Realice una búsqueda con resultados antes de exportar.'
    return
  }
  aviso.value = ''
  window.open(urlExportarNecesidades(parametrosConsulta.value), '_blank')
}

const forzarActualizacion = async () => {
  actualizando.value = true
  aviso.value = ''
  try {
    const resultado = await actualizarNecesidades()
    aviso.value = `Datos actualizados desde el SERCOP (${resultado.registros} necesidades vigentes).`
    pagina.value = 1
    await buscar()
  } catch {
    error.value = 'No se pudo actualizar el listado desde el SERCOP.'
  } finally {
    actualizando.value = false
  }
}

onMounted(async () => {
  await cargarCatalogo()
  await buscar()
})

defineExpose({ buscar })
</script>

<template>
  <section class="panel">
    <h2>Filtros de búsqueda</h2>

    <div class="rejilla-filtros">
      <div class="campo ancho">
        <label>Palabras clave (separe con comas)</label>
        <input
          type="text"
          v-model="filtros.q"
          placeholder="Ej: mantenimiento, medicamentos, vehículos"
        />
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
        <select v-model="filtros.provincia">
          <option value="">Todas las provincias</option>
          <option v-for="fila in catalogo.provincias" :key="fila.provincia" :value="fila.provincia">
            {{ fila.provincia }} ({{ fila.total }})
          </option>
        </select>
      </div>

      <div class="campo">
        <label>Cantón</label>
        <select v-model="filtros.canton" :disabled="!cantonesDisponibles.length">
          <option value="">Todos los cantones</option>
          <option v-for="canton in cantonesDisponibles" :key="canton" :value="canton">
            {{ canton }}
          </option>
        </select>
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
        <label>Entrega de proformas</label>
        <select v-model="filtros.por_vencer_horas">
          <option value="">Cualquier plazo</option>
          <option value="24">Vence en 24 horas</option>
          <option value="48">Vence en 48 horas</option>
          <option value="168">Vence en 7 días</option>
        </select>
      </div>

      <div class="campo casilla">
        <label>
          <input type="checkbox" v-model="filtros.solo_vigentes" />
          Ocultar plazos ya vencidos
        </label>
      </div>
    </div>

    <div class="chips">
      <span class="chips-titulo">Búsquedas rápidas:</span>
      <button
        v-for="palabra in PALABRAS_RAPIDAS"
        :key="palabra"
        class="chip"
        :class="{ activa: palabraActiva(palabra) }"
        @click="alternarPalabra(palabra)"
      >
        {{ palabra }}
      </button>
    </div>

    <div class="acciones">
      <button class="btn primario" @click="buscar" :disabled="cargando">
        {{ cargando ? 'Buscando…' : 'Buscar' }}
      </button>
      <button class="btn" @click="limpiarFiltros" :disabled="cargando">Limpiar filtros</button>
      <button class="btn verde" @click="exportar" :disabled="cargando || !datos.length">
        ⬇️ Exportar Excel
      </button>
      <button class="btn" @click="forzarActualizacion" :disabled="actualizando">
        {{ actualizando ? 'Actualizando…' : '🔄 Actualizar del SERCOP' }}
      </button>
      <span class="actualizado" v-if="catalogo.actualizado">
        Datos al {{ catalogo.actualizado }} · {{ (catalogo.total || 0).toLocaleString('es-EC') }}
        necesidades vigentes en el portal
      </span>
    </div>

    <p v-if="error" class="mensaje error">{{ error }}</p>
    <p v-if="aviso" class="mensaje ok">{{ aviso }}</p>
  </section>

  <section class="panel resultados">
    <div class="cabecera-resultados">
      <h2>
        Resultados
        <span class="contador">{{ total.toLocaleString('es-EC') }}</span>
      </h2>
      <span v-if="cargando" class="cargando">Consultando al SERCOP…</span>
    </div>

    <div class="tabla-scroll">
      <table class="tabla">
        <thead>
          <tr>
            <th class="ordenable" @click="ordenarPor('tipo')">
              Tipo de Necesidad <span class="flecha">{{ indicadorOrden('tipo') }}</span>
            </th>
            <th class="ordenable" @click="ordenarPor('codigo')">
              Código Necesidad de Contratación <span class="flecha">{{ indicadorOrden('codigo') }}</span>
            </th>
            <th class="ordenable" @click="ordenarPor('fecha_publicacion')">
              Fecha de Publicación <span class="flecha">{{ indicadorOrden('fecha_publicacion') }}</span>
            </th>
            <th class="ordenable" @click="ordenarPor('provincia')">
              Provincia - Cantón <span class="flecha">{{ indicadorOrden('provincia') }}</span>
            </th>
            <th>Descripción del Objeto de compra</th>
            <th class="ordenable" @click="ordenarPor('estado')">
              Estado de la Necesidad <span class="flecha">{{ indicadorOrden('estado') }}</span>
            </th>
            <th class="ordenable" @click="ordenarPor('fecha_limite_proformas')">
              Fecha límite para la entrega de proformas
              <span class="flecha">{{ indicadorOrden('fecha_limite_proformas') }}</span>
            </th>
            <th>Entidad Contratante</th>
            <th>Dirección de Entrega</th>
            <th>Contacto</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in datos" :key="item.codigo">
            <td class="tipo">{{ item.tipo_necesidad }}</td>
            <td class="codigo">
              <a v-if="item.enlace" :href="item.enlace" target="_blank" rel="noopener">
                {{ item.codigo }}
              </a>
              <span v-else>{{ item.codigo }}</span>
            </td>
            <td class="fecha">{{ item.fecha_publicacion }}</td>
            <td>
              <strong>{{ item.provincia }}</strong>
              <div class="secundario">{{ item.canton }}</div>
            </td>
            <td class="objeto">{{ item.objeto_compra }}</td>
            <td>
              <EtiquetaEstado :estado="item.estado" :dias="item.dias_restantes" />
            </td>
            <td class="fecha">{{ item.fecha_limite_proformas || '—' }}</td>
            <td>
              <a v-if="item.enlace" :href="item.enlace" target="_blank" rel="noopener">
                {{ item.entidad }}
              </a>
              <span v-else>{{ item.entidad }}</span>
            </td>
            <td class="direccion">{{ item.direccion_entrega || '—' }}</td>
            <td class="contacto">
              <div v-if="item.funcionario">Funcionario Encargado: {{ item.funcionario }}</div>
              <div v-if="item.email">
                Email:
                <a :href="`mailto:${item.email}`">{{ item.email }}</a>
              </div>
              <div v-if="item.telefono">Teléfono: {{ item.telefono }}</div>
              <div v-if="!item.funcionario && !item.email && !item.telefono">
                {{ item.contacto || '—' }}
              </div>
            </td>
          </tr>
          <tr v-if="!datos.length && !cargando">
            <td colspan="10" class="sin-datos">
              No se encontraron necesidades con los filtros seleccionados.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Paginacion
      :pagina="pagina"
      :total-paginas="totalPaginas"
      :total="total"
      :por-pagina="porPagina"
      @update:pagina="(valor) => (pagina = valor)"
      @update:porPagina="(valor) => (porPagina = valor)"
    />
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
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
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

.campo.casilla {
  justify-content: flex-end;
}

.campo label {
  font-size: 0.82em;
  font-weight: 600;
  color: var(--gris-700);
}

.campo.casilla label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
  padding-bottom: 10px;
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

input:focus,
select:focus {
  outline: 2px solid rgba(11, 79, 158, 0.25);
  border-color: var(--azul);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin-top: 16px;
}

.chips-titulo {
  font-size: 0.82em;
  font-weight: 600;
  color: var(--gris-700);
}

.chip {
  border: 1px dashed var(--gris-200);
  background: var(--gris-100);
  padding: 5px 12px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 0.82em;
  transition: 0.15s;
}

.chip:hover {
  border-color: var(--azul);
  color: var(--azul);
}

.chip.activa {
  background: var(--azul);
  border-color: var(--azul);
  color: #fff;
  border-style: solid;
}

.acciones {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-top: 18px;
}

.btn {
  padding: 10px 18px;
  border: 1px solid var(--gris-200);
  background: #fff;
  border-radius: 9px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.9em;
  transition: 0.15s;
}

.btn:hover:not(:disabled) {
  border-color: var(--azul);
  color: var(--azul);
}

.btn.primario {
  background: var(--azul);
  border-color: var(--azul);
  color: #fff;
}

.btn.primario:hover:not(:disabled) {
  background: var(--azul-oscuro);
  color: #fff;
}

.btn.verde {
  background: var(--verde);
  border-color: var(--verde);
  color: #fff;
}

.btn.verde:hover:not(:disabled) {
  background: #0d6a33;
  color: #fff;
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.actualizado {
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

.mensaje.ok {
  background: var(--verde-claro);
  color: var(--verde);
  border-left: 4px solid var(--verde);
}

.cabecera-resultados {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.contador {
  background: var(--azul-claro);
  color: var(--azul-oscuro);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.8em;
  margin-left: 8px;
}

.cargando {
  color: var(--azul);
  font-size: 0.85em;
  font-weight: 600;
}

.tabla-scroll {
  max-height: 68vh;
  overflow: auto;
  border: 1px solid var(--gris-200);
  border-radius: 10px;
}

.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.83em;
}

.tabla th,
.tabla td {
  border-bottom: 1px solid var(--gris-200);
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
}

.tabla thead th {
  position: sticky;
  top: 0;
  background: var(--azul);
  color: #fff;
  font-size: 0.92em;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  z-index: 1;
}

.tabla th.ordenable {
  cursor: pointer;
  user-select: none;
}

.flecha {
  font-size: 0.8em;
  opacity: 0.9;
}

.tabla tbody tr:nth-child(even) {
  background: #fbfcfe;
}

.tabla tbody tr:hover {
  background: var(--azul-claro);
}

.codigo a {
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.codigo a:hover {
  text-decoration: underline;
}

.tipo {
  white-space: nowrap;
  font-weight: 600;
  color: var(--azul-oscuro);
}

.fecha {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.objeto {
  min-width: 260px;
  line-height: 1.45;
}

.direccion,
.contacto {
  min-width: 190px;
  line-height: 1.45;
  color: var(--gris-700);
}

.secundario {
  color: var(--gris-400);
  font-size: 0.92em;
}

.sin-datos {
  text-align: center;
  padding: 34px;
  color: var(--gris-400);
}
</style>
