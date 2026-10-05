"""Cola de ingesta de palabras clave contra una base real.

Esta prueba defiende el requisito que más caro sale si se incumple: **cuando un cliente agrega una
palabra clave nueva, la búsqueda tiene que hacerse y no puede quedarse fuera de la cola**.

El defecto que la motivó era real y silencioso. El planificador pedía los términos con un orden que
empezaba por `ultima_ingesta_en NULLS FIRST`, pero `ultima_ingesta_en` no se actualizaba en ninguna
parte. Como todos los términos lo tenían nulo, el orden degeneraba en «los 20 primeros por fecha
 de creación»: **todo término añadido después del vigésimo no se ingestaba jamás**, y el panel lo
mostraba eternamente «en cola» sin que nada fallara.

Las pruebas escriben en el catálogo **real**, así que se limpian solas: los términos que crean
llevan un prefijo reconocible y se borran al empezar y al terminar. Sin esa limpieza, cada
ejecución dejaría pendientes de verdad en la cola del sistema.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.adaptadores.salida.bd.terminos import RepositorioTerminosBd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

PREFIJO = "zz-prueba-cola-"
AHORA = datetime.now(UTC)


def _nombre(etiqueta: str) -> str:
    return f"{PREFIJO}{etiqueta}-{uuid.uuid4().hex[:8]}"


async def _limpiar(motor: AsyncEngine) -> None:
    async with motor.begin() as conexion:
        await conexion.execute(
            text("DELETE FROM termino WHERE texto_normalizado LIKE :patron"),
            {"patron": f"{PREFIJO}%"},
        )


async def _crear_termino(
    motor: AsyncEngine, etiqueta: str, *, ultima: datetime | None, prioridad: int = 0
) -> uuid.UUID:
    texto = _nombre(etiqueta)
    async with motor.begin() as conexion:
        valor: Any = (
            await conexion.execute(
                text(
                    """
                    INSERT INTO termino (texto, texto_normalizado, origen, prioridad,
                                         ultima_ingesta_en)
                    VALUES (:texto, :normalizado, 'usuario', :prioridad, :ultima)
                    RETURNING id
                    """
                ),
                {
                    "texto": texto,
                    "normalizado": texto.lower(),
                    "prioridad": prioridad,
                    "ultima": ultima,
                },
            )
        ).scalar_one()
    return valor if isinstance(valor, uuid.UUID) else uuid.UUID(str(valor))


async def _crear_muchos(motor: AsyncEngine, cuantos: int) -> list[uuid.UUID]:
    return [await _crear_termino(motor, f"tope{i:02d}", ultima=None) for i in range(cuantos)]


async def _posiciones(motor: AsyncEngine) -> list[uuid.UUID]:
    """Cola completa, limitada a los términos que crea esta prueba."""
    pendientes = await RepositorioIngesta(motor).obtener_pendientes_de_ingesta(1000)
    return [
        fila["termino_id"]
        for fila in pendientes
        if str(fila["texto_normalizado"]).startswith(PREFIJO)
    ]


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    creado = create_async_engine(
        normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False),
        pool_pre_ping=True,
    )
    await _limpiar(creado)
    try:
        yield creado
    finally:
        await _limpiar(creado)
        await creado.dispose()


# --------------------------------------------------------------------------- #
# Orden de la cola
# --------------------------------------------------------------------------- #


async def test_lo_que_nunca_se_ha_buscado_va_primero(motor: AsyncEngine) -> None:
    reciente = await _crear_termino(motor, "reciente", ultima=AHORA)
    nunca = await _crear_termino(motor, "nunca", ultima=None)

    ids = await _posiciones(motor)
    assert ids.index(nunca) < ids.index(reciente)


async def test_entre_buscados_gana_el_mas_olvidado(motor: AsyncEngine) -> None:
    """Es la rotación: sin ella se buscarían siempre los mismos y otros no se buscarían nunca."""
    antiguo = await _crear_termino(motor, "antiguo", ultima=AHORA - timedelta(days=2))
    medio = await _crear_termino(motor, "medio", ultima=AHORA - timedelta(hours=5))
    nuevo = await _crear_termino(motor, "nuevo", ultima=AHORA)

    ids = await _posiciones(motor)
    assert ids.index(antiguo) < ids.index(medio) < ids.index(nuevo)


async def test_la_prioridad_no_puede_dejar_a_nadie_sin_turno(motor: AsyncEngine) -> None:
    """La urgencia por tiempo manda; la prioridad solo desempata.

    Si la prioridad mandara, un término urgente y otro tranquilo competirían y el segundo acabaría
    sin buscarse nunca. El producto no puede permitirse que un cliente se quede sin sus datos porque
    otro pagó por ir primero.
    """
    olvidado = await _crear_termino(motor, "olvidado", ultima=AHORA - timedelta(days=3))
    urgente = await _crear_termino(
        motor, "urgente", ultima=AHORA - timedelta(minutes=1), prioridad=10
    )

    ids = await _posiciones(motor)
    assert ids.index(olvidado) < ids.index(urgente)


async def test_el_conteo_de_suscriptores_funciona_sin_contexto_de_negocio(
    motor: AsyncEngine,
) -> None:
    """La cola corre sin contexto, así que el conteo atraviesa RLS devolviendo solo un número."""
    primero = await _crear_termino(motor, "popular", ultima=None)

    pendientes = await RepositorioIngesta(motor).obtener_pendientes_de_ingesta(1000)
    por_id = {fila["termino_id"]: fila for fila in pendientes}

    assert por_id[primero]["suscriptores"] == 0


async def test_los_suscriptores_de_varios_terminos_se_leen_de_una_vez(motor: AsyncEngine) -> None:
    """La consulta en lote, contra la base de verdad.

    Es la que sustituye al N+1 que tardaba segundos en pintar la lista de palabras clave. Se
    comprueba con identificadores que existen y con uno inventado, porque lo que puede fallar de una
    consulta en lote es justo el caso raro: un identificador que no está, o una lista vacía.
    """
    primero = await _crear_termino(motor, "lote uno", ultima=None)
    segundo = await _crear_termino(motor, "lote dos", ultima=None)
    inventado = uuid.uuid4()

    leidos = await RepositorioTerminosBd(motor).suscriptores_de([primero, segundo, inventado])

    # Los tres aparecen, y el inventado con cero. **Esto no es un descuido**: se preguntó por él y
    # se responde, en lugar de devolver un mapa al que le falta una clave y obligar a quien consulta
    # a tratar la ausencia. Un término que se borre entre que se lee el listado y se piden los
    # conteos —o un identificador mal formado que llegue de fuera— no puede tumbar la pantalla.
    assert leidos == {primero: 0, segundo: 0, inventado: 0}


async def test_una_lista_vacia_de_identificadores_no_consulta_nada(motor: AsyncEngine) -> None:
    """Sin identificadores, la respuesta es un mapa vacío y no una ida y vuelta a la base."""
    assert await RepositorioTerminosBd(motor).suscriptores_de([]) == {}


# --------------------------------------------------------------------------- #
# La marca que hace rotar la cola
# --------------------------------------------------------------------------- #


async def test_marcar_como_buscado_actualiza_la_cola(motor: AsyncEngine) -> None:
    """Sin esta marca, `ultima_ingesta_en` se queda nulo y la cola siempre devuelve lo mismo."""
    repositorio = RepositorioIngesta(motor)
    primero = await _crear_termino(motor, "primero", ultima=None)
    segundo = await _crear_termino(motor, "segundo", ultima=None)

    assert await repositorio.marcar_terminos_ingestados([primero, segundo], AHORA) == 2

    pendientes = await repositorio.obtener_pendientes_de_ingesta(1000)
    por_id = {fila["termino_id"]: fila for fila in pendientes}
    assert por_id[primero]["ultima_ingesta_en"] is not None
    assert por_id[segundo]["ultima_ingesta_en"] is not None


async def test_un_termino_agregado_despues_entra_por_delante(motor: AsyncEngine) -> None:
    """Es exactamente el caso que pidió cubrir el cliente: una palabra clave nueva.

    Todo lo ya buscado queda detrás, así que el término recién agregado se atiende en el ciclo
    siguiente, no «algún día».
    """
    buscados = [
        await _crear_termino(motor, f"previo{i}", ultima=AHORA - timedelta(minutes=i + 1))
        for i in range(3)
    ]
    recien = await _crear_termino(motor, "recien", ultima=None)

    ids = await _posiciones(motor)
    assert ids.index(recien) < min(ids.index(previo) for previo in buscados)


async def test_con_mas_terminos_que_el_tope_ninguno_se_queda_sin_turno(motor: AsyncEngine) -> None:
    """Con 25 términos y un tope de 20 por ciclo, todos pasan en dos ciclos.

    Lo que **no** puede pasar es que alguno espere para siempre, que era justo el defecto anterior.
    La comprobación se hace solo sobre los términos de esta prueba, porque el catálogo real puede
    contener otros que también compiten por el turno.
    """
    repositorio = RepositorioIngesta(motor)
    await _crear_muchos(motor, 25)

    primera = await _posiciones(motor)
    assert len(primera) == 25
    await repositorio.marcar_terminos_ingestados(primera[:20], AHORA)

    # Los cinco que no recibieron turno pasan ahora por delante de los veinte ya atendidos.
    despues = await _posiciones(motor)
    assert set(despues[:5]) == set(primera[20:])


async def test_marcar_sin_terminos_no_es_un_error(motor: AsyncEngine) -> None:
    assert await RepositorioIngesta(motor).marcar_terminos_ingestados([], AHORA) == 0
