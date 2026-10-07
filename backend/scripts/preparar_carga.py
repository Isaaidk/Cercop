"""Crea (o borra) las cuentas que usa la prueba de carga.

    # 1.000 usuarios, cada uno con su negocio, con todas las vistas y los términos aceptados
    python scripts\\preparar_carga.py

    # Las cifras que se quieran
    python scripts\\preparar_carga.py --usuarios 200

    # Y para dejarlo como estaba
    python scripts\\preparar_carga.py --borrar

Escribe `carga/credenciales.json` con el correo, la contraseña y **los dos tokens** de cada cuenta.
El archivo lleva credenciales de verdad: es de usar y borrar, y va al `.gitignore`.

Por qué las cuentas se crean aquí y no dentro de k6
--------------------------------------------------
Dos razones que se notan en la medida:

1. **El inicio de sesión cuesta trabajo a propósito.** Cada contraseña se verifica con Argon2, que
   está hecho para ser lento. Si k6 iniciara sesión dentro de la prueba, el primer minuto mediría el
   coste de Argon2 —una sola vez por usuario, en el peor momento— y no lo que aguanta el panel. Aquí
   los inicios de sesión se hacen **en paralelo** y antes de empezar a medir.
2. **Las cuentas no pueden tener tope.** El panel solo deja dos sesiones por cuenta: mil usuarios
   concurrentes con una sola cuenta se expulsarían entre ellos y la prueba mediría la evicción. Cada
   usuario de esta prueba tiene **su propia cuenta y su propio negocio**, así que el aislamiento por
   RLS se somete al mismo ritmo que las lecturas, que es como estará en producción.

Los tokens caducan (el de acceso, en minutos), así que la prueba **renueva** como lo hace el panel
cuando recibe un 401. Los de renovación duran días y son los que hacen que la prueba sobreviva a una
sesión larga.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, "src")

import httpx
from sqlalchemy import text

from contratacion.aplicacion.puertos.negocios import AltaEmpresa
from contratacion.dominio.acceso import Plazo, Vista
from contratacion.dominio.negocios import construir_datos_empresa
from contratacion.dominio.roles import Rol
from contratacion.infraestructura.adaptadores.salida.bd.negocios import (
    RepositorioNegociosBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import obtener_motor
from contratacion.infraestructura.adaptadores.salida.seguridad.fabrica import (
    obtener_contrasenas,
)

API = "http://127.0.0.1:8001"
# La ruta se calcula desde la **ubicación de este archivo** y no desde el directorio de trabajo: k6
# resuelve `open('./credenciales.json')` respecto a su propio guion, así que el archivo tiene que
# estar siempre en `carga/` aunque el guion se ejecute desde `backend/`.
RUTA_CREDENCIALES = Path(__file__).resolve().parents[2] / "carga" / "credenciales.json"
# Prefijo del nombre de la empresa. Es lo que permite reconocerlas y borrarlas después sin guardar
# una lista aparte: una lista se pierde, y con ella la forma de deshacer.
PREFIJO = "Carga"
# Cuántos inicios de sesión a la vez. Argon2 es lento a propósito y el API tiene un proceso, así que
# paralelizar sin tope solo cambiaría de sitio la cola.
LOGINS_EN_PARALELO = 16


async def _crear(cantidad: int, api: str, salida: Path) -> int:
    motor = obtener_motor()
    repositorio = RepositorioNegociosBd(motor)
    contrasenas = obtener_contrasenas()
    momento = datetime.now(UTC)
    # Una sola contraseña para todas las cuentas de la prueba, generada aquí y escrita solo en el
    # archivo de credenciales. No hay ninguna escrita en el repositorio.
    contrasena = f"Carga-{secrets.token_urlsafe(12)}"
    huella = contrasenas.hash(contrasena)

    cuentas: list[dict[str, str]] = []
    for indice in range(cantidad):
        negocio_id = uuid4()
        correo = f"carga-{indice:05d}-{uuid4().hex[:6]}@{PREFIJO.lower()}.ec"
        await repositorio.crear(
            AltaEmpresa(
                negocio_id=negocio_id,
                datos=construir_datos_empresa(
                    nombre=f"{_cifra_por_indice(indice)} {negocio_id.hex[:6]}"
                ),
                admin_id=uuid4(),
                admin_email=correo,
                admin_nombre=f"Carga {indice:05d}",
                admin_rol=Rol.SUPER_ADMIN,
                huella=huella,
                vistas_prueba=tuple(Vista),
                plazo_prueba=Plazo.A1,
                momento=momento,
            )
        )
        cuentas.append({"email": correo, "negocio_id": str(negocio_id)})

    # Los términos, aceptados y los tokens, obtenidos. Van en paralelo por tandas: en serie, mil
    # inicios de sesión con Argon2 son varios minutos de espera antes de empezar.
    limite = asyncio.Semaphore(LOGINS_EN_PARALELO)
    async with httpx.AsyncClient(base_url=api, timeout=90) as cliente:

        async def preparar(cuenta: dict[str, str]) -> None:
            async with limite:
                sesion = await cliente.post(
                    "/v1/auth/sesion",
                    json={"email": cuenta["email"], "contrasena": contrasena},
                )
                sesion.raise_for_status()
                cuerpo = sesion.json()
                cabeceras = {"Authorization": f"Bearer {cuerpo['token_acceso']}"}
                pendientes = (await cliente.get("/v1/politicas", headers=cabeceras)).json()[
                    "politicas"
                ]
                for politica in pendientes:
                    await cliente.post(
                        f"/v1/politicas/{politica['tipo']}/aceptacion",
                        json={"version": politica["version"], "hash": politica["hash"]},
                        headers=cabeceras,
                    )
                cuenta["token_acceso"] = cuerpo["token_acceso"]
                cuenta["token_renovacion"] = cuerpo["token_renovacion"]
                cuenta["acceso_expira_en"] = cuerpo["acceso_expira_en"]

        await asyncio.gather(*(preparar(cuenta) for cuenta in cuentas))

    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps({"api": api, "contrasena": contrasena, "cuentas": cuentas}, indent=2),
        encoding="utf-8",
    )
    print(f"usuarios creados: {len(cuentas)}")
    print(f"credenciales: {salida} (contiene credenciales de verdad: no subir al repositorio)")
    return 0


def _cifra_por_indice(indice: int) -> str:
    return f"{PREFIJO} {indice:05d}"


async def _borrar() -> int:
    """Retira las empresas de la prueba. La clave ajena se lleva cuentas, sesiones y concesiones."""
    motor = obtener_motor()
    async with motor.begin() as conexion:
        resultado = await conexion.execute(
            text("DELETE FROM negocio WHERE nombre LIKE :prefijo"), {"prefijo": f"{PREFIJO} %"}
        )
    print(f"empresas borradas: {resultado.rowcount}")
    return 0


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cuentas para la prueba de carga.")
    parser.add_argument("--usuarios", type=int, default=1000, help="Cuántas cuentas crear.")
    parser.add_argument("--api", default=API, help=f"Dónde responde el API (por defecto {API}).")
    parser.add_argument("--salida", type=Path, default=RUTA_CREDENCIALES)
    parser.add_argument("--borrar", action="store_true", help="Borra las cuentas de carga y sale.")
    argumentos = parser.parse_args(argv)

    if argumentos.borrar:
        return await _borrar()
    if argumentos.usuarios < 1:
        parser.error("--usuarios tiene que ser al menos 1")
    return await _crear(argumentos.usuarios, argumentos.api, argumentos.salida)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
