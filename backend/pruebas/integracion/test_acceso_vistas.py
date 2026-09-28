"""Acceso a vistas contra una base real.

Lo que se comprueba aquí no se puede comprobar con dobles: que el aislamiento lo impone la base de
datos, que el vencimiento se guarda como instante absoluto y que retirar un acceso deja el rastro en
lugar de borrar la fila.

Se conecta con un **rol de aplicación real**, sin superusuario y sin `BYPASSRLS`. Es imprescindible:
los superusuarios ignoran las políticas por completo, así que probar el aislamiento conectándose
como `postgres` no demostraría nada.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from contratacion.dominio.acceso import Plazo, Vista, concesion_vigente
from contratacion.infraestructura.adaptadores.salida.bd.accesos import RepositorioAccesosBd
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

ROL_APLICACION = "app_contratacion_pruebas"
AHORA = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


class Escenario(NamedTuple):
    """Dos negocios con un usuario cada uno, vistos a través del rol de aplicación."""

    motor: AsyncEngine
    negocio_a: uuid.UUID
    negocio_b: uuid.UUID
    usuario_a: uuid.UUID
    usuario_b: uuid.UUID


def _url_admin() -> str:
    return normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False)


async def _asegurar_rol(conexion: AsyncConnection, clave_sql: str) -> None:
    """Crea el rol de aplicación (o le refresca la clave) y le concede permisos.

    No se elimina al terminar: `DROP ROLE` falla mientras conserve privilegios y revocarlos exige
    permisos que un proveedor gestionado no siempre da. Crear o actualizar es idempotente.
    """
    existe = (
        await conexion.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :nombre"), {"nombre": ROL_APLICACION}
        )
    ).scalar_one_or_none()

    clave = f"LOGIN PASSWORD '{clave_sql}'"
    if existe:
        await conexion.execute(text(f"ALTER ROLE {ROL_APLICACION} WITH {clave}"))
    else:
        # Los atributos privilegiados solo se pueden fijar al crear: cambiarlos después exige
        # superusuario. Por eso se crea ya con todos los que hacen falta.
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
    """Prepara el rol de aplicación y dos negocios con un usuario cada uno."""
    password = secrets.token_urlsafe(24)
    negocio_a, negocio_b = uuid.uuid4(), uuid.uuid4()
    usuario_a, usuario_b = uuid.uuid4(), uuid.uuid4()
    admin = create_async_engine(_url_admin(), pool_pre_ping=True)

    async with admin.begin() as conexion:
        await _asegurar_rol(conexion, password.replace("'", "''"))
        for negocio, usuario, email in (
            (negocio_a, usuario_a, f"a-{negocio_a}@prueba.ec"),
            (negocio_b, usuario_b, f"b-{negocio_b}@prueba.ec"),
        ):
            # El contexto se fija antes de insertar porque las políticas exigen que quien escribe
            # sea el propio negocio; así la prueba no depende de saltarse RLS.
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, :nombre, 'activo')"),
                {"id": str(negocio), "nombre": f"Negocio {str(negocio)[:8]}"},
            )
            await conexion.execute(
                text(
                    "INSERT INTO usuario (id, negocio_id, email, hash_password, rol, estado) "
                    "VALUES (:id, :negocio, :email, 'x', 'admin_negocio', 'activo')"
                ),
                {"id": str(usuario), "negocio": str(negocio), "email": email},
            )

    motor = create_async_engine(
        make_url(_url_admin())
        .set(username=ROL_APLICACION, password=password)
        .render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    try:
        yield Escenario(motor, negocio_a, negocio_b, usuario_a, usuario_b)
    finally:
        # Los datos **se borran**. Dejarlos «porque cada prueba usa identificadores nuevos» es
        # cierto y aun así insuficiente: nadie los borra nunca, y una base que se use para ejecutar
        # la suite unas cuantas veces acumula cientos de negocios de prueba. Llegado ese punto,
        # cualquier listado con límite empieza a devolver basura y el problema parece del listado.
        #
        # Se borra con la conexión de administración porque las políticas de la base no permiten
        # eliminar un negocio desde dentro de sí mismo, y borrar el negocio arrastra en cascada sus
        # usuarios, sesiones, concesiones y consentimientos.
        async with admin.begin() as conexion:
            for negocio in (negocio_a, negocio_b):
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()
        await admin.dispose()


# --------------------------------------------------------------------------- #
# Estructura: la migración dejó lo que debía
# --------------------------------------------------------------------------- #


async def test_las_tablas_de_acceso_tienen_aislamiento_forzado(escenario: Escenario) -> None:
    """`ENABLE` sin `FORCE` parece protección y no lo es para el propietario de la tabla."""
    async with escenario.motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity,
                           EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = 'acceso_vista'
                    """
                )
            )
        ).one()

    assert fila[0] is True, "RLS no está activado en acceso_vista"
    assert fila[1] is True, "RLS no está forzado en acceso_vista"
    assert fila[2] is True, "acceso_vista no tiene ninguna política"


async def test_la_funcion_de_conteo_existe_y_cuenta(escenario: Escenario) -> None:
    """El planificador corre sin contexto de negocio: necesita esta función para ver los
    suscriptores."""
    async with escenario.motor.connect() as conexion:
        valor: Any = (
            await conexion.execute(
                text("SELECT conteo_suscriptores(:id)"), {"id": str(uuid.uuid4())}
            )
        ).scalar_one()

    assert valor == 0


async def test_el_rol_de_aplicacion_no_puede_saltarse_el_aislamiento(
    escenario: Escenario,
) -> None:
    """Si esta prueba falla, todo lo demás sobre el aislamiento es decorativo."""
    async with escenario.motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).one()

    assert fila[0] is False
    assert fila[1] is False


# --------------------------------------------------------------------------- #
# Concesión
# --------------------------------------------------------------------------- #


async def test_conceder_treinta_dias_guarda_el_vencimiento_exacto(escenario: Escenario) -> None:
    repositorio = RepositorioAccesosBd(escenario.motor)

    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        plazo=Plazo.D30,
        otorgado_en=AHORA,
        vence_en=Plazo.D30.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    assert len(accesos) == 1
    assert accesos[0].vista is Vista.OFERTAS
    assert accesos[0].plazo is Plazo.D30
    # La fecha se guarda, no el plazo: es lo que permite auditarla más adelante.
    assert accesos[0].vence_en == AHORA + timedelta(days=30)


async def test_el_acceso_recien_concedido_esta_vigente(escenario: Escenario) -> None:
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.NECESIDADES,
        plazo=Plazo.M3,
        otorgado_en=AHORA,
        vence_en=Plazo.M3.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    vigentes = concesion_vigente(accesos, AHORA + timedelta(days=1))
    assert Vista.NECESIDADES in vigentes


async def test_un_acceso_vencido_no_concede_aunque_nadie_lo_haya_marcado(
    escenario: Escenario,
) -> None:
    """El vencimiento se comprueba al leer. No hay ningún proceso que marque caducidades."""
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.GRAFICAS,
        plazo=Plazo.D7,
        otorgado_en=AHORA,
        vence_en=Plazo.D7.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    assert not concesion_vigente(accesos, AHORA + timedelta(days=8))


async def test_extender_anade_una_fila_y_no_acorta(escenario: Escenario) -> None:
    repositorio = RepositorioAccesosBd(escenario.motor)
    for plazo in (Plazo.D30, Plazo.A1):
        await repositorio.conceder(
            negocio_id=escenario.negocio_a,
            usuario_id=escenario.usuario_a,
            vista=Vista.CONTRATACIONES,
            plazo=plazo,
            otorgado_en=AHORA,
            vence_en=plazo.calcular(AHORA),
            otorgado_por=escenario.usuario_a,
        )

    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    # Dos filas, no una reescrita: el historial conserva las dos concesiones.
    assert len(accesos) == 2
    vigente = concesion_vigente(accesos, AHORA + timedelta(days=1))[Vista.CONTRATACIONES]
    assert vigente.plazo is Plazo.A1
    assert vigente.vence_en == Plazo.A1.calcular(AHORA)


# --------------------------------------------------------------------------- #
# Retirada
# --------------------------------------------------------------------------- #


async def test_retirar_deja_de_conceder_sin_borrar_la_fila(escenario: Escenario) -> None:
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        plazo=Plazo.A1,
        otorgado_en=AHORA,
        vence_en=Plazo.A1.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    retiradas = await repositorio.retirar(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        momento=AHORA + timedelta(days=2),
        retirado_por=escenario.usuario_a,
    )
    assert retiradas == 1

    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    # La fila sigue ahí: se marca, no se borra, para poder auditar quién retiró el acceso.
    assert len(accesos) == 1
    assert accesos[0].revocado_en is not None
    assert not concesion_vigente(accesos, AHORA + timedelta(days=3))


async def test_retirar_dos_veces_no_encuentra_nada_la_segunda(escenario: Escenario) -> None:
    """Devolver cero es lo que permite distinguir «no se pudo» de «no había nada que retirar»."""
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        plazo=Plazo.D7,
        otorgado_en=AHORA,
        vence_en=Plazo.D7.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    argumentos: dict[str, Any] = {
        "negocio_id": escenario.negocio_a,
        "usuario_id": escenario.usuario_a,
        "vista": Vista.OFERTAS,
        "momento": AHORA,
        "retirado_por": escenario.usuario_a,
    }
    assert (
        await repositorio.retirar(
            negocio_id=argumentos["negocio_id"],
            usuario_id=argumentos["usuario_id"],
            vista=argumentos["vista"],
            momento=argumentos["momento"],
            retirado_por=argumentos["retirado_por"],
        )
        == 1
    )
    assert (
        await repositorio.retirar(
            negocio_id=argumentos["negocio_id"],
            usuario_id=argumentos["usuario_id"],
            vista=argumentos["vista"],
            momento=argumentos["momento"],
            retirado_por=argumentos["retirado_por"],
        )
        == 0
    )


async def test_retirar_alcanza_todas_las_concesiones_activas(escenario: Escenario) -> None:
    """Con dos concesiones vivas, retirar solo la última dejaría el acceso abierto."""
    repositorio = RepositorioAccesosBd(escenario.motor)
    for plazo in (Plazo.D30, Plazo.A1):
        await repositorio.conceder(
            negocio_id=escenario.negocio_a,
            usuario_id=escenario.usuario_a,
            vista=Vista.GRAFICAS,
            plazo=plazo,
            otorgado_en=AHORA,
            vence_en=plazo.calcular(AHORA),
            otorgado_por=escenario.usuario_a,
        )

    retiradas = await repositorio.retirar(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.GRAFICAS,
        momento=AHORA,
        retirado_por=escenario.usuario_a,
    )

    assert retiradas == 2
    accesos = await repositorio.obtener(
        negocio_id=escenario.negocio_a, usuario_id=escenario.usuario_a
    )
    assert not concesion_vigente(accesos, AHORA + timedelta(days=1))


# --------------------------------------------------------------------------- #
# Aislamiento
# --------------------------------------------------------------------------- #


async def test_un_negocio_no_ve_los_accesos_de_otro(escenario: Escenario) -> None:
    """Se consulta **sin filtrar por negocio a propósito**: el aislamiento lo pone la base."""
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        plazo=Plazo.A1,
        otorgado_en=AHORA,
        vence_en=Plazo.A1.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    async with contexto_negocio(escenario.motor, escenario.negocio_b) as conexion:
        total: Any = (
            await conexion.execute(text("SELECT count(*) FROM acceso_vista"))
        ).scalar_one()

    assert total == 0


async def test_un_negocio_no_puede_conceder_en_nombre_de_otro(escenario: Escenario) -> None:
    """La política `WITH CHECK` impide escribir una concesión que no sea del propio negocio."""
    with pytest.raises(Exception):  # noqa: B017 - el controlador concreto no importa aquí
        async with contexto_negocio(escenario.motor, escenario.negocio_b) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO acceso_vista (negocio_id, usuario_id, vista, plazo_codigo, vence_en)
                    VALUES (:negocio, :usuario, 'ofertas', '30d', now() + interval '30 days')
                    """
                ),
                {"negocio": str(escenario.negocio_a), "usuario": str(escenario.usuario_a)},
            )


async def test_sin_contexto_no_se_ve_ninguna_concesion(escenario: Escenario) -> None:
    """Denegar por defecto: sin `app.negocio_id`, la comparación resulta nula y no hay filas."""
    repositorio = RepositorioAccesosBd(escenario.motor)
    await repositorio.conceder(
        negocio_id=escenario.negocio_a,
        usuario_id=escenario.usuario_a,
        vista=Vista.OFERTAS,
        plazo=Plazo.D7,
        otorgado_en=AHORA,
        vence_en=Plazo.D7.calcular(AHORA),
        otorgado_por=escenario.usuario_a,
    )

    async with escenario.motor.connect() as conexion:
        total: Any = (
            await conexion.execute(text("SELECT count(*) FROM acceso_vista"))
        ).scalar_one()

    assert total == 0


async def test_la_base_rechaza_un_vencimiento_anterior_a_la_concesion(
    escenario: Escenario,
) -> None:
    """La restricción `CHECK` es la última barrera: ni un error de cálculo puede colarla."""
    with pytest.raises(Exception):  # noqa: B017
        async with contexto_negocio(escenario.motor, escenario.negocio_a) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO acceso_vista (negocio_id, usuario_id, vista, plazo_codigo,
                                              otorgado_en, vence_en)
                    VALUES (:negocio, :usuario, 'ofertas', '30d', :despues, :antes)
                    """
                ),
                {
                    "negocio": str(escenario.negocio_a),
                    "usuario": str(escenario.usuario_a),
                    "despues": AHORA,
                    "antes": AHORA - timedelta(days=1),
                },
            )


async def test_la_base_rechaza_un_plazo_fuera_del_catalogo(escenario: Escenario) -> None:
    """Un plazo inventado no puede entrar ni por SQL directo."""
    with pytest.raises(Exception):  # noqa: B017
        async with contexto_negocio(escenario.motor, escenario.negocio_a) as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO acceso_vista (negocio_id, usuario_id, vista, plazo_codigo, vence_en)
                    VALUES (:negocio, :usuario, 'ofertas', '99a', now() + interval '30 days')
                    """
                ),
                {"negocio": str(escenario.negocio_a), "usuario": str(escenario.usuario_a)},
            )
