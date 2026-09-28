"""Roles de usuario: qué puede hacer cada uno.

Existe para que la lista de roles viva en **un solo sitio**. Antes estaban escritos a mano en
`dominio/acceso.py` (para decidir quién gestiona accesos) y, por separado, en la restricción
`CHECK` de la tabla `usuario`. Dos listas del mismo catálogo acaban separándose: se añade un rol
en la base y la comprobación de permisos sigue sin conocerlo, o al revés.

El catálogo es **cerrado y ordenado**: no hay roles libres. Cada miembro representa una frontera de
autorización, así que añadir uno es un cambio de código y de migración, revisable, y no una fila
insertada en una tabla de configuración.

Sobre la jerarquía
------------------
No se modela como una escala numérica («nivel 3 &gt; nivel 2»). Se modela como **capacidades
concretas**, porque las jerarquías numéricas esconden la pregunta que importa: no es «¿tiene más
nivel?», es «¿puede crear cuentas?», «¿puede concederse vistas a sí mismo?». Con capacidades
explícitas, revisar quién puede hacer qué es leer una tabla.
"""

from __future__ import annotations

from enum import StrEnum

from contratacion.dominio.errores import DatoInvalido


class Rol(StrEnum):
    """Los cuatro roles que existen, con el mismo código que guarda la base de datos."""

    SUPER_ADMIN = "super_admin"
    ADMIN_NEGOCIO = "admin_negocio"
    CONSULTOR = "consultor"
    LECTOR = "lector"


ETIQUETAS_ROL: dict[Rol, str] = {
    Rol.SUPER_ADMIN: "Superadministrador",
    Rol.ADMIN_NEGOCIO: "Administrador de la empresa",
    Rol.CONSULTOR: "Consultor",
    Rol.LECTOR: "Solo lectura",
}

DESCRIPCION_ROL: dict[Rol, str] = {
    Rol.SUPER_ADMIN: (
        "Administra la plataforma: puede actuar sobre cualquier empresa. Se crea desde la línea de "
        "órdenes, no desde el panel."
    ),
    Rol.ADMIN_NEGOCIO: (
        "Administra su propia empresa: crea y elimina usuarios, les asigna la contraseña y concede "
        "o retira el acceso a las vistas."
    ),
    Rol.CONSULTOR: (
        "Consulta las contrataciones y gestiona sus propias palabras clave. No puede tocar cuentas "
        "ni permisos."
    ),
    Rol.LECTOR: ("Solo consulta. No puede agregar palabras clave, ni exportar, ni gestionar nada."),
}

# Roles que pueden gestionar cuentas y permisos.
ROLES_ADMINISTRATIVOS: frozenset[Rol] = frozenset({Rol.SUPER_ADMIN, Rol.ADMIN_NEGOCIO})

# Roles que pueden sacar el histórico en un archivo.
#
# Es una capacidad **aparte de ver la tabla**, y no un efecto colateral, porque el resultado es
# distinto: exportar produce un archivo que sale de la plataforma y deja de estar bajo nuestro
# control, con datos de terceros dentro —razón social, nombre del responsable, correo y teléfono de
# contacto de una entidad pública—. `lector` ve esas mismas filas en pantalla y no las descarga, que
# es exactamente lo que dice su descripción.
ROLES_EXPORTADORES: frozenset[Rol] = frozenset({Rol.SUPER_ADMIN, Rol.ADMIN_NEGOCIO, Rol.CONSULTOR})

# Roles que un administrador de empresa puede asignar al crear una cuenta.
#
# `super_admin` **no** está en la lista y no es un olvido: si estuviera, cualquiera con permiso para
# crear usuarios podría fabricarse una cuenta de superadministrador y salir de su empresa. La
# escalada de privilegios sería de un solo formulario.
ROLES_ASIGNABLES_POR_ADMIN: tuple[Rol, ...] = (
    Rol.ADMIN_NEGOCIO,
    Rol.CONSULTOR,
    Rol.LECTOR,
)

# Los roles que ve el panel al crear una cuenta, en el orden en que se muestran.
ORDEN_ROLES: tuple[Rol, ...] = (
    Rol.ADMIN_NEGOCIO,
    Rol.CONSULTOR,
    Rol.LECTOR,
)


def rol_desde_codigo(codigo: str | None) -> Rol:
    """Traduce el código que envía el panel. Un valor fuera del catálogo se rechaza.

    Se rechaza en lugar de caer a un valor por defecto porque un rol no reconocido interpretado como
    «el más bajo» deja a alguien sin permisos que cree tener, y como «el más alto» es una escalada.
    Ninguno de los dos errores se nota hasta que es tarde.
    """
    try:
        return Rol(str(codigo or "").strip().lower())
    except ValueError as exc:
        permitidos = ", ".join(rol.value for rol in Rol)
        raise DatoInvalido(
            f"Rol no reconocido: {codigo!r}. Se espera uno de: {permitidos}."
        ) from exc


def es_administrativo(rol: str | Rol) -> bool:
    """¿Este rol puede gestionar cuentas y permisos?"""
    try:
        return Rol(str(rol).strip().lower()) in ROLES_ADMINISTRATIVOS
    except ValueError:
        # Un rol desconocido no es administrativo. Es la respuesta prudente: la alternativa sería
        # que un valor raro en la base concediera permisos.
        return False


def puede_asignar(rol_solicitado: Rol) -> bool:
    """¿Un administrador de empresa puede crear una cuenta con este rol?"""
    return rol_solicitado in ROLES_ASIGNABLES_POR_ADMIN


def puede_exportar(rol: str | Rol) -> bool:
    """¿Este rol puede descargar el histórico?

    Un rol desconocido no exporta, por la misma razón que no administra: si un valor raro en la base
    se interpretara como permiso, el fallo estaría del lado peligroso.
    """
    try:
        return Rol(str(rol).strip().lower()) in ROLES_EXPORTADORES
    except ValueError:
        return False


def etiqueta(rol: str | Rol) -> str:
    """Nombre del rol para mostrar. Un valor desconocido se muestra tal cual, sin inventar nada."""
    try:
        return ETIQUETAS_ROL[Rol(str(rol).strip().lower())]
    except ValueError:
        return str(rol)


def catalogo_para_panel() -> list[dict[str, str]]:
    """Los roles asignables con su descripción, para que el panel pinte el desplegable.

    Se sirve desde el código del dominio y no desde una tabla: un rol es una frontera de
    autorización, y añadir uno debe ser un cambio revisable.
    """
    return [
        {
            "codigo": rol.value,
            "etiqueta": ETIQUETAS_ROL[rol],
            "descripcion": DESCRIPCION_ROL[rol],
        }
        for rol in ORDEN_ROLES
    ]
