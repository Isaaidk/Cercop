import axios from 'axios'

// URL del backend FastAPI (se puede sobreescribir con VITE_API_URL en .env).
const API_BASE = import.meta.env.VITE_API_URL || 'https://rdn757vv-8000.use.devtunnels.ms/api'

const cliente = axios.create({ baseURL: API_BASE, timeout: 180000 })

/** Quita parámetros vacíos/nulos para no ensuciar la query string. */
export const limpiarParametros = (parametros = {}) =>
  Object.fromEntries(
    Object.entries(parametros).filter(
      ([, valor]) => valor !== null && valor !== undefined && valor !== ''
    )
  )

const aQueryString = (parametros) => new URLSearchParams(limpiarParametros(parametros)).toString()

// --------------------------- Necesidades (NCO) --------------------------- //
export const obtenerCatalogo = async () => (await cliente.get('/necesidades/filtros')).data

export const buscarNecesidades = async (parametros) =>
  (await cliente.get('/necesidades', { params: limpiarParametros(parametros) })).data

export const actualizarNecesidades = async () => (await cliente.post('/necesidades/actualizar')).data

export const urlExportarNecesidades = (parametros) =>
  `${API_BASE}/necesidades/exportar?${aQueryString(parametros)}`

/** Agregados para las gráficas (mismos filtros que la tabla de necesidades). */
export const obtenerEstadisticas = async (parametros) =>
  (await cliente.get('/necesidades/estadisticas', { params: limpiarParametros(parametros) })).data

// ---------------------- Ofertas (procesos publicados) ---------------------- //
export const buscarOfertas = async (parametros) =>
  (await cliente.get('/ofertas', { params: limpiarParametros(parametros) })).data

export const urlExportarOfertas = (parametros) =>
  `${API_BASE}/ofertas/exportar?${aQueryString(parametros)}`

// ------------------------- Procesos publicados (OCDS) ------------------------- //
export const buscarProcesos = async (parametros) =>
  (await cliente.get('/contrataciones', { params: limpiarParametros(parametros) })).data

export const urlExportarProcesos = (parametros) =>
  `${API_BASE}/exportar?${aQueryString(parametros)}`

export const detalleProceso = async (ocid) => (await cliente.get(`/procesos/${ocid}/detalle`)).data

export { API_BASE }
