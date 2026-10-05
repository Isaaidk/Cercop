"""Aislamiento entre negocios — la prueba más importante del proyecto.

Demuestra que el aislamiento lo garantiza **la base de datos**, no el código de la aplicación: aquí
se consulta con SQL directo, **sin ningún `WHERE`**, y aun así un negocio no puede ver los datos de
otro. Si esta prueba falla, el producto no se puede vender a varios clientes.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.

Requisitos que se comprueban y que son imprescindibles para que RLS sirva de algo:

1. Las tablas tienen RLS activado **y forzado** (`FORCE`), así que también se aplica al
   propietario de la tabla.
2. El rol de la aplicación **no es superusuario** ni tiene `BYPASSRLS`: los superusuarios
   ignoran RLS por completo.
3. Sin contexto de negocio establecido, el resultado por defecto es **denegar**.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes


class Escenario(NamedTuple):
    """Dos negocios con un usuario cada uno, más la clave del rol de aplicación."""

    a: uuid.UUID
    b: uuid.UUID
    password: str


pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

ROL_APLICACION = "app_contratacion_pruebas"
# Fija a propósito: el agrupador de Supabase reutiliza conexiones por usuario y una clave rotada en
# cada prueba hace que la conexión reutilizada deje de valer (`password authentication failed`).
# El motivo completo está explicado en `test_acceso_vistas.py`. El rol es de solo lectura.
CLAVE_ROL = "pruebas-rol-aplicacion"
TABLAS_CON_NEGOCIO = (
    "usuario",
    "sesion",
    "suscripcion_termino",
    "conjunto_terminos",
    "filtro_guardado",
    "exportacion",
    "consentimiento",
    "solicitud_arco",
    "auditoria",
    "conjunto_termino",
)


def _url_admin() -> str:
    url = normalizar_url_bd(obtener_ajustes().database_url)
    return url.render_as_string(hide_password=False)


def _usuario_del_rol(rol: str) -> str:
    """El nombre del rol **con el sufijo del proyecto**, que es lo que enruta el agrupador.

    Supabase recibe las conexiones en Supavisor, que deduce de qué proyecto son a partir del sufijo
    del nombre de usuario (`rol.referencia_del_proyecto`). Un rol suelto —el de aplicación de estas
    pruebas— no le dice nada y responde `ENOIDENTIFIER: no tenant identifier provided (external_id
    or sni_hostname required)`, un error de **enrutado** que se lee como si fueran las credenciales
    y hace fallar las pruebas del archivo por un motivo que no está en ninguna de ellas. El sufijo
    se toma del usuario de administración, que sí lo trae, y así sigue valiendo si el proyecto
    cambia.
    """
    usuario_admin = make_url(_url_admin()).username or ""
    _, _, sufijo = usuario_admin.partition(".")
    return f"{rol}.{sufijo}" if sufijo else rol


def _url_como_rol(password: str) -> str:
    url = make_url(_url_admin()).set(username=_usuario_del_rol(ROL_APLICACION), password=password)
    return url.render_as_string(hide_password=False)


async def _contar(motor: AsyncEngine, negocio_id: uuid.UUID | None) -> int:
    """Cuenta usuarios **sin filtrar por negocio a propósito**: RLS debe hacer el trabajo."""
    async with motor.connect() as conexion, conexion.begin():
        if negocio_id is not None:
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio_id)},
            )
        resultado = await conexion.execute(text("SELECT count(*) FROM usuario"))
        return int(resultado.scalar_one())


async def _asegurar_rol(conexion: AsyncConnection, clave_sql: str) -> None:
    """Crea el rol de aplicación y concede los permisos; si ya existe, **no lo toca**.

    No se elimina al terminar: `DROP ROLE` falla mientras el rol conserve privilegios, y revocarlos
    exige permisos que el usuario administrador de un proveedor gestionado no siempre tiene. Crear
    es idempotente y no deja basura.

    Tampoco se le refresca la clave: `ALTER ROLE ... PASSWORD` rehace el verificador SCRAM aunque la
    clave sea la misma, y el agrupador de Supabase tiene memorizada la credencial de ese usuario (el
    fallo y el remedio están explicados en `test_acceso_vistas.py::_asegurar_rol`).
    """
    existe = (
        await conexion.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :nombre"), {"nombre": ROL_APLICACION}
        )
    ).scalar_one_or_none()

    # Cambiar los atributos privilegiados de un rol exige superusuario, así que la clave solo se
    # fija al crear. Los atributos seguros (no superusuario, sin BYPASSRLS, sin crear bases ni
    # roles) también se fijan al crear, y la prueba los verifica después.
    clave = f"LOGIN PASSWORD '{clave_sql}'"
    if not existe:
        await conexion.execute(
            text(
                f"CREATE ROLE {ROL_APLICACION} WITH "
                f"NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE {clave}"
            )
        )

    await conexion.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROL_APLICACION}"))
    await conexion.execute(
        text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            f"TO {ROL_APLICACION}"
        )
    )
    await conexion.execute(
        text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROL_APLICACION}")
    )


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Crea un rol de aplicación real y dos negocios con un usuario cada uno."""
    password = CLAVE_ROL
    negocio_a, negocio_b = uuid.uuid4(), uuid.uuid4()
    admin = create_async_engine(_url_admin(), pool_pre_ping=True)

    async with admin.begin() as conexion:
        # Las sentencias DDL no admiten parámetros, así que hay que componer el literal. La clave se
        # genera aquí y se escapa por si contuviera comillas.
        await _asegurar_rol(conexion, password)
        for identificador, nombre in ((negocio_a, "Negocio A"), (negocio_b, "Negocio B")):
            # El contexto se fija antes de insertar: las políticas exigen que quien escribe sea el
            # propio negocio. Así la prueba no depende de que el administrador se salte RLS.
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(identificador)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, :nombre, 'activo')"),
                {"id": str(identificador), "nombre": nombre},
            )
            await conexion.execute(
                text(
                    "INSERT INTO usuario (negocio_id, email, hash_password, estado) "
                    "VALUES (:negocio, :email, 'x', 'activo')"
                ),
                {
                    "negocio": str(identificador),
                    "email": f"consultor@{nombre.split()[-1].lower()}.test",
                },
            )

    yield Escenario(a=negocio_a, b=negocio_b, password=password)

    async with admin.begin() as conexion:
        for identificador in (negocio_a, negocio_b):
            # El contexto también hace falta para borrar: las políticas se aplican a toda escritura.
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(identificador)},
            )
            await conexion.execute(
                text("DELETE FROM usuario WHERE negocio_id = :valor"),
                {"valor": str(identificador)},
            )
            await conexion.execute(
                text("DELETE FROM negocio WHERE id = :valor"),
                {"valor": str(identificador)},
            )
    await admin.dispose()


async def test_las_tablas_tienen_rls_activado_y_forzado() -> None:
    """`FORCE` es imprescindible: sin él, el propietario de la tabla se salta las políticas."""
    admin = create_async_engine(_url_admin(), pool_pre_ping=True)
    try:
        async with admin.connect() as conexion:
            resultado = await conexion.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = ANY(:tablas)"
                ),
                {"tablas": [*TABLAS_CON_NEGOCIO, "negocio"]},
            )
            filas = resultado.all()
    finally:
        await admin.dispose()

    assert len(filas) == len(TABLAS_CON_NEGOCIO) + 1, "faltan tablas del plano de negocio"
    sin_forzar = [nombre for nombre, _, forzado in filas if not forzado]
    assert not sin_forzar, f"estas tablas no fuerzan RLS: {sin_forzar}"


async def test_un_negocio_no_ve_los_datos_de_otro(escenario: Escenario) -> None:
    """La prueba central: consulta sin `WHERE` y aun así cada negocio solo ve lo suyo."""
    motor = create_async_engine(_url_como_rol(escenario.password), pool_pre_ping=True)
    try:
        assert await _contar(motor, escenario.a) == 1
        assert await _contar(motor, escenario.b) == 1
    finally:
        await motor.dispose()


async def test_sin_contexto_no_se_ve_nada(escenario: Escenario) -> None:
    """El comportamiento por defecto debe ser denegar, no mostrar todo."""
    motor = create_async_engine(_url_como_rol(escenario.password), pool_pre_ping=True)
    try:
        assert await _contar(motor, None) == 0
    finally:
        await motor.dispose()


async def test_no_se_puede_insertar_en_otro_negocio(escenario: Escenario) -> None:
    """El `WITH CHECK` impide escribir datos a nombre de otro negocio."""
    motor = create_async_engine(_url_como_rol(escenario.password), pool_pre_ping=True)
    try:
        with pytest.raises(DBAPIError, match="row-level security"):
            async with motor.begin() as conexion:
                await conexion.execute(
                    text("SELECT set_config('app.negocio_id', :valor, true)"),
                    {"valor": str(escenario.a)},
                )
                await conexion.execute(
                    text(
                        "INSERT INTO usuario (negocio_id, email, hash_password, estado) "
                        "VALUES (:negocio, 'intruso@test.test', 'x', 'activo')"
                    ),
                    {"negocio": str(escenario.b)},
                )
    finally:
        await motor.dispose()


async def test_el_rol_de_aplicacion_no_es_superusuario(escenario: Escenario) -> None:
    """Si el rol fuera superusuario, RLS se ignoraría y todo lo anterior sería falso."""
    motor = create_async_engine(_url_como_rol(escenario.password), pool_pre_ping=True)
    try:
        async with motor.connect() as conexion:
            resultado = await conexion.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
            es_superusuario, salta_rls = resultado.one()
    finally:
        await motor.dispose()

    assert es_superusuario is False
    assert salta_rls is False
