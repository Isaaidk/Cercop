"""Pruebas de la lista de términos de CPC de un negocio.

Lo que se protege aquí es que **la regla del servidor sea la misma que la de la pantalla**, que es
lo único que hace fiable el contador que ve la persona antes de pulsar: si el panel dice «se van a
añadir 3» y el servidor guarda 5, el aviso sobra. Por eso se comprueban los mismos casos que en el
navegador: separadores de hoja de cálculo, términos repetidos y términos demasiado cortos.

También se fija la deduplicación: repetir algo que ya está **no es un error** —es la respuesta a
«añade esto», que a veces ya está— pero tiene que contarse, porque el recuento se le enseña a quien
lo pidió.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_cpc import agregar, limpiar, listar, quitar
from contratacion.aplicacion.puertos.cpc import ClaveCpc
from contratacion.dominio.palabras import normalizar_termino

NEGOCIO = uuid4()
USUARIO = uuid4()
ACTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="consultor")
AHORA = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _clave(texto: str) -> ClaveCpc:
    return ClaveCpc(id=uuid4(), texto=texto, creado_en=AHORA)


class RepositorioFalso:
    """Doble del puerto. Guarda por forma normalizada, como la clave única de la tabla."""

    def __init__(self, guardadas: Sequence[str] = ()) -> None:
        self.guardadas: dict[str, str] = {normalizar_termino(t): t for t in guardadas}
        self.altas: list[str] = []
        self.negocios: list[UUID] = []

    async def listar(self, *, negocio_id: UUID) -> tuple[ClaveCpc, ...]:
        del negocio_id
        return tuple(_clave(texto) for texto in self.guardadas.values())

    async def agregar(
        self,
        *,
        negocio_id: UUID,
        texto: str,
        texto_normalizado: str,
        creado_por: UUID | None,
        momento: datetime,
    ) -> bool:
        del creado_por, momento
        self.negocios.append(negocio_id)
        if texto_normalizado in self.guardadas:
            return False
        self.altas.append(texto)
        self.guardadas[texto_normalizado] = texto
        return True

    async def quitar(self, *, negocio_id: UUID, texto_normalizado: str) -> bool:
        self.negocios.append(negocio_id)
        return self.guardadas.pop(texto_normalizado, None) is not None

    async def limpiar(self, *, negocio_id: UUID) -> int:
        self.negocios.append(negocio_id)
        cuantas = len(self.guardadas)
        self.guardadas.clear()
        return cuantas


# --------------------------------------------------------------------------- #
# Alta
# --------------------------------------------------------------------------- #


async def test_guarda_la_lista_pegada_de_golpe() -> None:
    repositorio = RepositorioFalso()

    resultado = await agregar(
        ACTOR, textos=["lavado, engrasado; 871410032"], repositorio=repositorio
    )

    assert resultado.agregadas == ("lavado", "engrasado", "871410032")
    assert resultado.repetidas == 0
    assert resultado.cortas == 0
    assert repositorio.altas == ["lavado", "engrasado", "871410032"]


async def test_separa_por_los_mismos_separadores_que_la_pantalla() -> None:
    """Comas, punto y coma y saltos de línea: lo que sale al copiar de una hoja de cálculo."""
    repositorio = RepositorioFalso()

    resultado = await agregar(ACTOR, textos=["lavado\naseo, 871410032"], repositorio=repositorio)

    assert resultado.agregadas == ("lavado", "aseo", "871410032")


async def test_los_terminos_cortos_se_descartan_y_se_cuentan() -> None:
    """Un término de dos letras no se puede buscar, así que no se guarda; pero se dice."""
    repositorio = RepositorioFalso()

    resultado = await agregar(ACTOR, textos=["lavado, de, aseo"], repositorio=repositorio)

    assert resultado.agregadas == ("lavado", "aseo")
    assert resultado.cortas == 1
    assert "de" not in repositorio.guardadas.values()


async def test_lo_que_ya_estaba_cuenta_como_repetido() -> None:
    repositorio = RepositorioFalso(guardadas=["lavado"])

    resultado = await agregar(ACTOR, textos=["lavado", "aseo"], repositorio=repositorio)

    assert resultado.agregadas == ("aseo",)
    assert resultado.repetidas == 1


async def test_el_mismo_termino_dos_veces_en_la_peticion_es_una_sola_alta() -> None:
    """Pegar una lista con un término repetido no puede provocar dos escrituras ni un error."""
    repositorio = RepositorioFalso()

    resultado = await agregar(ACTOR, textos=["lavado, lavado, LAVADO"], repositorio=repositorio)

    assert resultado.agregadas == ("lavado",)
    assert resultado.repetidas == 2
    assert repositorio.altas == ["lavado"]


async def test_la_mayuscula_y_el_acento_no_crean_dos_terminos() -> None:
    """«LAVADO», «Lavado» y «lavado» son el mismo filtro: se reducen al mismo término."""
    repositorio = RepositorioFalso(guardadas=["lavado"])

    resultado = await agregar(ACTOR, textos=["LAVADO"], repositorio=repositorio)

    assert resultado.agregadas == ()
    assert resultado.repetidas == 1


async def test_una_lista_vacia_no_escribe_nada() -> None:
    repositorio = RepositorioFalso()

    resultado = await agregar(ACTOR, textos=["", "   ", "de"], repositorio=repositorio)

    assert resultado.agregadas == ()
    assert resultado.cortas == 1
    assert repositorio.altas == []


async def test_todo_se_guarda_en_el_negocio_de_quien_lo_pide() -> None:
    """El aislamiento no depende de que la consulta se acuerde: la empresa va desde el actor."""
    repositorio = RepositorioFalso()

    await agregar(ACTOR, textos=["lavado"], repositorio=repositorio)

    assert repositorio.negocios == [NEGOCIO]


# --------------------------------------------------------------------------- #
# Quitar y vaciar
# --------------------------------------------------------------------------- #


async def test_quitar_encuentra_el_termino_aunque_cambie_la_grafia() -> None:
    """Se quita por la forma normalizada, así que «LAVADO» quita «lavado» sin pedir la grafía."""
    repositorio = RepositorioFalso(guardadas=["LAVADO"])

    assert await quitar(ACTOR, texto="lavado", repositorio=repositorio) is True
    assert repositorio.guardadas == {}


async def test_quitar_algo_que_no_esta_no_es_un_error() -> None:
    repositorio = RepositorioFalso()

    assert await quitar(ACTOR, texto="lavado", repositorio=repositorio) is False


async def test_vaciar_devuelve_cuantos_habia() -> None:
    repositorio = RepositorioFalso(guardadas=["lavado", "aseo"])

    assert await limpiar(ACTOR, repositorio=repositorio) == 2
    assert repositorio.guardadas == {}


async def test_la_lista_se_lee_desde_el_repositorio() -> None:
    """Devuelve los textos y no las filas: al panel le llega la lista, no el registro entero."""

    class ConFilas(RepositorioFalso):
        async def listar(self, *, negocio_id: UUID) -> tuple[ClaveCpc, ...]:
            del negocio_id
            return (_clave("lavado"), _clave("aseo"))

    assert await listar(ACTOR, repositorio=ConFilas()) == ("lavado", "aseo")
