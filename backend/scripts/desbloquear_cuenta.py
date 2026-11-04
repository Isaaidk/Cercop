"""Quita el bloqueo por intentos fallidos de una cuenta.

Existe para el caso en que no queda nadie que pueda hacerlo desde el panel: el único administrador
de una empresa, o el superadministrador, bloqueados a la vez. El bloqueo caduca solo a los quince
minutos, pero quien está delante de la pantalla no siempre puede esperar ni sabe que caduca.

Cómo usarlo
-----------
    python scripts/desbloquear_cuenta.py --email correo@dominio.ec

No cambia la contraseña. Si además la persona la olvidó, usa `crear_super_admin.py --restablecer`
para el superadministrador, o el botón «Contraseña» del panel para cualquier otra cuenta.

Igual que `crear_super_admin.py`, no lleva SQL: todo pasa por los adaptadores de la aplicación.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contratacion.infraestructura.adaptadores.salida.bd.cuentas import RepositorioCuentasBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.bd.usuarios import RepositorioUsuariosBd


def _argumentos() -> argparse.Namespace:
    analizador = argparse.ArgumentParser(description="Desbloquea una cuenta por su correo.")
    analizador.add_argument("--email", required=True, help="Correo de la cuenta bloqueada.")
    return analizador.parse_args()


async def _desbloquear(correo: str) -> int:
    motor = obtener_motor()
    try:
        cuentas = RepositorioCuentasBd(motor)
        encontrada = await cuentas.resolver(correo)
        if encontrada is None:
            print(f"No hay ninguna cuenta con el correo {correo!r}.", file=sys.stderr)
            return 1
        usuario_id, negocio_id = encontrada
        await RepositorioUsuariosBd(motor).desbloquear(negocio_id=negocio_id, usuario_id=usuario_id)
        await cuentas.auditar(
            accion="desbloqueo_usuario",
            negocio_id=negocio_id,
            entidad="usuario",
            entidad_id=str(usuario_id),
            resultado="ok",
            detalle={"origen": "script"},
        )
        print(f"Cuenta {correo} desbloqueada. Ya puede volver a intentar entrar.")
        return 0
    finally:
        await motor.dispose()


def main() -> int:
    """Punto de entrada. Devuelve el código de salida del proceso."""
    args = _argumentos()
    try:
        return asyncio.run(_desbloquear(args.email.strip().lower()))
    except OSError as error:
        print(f"No hay conexión con la base de datos: {error}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
