"""Diagnóstico del esquema: qué objetos existen y si el aislamiento está activo.

Sirve para responder en un despliegue a dos preguntas que no se pueden contestar mirando el código:
«¿se aplicaron todas las migraciones?» y «¿está RLS realmente activo y forzado en todas las tablas
de negocio?».

La segunda es la importante. Una tabla con `ENABLE ROW LEVEL SECURITY` pero sin `FORCE` parece
protegida y **no lo está** para el propietario de la tabla, que es justo el rol con el que se
conectan muchos despliegues. Comprobarlo aquí evita descubrirlo con datos de un cliente a la vista
de otro.

No modifica nada: solo lee. No imprime credenciales.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from contratacion.infraestructura.adaptadores.salida.bd.sesion import (
    cerrar_bd,
    normalizar_url_bd,
    obtener_motor,
)
from contratacion.infraestructura.config.ajustes import obtener_ajustes

TABLAS_ESPERADAS = (
    "fuente",
    "campo_mapeo",
    "campo_pendiente",
    "termino",
    "registro",
    "sincronizacion",
    "negocio",
    "usuario",
    "sesion",
    "suscripcion_termino",
    "acceso_vista",
    "consentimiento",
    "auditoria",
)

# Tablas del plano de negocio: deben tener RLS activo **y forzado**.
TABLAS_CON_AISLAMIENTO = (
    "negocio",
    "usuario",
    "sesion",
    "suscripcion_termino",
    "conjunto_terminos",
    "conjunto_termino",
    "filtro_guardado",
    "exportacion",
    "consentimiento",
    "solicitud_arco",
    "auditoria",
    "acceso_vista",
)


async def _revision() -> str:
    motor = obtener_motor()
    async with motor.connect() as conexion:
        valor = (
            await conexion.execute(text("SELECT version_num FROM alembic_version"))
        ).scalar_one_or_none()
    return str(valor) if valor else "(sin versión registrada)"


async def _tablas_faltantes() -> list[str]:
    motor = obtener_motor()
    async with motor.connect() as conexion:
        presentes = {
            str(fila[0])
            for fila in (
                await conexion.execute(
                    text(
                        "SELECT tablename FROM pg_tables "
                        "WHERE schemaname = 'public' AND tablename = ANY(:nombres)"
                    ),
                    {"nombres": list(TABLAS_ESPERADAS)},
                )
            ).all()
        }
    return [tabla for tabla in TABLAS_ESPERADAS if tabla not in presentes]


async def _sin_aislamiento() -> list[tuple[str, bool, bool, bool]]:
    """Tablas de negocio cuya configuración de RLS no está completa."""
    motor = obtener_motor()
    async with motor.connect() as conexion:
        filas = (
            await conexion.execute(
                text(
                    """
                    SELECT c.relname,
                           c.relrowsecurity,
                           c.relforcerowsecurity,
                           EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind = 'r'
                      AND c.relname = ANY(:nombres)
                    ORDER BY c.relname
                    """
                ),
                {"nombres": list(TABLAS_CON_AISLAMIENTO)},
            )
        ).all()

    problemas: list[tuple[str, bool, bool, bool]] = []
    for fila in filas:
        activo, forzado, politica = (bool(valor) for valor in fila[1:])
        if not (activo and forzado and politica):
            problemas.append((str(fila[0]), activo, forzado, politica))
    return problemas


async def _rol_actual() -> tuple[str, bool, bool]:
    """Nombre del rol de la conexión y si es superusuario o puede saltarse RLS.

    Ambos atributos anulan el aislamiento por completo: un superusuario ignora las políticas. Si
    esta línea sale en `True`, todo lo demás del informe da igual.
    """
    motor = obtener_motor()
    async with motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    """
                    SELECT current_user::text, rolsuper, rolbypassrls
                    FROM pg_roles WHERE rolname = current_user
                    """
                )
            )
        ).one()
    return str(fila[0]), bool(fila[1]), bool(fila[2])


async def main() -> int:
    ajustes = obtener_ajustes()
    destino = normalizar_url_bd(ajustes.database_url)
    print(f"Destino: {destino.host}/{destino.database}")

    rol, superusuario, bypass = await _rol_actual()
    print(f"Rol     : {rol}")

    revision = await _revision()
    print(f"Revisión: {revision}")

    fallos = 0

    faltantes = await _tablas_faltantes()
    if faltantes:
        print(f"  FALTAN TABLAS: {', '.join(faltantes)}")
        fallos += 1
    else:
        print(f"Tablas  : las {len(TABLAS_ESPERADAS)} esperadas existen")

    problemas = await _sin_aislamiento()
    if problemas:
        print("  AISLAMIENTO INCOMPLETO:")
        for tabla, activo, forzado, politica in problemas:
            print(f"    {tabla}: activo={activo} forzado={forzado} política={politica}")
        fallos += 1
    else:
        print(f"Aislamiento: activo y forzado en las {len(TABLAS_CON_AISLAMIENTO)} tablas")

    if superusuario or bypass:
        print(
            f"  AVISO: este rol es superusuario={superusuario} y puede saltarse RLS={bypass}. "
            "Mientras la aplicación se conecte así, las políticas no se aplican."
        )
        fallos += 1

    await cerrar_bd()

    if fallos:
        print("\nResultado: hay problemas que corregir.")
        return 1
    print("\nResultado: esquema correcto.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
