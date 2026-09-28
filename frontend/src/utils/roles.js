/**
 * Nombres de los roles, para mostrarlos.
 *
 * El catálogo de verdad vive en el servidor (`dominio/roles.py`), que es quien decide qué rol puede
 * hacer qué. Aquí solo están los nombres, y el panel pide la lista de roles asignables a la API
 * (`GET /v1/usuarios`, campo `roles`) en lugar de deducirla de este archivo. Así, el día que se añada
 * un rol, el desplegable lo ofrecerá solo y lo único que faltará es su nombre bonito, que es lo peor
 * que puede pasar: se vería el código del rol, no una lista incompleta.
 */

export const ETIQUETAS_ROL = {
  super_admin: 'Superadministrador',
  admin_negocio: 'Administrador de la empresa',
  consultor: 'Consultor',
  lector: 'Solo lectura',
}

/** ¿Puede este rol gestionar cuentas y permisos? */
export function esAdministrativo(rol) {
  return rol === 'super_admin' || rol === 'admin_negocio'
}

/**
 * ¿Puede este rol descargar el histórico?
 *
 * Espeja `ROLES_EXPORTADORES` del servidor, y sirve solo para no ofrecer un botón que va a ser
 * rechazado: la comprobación de verdad está en el servidor, que la repite. `lector` ve la tabla y no
 * la descarga, porque el archivo sale de la plataforma y deja de estar bajo nuestro control.
 */
export function puedeExportar(rol) {
  return rol === 'super_admin' || rol === 'admin_negocio' || rol === 'consultor'
}
