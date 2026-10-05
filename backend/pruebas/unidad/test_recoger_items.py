"""Pruebas del relleno de ítems con CPC.

El caso de uso tiene una responsabilidad pequeña y dos formas de equivocarse que no dan la cara:

- **Marcar como leída una ficha que no se pudo leer.** Si un fallo de red se tratara como «esta
  necesidad no tiene detalle», esa necesidad no se reintentaría nunca y se quedaría buscándose solo
  por texto libre para siempre, sin un error que mirar.
- **Confundir «no tiene detalle» con «no se ha pedido».** Lo contrario: las necesidades sin tabla
  —que existen— se reintentarían en cada tanda, una petición perdida por ciclo y por necesidad,
  contra una fuente que limita la tasa.

Las dos se comprueban aquí, sin base de datos ni red, con dobles que implementan el puerto completo.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import DefinicionFuente
from contratacion.aplicacion.casos_uso.recoger_items import LIMITE_FICHAS_POR_CICLO, recoger_items
from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.cpc import ItemCpc
from contratacion.dominio.ingesta import Presupuesto

ITEM = ItemCpc(
    numero=1,
    codigo="871410032",
    descripcion_cpc="LAVADO Y ENGRASADO DE AUTOMOTORES",
    descripcion="Lavado, engrasado y pulverizado de la Volqueta 5 kodiak chevrolet",
    unidad="Unidad",
    cantidad="6.00",
)


class FuenteFalsa:
    """Fuente con ficha. Implementa los dos puertos completos.

    Los métodos que este caso de uso **no** debe usar lanzan `AssertionError` en lugar de devolver
    algo: si alguna vez se llamaran desde aquí, el relleno de ítems habría empezado a traer el
    listado, que es justo lo que no tiene que hacer.
    """

    codigo = "NCO"

    def __init__(self, respuestas: Sequence[tuple[ItemCpc, ...] | None] = ()) -> None:
        self.respuestas = list(respuestas)
        self.pedidos: list[str | None] = []

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        raise AssertionError("el relleno de ítems no debe pedir el listado")

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        raise AssertionError("el relleno de ítems no calcula claves naturales")

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        raise AssertionError("el relleno de ítems no reparte términos")

    async def items(
        self, enlace: str | None, presupuesto: Presupuesto
    ) -> tuple[ItemCpc, ...] | None:
        presupuesto.consumir()
        self.pedidos.append(enlace)
        return self.respuestas.pop(0) if self.respuestas else ()


class FuenteSinFicha:
    """Fuente que solo publica listado: no tiene el método `items`."""

    codigo = "OCDS"

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        raise AssertionError("este doble no se usa para extraer")

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        return None

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        return ()


class RepositorioFalso:
    """Doble del puerto de ítems. Anota lo que se le pide y lo que se le guarda."""

    def __init__(self, pendientes: Sequence[Mapping[str, Any]] = ()) -> None:
        self.pendientes = list(pendientes)
        self.pedidos: list[tuple[list[str], int]] = []
        self.guardados: dict[UUID, dict[str, Any]] = {}

    async def registros_sin_items(
        self, fuentes: Sequence[str], limite: int
    ) -> list[dict[str, Any]]:
        self.pedidos.append((list(fuentes), limite))
        return [dict(fila) for fila in self.pendientes[:limite]]

    async def contar_sin_items(self, fuentes: Sequence[str]) -> int:
        """Lo que falta de verdad: lo que ya se guardó deja de estar pendiente.

        Se calcula así y no devolviendo un número fijo para que las pruebas distingan «lo que falta»
        de «el sobrante de la tanda», que es exactamente el defecto que se corrigió.
        """
        return len([fila for fila in self.pendientes if fila["id"] not in self.guardados])

    async def guardar_items(
        self,
        registro_id: UUID,
        *,
        items: Sequence[Mapping[str, Any]],
        cpc_busqueda: str,
        cpc_codigos: Sequence[str],
    ) -> None:
        self.guardados[registro_id] = {
            "items": list(items),
            "cpc_busqueda": cpc_busqueda,
            "cpc_codigos": list(cpc_codigos),
        }


def _pendiente(enlace: str | None = "/NCO/NCORegistroDetalle.cpe?id=abc&op=0") -> dict[str, Any]:
    return {"id": uuid4(), "fuente": "NCO", "enlace": enlace}


def _definicion(adaptador: Any) -> DefinicionFuente:
    return DefinicionFuente(
        codigo=adaptador.codigo,
        nombre="Fuente de prueba",
        endpoint_base="https://www.compraspublicas.gob.ec/x.cpe",
        adaptador=adaptador,
    )


# --------------------------------------------------------------------------- #
# El camino que funciona
# --------------------------------------------------------------------------- #


async def test_guarda_los_items_y_su_texto_de_busqueda() -> None:
    fila = _pendiente()
    fuente = FuenteFalsa([(ITEM,)])
    repositorio = RepositorioFalso([fila])

    resultado = await recoger_items(repositorio, [_definicion(fuente)], presupuesto_peticiones=10)

    assert resultado.revisados == 1
    assert resultado.con_items == 1
    assert resultado.fallidos == 0
    assert resultado.peticiones == 1
    guardado = repositorio.guardados[fila["id"]]
    assert guardado["cpc_busqueda"] == "871410032 lavado y engrasado de automotores"
    assert guardado["cpc_codigos"] == ["871410032"]
    assert guardado["items"][0]["descripcion"].startswith("Lavado, engrasado")


async def test_usa_el_enlace_guardado_para_pedir_la_ficha() -> None:
    fila = _pendiente("/NCO/NCORegistroDetalle.cpe?id=xyz&op=0")
    fuente = FuenteFalsa([(ITEM,)])

    await recoger_items(RepositorioFalso([fila]), [_definicion(fuente)], presupuesto_peticiones=10)

    assert fuente.pedidos == ["/NCO/NCORegistroDetalle.cpe?id=xyz&op=0"]


# --------------------------------------------------------------------------- #
# Los dos fallos que no dan la cara
# --------------------------------------------------------------------------- #


async def test_un_fallo_de_la_fuente_no_marca_la_ficha_como_leida() -> None:
    """Se queda pendiente: si se diera por leída, esa necesidad no se reintentaría jamás."""
    fila = _pendiente()
    repositorio = RepositorioFalso([fila])

    resultado = await recoger_items(
        repositorio, [_definicion(FuenteFalsa([None]))], presupuesto_peticiones=10
    )

    assert resultado.fallidos == 1
    assert resultado.revisados == 1
    assert repositorio.guardados == {}


async def test_una_necesidad_sin_detalle_se_marca_como_leida() -> None:
    """Hay necesidades publicadas sin tabla; reintentarlas sería una petición perdida por ciclo."""
    fila = _pendiente()
    repositorio = RepositorioFalso([fila])

    resultado = await recoger_items(
        repositorio, [_definicion(FuenteFalsa([()]))], presupuesto_peticiones=10
    )

    assert resultado.sin_items == 1
    assert resultado.con_items == 0
    assert repositorio.guardados[fila["id"]]["items"] == []
    assert repositorio.guardados[fila["id"]]["cpc_busqueda"] == ""


# --------------------------------------------------------------------------- #
# Presupuesto y fuentes
# --------------------------------------------------------------------------- #


async def test_el_presupuesto_corta_la_tanda() -> None:
    """El tope es de **peticiones**: pasarse no solo tarda, además gasta la cuota de todos."""
    fuente = FuenteFalsa([(ITEM,)] * 10)
    repositorio = RepositorioFalso([_pendiente() for _ in range(10)])

    resultado = await recoger_items(repositorio, [_definicion(fuente)], presupuesto_peticiones=3)

    assert resultado.revisados == 3
    assert resultado.peticiones == 3
    assert len(fuente.pedidos) == 3
    assert resultado.quedan == 7


async def test_lo_que_queda_es_el_total_pendiente_y_no_el_sobrante_de_la_tanda() -> None:
    """El aviso tiene que decir cuánto falta del relleno entero.

    Antes decía el sobrante de la tanda —la diferencia entre lo que se pidió y lo que cupo en el
    presupuesto—, que en el caso normal vale **cero**: el registro del worker anunciaba «0
    pendientes» con el relleno a medias, que es peor que no decir nada.
    """
    fuente = FuenteFalsa([(ITEM,)] * 10)
    repositorio = RepositorioFalso([_pendiente() for _ in range(10)])

    resultado = await recoger_items(repositorio, [_definicion(fuente)], presupuesto_peticiones=4)

    # Cupo todo lo que se pidió, así que no sobró nada de la tanda… y aun así faltan seis.
    assert resultado.revisados == 4
    assert resultado.quedan == 6


async def test_una_ficha_que_no_se_pudo_leer_sigue_contando_como_pendiente() -> None:
    fuente = FuenteFalsa([None, (ITEM,)])
    repositorio = RepositorioFalso([_pendiente(), _pendiente()])

    resultado = await recoger_items(repositorio, [_definicion(fuente)], presupuesto_peticiones=10)

    assert resultado.fallidos == 1
    assert resultado.quedan == 1


async def test_no_pide_fichas_de_fuentes_que_no_las_tienen() -> None:
    """Preguntar por una ficha que no existe gastaría una petición del presupuesto común."""
    repositorio = RepositorioFalso([_pendiente()])

    resultado = await recoger_items(
        repositorio,
        [_definicion(FuenteSinFicha())],
        presupuesto_peticiones=10,
    )

    assert resultado.revisados == 0
    assert repositorio.pedidos == []


async def test_solo_pide_los_registros_de_las_fuentes_con_ficha() -> None:
    repositorio = RepositorioFalso([_pendiente()])

    await recoger_items(
        repositorio,
        [_definicion(FuenteFalsa([(ITEM,)])), _definicion(FuenteSinFicha())],
        presupuesto_peticiones=10,
    )

    assert repositorio.pedidos == [(["NCO"], LIMITE_FICHAS_POR_CICLO)]


async def test_un_limite_de_cero_desactiva_la_lectura() -> None:
    fuente = FuenteFalsa([(ITEM,)])
    repositorio = RepositorioFalso([_pendiente()])

    resultado = await recoger_items(
        repositorio, [_definicion(fuente)], presupuesto_peticiones=10, limite=0
    )

    assert resultado.revisados == 0
    assert repositorio.pedidos == []
