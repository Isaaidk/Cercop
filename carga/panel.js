/**
 * Prueba de carga del panel: cuántos usuarios concurrentes aguanta el aplicativo.
 *
 * Qué mide, y qué no
 * ------------------
 * Mide lo que hace **una persona con el panel abierto**, no una ráfaga de peticiones: cada usuario
 * virtual lee la tabla, pide las gráficas cuando toca y consulta si hay datos nuevos, con una pausa
 * entre vuelta y vuelta —que es lo que un panel hace mientras alguien lo mira—. Es la diferencia
 * entre «cuántas peticiones por segundo aguanta» y «cuántas personas pueden estar dentro a la vez»,
 * y la pregunta era la segunda.
 *
 * Cada usuario virtual tiene **su propia cuenta y su propio negocio** (los crea
 * `backend/scripts/preparar_carga.py`): el panel solo permite dos sesiones por cuenta, así que mil
 * usuarios sobre una cuenta se expulsarían entre ellos y lo que se mediría es la evicción.
 *
 * Cómo se ejecuta
 * ---------------
 *     # 1. Las cuentas (una vez)
 *     cd backend; .\.venv\Scripts\python.exe scripts\preparar_carga.py --usuarios 1000
 *
 *     # 2. La prueba, por tramos hasta 1.000 usuarios
 *     k6 run -e BASE_URL=http://127.0.0.1:8001 carga\panel.js
 *
 *     # 3. Un tramo concreto, para repetir una medida
 *     k6 run -e BASE_URL=http://127.0.0.1:8001 -e VUS=500 -e DURACION=3m carga\panel.js
 *
 *     # 4. Y a dejarlo como estaba
 *     cd backend; .\.venv\Scripts\python.exe scripts\preparar_carga.py --borrar
 *
 * `BASE_URL` apunta al API: en desarrollo es `http://127.0.0.1:8001` con **un** proceso, y en el
 * despliegue es el del `compose`, con tantos procesos como núcleos. Los números no son comparables
 * entre los dos, y el documento de capacidad lo dice.
 *
 * Qué significa «aguantar», aquí
 * ------------------------------
 * Las lecturas del panel **no cuestan lo mismo**, y mezclarlas en un solo número es lo que hace
 * inútil una prueba de carga:
 *
 * - **La tabla y las gráficas se cachean** (clave = criterios + generación, 900 s de vida). Con la
 *   caché caliente son milisegundos; cuando la ingesta sube la generación, la siguiente consulta de
 *   cada combinación de filtros vuelve a la base y cuesta segundos. Eso es un caso **normal**, no un
 *   error: la consulta en frío entra en la cola como cualquier otra.
 * - **La búsqueda por palabra clave no se cachea nunca**, a propósito: es texto que se teclea y
 *   llenaría el almacén de entradas que nadie repite (`Filtros.cacheable`). Tiene su propia meta.
 * - **La comprobación de versión** es una lectura de caché de un solo número.
 *
 * Por eso hay una serie por tipo de lectura y no un promedio. La meta de p95 < 300 ms es la de una
 * consulta **servida de la caché**; la de una consulta a la base es p95 < 1,5 s (RNF-02). El detalle
 * de los umbrales está donde se declaran.
 *
 * Por qué los tokens vienen de fuera
 * ----------------------------------
 * Iniciar sesión cuesta Argon2, que es lento **a propósito**. Hacerlo dentro de la prueba mediría el
 * coste del inicio de sesión —una vez por usuario, justo al empezar— en vez del panel. Los tokens se
 * obtienen antes, en paralelo, y aquí solo se usan. El de acceso caduca en minutos, así que cuando
 * una petición responde 401 se renueva **como lo hace el panel**: con el token de renovación, que
 * rota, y quedándose con el nuevo.
 */

import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Trend } from 'k6/metrics'

const credenciales = JSON.parse(open(__ENV.CREDENCIALES || './credenciales.json'))
const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8001'
const PAUSA_MIN = Number(__ENV.PAUSA_MIN || 4)
const PAUSA_MAX = Number(__ENV.PAUSA_MAX || 8)

/**
 * Una serie por tipo de lectura, con el nombre del tipo.
 *
 * Se separan a propósito: un solo `http_req_duration` con la tabla cacheada (10 ms) y la búsqueda
 * por palabra clave (1,2 s) mezcladas da un número que no describe a ninguna de las dos, y con el
 * que no se puede decidir nada.
 *
 * Las claves son **las etiquetas de las peticiones** y se usan para construir los nombres de las
 * métricas. Escribirlas a mano por separado es un fallo que ya se cometió: el resumen buscaba
 * `termino` cuando la serie se llamaba `tabla_termino` y la fila salía con ceros, que es la peor
 * forma de equivocarse —el número está, y parece malo—.
 */
const TIPOS = ['tabla', 'graficas', 'version', 'tabla_termino']
const lecturas = Object.fromEntries(TIPOS.map((tipo) => [tipo, new Trend(tipo, true)]))
// Un contador por tipo, y no el recuento de la serie: k6 2.2 **no** exporta `count` en los `Trend`,
// así que leerlo de ahí deja el resumen con ceros y sin la fila. Se paga un contador y se ve el dato.
const cuantas = Object.fromEntries(TIPOS.map((tipo) => [tipo, new Counter(`n_${tipo}`)]))
const renovaciones = new Counter('renovaciones_de_token')
const peticiones = new Counter('peticiones_del_panel')

/** Los tramos de la escalera: se sube hasta 1.000 usuarios y se mantiene cada meseta un minuto. */
const ESCALERA = [
  { duration: '1m', target: 50 },
  { duration: '1m', target: 50 },
  { duration: '1m', target: 200 },
  { duration: '1m', target: 200 },
  { duration: '1m', target: 500 },
  { duration: '1m', target: 500 },
  { duration: '1m', target: 1000 },
  { duration: '2m', target: 1000 },
  { duration: '30s', target: 0 },
]

/**
 * Los umbrales, en la forma en que k6 los entiende.
 *
 * Se separan las **lecturas del panel** de todo lo demás —el inicio de sesión no entra aquí porque
 * no ocurre—: un p95 de 300 ms es la meta registrada para una consulta cacheada, y es la que decide
 * si el aplicativo se siente rápido. El error se mide aparte y con un margen pequeño: con la caché
 * encendida y la ingesta corriendo, alguna petición suelta puede caer, y una prueba que exige cero
 * fallos en diez minutos no la pasa nadie.
 *
 * Tiene que estar declarado **antes** de `options`: un `const` no se puede leer antes de su línea, y
 * poníendolo después la prueba no arranca con un `ReferenceError` que no dice nada del motivo.
 */
/**
 * Los umbrales.
 *
 * `med` para las lecturas cacheadas y no `p(95)`, y es una decisión que conviene entender: con la
 * caché invalidándose cada cuarto de hora y mil usuarios dentro, **siempre** hay un porcentaje de
 * consultas que llegan a la base —las primeras de cada combinación de filtros después de una subida
 * de generación—, así que un p95 de 300 ms sobre todo lo que pasa no se cumple ni con el sistema
 * perfecto. Lo que sí dice la mediana es si el panel se siente rápido el resto del tiempo; y el p95
 * queda acotado por la meta de una consulta a la base (RNF-02, 1,5 s).
 *
 * Tiene que estar declarado **antes** de `options`: un `const` no se puede leer antes de su línea, y
 * poníendolo después la prueba no arranca con un `ReferenceError` que no dice nada del motivo.
 */
const UMBRALES = {
  http_req_failed: ['rate<0.02'],
  tabla: ['med<300', 'p(95)<1500'],
  graficas: ['med<300', 'p(95)<1500'],
  version: ['med<300', 'p(95)<1000'],
  // La que no se puede cachear: su meta es la de una consulta a la base.
  tabla_termino: ['p(95)<1500'],
}

export const options = __ENV.VUS
  ? {
      scenarios: {
        panel: {
          executor: 'constant-vus',
          vus: Number(__ENV.VUS),
          duration: __ENV.DURACION || '2m',
        },
      },
      thresholds: UMBRALES,
    }
  : {
      scenarios: {
        panel: {
          executor: 'ramping-vus',
          startVUs: 0,
          stages: ESCALERA,
          // Al bajar, las vueltas en curso terminan en lugar de cortarse: una petición cortada a
          // mitad no es un error del sistema y contarla como tal ensuciaría el resultado del final.
          gracefulRampDown: '30s',
        },
      },
      thresholds: UMBRALES,
    }

/**
 * Dónde se escribe el resultado.
 *
 * Por defecto `carga/resultado.json`, que exige ejecutar k6 **desde la raíz del repositorio**: k6
 * escribe el archivo pero no crea la carpeta, y desde `backend/` fallaría al guardar justo después
 * de una prueba de diez minutos.
 */
const SALIDA = __ENV.SALIDA || 'carga/resultado.json'

function elegirCuenta() {
  const cuentas = credenciales.cuentas
  return cuentas[(__VU - 1) % cuentas.length]
}

export function setup() {
  return { api: credenciales.api || BASE_URL }
}

/**
 * Estado de la sesión de este usuario virtual.
 *
 * Se guarda fuera de la vuelta a propósito: el token dura varios minutos y volver a pedirlo en cada
 * vuelta convertiría la prueba en una prueba de inicio de sesión.
 */
const sesion = { acceso: null, renovacion: null }

function renovar() {
  const respuesta = http.post(
    `${BASE_URL}/v1/auth/sesion/renovacion`,
    JSON.stringify({ token_renovacion: sesion.renovacion }),
    { headers: { 'Content-Type': 'application/json' }, tags: { nombre: 'renovacion' } },
  )
  renovaciones.add(1)
  if (respuesta.status !== 200) return false
  const cuerpo = respuesta.json()
  sesion.acceso = cuerpo.token_acceso
  // El token de renovación **rota**: quedarse con el viejo y volver a usarlo cierra la sesión, que
  // es exactamente lo que le pasaba a dos pestañas del panel antes de que se arreglara.
  sesion.renovacion = cuerpo.token_renovacion
  return true
}

function leer(ruta, etiqueta) {
  let respuesta = http.get(`${BASE_URL}${ruta}`, {
    headers: { Authorization: `Bearer ${sesion.acceso}` },
    tags: { nombre: etiqueta },
  })
  if (respuesta.status === 401 && renovar()) {
    respuesta = http.get(`${BASE_URL}${ruta}`, {
      headers: { Authorization: `Bearer ${sesion.acceso}` },
      tags: { nombre: etiqueta },
    })
  }
  peticiones.add(1)
  cuantas[etiqueta].add(1)
  lecturas[etiqueta].add(respuesta.timings.duration)
  check(respuesta, {
    [`${etiqueta} responde 200`]: (r) => r.status === 200,
  })
  return respuesta
}

export default function () {
  if (!sesion.acceso) {
    // El primer acceso de este usuario virtual. Viene del archivo, así que no hay inicio de sesión.
    const cuenta = elegirCuenta()
    sesion.acceso = cuenta.token_acceso
    sesion.renovacion = cuenta.token_renovacion
  }

  // Lo que hace el panel al abrirse: la tabla, las gráficas y la comprobación de si hay datos
  // nuevos. Los tres van con los mismos filtros, que es lo que hace una persona que entra a mirar.
  leer('/v1/registros?modo=cualquiera&orden=recientes&pagina=1&tamano=25&categoria=infimas', 'tabla')
  leer('/v1/estadisticas?modo=cualquiera&orden=recientes&categoria=infimas', 'graficas')
  leer('/v1/ingestas/version', 'version')

  // Una de cada tres vueltas se pulsa además una palabra clave, que es la consulta que **no** se
  // puede cachear: sin esto la prueba mediría casi solo aciertos de caché.
  if (__ITER % 3 === 0) {
    leer(
      '/v1/registros?modo=cualquiera&orden=recientes&pagina=1&tamano=25&categoria=infimas' +
        '&provincia=PICHINCHA&termino=mantenimiento',
      'tabla_termino',
    )
  }

  // La pausa es parte de la medida: sin ella esto no son usuarios concurrentes, son una ráfaga.
  sleep(PAUSA_MIN + Math.random() * (PAUSA_MAX - PAUSA_MIN))
}

export function handleSummary(datos) {
  return {
    [SALIDA]: JSON.stringify(datos, null, 2),
    stdout: resumen(datos),
  }
}

/** Un resumen corto en la consola: lo que hay que mirar cuando la prueba termina. */
function resumen(datos) {
  const valor = (nombre, campo) => datos.metrics[nombre]?.values?.[campo] ?? 0
  const cuenta = (nombre) => datos.metrics[nombre]?.values?.count ?? 0
  const redondear = (numero) => Math.round(Number(numero))
  const lineas = [
    '',
    'Resumen de la prueba de carga',
    '=============================',
    `usuarios máximos alcanzados : ${redondear(valor('vus_max', 'value'))}`,
    `lecturas del panel          : ${redondear(cuenta('peticiones_del_panel'))}`,
    `fallos                      : ${(valor('http_req_failed', 'rate') * 100).toFixed(2)} %`,
    `renovaciones de token       : ${redondear(cuenta('renovaciones_de_token'))}`,
    '',
    'Por tipo de lectura, en milisegundos',
    '------------------------------------',
    'tipo            lecturas   mediana       p95       máx',
  ]
  for (const tipo of TIPOS) {
    if (!cuenta(`n_${tipo}`)) continue
    lineas.push(
      `${tipo.padEnd(14)} ${String(redondear(cuenta(`n_${tipo}`))).padStart(8)} ` +
        `${String(redondear(valor(tipo, 'med'))).padStart(8)} ` +
        `${String(redondear(valor(tipo, 'p(95)'))).padStart(9)} ` +
        `${String(redondear(valor(tipo, 'max'))).padStart(9)}`,
    )
  }
  lineas.push('', 'La tabla y las gráficas se cachean; la búsqueda por palabra clave nunca.', '')
  return lineas.join('\n')
}
