/**
 * Prueba de carga del **trabajo pesado**: lo que hace una empresa cuando prepara una oferta.
 *
 * `panel.js` mide a la gente mirando el panel. Esta mide el negocio: subir un TDR y leerlo, armar el
 * borrador, guardar la proforma con precios, bajarla en PDF y en Word y exportar a Excel. Todo eso
 * pasa por el encolador (`aplicacion/encolador.py`): turnos por tipo, fila acotada y reparto entre
 * empresas. Lo que se quiere comprobar es la promesa del encolador: **con avalancha el sistema no se
 * cae**; quien no cabe recibe enseguida un 503 «hay mucha demanda, vuelve en N s» (`Retry-After`), y
 * el panel lo reintenta solo. Esa respuesta **no** es un fallo; un 500, un 502 o un corte sí.
 *
 * Dos grupos a la vez, porque así es el uso real:
 *
 * - `panel`: gente mirando (tabla, gráficas, versión), VUS_PANEL usuarios.
 * - `oferta`: gente preparando ofertas, VUS_OFERTA usuarios, con pausas de persona entre pasos.
 *
 * Fuera a propósito: la bajada del TDR desde el portal (pegaría al SERCOP desde la IP de Ecuador) y
 * la IA (gasta la cuota del proveedor). El borrador se arma con la plantilla (`con_ia: false`).
 *
 *     k6 run -e BASE_URL=https://api-…railway.app -e PERMITIR_REMOTO=1 carga/pesado.js
 *     k6 run … -e VUS_PANEL=300 -e VUS_OFERTA=200 -e DURACION=5m carga/pesado.js
 */

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const credenciales = JSON.parse(open(__ENV.CREDENCIALES || './credenciales.json'))
const TDR = open(__ENV.TDR || './muestras/tdr_prueba.pdf', 'b')
const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8001'

const ES_LOCAL = /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/.test(BASE_URL)
if (!ES_LOCAL && __ENV.PERMITIR_REMOTO !== '1') {
  throw new Error(
    `BASE_URL=${BASE_URL} no es local. Esta prueba no se lanza contra producción; para un entorno ` +
      'de ensayo propio, añade -e PERMITIR_REMOTO=1.',
  )
}

const VUS_PANEL = Number(__ENV.VUS_PANEL || 400)
const VUS_OFERTA = Number(__ENV.VUS_OFERTA || 150)
const DURACION = __ENV.DURACION || '6m'
const SUBIDA = __ENV.SUBIDA || '2m'
const SALIDA = __ENV.SALIDA || 'carga/resultado-pesado.json'

const PASOS = [
  'tabla',
  'graficas',
  'version',
  'leer_tdr',
  'borrador',
  'proforma',
  'pdf',
  'word',
  'excel',
]
const tiempos = Object.fromEntries(PASOS.map((p) => [p, new Trend(`t_${p}`, true)]))
const hechos = Object.fromEntries(PASOS.map((p) => [p, new Counter(`n_${p}`)]))
// 503 del encolador: «hay mucha demanda». Es la respuesta prevista ante la avalancha, no un fallo.
const saturado = Object.fromEntries(PASOS.map((p) => [p, new Counter(`s_${p}`)]))
const errorReal = new Rate('error_real')
// Respuestas 2xx por paso: un 4xx no tumba nada pero tampoco es una oferta hecha (lo ve la persona).
const correcto = Object.fromEntries(PASOS.map((p) => [p, new Rate(`ok_${p}`)]))
const primerFallo = {}
const ofertasCompletas = new Counter('ofertas_completas')
const renovaciones = new Counter('renovaciones_de_token')

export const options = {
  scenarios: {
    panel: {
      executor: 'ramping-vus',
      exec: 'panel',
      startVUs: 0,
      stages: [
        { duration: SUBIDA, target: VUS_PANEL },
        { duration: DURACION, target: VUS_PANEL },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
    oferta: {
      executor: 'ramping-vus',
      exec: 'oferta',
      startVUs: 0,
      stages: [
        { duration: SUBIDA, target: VUS_OFERTA },
        { duration: DURACION, target: VUS_OFERTA },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '60s',
    },
  },
  // `http_req_failed` contaría los 503 previstos; el umbral de verdad es `error_real`.
  thresholds: {
    error_real: ['rate<0.01'],
    t_tabla: ['med<500'],
    t_leer_tdr: ['p(95)<15000'],
    t_proforma: ['p(95)<5000'],
    t_pdf: ['p(95)<15000'],
    t_word: ['p(95)<15000'],
  },
  // Los PDF y los Excel no se guardan: solo interesa cuánto tardan y si llegan.
  discardResponseBodies: false,
}

// Cuentas repartidas: el panel usa las primeras, las ofertas las últimas, para que nadie comparta
// sesión (el panel admite dos por cuenta).
function cuentaPara(grupo) {
  const cuentas = credenciales.cuentas
  const indice = grupo === 'panel' ? (__VU - 1) % cuentas.length : cuentas.length - 1 - ((__VU - 1) % cuentas.length)
  return cuentas[indice]
}

const sesion = { acceso: null, renovacion: null }

function renovar() {
  const r = http.post(
    `${BASE_URL}/v1/auth/sesion/renovacion`,
    JSON.stringify({ token_renovacion: sesion.renovacion }),
    { headers: { 'Content-Type': 'application/json' }, tags: { nombre: 'renovacion' } },
  )
  renovaciones.add(1)
  if (r.status !== 200) return false
  const cuerpo = r.json()
  sesion.acceso = cuerpo.token_acceso
  sesion.renovacion = cuerpo.token_renovacion
  return true
}

/**
 * Una petición como la hace el panel: renueva ante un 401 y, ante un 503 del encolador, espera lo
 * que dice `Retry-After` y reintenta (como mucho dos veces). Mide el tiempo **total** que la persona
 * espera, reintentos incluidos, que es lo que importa.
 */
function paso(nombre, metodo, ruta, cuerpo = null, json = true) {
  const opciones = () => ({
    headers: {
      Authorization: `Bearer ${sesion.acceso}`,
      ...(cuerpo && json ? { 'Content-Type': 'application/json' } : {}),
    },
    tags: { nombre },
    timeout: '120s',
  })
  const datos = cuerpo && json ? JSON.stringify(cuerpo) : cuerpo
  const inicio = Date.now()
  let r = http.request(metodo, `${BASE_URL}${ruta}`, datos, opciones())
  if (r.status === 401 && renovar()) r = http.request(metodo, `${BASE_URL}${ruta}`, datos, opciones())
  for (let intento = 0; r.status === 503 && intento < 2; intento++) {
    saturado[nombre].add(1)
    const espera = Math.min(Number(r.headers['Retry-After'] || 5), 20)
    sleep(espera)
    r = http.request(metodo, `${BASE_URL}${ruta}`, datos, opciones())
  }
  tiempos[nombre].add(Date.now() - inicio)
  hechos[nombre].add(1)
  // 429 = tope por persona: lo provoca la prueba, no el sistema. 503 tras reintentos: saturado.
  const malo = r.status === 0 || (r.status >= 500 && r.status !== 503)
  errorReal.add(malo, { paso: nombre })
  correcto[nombre].add(r.status >= 200 && r.status < 300)
  if ((r.status < 200 || r.status >= 300) && !primerFallo[`${nombre}${r.status}`]) {
    primerFallo[`${nombre}${r.status}`] = true
    console.warn(`${nombre}: respuesta ${r.status} ${String(r.body || r.error).slice(0, 200)}`)
  }
  check(r, { [`${nombre} sin error del servidor`]: () => !malo })
  return r
}

function asegurarSesion(grupo) {
  if (sesion.acceso) return
  const cuenta = cuentaPara(grupo)
  sesion.acceso = cuenta.token_acceso
  sesion.renovacion = cuenta.token_renovacion
}

export function panel() {
  asegurarSesion('panel')
  paso('tabla', 'GET', '/v1/registros?modo=cualquiera&orden=recientes&pagina=1&tamano=25&categoria=infimas')
  paso('graficas', 'GET', '/v1/estadisticas?modo=cualquiera&orden=recientes&categoria=infimas')
  paso('version', 'GET', '/v1/ingestas/version')
  sleep(4 + Math.random() * 4)
}

export function oferta() {
  asegurarSesion('oferta')

  // 1. Sube el TDR y lo lee (CPU: texto de cada página, apartados, presupuesto, entidad).
  const lectura = paso('leer_tdr', 'POST', '/v1/documentos/leer', {
    archivo: http.file(TDR, `tdr-${__VU}-${__ITER}.pdf`, 'application/pdf'),
  }, false)
  const lecturaId = lectura.status === 200 ? lectura.json('lectura_id') : null
  sleep(5 + Math.random() * 10)

  // 2. El borrador con la plantilla y los datos de la empresa (sin IA).
  if (lecturaId) {
    paso('borrador', 'POST', '/v1/documentos/generar', { lectura_id: lecturaId, con_ia: false })
    sleep(10 + Math.random() * 20)
  }

  // 3. Guarda la proforma con precios. El título es único por empresa (409 si se repite).
  const lineas = Array.from({ length: 5 }, (_, i) => ({
    descripcion: `Mantenimiento preventivo equipo ${i + 1}, incluye repuestos y mano de obra`,
    cantidad: 1 + i,
    precio_unitario: 35.5 + i * 12,
    unidad: 'u',
  }))
  const proforma = paso('proforma', 'POST', '/v1/documentos/proformas', {
    titulo: `Carga ${__VU}-${__ITER}-${Date.now()}`,
    entidad: 'Entidad de prueba de carga',
    objeto: 'Servicio de mantenimiento preventivo y correctivo de equipos informáticos',
    impuesto_porcentaje: 15,
    lineas,
  })
  const proformaId = proforma.status === 201 ? proforma.json('id') : null
  sleep(3 + Math.random() * 5)

  // 4. La baja en PDF y en Word (CPU: maquetación).
  if (proformaId) {
    paso('pdf', 'GET', `/v1/documentos/proformas/${proformaId}/pdf`)
    sleep(2 + Math.random() * 3)
    paso('word', 'GET', `/v1/documentos/proformas/${proformaId}/docx`)
    ofertasCompletas.add(1)
  }

  // 5. Una de cada cuatro vueltas exporta a Excel todo lo vigente (la consulta más grande).
  if (__ITER % 4 === 0) {
    sleep(3)
    // Lo más grande que se admite: los últimos 3 meses (el servidor rechaza más atrás).
    const desde = new Date(Date.now() - 89 * 86400000).toISOString().slice(0, 10)
    paso(
      'excel',
      'GET',
      `/v1/registros/exportacion?modo=cualquiera&orden=recientes&categoria=infimas&desde=${desde}`,
    )
  }
  sleep(10 + Math.random() * 20)
}

export function handleSummary(datos) {
  return { [SALIDA]: JSON.stringify(datos, null, 2), stdout: resumen(datos) }
}

function resumen(datos) {
  const m = (n, c) => datos.metrics[n]?.values?.[c] ?? 0
  const r = (x) => Math.round(Number(x))
  const lineas = [
    '',
    'Prueba de carga: trabajo pesado',
    '===============================',
    `usuarios máximos            : ${r(m('vus_max', 'value'))}`,
    `ofertas completas           : ${r(m('ofertas_completas', 'count'))}`,
    `errores reales (5xx/corte)  : ${(m('error_real', 'rate') * 100).toFixed(2)} %`,
    `renovaciones de token       : ${r(m('renovaciones_de_token', 'count'))}`,
    '',
    'paso          veces   ok %  «saturado»  mediana ms   p95 ms   máx ms',
    '-----------------------------------------------------------------------',
  ]
  for (const p of PASOS) {
    if (!m(`n_${p}`, 'count')) continue
    lineas.push(
      `${p.padEnd(12)} ${String(r(m(`n_${p}`, 'count'))).padStart(6)} ` +
        `${(m(`ok_${p}`, 'rate') * 100).toFixed(0).padStart(5)} ` +
        `${String(r(m(`s_${p}`, 'count'))).padStart(11)} ` +
        `${String(r(m(`t_${p}`, 'med'))).padStart(11)} ` +
        `${String(r(m(`t_${p}`, 'p(95)'))).padStart(8)} ` +
        `${String(r(m(`t_${p}`, 'max'))).padStart(8)}`,
    )
  }
  lineas.push(
    '',
    '«saturado» = 503 del encolador («hay mucha demanda»), reintentado tras Retry-After: previsto.',
    'Los tiempos incluyen esas esperas: es lo que la persona espera de verdad.',
    '',
  )
  return lineas.join('\n')
}
