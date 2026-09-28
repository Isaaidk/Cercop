"""Pruebas del ciclo de ingesta contra una base real, con una fuente falsa.

La fuente falsa es posible gracias al puerto `FuenteExterna`: permite probar la cadena completa
—mapeo, clasificación, escritura, historial, invalidación de caché— sin tocar la red ni gastar cuota
del SERCOP. Es también lo que demuestra que la ingesta no depende de que la fuente esté disponible
para poder verificarse.

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

CODIGO = "PRUEBA"
INTERVALO_MIN = 15
SOLAPE_CICLOS = 2
PRESUPUESTO = 10

MAPEOS: tuple[dict[str, Any], ...] = (
    {
        "clave_cruda": "id",
        "campo_canonico": "codigo",
        "etiqueta": "Código",
        "tipo_dato": "texto",
        "requerido": True,
    },
    {
        "clave_cruda": "estado",
        "campo_canonico": "estado",
        "etiqueta": "Estado",
        "tipo_dato": "texto",
    },
    {
        "clave_cruda": "fecha",
        "campo_canonico": "fecha_publicacion",
        "etiqueta": "Fecha",
        "tipo_dato": "fecha_hora",
    },
    {
        "clave_cruda": "objeto",
        "campo_canonico": "objeto_compra",
        "etiqueta": "Objeto",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "html_a_texto"},
    },
)


def _registro_base(identificador: str, estado: str = "En Curso") -> dict[str, Any]:
    return {
        "id": identificador,
        "estado": estado,
        "fecha": "2026-09-27 10:00:00",
        "objeto": f"<b>Obra {identificador}</b><br/>Vías",
    }


class FuenteFalsa:
    """Cumple el puerto `FuenteExterna` sin salir a la red."""

    codigo = CODIGO

    def __init__(
        self,
        registros: Sequence[dict[str, Any]],
        *,
        parcial: bool = False,
        avisos: Sequence[str] = (),
    ) -> None:
        self.registros = list(registros)
        self.parcial = parcial
        self.avisos = list(avisos)
        self.desde_recibido: datetime | None = None

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        self.desde_recibido = desde
        presupuesto.consumir()
        return ResultadoExtraccion(
            registros=list(self.registros),
            avisos=list(self.avisos),
            peticiones=1,
            parcial=self.parcial,
        )

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        valor = str(crudo.get("id") or "").strip()
        return valor or None

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        return ()


class CacheEspia:
    """Registra los incrementos para poder comprobar la invalidación."""

    def __init__(self) -> None:
        self.incrementos: list[str] = []

    async def obtener(self, clave: str) -> str | None:
        return None

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        return None

    async def eliminar(self, clave: str) -> None:
        return None

    async def incrementar(self, clave: str) -> int:
        self.incrementos.append(clave)
        return len(self.incrementos)

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


def _url() -> str:
    return normalizar_url_bd(obtener_ajustes().database_url).render_as_string(hide_password=False)


async def _limpiar(motor: AsyncEngine) -> None:
    """Borra todo lo que dejó la fuente de prueba.

    El histórico no tiene clave foránea (el registro puede desaparecer antes que su historia), así
    que hay que borrarlo explícitamente.
    """
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


async def _escalar(motor: AsyncEngine, sql: str, **parametros: Any) -> int:
    async with motor.connect() as conexion:
        return int((await conexion.execute(text(sql), parametros)).scalar_one())


async def _valor(motor: AsyncEngine, sql: str, **parametros: Any) -> Any:
    """Devuelve el valor tal cual, sin convertirlo: sirve para identificadores y fechas."""
    async with motor.connect() as conexion:
        return (await conexion.execute(text(sql), parametros)).scalar_one()


async def _definicion(registros: Sequence[dict[str, Any]], **extra: Any) -> DefinicionFuente:
    return DefinicionFuente(
        codigo=CODIGO,
        nombre="Fuente de prueba",
        endpoint_base="http://localhost/prueba",
        adaptador=FuenteFalsa(registros, **extra),
        mapeos_por_defecto=MAPEOS,
    )


async def _ciclo(
    repositorio: RepositorioIngesta, definicion: DefinicionFuente, cache: CacheEspia
) -> Any:
    return await ejecutar_ciclo(
        definicion,
        repositorio,
        cache,
        intervalo_min=INTERVALO_MIN,
        ventana_solape_ciclos=SOLAPE_CICLOS,
        presupuesto_peticiones=PRESUPUESTO,
    )


@pytest.fixture
async def motor() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(_url(), pool_pre_ping=True)
    await _limpiar(engine)
    try:
        yield engine
    finally:
        await _limpiar(engine)
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Idempotencia
# --------------------------------------------------------------------------- #


async def test_el_ciclo_es_idempotente(motor: AsyncEngine) -> None:
    """Ejecutar dos veces el mismo ciclo no duplica ni crea historial falso.

    Es la propiedad que permite solapar ventanas sin miedo y reintentar tras un fallo.
    """
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()
    registros = [_registro_base("A"), _registro_base("B")]
    definicion = await _definicion(registros)

    primero = await _ciclo(repositorio, definicion, cache)
    assert (primero.nuevos, primero.actualizados, primero.iguales) == (2, 0, 0)

    segundo = await _ciclo(repositorio, definicion, cache)
    assert (segundo.nuevos, segundo.actualizados, segundo.iguales) == (0, 0, 2)

    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro WHERE clave_natural IN ('A', 'B')",
        )
        == 2
    )
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro_historial h JOIN registro r ON r.id = h.registro_id "
            "WHERE r.clave_natural IN ('A', 'B')",
        )
        == 0
    )


async def test_detecta_cambios_y_guarda_historial(motor: AsyncEngine) -> None:
    """Un cambio real se registra como actualización y deja una versión en el histórico.

    Es el activo comercial: la fuente no publica histórico de necesidades, así que lo que no se
    guarde aquí se pierde para siempre.
    """
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()

    await _ciclo(repositorio, await _definicion([_registro_base("A")]), cache)
    resultado = await _ciclo(
        repositorio, await _definicion([_registro_base("A", estado="Finalizada")]), cache
    )

    assert (resultado.nuevos, resultado.actualizados, resultado.iguales) == (0, 1, 0)
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro_historial h JOIN registro r ON r.id = h.registro_id "
            "WHERE r.clave_natural = 'A'",
        )
        == 1
    )
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro WHERE clave_natural = 'A' "
            "AND datos ->> 'estado' = 'Finalizada'",
        )
        == 1
    )


# --------------------------------------------------------------------------- #
# Mapeo automático
# --------------------------------------------------------------------------- #


async def test_un_campo_nuevo_queda_pendiente_sin_perder_el_crudo(motor: AsyncEngine) -> None:
    """Si la fuente publica una columna desconocida, no se descarta: se avisa y se conserva."""
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()
    registro = _registro_base("C")
    registro["campo_recien_publicado"] = "valor importante"

    resultado = await _ciclo(repositorio, await _definicion([registro]), cache)

    assert resultado.sin_mapear == 1
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM campo_pendiente WHERE clave_cruda = 'campo_recien_publicado'",
        )
        == 1
    )
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro WHERE clave_natural = 'C' "
            "AND crudo ->> 'campo_recien_publicado' = 'valor importante'",
        )
        == 1
    )


async def test_resolver_un_pendiente_puebla_el_campo_en_el_siguiente_ciclo(
    motor: AsyncEngine,
) -> None:
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()
    registro = _registro_base("D")
    registro["campo_recien_publicado"] = "valor importante"

    await _ciclo(repositorio, await _definicion([registro]), cache)

    # Un administrador resuelve el pendiente añadiendo la regla.
    fuente_id = await _valor(motor, "SELECT id FROM fuente WHERE codigo = :codigo", codigo=CODIGO)
    async with motor.begin() as conexion:
        await conexion.execute(
            text(
                "INSERT INTO campo_mapeo "
                "(fuente_id, clave_cruda, campo_canonico, etiqueta, tipo_dato) "
                "VALUES (:fuente, 'campo_recien_publicado', 'campo_nuevo', 'Campo nuevo', 'texto')"
            ),
            {"fuente": fuente_id},
        )

    resultado = await _ciclo(repositorio, await _definicion([registro]), cache)

    assert resultado.sin_mapear == 0
    assert resultado.actualizados == 1
    assert (
        await _escalar(
            motor,
            "SELECT count(*) FROM registro WHERE clave_natural = 'D' "
            "AND datos ->> 'campo_nuevo' = 'valor importante'",
        )
        == 1
    )


# --------------------------------------------------------------------------- #
# Fallos parciales y caché
# --------------------------------------------------------------------------- #


async def test_si_el_ciclo_es_parcial_la_marca_de_agua_no_avanza(motor: AsyncEngine) -> None:
    """Un fallo no debe dejar un hueco: el siguiente ciclo vuelve a cubrir lo pendiente."""
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()

    await _ciclo(repositorio, await _definicion([_registro_base("E")]), cache)
    assert (
        await _valor(
            motor,
            "SELECT max(s.watermark_fecha) FROM sincronizacion s "
            "JOIN fuente f ON f.id = s.fuente_id "
            "WHERE f.codigo = :codigo AND s.estado = 'ok'",
            codigo=CODIGO,
        )
        is not None
    )

    marca_antes = await _valor(
        motor,
        "SELECT s.watermark_fecha FROM sincronizacion s JOIN fuente f ON f.id = s.fuente_id "
        "WHERE f.codigo = :codigo AND s.estado = 'ok' "
        "ORDER BY s.iniciada_en DESC LIMIT 1",
        codigo=CODIGO,
    )

    parcial = await _ciclo(
        repositorio,
        await _definicion([_registro_base("F")], parcial=True, avisos=["La fuente no respondió."]),
        cache,
    )
    assert parcial.estado == "parcial"

    marca_parcial = await _valor(
        motor,
        "SELECT s.watermark_fecha FROM sincronizacion s JOIN fuente f ON f.id = s.fuente_id "
        "WHERE f.codigo = :codigo AND s.estado = 'parcial' "
        "ORDER BY s.iniciada_en DESC LIMIT 1",
        codigo=CODIGO,
    )
    # La marca no avanza: el siguiente ciclo vuelve a cubrir lo que quedó pendiente.
    assert marca_parcial == marca_antes


async def test_la_generacion_de_cache_solo_sube_cuando_hay_cambios(motor: AsyncEngine) -> None:
    """Invalidar la caché en cada ciclo sin cambios sería tirar trabajo ya hecho.

    Se suben dos contadores y no uno: el propio de la fuente, que invalida lo que solo depende de
    ella, y el global, que invalida las búsquedas. Hace falta el segundo porque una consulta puede
    abarcar varias fuentes a la vez y no se puede saber cuáles toca cada página que quedó cacheada.
    """
    repositorio = RepositorioIngesta(motor)
    cache = CacheEspia()
    registros = [_registro_base("G")]
    esperado = [f"generacion:{CODIGO}", "generacion:global"]

    await _ciclo(repositorio, await _definicion(registros), cache)
    assert cache.incrementos == esperado

    await _ciclo(repositorio, await _definicion(registros), cache)
    assert cache.incrementos == esperado
