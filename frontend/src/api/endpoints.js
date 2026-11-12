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

  /**
   * Da de baja la palabra clave: deja de seguirla el negocio.
   *
   * No borra el término del catálogo —es global y puede estar suscrito por otros negocios—, solo
   * desactiva **esta** suscripción. Es la operación que faltaba: el panel podía deseleccionar una
   * palabra pero no darla de baja, y por eso volver a agregarla contestaba «ya se consultó hace
   * poco», que se lee como que ya estaba puesta.
   *
   * Va por `POST /quitar` y no por `DELETE /{id}` para seguir la misma forma que la baja del CPC.
   */
  quitarTermino: (terminoId) => http.post('/v1/terminos/quitar', { termino_id: terminoId }),

  // --- Términos de CPC del negocio -----------------------------------------
  //
  // Se guardan en el servidor, como las palabras clave, para que la lista sea la misma para todo el
  // equipo y siga ahí al recargar. **No disparan ingesta**: solo acotan un histórico ya descargado,
  // así que no hay cola ni espera.
  listarCpc: () => http.get('/v1/cpc'),

  agregarCpc: (textos) => http.post('/v1/cpc/lote', { textos }),

  /** Un solo término. Va aparte del lote para no mandar una lista de uno. */
  agregarUnCpc: (texto) => http.post('/v1/cpc', { texto }),

  /**
   * Quita un término. Va por `POST /quitar` y no por `DELETE /{texto}` porque el término lleva
   * espacios y acentos —«LAVADO Y ENGRASADO DE AUTOMOTORES»— y en la ruta dependería de que quien
   * llama lo escape bien.
   */
  quitarCpc: (texto) => http.post('/v1/cpc/quitar', { texto }),

  vaciarCpc: () => http.del('/v1/cpc'),

  verPerfil: () => http.get('/v1/empresa/perfil'),
  guardarPerfil: (campos) => http.put('/v1/empresa/perfil', campos),
  consultarRuc: (ruc) => http.post('/v1/empresa/perfil/consulta-ruc', { ruc }),
  consultarContratos: (ruc, razon_social) =>
    http.post('/v1/empresa/perfil/consulta-contratos', { ruc, razon_social }),
  // El RUP no tiene consulta pública: se sube el certificado en PDF impreso desde el SOCE.
  leerRup: (archivo) => http.enviarArchivo('/v1/empresa/perfil/leer-rup', archivo),
  // Lo mismo con el texto ya sacado en el navegador por OCR (RUP escaneado o foto).
  leerRupTexto: (texto) => http.post('/v1/empresa/perfil/leer-rup-texto', { texto }),
  aplicarRup: (eleccion) => http.post('/v1/empresa/perfil/aplicar-rup', eleccion),
  agregarPerfil: (coleccion, campos) => http.post(`/v1/empresa/perfil/${coleccion}`, campos),
  quitarPerfil: (coleccion, id) => http.del(`/v1/empresa/perfil/${coleccion}/${id}`),

  verRadar: () => http.get('/v1/radar'),
  verPropuestas: (parametros = {}) => http.get('/v1/propuestas', parametros),
  listarBusquedas: () => http.get('/v1/busquedas'),
  guardarBusqueda: (nombre, parametros) => http.post('/v1/busquedas', { nombre, parametros }),
  quitarBusqueda: (id) => http.del(`/v1/busquedas/${id}`),
  listarAlertas: () => http.get('/v1/alertas'),
  crearAlerta: (campos) => http.post('/v1/alertas', campos),
  previsualizarAlerta: (campos) => http.post('/v1/alertas/vista-previa', campos),
  // «Mis ofertas»: las proformas hechas, por etapa.
  misOfertas: () => http.get('/v1/mis-ofertas'),
  moverOferta: (id, campos) => http.patch(`/v1/mis-ofertas/${id}`, campos),
  quitarAlerta: (id) => http.del(`/v1/alertas/${id}`),
  listarAvisos: () => http.get('/v1/avisos'),
  leerAviso: (id) => http.post(`/v1/avisos/${id}/leido`),

  adjudicaciones: (parametros) => http.get('/v1/mercado/adjudicaciones', parametros),
  preciosMercado: (parametros) => http.get('/v1/mercado/precios', parametros),
  proveedoresMercado: (parametros) => http.get('/v1/mercado/proveedores', parametros),
  entidadesMercado: (parametros) => http.get('/v1/mercado/entidades', parametros),
  demandaMercado: (parametros) => http.get('/v1/mercado/demanda', parametros),
  compararMercado: (ids) => http.post('/v1/mercado/comparar', { ids }),

  leerDocumento: (archivo) => http.enviarArchivo('/v1/documentos/leer', archivo),
  lecturas: () => http.get('/v1/documentos/lecturas'),
  resumenDocumento: (campos) => http.post('/v1/documentos/resumen', campos),
  estadoDesdeCodigo: (codigo) => http.get('/v1/documentos/desde-codigo/estado', { codigo }),
  prepararDesdeCodigo: (codigo, reintentar = false) =>
    http.post('/v1/documentos/desde-codigo', { codigo, reintentar }),
  requisitosDocumento: (lecturaId) =>
    http.get('/v1/documentos/requisitos', lecturaId ? { lectura_id: lecturaId } : {}),
  marcarRequisito: (id, estado) => http.post(`/v1/documentos/requisitos/${id}`, { estado }),
  crearProforma: (campos) => http.post('/v1/documentos/proformas', campos),
  // Títulos ya usados: el panel avisa antes de guardar, porque no se pueden repetir.
  titulosProformas: () => http.get('/v1/documentos/proformas/titulos'),
  crearCotizacion: (campos) => http.post('/v1/documentos/cotizaciones', campos),
  crearFicha: (campos) => http.post('/v1/documentos/fichas', campos),
  contrastarDocumento: (lecturaId, proformaId) =>
    http.post('/v1/documentos/contrastar', { lectura_id: lecturaId, proforma_id: proformaId }),
  preguntar: (pregunta, lecturaId = null) =>
    http.post('/v1/documentos/preguntar', { pregunta, lectura_id: lecturaId }),
  bajarDocumento: (id, formato) =>
    http.descargar(`/v1/documentos/proformas/${id}/${formato}`, { aceptar: '*/*' }),
  generarOferta: (campos) => http.post('/v1/documentos/generar', campos),
  verificarDocumento: (id) => http.get(`/v1/documentos/proformas/${id}/verificacion`),
  // El servidor entrega los datos; el PDF lo arma el navegador y el servidor solo lo firma.
  verDocumento: (id) => http.get(`/v1/documentos/proformas/${id}`),
  firmarPdf: (id, pdf, cajas, certificado, clave, lugar = '') => {
    const formulario = new FormData()
    formulario.append('pdf', pdf, 'proforma.pdf')
    formulario.append('cajas', JSON.stringify(cajas))
    formulario.append('certificado', certificado, certificado.name)
    formulario.append('clave', clave)
    formulario.append('lugar', lugar)
    return http.enviarFormularioYBajar(`/v1/documentos/proformas/${id}/firmar-pdf`, formulario)
  },
  // El certificado y la clave van solo en esta petición; el servidor no los guarda.
  firmarDocumento: (id, certificado, clave, lugar = '') => {
    const formulario = new FormData()
    formulario.append('certificado', certificado, certificado.name)
    formulario.append('clave', clave)
    formulario.append('lugar', lugar)
    return http.enviarFormularioYBajar(`/v1/documentos/proformas/${id}/firmar`, formulario)
  },
  verCreditos: () => http.get('/v1/ia/creditos'),
  comprarCreditos: (paquete) => http.post('/v1/ia/compras', { paquete }),
  otorgarCreditosIa: (negocioId, cantidad, motivo) =>
    http.post(`/v1/plataforma/ia/otorgar/${negocioId}`, { cantidad, motivo }),
  comprasPendientesIa: () => http.get('/v1/plataforma/ia/compras'),
  resolverCompraIa: (negocioId, compraId, pagada) =>
    http.post(`/v1/plataforma/ia/compras/${negocioId}/${compraId}`, { pagada }),

  pedirTdr: (registroId) => http.post(`/v1/tdr/${registroId}`),
  estadoTdr: (registroId) => http.get(`/v1/tdr/${registroId}`),
  rellenoTdr: (registroId) => http.get(`/v1/tdr/${registroId}/relleno`),
  // El archivo va con el token. Un iframe con la URL a pelo no manda Authorization y el visor
  // recibiría un 401.
  archivoTdr: (registroId, documentoId) =>
    http.descargar(`/v1/tdr/${registroId}/archivo/${documentoId}`, { aceptar: '*/*' }),

  // --- Datos ---------------------------------------------------------------
  /**
   * La versión de los datos: un solo número que sube cuando la ingesta escribe algo.
   *
   * Cuesta una lectura de caché —no toca la base—, y es lo que permite que el panel sepa que el
   * ciclo terminó en lugar de recargar la tabla a ciegas cada minuto. La ingesta la sube también
   * cuando escribe los **CPC**, así que la recarga trae la clasificación y no solo la necesidad.
   */
  versionDatos: () => http.get('/v1/ingestas/version'),

  /** `parametros.termino` puede ser una lista: la API acepta `termino=a&termino=b`. */
  buscar: (parametros) => http.get('/v1/registros', parametros),

  /**
   * Descarga el Excel con **todos** los resultados de los filtros, no solo la página visible.
   *
   * No usa `http.get` porque la respuesta son bytes y no JSON: la descarga pasa por el mismo camino
   * que el resto en cuanto a token, renovación y errores, pero devuelve el archivo en lugar de
   * intentar interpretarlo.
   *
   * Los criterios van **envueltos en `{ parametros }`** porque `descargar` recibe un objeto con
   * opciones, no los parámetros sueltos. Sin la envoltura, `parametros` llegaba `undefined` y la
   * petición salía sin querystring: el archivo traía el histórico entero —hasta el tope de veinte
   * mil filas— en vez de lo que estaba filtrado en pantalla, y el usuario no tenía forma de notarlo
   * salvo contando las filas del Excel.
   */
  exportarRegistros: (parametros) =>
    http.descargar('/v1/registros/exportacion', { parametros }),

  // --- Plantilla de Excel de la empresa ------------------------------------
  //
  // La plantilla es del negocio, no del usuario: la sube un administrador y la usan todas las
  // exportaciones de esa empresa. Por eso no lleva ninguna clave en la ruta.
  verPlantilla: () => http.get('/v1/plantilla'),
  subirPlantilla: (archivo) => http.enviarArchivo('/v1/plantilla', archivo),
  quitarPlantilla: () => http.del('/v1/plantilla'),

  /**
   * Guarda qué columnas llevan las exportaciones de la empresa.
   *
   * Se manda la lista **entera**, no un cambio parcial: con «añade esta y quita aquella» habría que
   * distinguir «no lo envíes» de «bórralo», y dos navegadores abiertos acabarían pisándose la
   * selección sin que ninguno se entere. La lista vacía significa «todas».
   */
  guardarColumnas: (columnas) => http.put('/v1/plantilla/columnas', { columnas }),

  /**
   * Qué haría el sistema con la plantilla subida: hoja de destino de cada familia, fila de títulos
   * reconocida y columnas que se van a rellenar. Abre el archivo, así que se pide a propósito.
   */
  analizarPlantilla: () => http.get('/v1/plantilla/analisis'),

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
  // Respaldo sin sesión de la consulta al SRI del registro (el navegador la intenta primero).
  consultarRucPublico: (ruc) => http.post('/v1/registro/consulta-ruc', { ruc }),

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

  /** Quita el bloqueo por intentos fallidos sin tocar la contraseña. */
  desbloquearUsuario: (usuarioId) => http.post(`/v1/usuarios/${usuarioId}/desbloqueo`),

  /** Las vistas propias con su plazo. Cualquiera puede consultar las suyas. */
  misVistas: (usuarioId) => http.get(`/v1/accesos/usuarios/${usuarioId}`),

  /** Avisa al superadministrador de que este usuario necesita más días. No alarga el plazo. */
  pedirMasTiempo: () => http.post('/v1/accesos/solicitud'),

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

  /**
   * Lo que han trabajado los workers: el último ciclo de cada fuente, la serie de los últimos y la
   * petición que esté pendiente.
   *
   * Es de lectura y no cuesta base de datos: el estado y el historial salen de `sincronizacion`, que
   * los propios ciclos ya escriben.
   */
  trabajoDeIngesta: () => http.get('/v1/plataforma/ingesta/historial'),

  /**
   * Pide un ciclo de ingesta completo. **No ingesta nada**: deja la petición donde el worker la ve y
   * contesta en cuanto está escrita, para que la pantalla pueda decir «en cola» sin quedarse
   * esperando minutos a que el ciclo termine.
   *
   * Va por aquí y no lo hace el navegador contra el SERCOP por una razón de diseño: ninguna petición
   * de usuario puede originar tráfico hacia la fuente oficial (R-01), y el único proceso que habla
   * con ella es el worker.
   */
  pedirCiclo: () => http.post('/v1/plataforma/ingesta/solicitud'),

  suspenderEmpresa: (negocioId) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/suspension`),

  reactivarEmpresa: (negocioId) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/reactivacion`),

  /**
   * Elimina una empresa con sus cuentas, sus accesos y su plantilla. **No se deshace.**
   *
   * `confirmacion` es el nombre de la empresa tal cual, y viaja como parámetro de la dirección porque
   * el borrado no tiene cuerpo: lo que se pide no es crear nada, es que algo deje de existir. El
   * servidor lo compara (sin distinguir mayúsculas ni espacios de sobra) y rechaza la petición si no
   * coincide, así que este texto no es una formalidad que se pueda saltar desde fuera: es la única
   * forma de que la operación ocurra.
   */
  eliminarEmpresa: (negocioId, confirmacion) =>
    http.del(`/v1/plataforma/empresas/${negocioId}`, { confirmacion }),

  /** Elimina una cuenta concreta de cualquier empresa. Se confirma con su correo. */
  eliminarUsuarioDeEmpresa: (negocioId, usuarioId, confirmacion) =>
    http.del(`/v1/plataforma/empresas/${negocioId}/usuarios/${usuarioId}`, { confirmacion }),

  /** Contraseña temporal para una cuenta de cualquier empresa; se exige cambiarla al entrar. */
  fijarContrasenaEnEmpresa: (negocioId, usuarioId, contrasena) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/usuarios/${usuarioId}/contrasena`, {
      contrasena,
    }),

  /** Quita el bloqueo por intentos fallidos de una cuenta de cualquier empresa. */
  desbloquearEnEmpresa: (negocioId, usuarioId) =>
    http.post(`/v1/plataforma/empresas/${negocioId}/usuarios/${usuarioId}/desbloqueo`),

  // Las vistas se conceden **por cuenta**, no por empresa: el plazo es de una persona concreta para
  // una vista concreta. Por eso hay que decir de qué negocio es la cuenta (`negocio`) cuando quien
  // llama es el superadministrador y la cuenta no es de su empresa.
  usuariosDeNegocio: (negocioId) => http.get('/v1/accesos/usuarios', { negocio: negocioId }),

  concederVista: (usuarioId, negocioId, vista, plazo) =>
    http.post(`/v1/accesos/usuarios/${usuarioId}/vistas`, { vista, plazo }, { negocio: negocioId }),

  retirarVista: (usuarioId, negocioId, vista) =>
    http.del(`/v1/accesos/usuarios/${usuarioId}/vistas/${vista}`, { negocio: negocioId }),

  /**
   * Anexos para la proforma de un proceso con oferta (OCDS): TDR, pliego, especificaciones y solo
   * la última acta, más el monto del proceso con su fuente. Consulta los datos abiertos del SERCOP
   * (una petición, recordada media hora); para una ínfima responde 400.
   */
  anexosDeProceso: (registroId) => http.get(`/v1/procesos/${registroId}/anexos`),

  // ------------------------------------------------------------------ Asistente (chat con IA)
  /** Saludo, resumen, sugerencias, conversaciones guardadas, la última abierta y los créditos de IA. */
  asistenteInicio: () => http.get('/v1/asistente/inicio'),
  asistenteConversaciones: () => http.get('/v1/asistente/conversaciones'),
  /** Una conversación con sus mensajes. */
  asistenteConversacion: (id) => http.get(`/v1/asistente/conversaciones/${encodeURIComponent(id)}`),
  renombrarConversacion: (id, titulo) =>
    http.patch(`/v1/asistente/conversaciones/${encodeURIComponent(id)}`, { titulo }),
  borrarConversacion: (id) => http.del(`/v1/asistente/conversaciones/${encodeURIComponent(id)}`),
  /** Envía un mensaje; sin `conversacion_id` el servidor abre una conversación nueva. */
  asistenteEnviar: ({ texto, conversacion_id = null }) =>
    http.post('/v1/asistente/mensajes', { texto, conversacion_id }),
}
