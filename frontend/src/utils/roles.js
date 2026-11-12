/**
 * Nombres de los roles, para mostrarlos.
 *
 * El catálogo de verdad vive en el servidor (`dominio/roles.py`). Aquí solo se decide qué botones
 * enseñar. Los códigos viejos (`admin_negocio`, `consultor`, `lector`) se aceptan para una sesión
 * que todavía no volvió a entrar después de la migración.
 */

export const ETIQUETAS_ROL = {
  super_admin: 'Superadministrador',
  dueno_empresa: 'Dueño de la empresa',
  usuario: 'Usuario',
  admin_negocio: 'Dueño de la empresa',
  consultor: 'Usuario',
  lector: 'Usuario',
}

/** ¿Puede este rol gestionar cuentas de su empresa? */
export function esAdministrativo(rol) {
  return rol === 'super_admin' || rol === 'dueno_empresa' || rol === 'admin_negocio'
}

/** ¿Este rol es el superadministrador? */
export function esDePlataforma(rol) {
  return rol === 'super_admin'
}

/** ¿Puede este rol editar el perfil con el que se rellenan los TDR? */
export function puedeEditarPerfil(rol) {
  return esAdministrativo(rol)
}

/**
 * ¿Puede este rol descargar el histórico?
 *
 * El usuario regular exporta. La comprobación de verdad está en el servidor.
 */
export function puedeExportar(rol) {
  return (
    rol === 'super_admin' ||
    rol === 'dueno_empresa' ||
    rol === 'usuario' ||
    rol === 'admin_negocio' ||
    rol === 'consultor' ||
    rol === 'lector'
  )
}

/** ¿Puede armar el borrador de oferta? El usuario regular ve el TDR y no lo rellena. */
export function puedeRellenarTdr(rol) {
  return esAdministrativo(rol)
}
