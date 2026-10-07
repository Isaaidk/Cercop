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
 *
 * Además de esperar al 401, la renovación se **programa** para un minuto antes de que caduque el
 * token de acceso. No es un adorno: sin ello, cada petición que llegara justo después de la
 * caducidad pagaría una ida y vuelta de más —y el canal de eventos, que no pasa por aquí, se
 * reconectaría con un token muerto—. Se sigue intentando en el 401 porque un temporizador puede
 * llegar tarde: un portátil que se suspende no lo ejecuta hasta que despierta.
 *
 * Varias pestañas del mismo navegador
 * -----------------------------------
 * Cada pestaña guarda su copia del token de renovación, y ese token **rota en cada uso**. Si la
 * pestaña A renueva, la copia de la pestaña B queda atrás; cuando B renueve con ella, el servidor
 * verá dos copias en circulación y cerrará todas las sesiones de la cuenta. Para que eso no pase,
 * la pestaña que renueva **publica el par nuevo** y las demás lo adoptan en el acto. Por el mismo
 * canal se avisa del cierre de sesión: si una cierra, las otras dejan de fingir que siguen dentro.
 *
 * Es una decisión, no una comodidad: sin ella el panel funcionaba bien con una pestaña y se
 * expulsaba solo con dos. El canal existe en todos los navegadores que soporta el panel, y donde
 * faltara el comportamiento es el de antes, apoyado en la ventana de gracia del servidor.
 */

const BASE = (import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')
const CLAVE_RENOVACION = 'contratacion:renovacion'

/**
 * Lo que se le dice a una persona cuando su sesión deja de servir.
 *
 * No habla de tokens ni de renovaciones aunque el problema sea exactamente eso. Un mensaje técnico
 * en pantalla no ayuda a nadie —a quien intentara forzar el sistema tampoco: ya sabe lo que estaba
 * haciendo— y sí confunde a quien simplemente ha vuelto al panel después de un rato y no entiende
 * por qué le hablan de algo que no ha visto en su vida.
 */
const MENSAJE_SESION_CAIDA = 'Tu sesión ha caducado. Vuelve a entrar.'

/**
 * Lo que se le dice a una persona cuando la sesión se cerró desde otra pestaña.
 *
 * No se reutiliza el mensaje de caducidad a propósito: aquí no ha fallado nada y no hay que volver a
 * entrar por un descuido, sino porque alguien pulsó «Salir». Contar lo que pasó evita que el usuario
 * crea que el panel se ha caído justo cuando él cerró sesión en la otra ventana.
 */
const MENSAJE_SESION_CERRADA = 'Se cerró la sesión en otra pestaña.'

// Nombre del canal entre pestañas y los dos avisos que viajan por él.
const CLAVE_CANAL = 'contratacion:sesion'
const AVISO_RENOVACION = 'renovacion'
const AVISO_CIERRE = 'cierre'

// Cuánto antes de la caducidad se pide el par nuevo. Un minuto es holgura de sobra para una petición
// que se hace en segundo plano, y deja catorce de los quince minutos del token para trabajar.
const MARGEN_RENOVACION_MS = 60_000

// Tiempo mínimo entre dos renovaciones programadas. Es una red contra el caso raro de que el
// servidor dé una caducidad ya pasada: sin suelo, se pediría una renovación detrás de otra.
const ESPERA_MINIMA_MS = 15_000

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
let renovacionProgramada = null

/**
 * Cada cierre de sesión abre una generación nueva.
 *
 * Sirve para descartar respuestas que llegan tarde. Una renovación puede tardar segundos, y en ese
 * hueco el usuario puede haber pulsado «Salir»: guardar entonces el par que acaba de llegar
 * devolvería a la vida la sesión que se acaba de cerrar, y las peticiones siguientes llevarían un
 * token que el servidor ya no reconoce. Se compara antes de guardar nada.
 */
let generacionDeSesion = 0

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
  generacionDeSesion += 1
  if (renovacionProgramada !== null) {
    clearTimeout(renovacionProgramada)
    renovacionProgramada = null
  }
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

// --- El canal entre las pestañas del mismo navegador -----------------------

/**
 * Abre el canal, o devuelve `null` si este navegador no lo tiene.
 *
 * Se comprueba antes de usarlo porque `BroadcastChannel` no existe en navegadores antiguos y
 * porque un navegador con el almacenamiento restringido puede lanzar al construirlo. En los dos
 * casos la aplicación tiene que seguir funcionando: lo único que se pierde es la coordinación entre
 * pestañas, que es una mejora, no un requisito.
 */
function abrirCanal() {
  try {
    return typeof BroadcastChannel === 'function' ? new BroadcastChannel(CLAVE_CANAL) : null
  } catch {
    return null
  }
}

const canal = abrirCanal()

canal?.addEventListener('message', (evento) => {
  const aviso = evento?.data
  if (!aviso || typeof aviso !== 'object') return

  if (aviso.tipo === AVISO_RENOVACION) {
    // Otra pestaña renovó: el token de renovación rota en cada uso, así que el de aquí acaba de
    // quedar atrás. Adoptar el nuevo —y **no** volver a renovar con el viejo— es lo que evita el
    // cierre de todas las sesiones de la cuenta.
    if (aviso.token_acceso) guardarAcceso(aviso.token_acceso)
    if (aviso.token_renovacion) guardarRenovacion(aviso.token_renovacion)
    programarRenovacion(aviso.acceso_expira_en)
    return
  }

  if (aviso.tipo === AVISO_CIERRE) {
    // No se renueva nada: la sesión ya no existe en el servidor porque la revocó la otra pestaña.
    // Seguir con el token que hay aquí dejaría la pantalla llena de peticiones que fallan sin decir
    // por qué, y el aviso bueno —«se cerró en otra pestaña»— no llegaría a leerse nunca.
    avisarSesionPerdida('cerrada_en_otra_pestana', MENSAJE_SESION_CERRADA)
  }
})

/**
 * Avisa a las demás pestañas de que la sesión se cerró aquí.
 *
 * Lo llama el cierre explícito —«Salir»— y no la pérdida de sesión: cuando el servidor rechaza un
 * token caducado, la sesión puede seguir viva y las otras pestañas están trabajando bien. Lo que
 * hay que contarles es la revocación, que es la que las deja sin nada que hacer.
 */
export function anunciarCierreDeSesion() {
  canal?.postMessage({ tipo: AVISO_CIERRE })
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
  // El `detail` de FastAPI es un **texto** cuando el error lo levantó el dominio —«Con estas palabras
  // el negocio llegaría a 61 palabras clave activas y el máximo es 60»— y una **lista** de errores de
  // validación cuando lo rechazó el esquema de la petición (un 422).
  //
  // La lista se comprueba primero a propósito: un arreglo siempre es «verdadero», así que mirando el
  // texto antes, la lista se colaba por ahí y `new Error([{...}])` acababa enseñando «[object Object]»
  // en pantalla. Un mensaje así es peor que no decir nada, porque oculta el dato que hacía falta para
  // corregir la petición.
  const detalle = Array.isArray(cuerpo?.detail)
    ? cuerpo.detail
        .map((fallo) => fallo?.msg)
        .filter(Boolean)
        .join('. ')
    : cuerpo?.detail
  const mensaje = detalle || `La API respondió ${respuesta.status}.`

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
    // El mensaje se sustituye por uno dirigido a la persona **antes** de lanzar. El que llegó del
    // servidor habla de la sesión desde el punto de vista del protocolo, y quien capture este error
    // lo enseña tal cual: sin esto, el aviso bueno que acaba de poner `avisarSesionPerdida` se
    // sobrescribía un renglón después con el texto de la respuesta y la pantalla acababa contando
    // algo que el usuario no puede entender ni usar.
    throw new ErrorApi(MENSAJE_SESION_CAIDA, {
      estado: 401,
      codigo: 'sesion_caducada',
      detalles: error.detalles,
    })
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
    // Mismo reemplazo que en `enviar`, y por el mismo motivo: quien capture este error lo enseña.
    throw new ErrorApi(MENSAJE_SESION_CAIDA, {
      estado: 401,
      codigo: 'sesion_caducada',
      detalles: error.detalles,
    })
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
 * Programa la renovación para un minuto antes de que caduque el token de acceso.
 *
 * Por qué no basta con esperar al 401
 * ----------------------------------
 * Esperar funciona —es lo que se hace igualmente—, pero cuesta: la petición que llega justo después
 * de la caducidad viaja con un token muerto, espera un rechazo, renueva y repite. Un minuto de
 * margen sobra para una petición que se hace sin nadie mirando.
 *
 * Lo que **no** garantiza
 * ----------------------
 * Un temporizador de navegador no es una alarma: una pestaña en segundo plano se estrangula y un
 * portátil suspendido no lo ejecuta hasta que despierta. Cuando eso pasa, el camino del 401 sigue
 * ahí y es el que termina de arreglarlo.
 *
 * `ESPERA_MINIMA_MS` existe para el caso raro de que el servidor dé una caducidad ya pasada —relojes
 * desajustados—: sin suelo, la renovación se pediría una y otra vez sin pausa.
 */
export function programarRenovacion(expiraEn) {
  if (renovacionProgramada !== null) {
    clearTimeout(renovacionProgramada)
    renovacionProgramada = null
  }

  const caduca = Date.parse(expiraEn || '')
  if (!Number.isFinite(caduca)) return

  const espera = Math.max(caduca - Date.now() - MARGEN_RENOVACION_MS, ESPERA_MINIMA_MS)

  renovacionProgramada = setTimeout(() => {
    renovacionProgramada = null
    // Que falle importa poco: si no se pudo renovar, la siguiente petición recibirá su 401 y lo
    // intentará por el camino de siempre.
    void renovarEnSilencio()
  }, espera)
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

  const generacion = generacionDeSesion

  renovacionEnCurso = (async () => {
    try {
      const respuesta = await fetch(construirUrl('/v1/auth/sesion/renovacion'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token_renovacion: token }),
      })
      if (!respuesta.ok) return false

      const datos = await respuesta.json()

      // La sesión puede haberse cerrado mientras esta petición iba de camino. Guardar el par que
      // acaba de llegar devolvería a la vida lo que el usuario acaba de cerrar.
      if (generacion !== generacionDeSesion) return false

      guardarAcceso(datos.token_acceso)
      guardarRenovacion(datos.token_renovacion)
      programarRenovacion(datos.acceso_expira_en)

      // Y se cuenta a las demás pestañas: la copia que tienen acaba de quedar atrás, y una
      // renovación con ella se leería como reutilización de token.
      canal?.postMessage({
        tipo: AVISO_RENOVACION,
        token_acceso: datos.token_acceso,
        token_renovacion: datos.token_renovacion,
        acceso_expira_en: datos.acceso_expira_en,
      })
      return true
    } catch {
      return false
    } finally {
      renovacionEnCurso = null
    }
  })()

  return renovacionEnCurso
}

/**
 * Sube un archivo a la API como `multipart/form-data`.
 *
 * No puede reutilizar `enviar`, que serializa el cuerpo a JSON, pero comparte con él lo que de verdad
 * importa: el token, la renovación silenciosa y la interpretación de errores. Reescribir eso aparte
 * duplicaría justo la parte donde es fácil equivocarse.
 *
 * **No se fija `Content-Type` a mano, y es lo más importante de esta función.** El navegador lo pone
 * solo, con la **frontera** que separa una parte de otra del formulario. Escribirlo a mano como
 * `multipart/form-data` —que es lo que apetece al ver el de `enviar`— deja el cuerpo sin frontera, y
 * el servidor no puede saber dónde acaba el nombre del archivo y empiezan los bytes. El síntoma es
 * un error de lectura en el servidor, no un 415: se pierde un rato buscando en el sitio equivocado.
 */
async function enviarArchivo(ruta, archivo, { sinReintento = false } = {}) {
  const formulario = new FormData()
  // El nombre del campo, `archivo`, es el que declara la ruta en el servidor. Se manda también el
  // nombre del fichero —el tercer argumento— porque es lo que se guarda como etiqueta para poder
  // decirle a la persona cuál subió.
  formulario.append('archivo', archivo, archivo.name)

  const cabeceras = { Accept: 'application/json' }
  if (tokenAcceso) cabeceras.Authorization = `Bearer ${tokenAcceso}`

  let respuesta
  try {
    respuesta = await fetch(construirUrl(ruta), {
      method: 'POST',
      headers: cabeceras,
      body: formulario,
    })
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
    // El mismo objeto `archivo` se puede reenviar: un `File` no se consume al subirlo, a diferencia
    // del cuerpo de una petición normal.
    if (renovado) return enviarArchivo(ruta, archivo, { sinReintento: true })
    avisarSesionPerdida('caducada')
    throw new ErrorApi(MENSAJE_SESION_CAIDA, {
      estado: 401,
      codigo: 'sesion_caducada',
      detalles: error.detalles,
    })
  }

  if (respuesta.status === 403) {
    const error = await interpretarError(respuesta)
    if (error.codigo === 'empresa_suspendida') avisarEmpresaSuspendida(error.message)
    throw error
  }

  // El 413 lo devuelve el servidor cuando el archivo pasa del tope, con un mensaje que explica qué
  // hacer. Se deja pasar tal cual en lugar de sustituirlo por uno genérico.
  if (!respuesta.ok) throw await interpretarError(respuesta)

  const texto = await respuesta.text()
  return texto ? JSON.parse(texto) : null
}

export const http = {
  get: (ruta, parametros) => enviar(ruta, { parametros }),
  post: (ruta, cuerpo, parametros) => enviar(ruta, { metodo: 'POST', cuerpo, parametros }),
  put: (ruta, cuerpo, parametros) => enviar(ruta, { metodo: 'PUT', cuerpo, parametros }),
  del: (ruta, parametros) => enviar(ruta, { metodo: 'DELETE', parametros }),
  descargar,
  enviarArchivo,
}
