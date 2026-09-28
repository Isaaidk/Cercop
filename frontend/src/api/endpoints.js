/**
 * Los endpoints de la API, cada uno con su nombre.
 *
 * Existe para que ninguna parte del panel escriba una ruta a mano. Una ruta escrita en un componente
 * es una ruta que no se puede cambiar ni buscar; aquí están todas juntas y se ve de un vistazo de
 * qué depende el panel.
 *
 * Se respeta el contrato tal y como lo publica la API (ver `backend/scripts/contrato_api.py`), y no
 * se «arreglan» aquí los nombres de los campos: si el panel y la API usaran nombres distintos para
 * lo mismo, alguien tendría que recordar la traducción, y eso se olvida.
 */

import { http } from './cliente'

export const api = {
  // --- Sesión --------------------------------------------------------------
  iniciarSesion: (email, contrasena) =>
    http.post('/v1/auth/sesion', { email, contrasena }),

  sesionActual: () => http.get('/v1/auth/sesion'),

  /** El token de renovación rota en cada uso: el que se acaba de enviar deja de valer. */
  renovarSesion: (tokenRenovacion) =>
    http.post('/v1/auth/sesion/renovacion', { token_renovacion: tokenRenovacion }),

  cerrarSesion: (tokenRenovacion, motivo = 'logout') =>
    http.post('/v1/auth/sesion/cierre', {
      token_renovacion: tokenRenovacion,
      motivo,
    }),

  // --- Políticas y consentimiento ------------------------------------------
  estadoConsentimiento: () => http.get('/v1/politicas'),
  textoPolitica: (tipo) => http.get(`/v1/politicas/${tipo}`),

  aceptarPolitica: (tipo, version, hash) =>
    http.post(`/v1/politicas/${tipo}/aceptacion`, { version, hash }),

  revocarPolitica: (tipo) => http.post(`/v1/politicas/${tipo}/revocacion`),

  // --- Palabras clave ------------------------------------------------------
  listarTerminos: () => http.get('/v1/terminos'),

  agregarTermino: (texto) => http.post('/v1/terminos', { texto }),

  /**
   * Agrega varias palabras clave en **una sola** petición.
   *
   * Se añadió porque pegar una lista de temas es el uso real, y hacerlo palabra a palabra son treinta
   * peticiones encadenadas: cada una abre su conexión con la base y la espera se va a más de un
   * minuto. El servidor las crea todas en una transacción.
   */
  agregarTerminos: (textos) => http.post('/v1/terminos/lote', { textos }),

  estadoTermino: (terminoId) => http.get(`/v1/terminos/${terminoId}/estado`),

  // --- Datos ---------------------------------------------------------------
  /** `parametros.termino` puede ser una lista: la API acepta `termino=a&termino=b`. */
  buscar: (parametros) => http.get('/v1/registros', parametros),

  /**
   * Descarga el Excel con **todos** los resultados de los filtros, no solo la página visible.
   *
   * No usa `http.get` porque la respuesta son bytes y no JSON: la descarga pasa por el mismo camino
   * que el resto en cuanto a token, renovación y errores, pero devuelve el archivo en lugar de
   * intentar interpretarlo.
   */
  exportarRegistros: (parametros) => http.descargar('/v1/registros/exportacion', parametros),

  catalogos: () => http.get('/v1/catalogos'),

  /**
   * Los agregados de las gráficas.
   *
   * Recibe **los mismos filtros que la búsqueda**, no solo la fuente. Antes esta función envolvía lo
   * que le llegara bajo la clave `fuente` —`{ fuente: { termino: [...], provincia: '...' } }`—, y el
   * resultado era que las gráficas resumían el histórico entero mientras la tabla mostraba lo
   * filtrado. Se pasan tal cual, sin envolver nada.
   */
  estadisticas: (parametros) => http.get('/v1/estadisticas', parametros),

  ingestas: () => http.get('/v1/ingestas'),

  // --- Presencia -----------------------------------------------------------
  presencia: () => http.get('/v1/presencia'),

  latir: (sesionId) => http.post('/v1/presencia/latido', { sesion_id: sesionId }),

  // El cierre de sesión es `cerrarSesion`. Existió un `avisarCierre` que revocaba la sesión al
  // descargar la página, y se retiró: saltaba también al recargar y dejaba al usuario fuera.

  // --- Registro de empresa -------------------------------------------------
  //
  // Los dos únicos endpoints del sistema que no necesitan sesión. `requisitos` existe para que el
  // formulario no tenga que copiar la política de contraseñas: una copia en el navegador diría
  // «mínimo 8 caracteres» el día que el servidor pase a exigir 12, y el formulario rechazaría lo que
  // acaba de dar por bueno.
  requisitosDeRegistro: () => http.get('/v1/registro/requisitos'),

  registrarEmpresa: (datos) => http.post('/v1/registro/empresa', datos),

  // --- Empresa propia ------------------------------------------------------
  miEmpresa: () => http.get('/v1/negocio'),

  editarMiEmpresa: (datos) => http.put('/v1/negocio', datos),

  // --- Gestión de usuarios -------------------------------------------------
  //
  // Dar de baja es `POST` y no `DELETE` aunque parezca lo contrario, y es a propósito: la baja es
  // reversible y conserva el registro de consentimiento de la persona. El borrado de verdad sí es
  // `DELETE`, y exige escribir el correo de la cuenta como confirmación.
  listarUsuarios: (incluirInactivos = true) =>
    http.get('/v1/usuarios', { inactivos: incluirInactivos }),

  crearUsuario: (datos) => http.post('/v1/usuarios', datos),

  darDeBajaUsuario: (usuarioId) => http.post(`/v1/usuarios/${usuarioId}/baja`),

  reactivarUsuario: (usuarioId, datos = {}) =>
    http.post(`/v1/usuarios/${usuarioId}/reactivacion`, datos),

  eliminarUsuario: (usuarioId, confirmacion) =>
    http.del(`/v1/usuarios/${usuarioId}`, { confirmacion }),

  fijarContrasenaDeUsuario: (usuarioId, contrasena) =>
    http.post(`/v1/usuarios/${usuarioId}/contrasena`, { contrasena }),

  // --- Contraseña propia --------------------------------------------------
  cambiarMiContrasena: (contrasenaActual, contrasenaNueva, sesionActual) =>
    http.post('/v1/auth/contrasena', {
      contrasena_actual: contrasenaActual,
      contrasena_nueva: contrasenaNueva,
      sesion_actual: sesionActual,
    }),

  // --- Administración de la plataforma -----------------------------------
  //
  // Solo responden al superadministrador; a cualquier otro le devuelven 403. La comprobación está en
  // el servidor, no aquí: esconder el botón no es un control de acceso.
  catalogoDeAccesos: () => http.get('/v1/accesos/catalogo'),

  listarEmpresas: () => http.get('/v1/plataforma/empresas'),

  suspenderEmpresa: (negocioId) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/suspension`),

  reactivarEmpresa: (negocioId) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/reactivacion`),

  // Las vistas se conceden **por cuenta**, no por empresa: el plazo es de una persona concreta para
  // una vista concreta. Por eso hay que decir de qué negocio es la cuenta (`negocio`) cuando quien
  // llama es el superadministrador y la cuenta no es de su empresa.
  usuariosDeNegocio: (negocioId) => http.get('/v1/accesos/usuarios', { negocio: negocioId }),

  concederVista: (usuarioId, negocioId, vista, plazo) =>
    http.post(`/v1/accesos/usuarios/${usuarioId}/vistas`, { vista, plazo }, { negocio: negocioId }),

  retirarVista: (usuarioId, negocioId, vista) =>
    http.del(`/v1/accesos/usuarios/${usuarioId}/vistas/${vista}`, { negocio: negocioId }),
}
