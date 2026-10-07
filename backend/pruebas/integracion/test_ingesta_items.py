"""Pruebas del desglose del producto contra una base real.

El desglose se escribe en la **misma** sentencia que el registro, y ahí hay una guarda que no se
puede comprobar de otra manera: una lista vacía de ítems **no borra** lo que ya hubiera. La misma
fila la escriben tres caminos distintos —la importación mensual, que trae el desglose; el listado
paginado y la vigilancia del listado, que no lo traen— y sin la guarda el último en pasar dejaría el
detalle en blanco. Es un fallo que no da error y que la persona ve como «a este proceso le falta la
información», semanas después de que ocurriera.

Requiere una base real: ejecutar con `PRUEBAS_INTEGRACION=1`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import DefinicionFuente, ejecutar_ciclo
from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import RepositorioIngesta
from contratacion.infraestructura.adaptadores.salida.bd.sesion import normalizar_url_bd
from contratacion.infraestructura.config.ajustes import obtener_ajustes

pytestmark = pytest.mark.skipif(
    os.getenv("PRUEBAS_INTEGRACION") != "1",
    reason="Requiere una base real: ejecutar con PRUEBAS_INTEGRACION=1",
)

CODIGO = "PRUEBA_ITEMS"

MAPEOS: tuple[dict[str, Any], ...] = (
    {
        "clave_cruda": "id",
        "campo_canonico": "codigo",
        "etiqueta": "Código",
        "tipo_dato": "texto",
        "requerido": True,
    },
    {
        "clave_cruda": "objeto",
        "campo_canonico": "objeto_compra",
        "etiqueta": "Objeto",
        "tipo_dato": "texto",
    },
)

ITEM: dict[str, Any] = {
    "numero": 1,
    "codigo": "832110112",
    "descripcion_cpc": "SERVICIO DE CONSULTORIA EN INGENIERIA SANITARIA AMBIENTAL",
    "descripcion": "CONSULTORIA AMBIENTAL PARA LA PLANTA DE TRATAMIENTO",
    "unidad": "Unidad",
    "cantidad": "1",
}


class FuenteFalsa:
    """Cumple el puerto `FuenteExterna` sin salir a la red."""

    codigo = CODIGO

    def __init__(self, registros: Sequence[dict[str, Any]]) -> None:
        self.registros = list(registros)

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        presupuesto.consumir()
        return ResultadoExtraccion(registros=list(self.registros), peticiones=1)

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        valor = str(crudo.get("id") or "").strip()
        return valor or None

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        return ()


class CacheNula:
    """Sin caché: aquí se prueba lo que queda escrito, no lo que se sirve."""

    habilitada = False

    async def obtener(self, clave: str) -> str | None:
        return None

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return None

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        return None

    async def eliminar(self, clave: str) -> None:
        return None

    async def incrementar(self, clave: str) -> int:
        return 1

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


def _registro(identificador: str, *, con_items: bool, objeto: str = "Obra") -> dict[str, Any]:
    registro: dict[str, Any] = {"id": identificador, "objeto": objeto}
    if con_items:
        # El guion delante es la convención del adaptador para lo que no es un campo canónico: el
        # desglose no tiene columna en `datos`, se guarda en la suya.
        registro["_items"] = [ITEM]
    return registro


async def _limpiar(motor: AsyncEngine) -> None:
    async with motor.begin() as conexion:
        await conexion.execute(
            text(
                "DELETE FROM registro_historial WHERE registro_id IN ("
                "  SELECT id FROM registro WHERE fuente_id IN ("
                "    SELECT id FROM fuente WHERE codigo = :codigo))"
            ),
            {"codigo": CODIGO},
        )
        await conexion.execute(
            text("DELETE FROM fuente WHERE codigo = :codigo"), {"codigo": CODIGO}
        )


async def _ciclo(motor: AsyncEngine, registros: Sequence[dict[str, Any]]) -> Any:
    definicion = DefinicionFuente(
        codigo=CODIGO,
        nombre="Fuente de prueba",
        endpoint_base="http://localhost/prueba",
        adaptador=FuenteFalsa(registros),
        mapeos_por_defecto=MAPEOS,
    )
    return await ejecutar_ciclo(
        definicion,
        RepositorioIngesta(motor),
        CacheNula(),
        intervalo_min=15,
        ventana_solape_ciclos=2,
        presupuesto_peticiones=10,
    )


async def _valor(motor: AsyncEngine, sql: str, **parametros: Any) -> Any:
    async with motor.connect() as conexion:
        return (await conexion.execute(text(sql), parametros)).scalar_one()


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_normalizar(), pool_pre_ping=True)
    await _limpiar(engine)
    try:
        yield engine
    finally:
        await _limpiar(engine)
        await engine.dispose()


def _normalizar() -> str:
    return normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False)


async def test_los_items_se_guardan_con_sus_codigos_y_su_texto_de_busqueda(
    motor: AsyncEngine,
) -> None:
    """El desglose llega a la tabla y, con él, los dos campos con los que se filtra.

    `cpc_busqueda` y `cpc_codigos` se calculan con las funciones del dominio que ya usan las
    ínfimas: es lo que hace que el buscador por clasificación encuentre una oferta igual que
    encuentra una necesidad, sin una segunda regla que se pueda separar.
    """
    await _ciclo(motor, [_registro("A", con_items=True)])

    assert (
        await _valor(
            motor, "SELECT jsonb_array_length(items) FROM registro WHERE clave_natural = 'A'"
        )
        == 1
    )
    assert await _valor(motor, "SELECT cpc_codigos FROM registro WHERE clave_natural = 'A'") == [
        "832110112"
    ]
    texto_cpc = await _valor(motor, "SELECT cpc_busqueda FROM registro WHERE clave_natural = 'A'")
    assert "832110112" in texto_cpc
    assert "consultoria en ingenieria sanitaria ambiental" in texto_cpc
    # La descripción libre **no** entra en el texto de búsqueda: es justo la parte que el CPC
    # viene a sustituir, y meterla devolvería el problema que la clasificación resuelve.
    assert "planta de tratamiento" not in texto_cpc
    assert await _valor(
        motor, "SELECT items_recogidos_en IS NOT NULL FROM registro WHERE clave_natural = 'A'"
    )


async def test_una_vuelta_sin_items_no_borra_los_que_ya_estaban(motor: AsyncEngine) -> None:
    """La guarda que evita el fallo silencioso.

    La misma fila la escriben tres caminos: la importación mensual trae el desglose, el listado
    paginado y la vigilancia del listado no. Sin la guarda, el primero que pasara después dejaría el
    detalle en blanco sin ningún error.
    """
    await _ciclo(motor, [_registro("A", con_items=True)])
    await _ciclo(motor, [_registro("A", con_items=False)])

    assert (
        await _valor(
            motor, "SELECT jsonb_array_length(items) FROM registro WHERE clave_natural = 'A'"
        )
        == 1
    )
    assert await _valor(motor, "SELECT cpc_codigos FROM registro WHERE clave_natural = 'A'") == [
        "832110112"
    ]


async def test_una_fila_sin_cambios_pero_con_items_se_escribe_y_no_deja_historial(
    motor: AsyncEngine,
) -> None:
    """El relleno del desglose de un año ya importado.

    El desglose **no entra en la huella** —`hash_contenido` mira `datos`—, así que una fila sin
    ítems y esa misma fila con ellos tienen la misma huella. Si el ciclo se saltara las filas
    «iguales» sin mirar los ítems, reimportar el año no escribiría ni uno solo: se contaría todo
    como «igual» y el detalle seguiría vacío. Y tampoco puede contarse como actualización: el
    contenido no cambió, y meterla en el histórico convertiría esa tabla en un registro de visitas.
    """
    await _ciclo(motor, [_registro("A", con_items=False)])
    resultado = await _ciclo(motor, [_registro("A", con_items=True)])

    assert (resultado.nuevos, resultado.actualizados, resultado.iguales) == (0, 0, 1)
    assert (
        await _valor(
            motor, "SELECT jsonb_array_length(items) FROM registro WHERE clave_natural = 'A'"
        )
        == 1
    )
    assert (
        await _valor(
            motor,
            "SELECT count(*) FROM registro_historial h JOIN registro r ON r.id = h.registro_id "
            "WHERE r.clave_natural = 'A'",
        )
        == 0
    )


async def test_un_item_sin_codigo_no_se_guarda(motor: AsyncEngine) -> None:
    """Lo que `items_desde_crudos` tiraría al leer tampoco se escribe.

    Si se guardara, el contador de «cuántos ítems trae» mentiría en el panel y la fila parecería
    tener desglose sin tenerlo.
    """
    await _ciclo(
        motor,
        [
            _registro("A", con_items=False)
            | {"_items": [{"numero": 1, "codigo": "", "cantidad": "2"}]}
        ],
    )

    assert (
        await _valor(
            motor, "SELECT jsonb_array_length(items) FROM registro WHERE clave_natural = 'A'"
        )
        == 0
    )
    assert (
        await _valor(
            motor, "SELECT items_recogidos_en IS NULL FROM registro WHERE clave_natural = 'A'"
        )
        is True
    )
