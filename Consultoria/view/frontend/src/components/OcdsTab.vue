<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import EtiquetaEstado from './EtiquetaEstado.vue'
import Paginacion from './Paginacion.vue'
import { buscarProcesos, urlExportarProcesos } from '../services/api'

const filtros = reactive({
  search: 'mantenimiento',
  fecha_inicio: '',
  fecha_fin: '',
  provincia: '',
  canton: '',
  estado: '',
  tipo: '',
  incluir_detalle: false,
  limite_detalle: 25,
  max_paginas: 2,
})

const pagina = ref(1)
const porPagina = ref(25)
const datos = ref([])
const total = ref(0)
const totalPaginas = ref(1)
const opciones = ref({ tipos: [], provincias: [], cantones: [] })
const cargando = ref(false)
const error = ref('')
const avisos = ref([])

// Por defecto: el año en curso (el SERCOP limita la tasa de peticiones).
const hoy = new Date()
filtros.fecha_inicio = `${hoy.getFullYear()}-01-01`
filtros.fecha_fin = hoy.toISOString().slice(0, 10)

/** El endpoint `record` tarda varios segundos por proceso: avisamos al usuario. */
const avisoDetalle = ref('')

const buscar = async () => {
  if (!filtros.search || filtros.search.replace(/,/g, '').trim().length < 3) {
    error.value = 'Ingrese al menos una palabra clave de 3 o más caracteres.'
    return
  }

  cargando.value = true
  error.value = ''
  avisos.value = []
  try {
    const respuesta = await buscarProcesos({
      ...filtros,
      incluir_detalle: filtros.incluir_detalle,
      pagina: pagina.value,
      por_pagina: porPagina.value,
    })
    datos.value = respuesta.data || []
    total.value = respuesta.total || 0
    totalPaginas.value = respuesta.total_paginas || 1
    opciones.value = {
      tipos: respuesta.tipos || [],
      provincias: respuesta.provincias || [],
      cantones: respuesta.cantones || [],
    }
    avisos.value = respuesta.avisos || []
    avisoDetalle.value =
      filtros.incluir_detalle && respuesta.detalle_aplicado
        ? `Detalle consultado para los primeros ${filtros.limite_detalle} resultados.`
        : ''
  } catch (excepcion) {
    error.value =
      excepcion?.response?.data?.detail ||
      'No se pudo conectar con el backend. Verifique que uvicorn esté ejecutándose en el puerto 8000.'
  } finally {
    cargando.value = false
  }
}

let temporizador = null
const programarBusqueda = () => {
  clearTimeout(temporizador)
  temporizador = setTimeout(() => {
    pagina.value = 1
    buscar()
  }, 500)
}

watch(filtros, programarBusqueda, { deep: true })
watch([pagina, porPagina], () => buscar())

const formatearMonto = (monto) => {
  const valor = Number(monto)
  if (!monto || Number.isNaN(valor)) return '—'
  return new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD' }).format(valor)
}

const exportar = () => {
  if (!datos.value.length) {
    error.value = 'Realice una búsqueda con resultados antes de exportar.'
    return
  }
  error.value = ''
  window.open(urlExportarProcesos(filtros), '_blank')
}

onMounted(buscar)
</script>

<template>
  <section class="panel">
    <h2>Filtros de procesos publicados</h2>

    <div class="rejilla-filtros">
      <div class="campo ancho">
        <label>Palabras clave (separe con comas)</label>
        <input type="text" v-model="filtros.search" placeholder="Ej: medicamentos, mantenimiento" />
      </div>

      <div class="campo">
        <label>Publicados desde</label>
        <input type="date" v-model="filtros.fecha_inicio" />
      </div>

      <div class="campo">
        <label>Publicados hasta</label>
        <input type="date" v-model="filtros.fecha_fin" />
      </div>

      <div class="campo">
        <label>Provincia</label>
        <input type="text" v-model="filtros.provincia" placeholder="Ej: PICHINCHA" list="provincias-ocds" />
        <datalist id="provincias-ocds">
          <option v-for="provincia in opciones.provincias" :key="provincia" :value="provincia" />
        </datalist>
      </div>

      <div class="campo">
        <label>Cantón</label>
        <input type="text" v-model="filtros.canton" placeholder="Ej: QUITO" list="cantones-ocds" />
        <datalist id="cantones-ocds">
          <option v-for="canton in opciones.cantones" :key="canton" :value="canton" />
        </datalist>
      </div>

      <div class="campo">
        <label>Tipo de proceso</label>
        <select v-model="filtros.tipo">
          <option value="">Todos los tipos</option>
          <option v-for="tipo in opciones.tipos" :key="tipo" :value="tipo">{{ tipo }}</option>
        </select>
      </div>

      <div class="campo">
        <label>Estado de la necesidad</label>
        <select v-model="filtros.estado">
          <option value="">Todos los estados</option>
          <option value="En Curso">En Curso</option>
          <option value="Finalizada">Finalizada</option>
          <option value="Cancelada">Cancelada</option>
          <option value="Desierto">Desierto</option>
        </select>
      </div>

      <div class="campo">
        <label>Páginas por palabra/año</label>
        <input type="number" min="1" max="40" v-model.number="filtros.max_paginas" />
      </div>

      <div class="campo casilla">
        <label>
          <input type="checkbox" v-model="filtros.incluir_detalle" />
          Incluir detalle (estado, proformas, contacto)
        </label>
      </div>

      <div class="campo" v-if="filtros.incluir_detalle">
        <label>Procesos a detallar</label>
        <input type="number" min="1" max="100" v-model.number="filtros.limite_detalle" />
      </div>
    </div>

    <div class="acciones">
      <button class="btn primario" @click="buscar" :disabled="cargando">
        {{ cargando ? 'Consultando…' : 'Buscar procesos' }}
      </button>
      <button class="btn verde" @click="exportar" :disabled="cargando || !datos.length">
        ⬇️ Exportar Excel
      </button>
      <span class="nota" v-if="filtros.incluir_detalle">
        El detalle se consulta proceso por proceso en el SERCOP: puede tardar varios segundos.
      </span>
      <span class="nota" v-else>
        El estado, la dirección y el contacto se completan al marcar “Incluir detalle”.
      </span>
    </div>

    <p v-if="error" class="mensaje error">{{ error }}</p>
    <p v-for="(aviso, indice) in avisos" :key="indice" class="mensaje advertencia">{{ aviso }}</p>
    <p v-if="avisoDetalle" class="mensaje ok">{{ avisoDetalle }}</p>
  </section>

  <section class="panel resultados">
    <div class="cabecera-resultados">
      <h2>
        Procesos publicados (OCDS)
        <span class="contador">{{ total.toLocaleString('es-EC') }}</span>
      </h2>
      <span v-if="cargando" class="cargando">Consultando datos abiertos…</span>
    </div>

    <div class="tabla-scroll">
      <table class="tabla">
        <thead>
          <tr>
            <th>Tipo de Necesidad</th>
            <th>Código Necesidad de Contratación</th>
            <th>Fecha de Publicación</th>
            <th>Provincia - Cantón</th>
            <th>Descripción del Objeto de compra</th>
            <th>Estado de la Necesidad</th>
            <th>Fecha límite para la entrega de proformas</th>
            <th>Entidad Contratante</th>
            <th>Dirección de Entrega</th>
            <th>Contacto</th>
            <th>Proveedor adjudicado</th>
            <th>Monto</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in datos" :key="item.ocid">
            <td class="tipo">{{ item.tipo_proceso || '—' }}</td>
            <td class="codigo">
              <a :href="item.enlace" target="_blank" rel="noopener">{{ item.codigo }}</a>
            </td>
            <td class="fecha">{{ item.fecha_publicacion || '—' }}</td>
            <td>
              <strong>{{ item.provincia || '—' }}</strong>
              <div class="secundario">{{ item.canton }}</div>
            </td>
            <td class="objeto">{{ item.objeto_compra }}</td>
            <td><EtiquetaEstado :estado="item.estado" /></td>
            <td class="fecha">{{ item.fecha_limite_proformas || '—' }}</td>
            <td>{{ item.entidad || '—' }}</td>
            <td class="direccion">{{ item.direccion_entrega || '—' }}</td>
            <td class="contacto">{{ item.contacto || '—' }}</td>
            <td class="proveedor">{{ item.proveedor || '—' }}</td>
            <td class="monto">{{ formatearMonto(item.monto) }}</td>
          </tr>
          <tr v-if="!datos.length && !cargando">
            <td colspan="12" class="sin-datos">
              No se encontraron procesos con los filtros seleccionados.
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
  width: 100%;
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
}

.btn.primario {
  background: var(--azul);
  border-color: var(--azul);
  color: #fff;
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
  max-width: 420px;
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

.mensaje.advertencia {
  background: var(--ambar-claro);
  color: var(--ambar);
  border-left: 4px solid var(--ambar);
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
  text-transform: uppercase;
  letter-spacing: 0.3px;
  z-index: 1;
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

.tipo {
  white-space: nowrap;
  font-weight: 600;
  color: var(--azul-oscuro);
}

.fecha,
.monto {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.objeto {
  min-width: 260px;
  line-height: 1.45;
}

.direccion,
.contacto,
.proveedor {
  min-width: 180px;
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
