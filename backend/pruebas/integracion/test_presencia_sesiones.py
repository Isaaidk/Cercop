"""Presencia contra una base real.

Lo que ninguna prueba de unidad puede cubrir: que las dos consultas nuevas devuelvan lo que dice su
comentario. `activas_del_negocio` alimenta el cuadro y `revocadas_del_negocio` lo explica; si la
segunda devolviera sesiones activas —o la primera dejara de filtrar por fecha—, el panel seguiría
funcionando pero con un motivo equivocado, que es el peor tipo de fallo porque parece correcto.

Se comprueba además el aislamiento: las sesiones de otro negocio no pueden aparecer por mucho que la
consulta no filtre por usuario.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion
from contratacion.infraestructura.adaptadores.salida.bd.cuentas import RepositorioSesionesBd
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

AHORA = datetime.now(UTC)


class Escenario(NamedTuple):
    motor: AsyncEngine
    negocio_id: uuid.UUID
    usuario_id: uuid.UUID
    otro_negocio_id: uuid.UUID


def _sql_sesion(negocio_id: uuid.UUID, usuario_id: uuid.UUID, **extra: object) -> dict[str, object]:
    return {
        "id": str(uuid.uuid4()),
        "negocio_id": str(negocio_id),
        "usuario_id": str(usuario_id),
        "estado": "activa",
        "expira_en": AHORA + timedelta(days=7),
        **extra,
    }


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Dos negocios con un usuario cada uno, para poder comprobar el aislamiento."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, otro_negocio_id = uuid.uuid4(), uuid.uuid4()
    usuario_id, otro_usuario_id = uuid.uuid4(), uuid.uuid4()

    async with motor.begin() as conexion:
        for negocio, usuario, nombre in (
            (negocio_id, usuario_id, "Presencia A"),
            (otro_negocio_id, otro_usuario_id, "Presencia B"),
        ):
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio)},
            )
            await conexion.execute(
                text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, :nombre, 'activo')"),
                {"id": str(negocio), "nombre": nombre},
            )
            await conexion.execute(
                text(
                    "INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol, "
                    "estado) VALUES (:id, :negocio, :email, 'x', 'Ana', 'admin_negocio', 'activo')"
                ),
                {
                    "id": str(usuario),
                    "negocio": str(negocio),
                    "email": f"presencia-{usuario.hex[:10]}@prueba.ec",
                },
            )

    try:
        yield Escenario(motor, negocio_id, usuario_id, otro_negocio_id)
    finally:
        async with motor.begin() as conexion:
            for negocio in (negocio_id, otro_negocio_id):
                await conexion.execute(
                    text("SELECT set_config('app.negocio_id', :valor, true)"),
                    {"valor": str(negocio)},
                )
                await conexion.execute(
                    text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio)}
                )
        await motor.dispose()


async def _insertar(escenario: Escenario, negocio_id: uuid.UUID, **extra: object) -> uuid.UUID:
    """Crea una sesión con el contexto del negocio dado."""
    datos = _sql_sesion(negocio_id, escenario.usuario_id, **extra)
    async with escenario.motor.begin() as conexion:
        await conexion.execute(
            text("SELECT set_config('app.negocio_id', :valor, true)"),
            {"valor": str(negocio_id)},
        )
        await conexion.execute(
            text(
                "INSERT INTO sesion (id, negocio_id, usuario_id, refresh_hash, creada_en, "
                "ultimo_uso_en, expira_en, estado, revocada_motivo) VALUES (:id, :negocio_id, "
                ":usuario_id, 'h', :ultimo_uso_en, :ultimo_uso_en, :expira_en, :estado, :motivo)"
            ),
            {
                **datos,
                "motivo": extra.get("motivo"),
                "ultimo_uso_en": extra.get("ultimo_uso_en") or AHORA,
            },
        )
    return uuid.UUID(str(datos["id"]))


async def _saltar_si_el_rol_se_salta_rls(escenario: Escenario) -> None:
    """Salta la prueba si el rol de conexión no está sujeto a las políticas.

    Es la limitación R-05, medida y no supuesta: el rol de Supabase con el que se conectan las
    pruebas tiene `rolbypassrls`, así que **la base no filtra nada** y las consultas devuelven filas
    de todos los negocios. El aislamiento conductual no se puede demostrar desde aquí y se verifica
    en `test_acceso_vistas.py`, que se conecta con un rol de aplicación sin privilegios.

    Se salta en lugar de afirmar algo que no depende de este código: una prueba que falla por el
    entorno deja de ser útil como señal, y acaba ignorándose.
    """
    async with escenario.motor.connect() as conexion:
        bypass: Any = (
            await conexion.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar_one()
    if bypass:
        pytest.skip("El rol de conexión se salta RLS: hace falta el rol de aplicación (R-05).")


# --------------------------------------------------------------------------- #
# Sesiones vigentes del negocio
# --------------------------------------------------------------------------- #


async def test_las_sesiones_vigentes_del_negocio_se_devuelven(
    escenario: Escenario,
) -> None:
    # Estas consultas **no llevan `negocio_id` en el SQL**: el aislamiento lo pone la política de la
    # base. Con un rol que se salta RLS devuelven las sesiones de todos los negocios, así que la
    # prueba no mide lo que dice medir y falla por la razón equivocada —en cuanto otro negocio crea
    # una sesión—. Se salta, como sus vecinas, y el aislamiento se comprueba donde sí se puede.
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(escenario, escenario.negocio_id)
    repositorio = RepositorioSesionesBd(escenario.motor)

    activas = await repositorio.activas_del_negocio(negocio_id=escenario.negocio_id, momento=AHORA)

    assert len(activas) == 1
    assert activas[0].estado is EstadoSesion.ACTIVA
    assert activas[0].usuario_id == escenario.usuario_id


async def test_una_sesion_caducada_no_cuenta_como_vigente(escenario: Escenario) -> None:
    """Una sesión cuyo plazo pasó no sirve para autenticar, así que no puede alimentar el cuadro."""
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(escenario, escenario.negocio_id, expira_en=AHORA - timedelta(minutes=1))
    repositorio = RepositorioSesionesBd(escenario.motor)

    activas = await repositorio.activas_del_negocio(negocio_id=escenario.negocio_id, momento=AHORA)

    assert activas == ()


async def test_una_sesion_revocada_no_cuenta_como_vigente(escenario: Escenario) -> None:
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(
        escenario,
        escenario.negocio_id,
        estado="revocada",
        motivo=str(MotivoRevocacion.ADMIN),
    )
    repositorio = RepositorioSesionesBd(escenario.motor)

    activas = await repositorio.activas_del_negocio(negocio_id=escenario.negocio_id, momento=AHORA)

    assert activas == ()


async def test_las_sesiones_de_otro_negocio_no_aparecen(escenario: Escenario) -> None:
    """Lo garantiza la política de la base, no un filtro del código.

    Es la prueba que distingue «lo filtramos nosotros» de «no puede llegar». Si algún día la
    consulta dejara de fijar el contexto de negocio, aquí se vería —cuando el entorno lo permita—.
    """
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(escenario, escenario.otro_negocio_id)
    repositorio = RepositorioSesionesBd(escenario.motor)

    activas = await repositorio.activas_del_negocio(negocio_id=escenario.negocio_id, momento=AHORA)

    assert activas == ()


# --------------------------------------------------------------------------- #
# Sesiones que ya no están activas: sirven para explicar el rojo
# --------------------------------------------------------------------------- #


async def test_una_revocada_se_devuelve_con_su_motivo(escenario: Escenario) -> None:
    """El motivo tiene que llegar convertido al enumerado, no como texto suelto.

    El panel lo usa como clave de un diccionario de textos. Si llegara como cadena, la búsqueda no
    encontraría nada y el rojo se quedaría sin explicación sin dar ningún error.
    """
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(
        escenario,
        escenario.negocio_id,
        estado="revocada",
        motivo=str(MotivoRevocacion.EVICCION),
    )
    repositorio = RepositorioSesionesBd(escenario.motor)

    revocadas = await repositorio.revocadas_del_negocio(negocio_id=escenario.negocio_id)

    assert len(revocadas) == 1
    assert revocadas[0].motivo_revocacion is MotivoRevocacion.EVICCION


async def test_las_activas_nunca_aparecen_entre_las_revocadas(escenario: Escenario) -> None:
    """Mezclarlas sería dar por abierta una sesión cerrada, y el cuadro lo comprobaría mal."""
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(escenario, escenario.negocio_id)
    repositorio = RepositorioSesionesBd(escenario.motor)

    revocadas = await repositorio.revocadas_del_negocio(negocio_id=escenario.negocio_id)

    assert revocadas == ()


async def test_las_revocadas_llegan_de_la_mas_reciente_a_la_mas_antigua(
    escenario: Escenario,
) -> None:
    """El motivo que se muestra tiene que ser el del último cierre, no el de hace tres semanas."""
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(
        escenario,
        escenario.negocio_id,
        estado="revocada",
        motivo=str(MotivoRevocacion.LOGOUT),
        ultimo_uso_en=AHORA - timedelta(days=9),
    )
    await _insertar(
        escenario,
        escenario.negocio_id,
        estado="revocada",
        motivo=str(MotivoRevocacion.CIERRE_VENTANA),
        ultimo_uso_en=AHORA - timedelta(hours=1),
    )
    repositorio = RepositorioSesionesBd(escenario.motor)

    revocadas = await repositorio.revocadas_del_negocio(negocio_id=escenario.negocio_id)

    assert [sesion.motivo_revocacion for sesion in revocadas] == [
        MotivoRevocacion.CIERRE_VENTANA,
        MotivoRevocacion.LOGOUT,
    ]


async def test_una_sesion_activa_no_trae_motivo_de_revocacion(escenario: Escenario) -> None:
    """`None` significa «nadie la revocó», no «no sabemos por qué»."""
    await _insertar(escenario, escenario.negocio_id)
    repositorio = RepositorioSesionesBd(escenario.motor)

    activas = await repositorio.activas_del_negocio(negocio_id=escenario.negocio_id, momento=AHORA)

    assert activas[0].motivo_revocacion is None


async def test_las_revocadas_de_otro_negocio_no_aparecen(escenario: Escenario) -> None:
    await _saltar_si_el_rol_se_salta_rls(escenario)
    await _insertar(
        escenario,
        escenario.otro_negocio_id,
        estado="revocada",
        motivo=str(MotivoRevocacion.ADMIN),
    )
    repositorio = RepositorioSesionesBd(escenario.motor)

    revocadas = await repositorio.revocadas_del_negocio(negocio_id=escenario.negocio_id)

    assert revocadas == ()


async def test_revocar_desde_el_repositorio_deja_el_motivo_escrito(
    escenario: Escenario,
) -> None:
    """El camino completo: cerrar la ventana y poder contarlo después."""
    sesion_id = await _insertar(escenario, escenario.negocio_id)
    repositorio = RepositorioSesionesBd(escenario.motor)

    await repositorio.revocar(
        negocio_id=escenario.negocio_id,
        sesion_id=sesion_id,
        motivo=MotivoRevocacion.CIERRE_VENTANA,
        momento=AHORA,
    )
    guardada = await repositorio.por_id(negocio_id=escenario.negocio_id, sesion_id=sesion_id)

    assert guardada is not None
    assert guardada.sesion.estado is EstadoSesion.REVOCADA
    assert guardada.sesion.motivo_revocacion is MotivoRevocacion.CIERRE_VENTANA
