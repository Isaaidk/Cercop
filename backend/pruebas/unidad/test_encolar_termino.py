"""Pruebas de la baja de una palabra clave y del re-encolado al volver a agregarla.

Existen por un defecto que se reportó como «el filtro no permite borrar y volver a poner la misma
palabra»: el panel podía deseleccionar una palabra —dejar de filtrar por ella— pero **no darla de
baja**, así que la suscripción seguía activa y el alta siguiente contestaba «ya se consultó hace
poco», que se lee como «ya estaba puesta».

Dos piezas lo arreglan y las dos se prueban aquí:

- `quitar_termino`, que sí desactiva la suscripción (el método `desuscribir` del repositorio existía
  desde el principio, pero ningún endpoint lo llamaba).
- `agregar_termino`, que vuelve a encolar una suscripción **nueva o reactivada** aunque la última
  consulta del término —del catálogo global de todos los negocios— sea de un minuto antes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.encolar_termino import (
    AVISO_EN_COLA,
    AVISO_RECIENTE,
    agregar_termino,
    quitar_termino,
)

AHORA = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
TERMINO_ID = UUID("33333333-3333-3333-3333-333333333333")
INTERVALO_MIN = 15
MAXIMO_TERMINOS = 40

ACTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="consultor")


class TerminosFalsos:
    """Repositorio en memoria con las dos operaciones que se prueban.

    Los demás métodos del puerto se declaran **todos** y lanzan: mypy también revisa las pruebas, y
    un doble al que le falte un método no falla al escribirlo, falla el día que alguien lo usa.
    Declararlos convierte el doble en una red que avisa de una llamada inesperada.
    """

    def __init__(self, *, alta: Mapping[str, Any] | None = None, baja: bool = True) -> None:
        self._alta = dict(alta or {})
        self._baja = baja
        self.desuscripciones: list[tuple[UUID, UUID]] = []

    async def alta_de_termino(
        self, negocio_id: UUID, *, texto: str, maximo_terminos: int, origen: str = "usuario"
    ) -> Mapping[str, Any]:
        return self._alta

    async def desuscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        self.desuscripciones.append((negocio_id, termino_id))
        return self._baja

    async def asegurar_termino(self, texto: str, *, origen: str = "usuario") -> UUID:
        raise AssertionError("no se crea el término por separado")

    async def suscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        raise AssertionError("la suscripción la hace el alta, no una llamada suelta")

    async def alta_de_terminos(
        self,
        negocio_id: UUID,
        *,
        textos: Sequence[str],
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("no es un alta en bloque")

    async def terminos_del_negocio(self, negocio_id: UUID) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("no se listan términos")

    async def estado_termino(self, termino_id: UUID) -> Mapping[str, Any] | None:
        raise AssertionError("no se consulta el estado de uno solo")

    async def pendientes_de_ingesta(self, limite: int) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("no se mira la cola de ingesta")

    async def suscriptores(self, termino_id: UUID) -> int:
        raise AssertionError("no se cuentan suscriptores de uno en uno")

    async def suscriptores_de(self, termino_ids: Sequence[UUID]) -> Mapping[UUID, int]:
        raise AssertionError("no se cuentan suscriptores")

    async def marcar_ingestado(self, termino_id: UUID, momento: datetime) -> None:
        raise AssertionError("no se marca nada como ingestado")


def _alta(*, suscripcion_nueva: bool, hace: timedelta | None) -> Mapping[str, Any]:
    return {
        "id": TERMINO_ID,
        "texto": "obras viales",
        "ultima_ingesta_en": AHORA - hace if hace else None,
        "suscriptores": 3,
        "suscripcion_nueva": suscripcion_nueva,
    }


async def test_rea_agregar_una_palabra_reactivada_vuelve_a_la_cola() -> None:
    """El defecto reportado: quitarla y volver a agregarla decía «ya se consultó hace poco».

    `ultima_ingesta_en` es del catálogo **global**: hace un minuto puede haber una consulta de otro
    negocio. Lo que importa es que esta suscripción acaba de nacer, así que quien la vuelve a
    agregar está pidiendo que se busque otra vez.
    """
    repositorio = TerminosFalsos(alta=_alta(suscripcion_nueva=True, hace=timedelta(minutes=1)))

    resultado = await agregar_termino(
        "obras viales",
        actor=ACTOR,
        repositorio=repositorio,
        intervalo_min=INTERVALO_MIN,
        maximo_terminos=MAXIMO_TERMINOS,
        momento=AHORA,
    )

    assert resultado.en_cola
    assert resultado.suscripcion_nueva
    assert resultado.avisos == (AVISO_EN_COLA,)
    assert resultado.como_diccionario()["estado_ingesta"] == "en_cola"


async def test_una_suscripcion_que_ya_estaba_y_se_consulto_hace_poco_no_encola() -> None:
    """El aviso de «reciente» sigue existiendo para lo que significa: ya estaba y está al día."""
    repositorio = TerminosFalsos(alta=_alta(suscripcion_nueva=False, hace=timedelta(minutes=1)))

    resultado = await agregar_termino(
        "obras viales",
        actor=ACTOR,
        repositorio=repositorio,
        intervalo_min=INTERVALO_MIN,
        maximo_terminos=MAXIMO_TERMINOS,
        momento=AHORA,
    )

    assert not resultado.en_cola
    assert not resultado.suscripcion_nueva
    assert resultado.avisos == (AVISO_RECIENTE,)


async def test_quitar_termino_desuscribe_y_dice_si_estaba_activa() -> None:
    repositorio = TerminosFalsos(baja=True)

    quitado = await quitar_termino(TERMINO_ID, actor=ACTOR, repositorio=repositorio)

    assert quitado is True
    assert repositorio.desuscripciones == [(NEGOCIO, TERMINO_ID)]


async def test_quitar_una_palabra_que_ya_no_estaba_no_es_un_error() -> None:
    """`False` es correcto: el término ya no se seguía, que es lo que la persona quería."""
    repositorio = TerminosFalsos(baja=False)

    assert await quitar_termino(TERMINO_ID, actor=ACTOR, repositorio=repositorio) is False
