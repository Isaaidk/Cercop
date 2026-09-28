"""Crea el superadministrador de la plataforma.

Por qué es un script y no una migración
---------------------------------------
Una migración se ejecuta en cada despliegue y en cada entorno, y lleva credenciales dentro.
Poner una contraseña en una migración es ponerla en el control de versiones, en el registro de
cada despliegue y en la cabeza de cualquiera que lea el repositorio. Y después de la primera
vez, la migración ya no hace nada: cambiar la contraseña exigiría otra migración.

Un script se ejecuta cuando alguien lo decide, con la contraseña que esa persona escribe, y no deja
rastro en el repositorio.

Cómo usarlo
-----------
    python scripts/crear_super_admin.py --email correo@dominio.ec

Pide la contraseña por teclado y no la muestra. Se puede pasar con `--contrasena`, y entonces sí
aparece en el historial de la consola y en la lista de procesos: se admite para automatizar, con el
aviso por delante.

Si la cuenta ya existe, no se toca nada y se explica qué opciones hay. Con `--restablecer` se le
cambia la contraseña y se cierran sus sesiones, que es la operación que hace falta cuando alguien
la ha olvidado —y que no debería obligar a entrar por la puerta de atrás de la base de datos—.

No hay SQL en este archivo
--------------------------
Todo pasa por los mismos adaptadores que usa la aplicación: los repositorios de negocios, de
cuentas, de usuarios y de sesiones. Escribir aquí unas cuantas sentencias a mano sería más corto
y traería dos problemas: no se probarían con el resto del sistema, y el día que cambiara el
esquema el script seguiría compilando mientras falla al ejecutarse.

Sobre el negocio «Plataforma»
-----------------------------
El superadministrador es un usuario como los demás y la tabla `usuario` exige un negocio: no
existe un usuario sin empresa. Se crea uno propio para la plataforma, y eso tiene una
consecuencia que conviene entender: las vistas del negocio de la plataforma son las que ve el
superadministrador, y no hereda las de los negocios que administra. Para mirar los datos de un
cliente hay que concederle vistas, o crear una cuenta de administrador dentro del negocio del
cliente. No es una limitación de este script: es cómo está modelado el acceso.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

# El paquete vive en `src/`, que no está instalado en todos los entornos donde se ejecuta esto.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.puertos.negocios import AltaEmpresa
from contratacion.aplicacion.puertos.usuarios import FichaUsuario
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.credenciales import (
    LONGITUD_MINIMA,
    validar_contrasena,
)
from contratacion.dominio.errores import DatoInvalido, ErrorDominio
from contratacion.dominio.negocios import construir_datos_empresa
from contratacion.dominio.roles import ETIQUETAS_ROL, Rol
from contratacion.dominio.sesiones import MotivoRevocacion
from contratacion.infraestructura.adaptadores.salida.bd.cuentas import (
    RepositorioCuentasBd,
    RepositorioSesionesBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.negocios import (
    RepositorioNegociosBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.bd.usuarios import (
    RepositorioUsuariosBd,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import (
    obtener_contrasenas,
)

NOMBRE_NEGOCIO_PLATAFORMA = "Plataforma"
ESTADO_ACTIVO = "activo"


def _argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(
        description="Crea el superadministrador de la plataforma, con la contraseña hasheada.",
    )
    analizador.add_argument("--email", required=True, help="Correo con el que entrará.")
    analizador.add_argument(
        "--contrasena",
        default=None,
        help=(
            "Contraseña. Si se omite —lo recomendable— se pide por teclado sin mostrarla. "
            f"Mínimo {LONGITUD_MINIMA} caracteres."
        ),
    )
    analizador.add_argument("--nombre", default="Superadministrador", help="Nombre de la persona.")
    analizador.add_argument(
        "--negocio",
        default=NOMBRE_NEGOCIO_PLATAFORMA,
        help="Nombre del negocio de la plataforma al que pertenece la cuenta.",
    )
    analizador.add_argument(
        "--sin-vistas",
        action="store_true",
        help=(
            "No conceder la prueba de vistas al negocio de la plataforma. Por defecto sí se "
            "concede, para que al entrar haya datos que ver."
        ),
    )
    analizador.add_argument(
        "--restablecer",
        action="store_true",
        help=(
            "Si la cuenta ya existe, cambiarle la contraseña en lugar de no hacer nada. También "
            "cierra todas sus sesiones."
        ),
    )
    return analizador.parse_args()


def _pedir_contrasena(argumento: str | None) -> str:
    """Contraseña para el superadministrador, con la misma política que la del resto.

        Se exige la misma política **a propósito**. Un superadministrador con una contraseña más
    débil que la de cualquier usuario sería la puerta de atrás del sistema, y la puerta de atrás es
    lo primero que se busca cuando se quiere entrar sin permiso.
    """
    if argumento:
        contrasena = argumento
    else:
        primera = getpass.getpass(f"Contraseña (mínimo {LONGITUD_MINIMA} caracteres): ")
        repetida = getpass.getpass("Repite la contraseña: ")
        if primera != repetida:
            raise DatoInvalido("Las dos contraseñas no coinciden.")
        contrasena = primera

    validar_contrasena(contrasena)
    return contrasena


async def _crear(args: argparse.Namespace, contrasena: str) -> int:
    """Crea la cuenta, o restablece la contraseña si el correo ya está tomado."""
    motor = obtener_motor()
    try:
        correo = args.email.strip().lower()

        # `resolver` es la única lectura sin contexto de negocio, y devuelve solo dos
        # identificadores. Es justo lo que hace falta aquí para saber si el correo está tomado:
        # una consulta directa a `usuario` no vería nada —las políticas filtran por negocio— y
        # el script creería que el correo está libre.
        encontrada = await RepositorioCuentasBd(motor).resolver(correo)
        if encontrada is not None:
            usuario_id, negocio_id = encontrada
            return await _resolver_existente(args, contrasena, motor, usuario_id, negocio_id)

        contrasenas = obtener_contrasenas()
        negocio_id = uuid4()
        admin_id = uuid4()
        sin_vistas = bool(args.sin_vistas)

        await RepositorioNegociosBd(motor).crear(
            AltaEmpresa(
                negocio_id=negocio_id,
                datos=construir_datos_empresa(nombre=args.negocio, email_contacto=correo),
                admin_id=admin_id,
                admin_email=correo,
                admin_nombre=args.nombre,
                admin_rol=Rol.SUPER_ADMIN,
                huella=contrasenas.hash(contrasena),
                vistas_prueba=() if sin_vistas else tuple(Vista),
                plazo_prueba=Plazo.A1,
                momento=datetime.now(UTC),
            )
        )

        print("Superadministrador creado.")
        print(f"  Correo  : {correo}")
        print(f"  Negocio : {args.negocio}  ({negocio_id})")
        print(f"  Rol     : {ETIQUETAS_ROL[Rol.SUPER_ADMIN]}")
        print(f"  Vistas  : {'ninguna' if sin_vistas else ', '.join(str(v) for v in Vista)}")
        if not sin_vistas:
            print("  Prueba  : 1 año, ampliable desde el panel de accesos")
        print()
        print("La contraseña se guardó como huella Argon2id: no se puede recuperar, solo cambiar.")
        print("Cámbiala desde el panel en cuanto entres.")
        return 0
    finally:
        await motor.dispose()


async def _resolver_existente(
    args: argparse.Namespace,
    contrasena: str,
    motor: AsyncEngine,
    usuario_id: UUID,
    negocio_id: UUID,
) -> int:
    """Qué hacer cuando el correo ya tiene cuenta. Nunca cambiar nada en silencio."""
    usuarios = RepositorioUsuariosBd(motor)
    ficha = await usuarios.obtener(negocio_id=negocio_id, usuario_id=usuario_id)

    if ficha is None:
        print(
            f"El correo {args.email!r} está registrado, pero su cuenta no se puede leer. "
            "Comprueba la conexión con la base de datos.",
            file=sys.stderr,
        )
        return 3

    if not args.restablecer:
        print(
            f"Ya existe una cuenta con el correo {args.email!r}. No se ha tocado nada.\n"
            f"  Rol actual    : {ETIQUETAS_ROL.get(ficha.rol, ficha.rol)}\n"
            f"  Estado actual : {ficha.estado}\n"
            "\n"
            "Si lo que quieres es restablecer su contraseña, vuelve a ejecutar con --restablecer."
        )
        return 1

    await _restablecer(contrasena, motor, ficha)
    return 0


async def _restablecer(contrasena: str, motor: AsyncEngine, ficha: FichaUsuario) -> None:
    """Cambia la contraseña, deja el rol de superadministrador y cierra las sesiones."""
    usuarios = RepositorioUsuariosBd(motor)
    contrasenas = obtener_contrasenas()
    instante = datetime.now(UTC)

    await usuarios.actualizar_identidad(
        negocio_id=ficha.negocio_id,
        usuario_id=ficha.usuario_id,
        nombre=ficha.nombre,
        rol=Rol.SUPER_ADMIN,
        huella=contrasenas.hash(contrasena),
    )
    await usuarios.cambiar_estado(
        negocio_id=ficha.negocio_id,
        usuario_id=ficha.usuario_id,
        estado=ESTADO_ACTIVO,
        momento=instante,
    )
    # Se cierran todas las sesiones: si hay que restablecer la contraseña es porque algo pasó con la
    # anterior, y dejar viva la sesión que quizá la tenía en la mano anularía el cambio.
    cerradas = await RepositorioSesionesBd(motor).revocar_todas(
        negocio_id=ficha.negocio_id,
        usuario_id=ficha.usuario_id,
        motivo=MotivoRevocacion.ADMIN,
        momento=instante,
    )

    print("Contraseña restablecida.")
    print(f"  Correo            : {ficha.email}")
    print(f"  Rol               : {ETIQUETAS_ROL[Rol.SUPER_ADMIN]}")
    print(f"  Estado            : {ESTADO_ACTIVO}")
    print(f"  Sesiones cerradas : {cerradas}")


def main() -> int:
    """Punto de entrada. Devuelve el código de salida del proceso."""
    args = _argumentos()

    try:
        contrasena = _pedir_contrasena(args.contrasena)
    except DatoInvalido as error:
        print(f"La contraseña no cumple la política: {error}", file=sys.stderr)
        return 2

    try:
        return asyncio.run(_crear(args, contrasena))
    except ErrorDominio as error:
        print(f"No se pudo completar: {error}", file=sys.stderr)
        return 3
    except OSError as error:
        print(f"No hay conexión con la base de datos: {error}", file=sys.stderr)
        return 4
    except Exception as error:  # noqa: BLE001 - el script explica el fallo, no muere con traza
        print(f"Error inesperado: {type(error).__name__}: {error}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
