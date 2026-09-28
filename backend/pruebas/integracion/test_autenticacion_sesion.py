"""Inicio de sesión contra una base real.

Es la prueba que valida la pieza nueva que ninguna prueba de unidad puede cubrir: la función de
base de datos que resuelve a qué negocio pertenece un correo **antes** de tener contexto de negocio.

Sin ella, el inicio de sesión es imposible: `usuario` está protegida por RLS y la política necesita
el `negocio_id` que precisamente se está averiguando. La función lo devuelve sin exponer nada más,
y aquí se comprueba que efectivamente resuelve y que no devuelve lo que no debe.

Se usan los adaptadores **reales** (Argon2 y JWT), así que también se verifica de paso que un token
emitido por el servicio se puede verificar y que la huella de la contraseña guardada es la correcta.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, NamedTuple

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.aplicacion.casos_uso.autenticar import (
    SesionIniciada,
    iniciar_sesion,
    renovar_sesion,
)
from contratacion.aplicacion.puertos.seguridad import TipoToken
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.sesiones import EstadoSesion
from contratacion.infraestructura.adaptadores.salida.bd.contexto import contexto_negocio
from contratacion.infraestructura.adaptadores.salida.bd.cuentas import (
    RepositorioCuentasBd,
    RepositorioSesionesBd,
)
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.adaptadores.salida.seguridad.contrasenas import (
    HUELLA_DESCARTE,
    ContrasenasArgon2,
)
from contratacion.infraestructura.adaptadores.salida.seguridad.tokens import TokensJwt
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

CONTRASENA = "viento-del-sur-2026"
ACCESO_TTL = 900
REFRESCO_TTL = 86_400
MAX_SESIONES = 2


class Escenario(NamedTuple):
    motor: AsyncEngine
    negocio_id: uuid.UUID
    usuario_id: uuid.UUID
    email: str


@pytest.fixture
async def escenario() -> AsyncIterator[Escenario]:
    """Un negocio con un usuario, con contraseña derivada de verdad."""
    ajustes = obtener_ajustes()
    motor = create_async_engine(
        normalizar_url_bd(ajustes.database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    negocio_id, usuario_id = uuid.uuid4(), uuid.uuid4()
    # El correo lleva el identificador para que la función de resolución no encuentre otro igual.
    email = f"login-{usuario_id.hex[:10]}@prueba.ec"
    hash_password = ContrasenasArgon2().hash(CONTRASENA)

    async with motor.begin() as conexion:
        # El contexto se fija antes de insertar: las políticas exigen que quien escribe sea el
        # propio negocio.
        await conexion.execute(
            text("SELECT set_config('app.negocio_id', :valor, true)"),
            {"valor": str(negocio_id)},
        )
        await conexion.execute(
            text("INSERT INTO negocio (id, nombre, estado) VALUES (:id, 'Prueba login', 'activo')"),
            {"id": str(negocio_id)},
        )
        await conexion.execute(
            text(
                "INSERT INTO usuario (id, negocio_id, email, hash_password, nombre, rol, estado) "
                "VALUES (:id, :negocio, :email, :huella, 'Ana', 'admin_negocio', 'activo')"
            ),
            {
                "id": str(usuario_id),
                "negocio": str(negocio_id),
                "email": email,
                "huella": hash_password,
            },
        )

    try:
        yield Escenario(motor, negocio_id, usuario_id, email)
    finally:
        # Borrar el negocio arrastra en cascada sus usuarios y sus sesiones, así que no queda
        # basura.
        async with motor.begin() as conexion:
            await conexion.execute(
                text("SELECT set_config('app.negocio_id', :valor, true)"),
                {"valor": str(negocio_id)},
            )
            await conexion.execute(
                text("DELETE FROM negocio WHERE id = :id"), {"id": str(negocio_id)}
            )
        await motor.dispose()


async def _entrar(escenario: Escenario, contrasena: str = CONTRASENA) -> SesionIniciada:
    return await iniciar_sesion(
        escenario.email,
        contrasena,
        cuentas=RepositorioCuentasBd(escenario.motor),
        sesiones=RepositorioSesionesBd(escenario.motor),
        contrasenas=ContrasenasArgon2(),
        tokens=TokensJwt(obtener_ajustes().jwt_secreto),
        huella_descarte=HUELLA_DESCARTE,
        max_sesiones=MAX_SESIONES,
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        momento=datetime.now(UTC),
    )


async def test_la_funcion_resuelve_la_cuenta_sin_contexto_de_negocio(escenario: Escenario) -> None:
    """Es la pieza que hace posible el inicio de sesión con RLS activo."""
    async with escenario.motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text("SELECT id_usuario, id_negocio FROM resolver_cuenta(:email)"),
                {"email": escenario.email.upper()},
            )
        ).one_or_none()

    assert fila is not None
    assert fila[0] == escenario.usuario_id
    assert fila[1] == escenario.negocio_id


async def test_la_funcion_no_devuelve_mas_que_los_identificadores() -> None:
    """La función existe para atravesar RLS: lo que devuelve importa tanto como que exista."""
    async with create_async_engine(
        normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False)
    ).connect() as conexion:
        columnas: list[Any] = list(
            (
                await conexion.execute(
                    text(
                        """
                    SELECT a.attname
                    FROM pg_proc p
                    JOIN unnest(p.proargnames) WITH ORDINALITY AS a(attname, pos) ON TRUE
                    WHERE p.proname = 'resolver_cuenta'
                    ORDER BY a.pos
                    """
                    )
                )
            )
            .scalars()
            .all()
        )

    assert set(columnas) <= {"id_usuario", "id_negocio", "p_email"}


async def test_la_funcion_es_de_definidor_y_fija_la_ruta_de_busqueda() -> None:
    """Sin `search_path` fijo, un esquema malicioso podría suplantar las tablas que consulta."""
    async with create_async_engine(
        normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False)
    ).connect() as conexion:
        fila = (
            await conexion.execute(
                text(
                    """
                    SELECT p.prosecdef, array_to_string(p.proconfig, ',')
                    FROM pg_proc p WHERE p.proname = 'resolver_cuenta'
                    """
                )
            )
        ).one()

    assert fila[0] is True, "la función debería ser SECURITY DEFINER"
    assert "search_path" in str(fila[1])


async def test_un_correo_desconocido_no_resuelve_nada(escenario: Escenario) -> None:
    async with escenario.motor.connect() as conexion:
        fila = (
            await conexion.execute(
                text("SELECT id_usuario FROM resolver_cuenta(:email)"),
                {"email": f"nadie-{uuid.uuid4().hex[:8]}@prueba.ec"},
            )
        ).one_or_none()

    assert fila is None


async def test_el_inicio_de_sesion_funciona_de_verdad(escenario: Escenario) -> None:
    resultado = await _entrar(escenario)

    assert resultado.usuario_id == escenario.usuario_id
    tokens = TokensJwt(obtener_ajustes().jwt_secreto)
    claims = tokens.verificar(resultado.acceso, TipoToken.ACCESO)
    assert claims.negocio_id == escenario.negocio_id
    assert claims.rol == "admin_negocio"


async def test_una_contrasena_incorrecta_se_rechaza(escenario: Escenario) -> None:
    with pytest.raises(SinPermiso):
        await _entrar(escenario, "otra-contrasena-larga")


async def test_el_tercer_inicio_de_sesion_expulsa_una(escenario: Escenario) -> None:
    primera = await _entrar(escenario)
    await _entrar(escenario)
    tercera = await _entrar(escenario)

    assert tercera.sesiones_expulsadas == 1

    repositorio = RepositorioSesionesBd(escenario.motor)
    activas = await repositorio.vigentes(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.usuario_id,
        momento=datetime.now(UTC),
    )
    assert len(activas) == MAX_SESIONES
    # La primera queda revocada y la más reciente sigue viva.
    assert all(sesion.estado is EstadoSesion.ACTIVA for sesion in activas)
    assert primera.sesion_id not in {sesion.id for sesion in activas}


async def test_la_renovacion_rota_el_token_y_el_viejo_deja_de_servir(escenario: Escenario) -> None:
    inicial = await _entrar(escenario)
    tokens = TokensJwt(obtener_ajustes().jwt_secreto)

    renovada = await renovar_sesion(
        inicial.refresco,
        cuentas=RepositorioCuentasBd(escenario.motor),
        sesiones=RepositorioSesionesBd(escenario.motor),
        tokens=tokens,
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
    )
    assert renovada.refresco != inicial.refresco

    # Reutilizar el token viejo cierra todas las sesiones de la cuenta.
    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.refresco,
            cuentas=RepositorioCuentasBd(escenario.motor),
            sesiones=RepositorioSesionesBd(escenario.motor),
            tokens=tokens,
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
        )

    activas = await RepositorioSesionesBd(escenario.motor).vigentes(
        negocio_id=escenario.negocio_id,
        usuario_id=escenario.usuario_id,
        momento=datetime.now(UTC),
    )
    assert activas == ()


async def test_las_sesiones_de_un_negocio_no_se_ven_desde_otro(escenario: Escenario) -> None:
    """Aislamiento de las sesiones, que también son datos del plano de negocio.

    Se salta si el rol de conexión se salta RLS: en ese caso la consulta devuelve las filas de todos
    los negocios y el fallo sería del entorno, no del código. El aislamiento conductual se verifica
    en `test_acceso_vistas.py`, que se conecta con un rol de aplicación sin privilegios.
    """
    async with escenario.motor.connect() as conexion:
        bypass: Any = (
            await conexion.execute(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        ).scalar_one()
    if bypass:
        pytest.skip("El rol de conexión se salta RLS: hace falta el rol de aplicación (R-05).")

    await _entrar(escenario)

    async with contexto_negocio(escenario.motor, uuid.uuid4()) as conexion:
        total: Any = (await conexion.execute(text("SELECT count(*) FROM sesion"))).scalar_one()

    assert total == 0
