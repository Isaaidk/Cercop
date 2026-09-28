/**
 * Cliente HTTP del panel.
 *
 * Concentra todo lo que tiene que ver con hablar con la API: la dirección, el token, qué hacer
 * cuando caduca y cómo convertir una respuesta de error en algo que el código pueda decidir. Los
 * componentes y los almacenes no saben que existe `fetch`.
 *
 * Dónde se guardan los tokens, y por qué así
 * ------------------------------------------
 * El de **acceso** vive solo en memoria. Dura minutos y se pierde al recargar; volver a pedirlo es
 * una petición que no cuesta nada, y no guardarlo elimina la copia que más se usa.
 *
 * El de **renovación** va en `sessionStorage`, no en `localStorage`. Los dos son legibles por
 * cualquier script que consiga ejecutarse en la página, así que la diferencia no es de seguridad
 * frente a un ataque: es de **persistencia**. Con `sessionStorage`, cerrar el navegador borra la
 * copia y un token robado deja de servir al día siguiente; con `localStorage` se queda ahí durante
 * meses. El precio es que hay que volver a entrar al reabrir el navegador, y se paga a gusto.
 *
 * Qué hacer cuando el token caduca
 * --------------------------------
 * Se renueva una vez, en silencio, y se repite la petición. Si la renovación falla, se avisa y se
 * deja que la aplicación muestre la pantalla de acceso. Se hace aquí, en un solo sitio, porque si
 * cada componente intentara arreglárselas por su cuenta acabaríamos con varias renovaciones
 * simultáneas —y el token de renovación **rota en cada uso**, así que la segunda cerraría todas las
 * sesiones de la cuenta—.
 */

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const CLAVE_RENOVACION = 'contratacion:renovacion'

// El mismo tipo que declara el servidor para el libro de Excel. Se envía en `Accept` y sirve para
// que un error de la API —que llega en JSON— no se confunda con el archivo.
const TIPO_LIBRO =
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

/** Error de la API con lo que hace falta para decidir qué mostrar. */
export class ErrorApi extends Error {
  constructor(mensaje, { estado = 0, codigo = 'error', detalles = null } = {}) {
    super(mensaje)
    this.name = 'ErrorApi'
    this.estado = estado
    this.codigo = codigo
    this.detalles = detalles
  }

  /** ¿Hay que hacer algo distinto en la interfaz por este error? */
  get requiereAceptarTerminos() {
    return this.codigo === 'consentimiento_pendiente'
  }

  get esSinPermiso() {
    return this.codigo === 'sin_permiso'
  }

  get esSinSesion() {
    return this.estado === 401
  }
}

// --- Estado de la sesión, en memoria ---------------------------------------
let tokenAcceso = null
let renovacionEnCurso = null

export function guardarAcceso(token) {
  tokenAcceso = token
}

/**
 * El token de acceso, para las pocas peticiones que no pasan por `http`.
 *
 * Solo lo usa el canal de eventos, que necesita `fetch` con lectura por partes y por tanto no puede
 * apoyarse en el envoltorio. Se expone una lectura y no la variable para que nadie pueda cambiarla
 * desde fuera por descuido: una sola escritura, una sola forma de saber cuál es el token vigente.
 */
export function leerAcceso() {
  return tokenAcceso
}

export function leerRenovacion() {
  try {
    return sessionStorage.getItem(CLAVE_RENOVACION)
  } catch {
    // Un navegador con el almacenamiento bloqueado no puede renovar sesiones, pero el panel debe
    // seguir funcionando hasta que caduque el token de acceso.
    return null
  }
}

export function guardarRenovacion(token) {
  try {
    if (token) sessionStorage.setItem(CLAVE_RENOVACION, token)
    else sessionStorage.removeItem(CLAVE_RENOVACION)
  } catch {
    /* sin almacenamiento: la sesión dura lo que dure el token de acceso */
  }
}

export function olvidarTokens() {
  tokenAcceso = null
  guardarRenovacion(null)
}

/**
 * Suscriptores a los que avisar cuando la sesión se pierde.
 *
 * Es un aviso y no una excepción a propósito: la sesión se cae en mitad de una petición cualquiera,
 * y quien la hizo no tiene por qué saber cómo llevar al usuario a la pantalla de acceso.
 */
const alPerderSesion = new Set()

export function alCaducarSesion(funcion) {
  alPerderSesion.add(funcion)
  return () => alPerderSesion.delete(funcion)
}

function avisarSesionPerdida(motivo, mensaje = '') {
  olvidarTokens()
  for (const funcion of alPerderSesion) funcion(motivo, mensaje)
}

/**
 * Quien se suscribe se entera de que su empresa quedó suspendida.
 *
 * Va aparte de la pérdida de sesión porque no es lo mismo: aquí la contraseña y la cuenta siguen
 * siendo válidas y lo que está cerrado es la empresa entera. Cerrar la sesión dejaría al usuario en
 * la pantalla de acceso con un formulario que, al rellenarlo, le devolvería al mismo sitio: una
 * puerta que gira y no lleva a ninguna parte.
 */
const alQuedarSuspendida = new Set()

export function alSuspenderEmpresa(funcion) {
  alQuedarSuspendida.add(funcion)
  return () => alQuedarSuspendida.delete(funcion)
}

function avisarEmpresaSuspendida(mensaje) {
  for (const funcion of alQuedarSuspendida) funcion(mensaje)
}

// --- Peticiones -------------------------------------------------------------

function construirUrl(ruta, parametros) {
  const url = new URL(`${BASE}${ruta}`, window.location.origin)
  for (const [clave, valor] of Object.entries(parametros || {})) {
    if (valor === null || valor === undefined || valor === '') continue
    // Los filtros de varias palabras clave viajan como parámetros repetidos
    // (`?termino=obras&termino=viales`), que es lo que espera la API.
    if (Array.isArray(valor)) {
      for (const elemento of valor) {
        if (elemento !== null && elemento !== undefined && elemento !== '') {
          url.searchParams.append(clave, elemento)
        }
      }
      continue
    }
    url.searchParams.append(clave, String(valor))
  }
  return url.toString()
}

async function interpretarError(respuesta) {
  let cuerpo = null
  try {
    cuerpo = await respuesta.json()
  } catch {
    /* la respuesta no traía JSON: se usa el texto de estado */
  }

  const codigo = cuerpo?.codigo || (respuesta.status === 401 ? 'sin_sesion' : 'error')
  const mensaje =
    cuerpo?.detail ||
    (Array.isArray(cuerpo?.detail) ? cuerpo.detail.map((d) => d.msg).join('. ') : null) ||
    `La API respondió ${respuesta.status}.`

  return new ErrorApi(mensaje, { estado: respuesta.status, codigo, detalles: cuerpo })
}

async function enviar(ruta, { metodo = 'GET', cuerpo, parametros, sinReintento = false } = {}) {
  const cabeceras = { Accept: 'application/json' }
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json'
  if (tokenAcceso) cabeceras.Authorization = `Bearer ${tokenAcceso}`

  let respuesta
  try {
    respuesta = await fetch(construirUrl(ruta, parametros), {
      method: metodo,
      headers: cabeceras,
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    })
  } catch (error) {
    // Aquí no hay respuesta: el problema es de red, no de la API. Se distingue porque el mensaje que
    // hay que dar al usuario es distinto: «no hay conexión» no es «algo falló en el servidor».
    throw new ErrorApi(
      'No se pudo contactar con el servidor. Comprueba tu conexión e inténtalo de nuevo.',
      { estado: 0, codigo: 'sin_conexion', detalles: error },
    )
  }

  if (respuesta.status === 401 && !sinReintento) {
    // El cuerpo se interpreta **antes** de intentar renovar, porque puede traer la explicación.
    const error = await interpretarError(respuesta)

    // Una sesión revocada es terminal. El token de acceso sigue pasando la firma —por eso la
    // respuesta es un 401 y no un 403— pero la sesión ya no existe, así que renovar no puede
    // funcionar nunca. Se evita el intento y, sobre todo, se conserva el motivo: el mensaje que hay
    // que enseñar viene en esta respuesta, no en la del intento de renovación.
    if (error.codigo === 'sesion_revocada') {
      avisarSesionPerdida(error.detalles?.motivo || 'revocada', error.message)
      throw error
    }

    const renovado = await renovarEnSilencio()
    if (renovado) return enviar(ruta, { metodo, cuerpo, parametros, sinReintento: true })
    avisarSesionPerdida('caducada')
    throw error
  }

  if (respuesta.status === 403) {
    const error = await interpretarError(respuesta)
    // Una empresa suspendida se avisa por su propio camino: la sesión no se toca.
    if (error.codigo === 'empresa_suspendida') avisarEmpresaSuspendida(error.message)
    throw error
  }

  if (!respuesta.ok) throw await interpretarError(respuesta)

  if (respuesta.status === 204) return null
  const texto = await respuesta.text()
  return texto ? JSON.parse(texto) : null
}

/**
 * Descarga un archivo de la API.
 *
 * No puede apoyarse en `enviar`, que devuelve JSON, porque aquí la respuesta son bytes. Lo que sí
 * comparte es lo que de verdad importa: la dirección con sus parámetros, el token, la renovación
 * silenciosa cuando caduca y la interpretación de los errores. Reescribir eso aparte sería duplicar
 * justo la parte donde es fácil equivocarse, y la que se arregló una vez —la sesión revocada que no
 * debe intentar renovar— volvería a estar mal en la copia.
 *
 * Se pide con `fetch` y no con un enlace `<a href>`: un enlace no lleva la cabecera del token, y el
 * archivo no es público. Sin sesión no hay descarga.
 */
async function descargar(ruta, { parametros, sinReintento = false } = {}) {
  const cabeceras = { Accept: TIPO_LIBRO }
  if (tokenAcceso) cabeceras.Authorization = `Bearer ${tokenAcceso}`

  let respuesta
  try {
    respuesta = await fetch(construirUrl(ruta, parametros), { headers: cabeceras })
  } catch (error) {
    throw new ErrorApi(
      'No se pudo contactar con el servidor. Comprueba tu conexión e inténtalo de nuevo.',
      { estado: 0, codigo: 'sin_conexion', detalles: error },
    )
  }

  if (respuesta.status === 401 && !sinReintento) {
    const error = await interpretarError(respuesta)
    if (error.codigo === 'sesion_revocada') {
      avisarSesionPerdida(error.detalles?.motivo || 'revocada', error.message)
      throw error
    }
    const renovado = await renovarEnSilencio()
    if (renovado) return descargar(ruta, { parametros, sinReintento: true })
    avisarSesionPerdida('caducada')
    throw error
  }

  if (respuesta.status === 403) {
    const error = await interpretarError(respuesta)
    if (error.codigo === 'empresa_suspendida') avisarEmpresaSuspendida(error.message)
    throw error
  }

  if (!respuesta.ok) throw await interpretarError(respuesta)

  return {
    contenido: await respuesta.blob(),
    nombre: nombreDeArchivo(respuesta),
    filas: Number(respuesta.headers.get('X-Contenido-Filas') || 0),
  }
}

/**
 * Nombre del archivo, tal y como lo propone el servidor.
 *
 * Se lee de la cabecera en lugar de componerlo aquí para que el nombre siga siendo una decisión del
 * servidor, que es quien sabe con qué filtros se generó. Si el navegador no deja leer la cabecera
 * —un despliegue con el origen cruzado y sin `expose_headers`— queda un nombre genérico: se pierde
 * detalle, pero la descarga funciona, que es lo que no puede fallar.
 */
function nombreDeArchivo(respuesta) {
  const cabecera = respuesta.headers.get('Content-Disposition') || ''
  const encontrado = /filename="?([^";]+)"?/i.exec(cabecera)
  return encontrado ? encontrado[1] : 'contrataciones.xlsx'
}

/**
 * Renueva los tokens una sola vez, aunque varias peticiones fallen a la vez.
 *
 * Sin esta guarda, cinco peticiones simultáneas con el token caducado lanzarían cinco renovaciones
 * con **el mismo** token de renovación. Como el token rota en cada uso, la primera valdría y las
 * otras cuatro se interpretarían como «hay dos copias en circulación»: el servidor cerraría todas
 * las sesiones de la cuenta. El usuario vería que el panel le echa la culpa de algo que hizo el
 * propio panel.
 */
async function renovarEnSilencio() {
  if (renovacionEnCurso) return renovacionEnCurso

  const token = leerRenovacion()
  if (!token) return false

  renovacionEnCurso = (async () => {
    try {
      const respuesta = await fetch(construirUrl('/v1/auth/sesion/renovacion'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token_renovacion: token }),
      })
      if (!respuesta.ok) return false

      const datos = await respuesta.json()
      guardarAcceso(datos.token_acceso)
      guardarRenovacion(datos.token_renovacion)
      return true
    } catch {
      return false
    } finally {
      renovacionEnCurso = null
    }
  })()

  return renovacionEnCurso
}

export const http = {
  get: (ruta, parametros) => enviar(ruta, { parametros }),
  post: (ruta, cuerpo, parametros) => enviar(ruta, { metodo: 'POST', cuerpo, parametros }),
  put: (ruta, cuerpo, parametros) => enviar(ruta, { metodo: 'PUT', cuerpo, parametros }),
  del: (ruta, parametros) => enviar(ruta, { metodo: 'DELETE', parametros }),
  descargar,
}
