"""Roles de usuario: qué puede hacer cada uno.

Hay tres roles y no más. El catálogo anterior tenía cuatro (`admin_negocio`, `consultor`, `lector`
además del superadministrador). Esos tres códigos siguen aceptándose al leer un token viejo, pero
se traducen al rol nuevo: no son capacidades distintas.

- `super_admin` administra la plataforma y puede actuar sobre cualquier empresa.
- `dueno_empresa` administra una sola empresa: sus usuarios, su clave y su perfil.
- `usuario` pertenece siempre a una empresa. Consulta, filtra, exporta y ve el TDR. No administra.

Los permisos viven en esta matriz y se siembran igual en `rol_permiso` (migración 0026). Autorizar
lee la matriz: si la caché estuviera vacía, un superadministrador no puede
quedarse sin poder entrar.
"""

from __future__ import annotations

from enum import StrEnum

from contratacion.dominio.errores import DatoInvalido


class Rol(StrEnum):
    """Los tres roles, con el mismo código que guarda la base de datos."""

    SUPER_ADMIN = "super_admin"
    DUENO_EMPRESA = "dueno_empresa"
    USUARIO = "usuario"


# Códigos que ya no se crean. Un token emitido antes de la migración 0026 todavía los trae.
_ALIAS: dict[str, Rol] = {
    "admin_negocio": Rol.DUENO_EMPRESA,
    "consultor": Rol.USUARIO,
    "lector": Rol.USUARIO,
}


ETIQUETAS_ROL: dict[Rol, str] = {
    Rol.SUPER_ADMIN: "Superadministrador",
    Rol.DUENO_EMPRESA: "Dueño de la empresa",
    Rol.USUARIO: "Usuario",
}

DESCRIPCION_ROL: dict[Rol, str] = {
    Rol.SUPER_ADMIN: (
        "Administra la plataforma: puede actuar sobre cualquier empresa. Se crea desde la línea de "
        "órdenes, no desde el panel."
    ),
    Rol.DUENO_EMPRESA: (
        "Administra su propia empresa: crea y elimina usuarios, les asigna la contraseña y edita "
        "el perfil con el que se rellenan los TDR. No concede plazos."
    ),
    Rol.USUARIO: (
        "Consulta las contrataciones de su empresa, filtra, exporta y ve el TDR. No gestiona "
        "cuentas ni el perfil."
    ),
}

ROLES_ADMINISTRATIVOS: frozenset[Rol] = frozenset({Rol.SUPER_ADMIN, Rol.DUENO_EMPRESA})

ROLES_EXPORTADORES: frozenset[Rol] = frozenset({Rol.SUPER_ADMIN, Rol.DUENO_EMPRESA, Rol.USUARIO})

# Lo que un dueño puede asignar al crear una cuenta. No incluye al dueño ni al superadministrador:
# si lo hiciera, cualquiera con el formulario podría salirse de su empresa.
ROLES_ASIGNABLES_POR_ADMIN: tuple[Rol, ...] = (Rol.USUARIO,)

ORDEN_ROLES: tuple[Rol, ...] = (Rol.USUARIO,)

# Matriz que siembra la migración 0026. Un permiso que no esté aquí no lo tiene nadie.
PERMISOS: dict[str, str] = {
    "empresas.gestionar": "Crear y administrar empresas de la plataforma.",
    "plazos.conceder": "Conceder o ampliar el plazo de uso.",
    "usuarios.gestionar": "Crear, editar y dar de baja usuarios de la propia empresa.",
    "usuarios.desbloquear": "Quitar el bloqueo por intentos fallidos.",
    "exportar": "Descargar el histórico.",
    "tdr.ver": "Ver el TDR de una ínfima.",
    "tdr.rellenar": "Armar el borrador de oferta con el perfil de la empresa.",
    "empresa.editar_perfil": "Editar el perfil con el que se rellenan los TDR.",
    "vistas.necesidades": "Consultar las vistas de datos concedidas.",
}

PERMISOS_POR_ROL: dict[Rol, frozenset[str]] = {
    Rol.SUPER_ADMIN: frozenset(PERMISOS),
    Rol.DUENO_EMPRESA: frozenset(
        {
            "usuarios.gestionar",
            "usuarios.desbloquear",
            "exportar",
            "tdr.ver",
            "tdr.rellenar",
            "empresa.editar_perfil",
            "vistas.necesidades",
        }
    ),
    Rol.USUARIO: frozenset({"exportar", "tdr.ver", "vistas.necesidades"}),
}


def normalizar_rol(rol: str | Rol | None) -> Rol:
    """Traduce un código, incluido uno viejo, al rol actual."""
    texto = str(rol or "").strip().lower()
    if texto in _ALIAS:
        return _ALIAS[texto]
    try:
        return Rol(texto)
    except ValueError as exc:
        permitidos = ", ".join(miembro.value for miembro in Rol)
        raise DatoInvalido(f"Rol no reconocido: {rol!r}. Se espera uno de: {permitidos}.") from exc


def rol_desde_codigo(codigo: str | None) -> Rol:
    """Traduce el código que envía el panel. Un valor fuera del catálogo se rechaza.

    Los códigos viejos no se aceptan al **asignar** un rol: crear una cuenta como `consultor`
    volvería a meter en la base un valor que la migración ya retiró. Para leer un token viejo está
    `normalizar_rol`.
    """
    try:
        return Rol(str(codigo or "").strip().lower())
    except ValueError as exc:
        permitidos = ", ".join(miembro.value for miembro in Rol)
        raise DatoInvalido(
            f"Rol no reconocido: {codigo!r}. Se espera uno de: {permitidos}."
        ) from exc


def es_administrativo(rol: str | Rol) -> bool:
    """¿Este rol puede gestionar cuentas de su empresa?"""
    try:
        return normalizar_rol(rol) in ROLES_ADMINISTRATIVOS
    except DatoInvalido:
        return False


def es_de_plataforma(rol: str | Rol) -> bool:
    """¿Este rol es el superadministrador?"""
    try:
        return normalizar_rol(rol) is Rol.SUPER_ADMIN
    except DatoInvalido:
        return False


def puede_asignar(rol_solicitado: Rol) -> bool:
    """¿Un dueño de empresa puede crear una cuenta con este rol?"""
    return rol_solicitado in ROLES_ASIGNABLES_POR_ADMIN


def puede_exportar(rol: str | Rol) -> bool:
    """¿Este rol puede descargar el histórico?"""
    try:
        return normalizar_rol(rol) in ROLES_EXPORTADORES
    except DatoInvalido:
        return False


def tiene_permiso(rol: str | Rol, permiso: str) -> bool:
    """¿Este rol tiene este permiso, según la matriz sembrada?"""
    try:
        return permiso in PERMISOS_POR_ROL[normalizar_rol(rol)]
    except DatoInvalido:
        return False


def etiqueta(rol: str | Rol) -> str:
    """Nombre del rol para mostrar. Un valor desconocido se muestra tal cual."""
    try:
        return ETIQUETAS_ROL[normalizar_rol(rol)]
    except DatoInvalido:
        return str(rol)


def catalogo_para_panel() -> list[dict[str, str]]:
    """Los roles que un dueño puede asignar, para el desplegable del panel."""
    return [
        {
            "codigo": rol.value,
            "etiqueta": ETIQUETAS_ROL[rol],
            "descripcion": DESCRIPCION_ROL[rol],
        }
        for rol in ORDEN_ROLES
    ]
