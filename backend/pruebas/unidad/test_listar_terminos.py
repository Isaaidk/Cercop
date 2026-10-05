"""Pruebas del listado de palabras clave de un negocio.

Este archivo existe por un fallo que **no daba error**: el listado pedía los suscriptores de cada
término con una consulta propia, dentro de un bucle. Con la base al otro lado de la red —120 ms por
ida y vuelta— y cuarenta palabras clave, el panel tardaba **16,7 segundos** en pintar la lista de
filtros, sin un solo mensaje de error y con la pantalla aparentemente colgada.

Se cumplía además la profecía de todo N+1: en local no se notaba, porque cada consulta es de medio
milisegundo, y en desarrollo tampoco, porque el ojo perdona dos segundos. El defecto solo aparece
cuando la distancia al dato es real.

Por eso la prueba que importa aquí no comprueba el resultado, sino **cuántas veces se pregunta**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.encolar_termino import listar_terminos
from contratacion.dominio.palabras import normalizar_termino

AHORA = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
INTERVALO_MIN = 15

ACTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="consultor")


class TerminosFalsos:
    """Repositorio en memoria que **cuenta** las llamadas.

    El contador es el punto entero de este doble: un repositorio que devolviera lo mismo sin contar
    no permitiría distinguir el listado bueno del que pregunta cuarenta veces.
    """

    def __init__(self, filas: list[dict[str, Any]], suscriptores: dict[UUID, int] | None = None):
        self._filas = filas
        self._suscriptores = suscriptores or {}
        self.llamadas_suscriptores: list[list[UUID]] = []
        self.llamadas_individuales: list[UUID] = []

    async def terminos_del_negocio(self, negocio_id: UUID) -> list[dict[str, Any]]:
        return list(self._filas)

    async def suscriptores_de(self, termino_ids: Sequence[UUID]) -> Mapping[UUID, int]:
        """Devuelve una entrada por identificador, con cero si no tiene suscriptores.

        Reproduce el comportamiento del repositorio real, que responde por **todo** lo que se le
        pregunta. Un doble que omitiera las claves ausentes estaría describiendo otro contrato, y la
        prueba del caso «recién creado, sin suscriptores» pasaría por el motivo equivocado.
        """
        self.llamadas_suscriptores.append(list(termino_ids))
        return {termino_id: self._suscriptores.get(termino_id, 0) for termino_id in termino_ids}

    async def suscriptores(self, termino_id: UUID) -> int:
        # Si alguien vuelve a llamar a esta dentro del bucle, la prueba lo dice con un contador en
        # lugar de con un tiempo, que es lo único que no depende de la máquina donde se ejecute.
        self.llamadas_individuales.append(termino_id)
        return self._suscriptores.get(termino_id, 0)

    # Miembros del puerto que el listado no usa. Se declaran **todos** para que el doble sea
    # estructuralmente compatible con el puerto: mypy también revisa las pruebas, y un doble al que
    # le falte un método no falla al escribirlo, falla el día que alguien usa el que falta.
    async def asegurar_termino(self, texto: str, *, origen: str = "usuario") -> UUID:
        raise AssertionError("listar_terminos no debe crear términos")

    async def suscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        raise AssertionError("listar_terminos no debe suscribir nada")

    async def marcar_ingestado(self, termino_id: UUID, momento: datetime) -> None:
        raise AssertionError("listar_terminos no debe marcar nada como ingestado")

    async def alta_de_termino(
        self, negocio_id: UUID, *, texto: str, maximo_terminos: int, origen: str = "usuario"
    ) -> Mapping[str, Any]:
        raise AssertionError("listar_terminos no debe dar de alta nada")

    async def alta_de_terminos(
        self,
        negocio_id: UUID,
        *,
        textos: Sequence[str],
        maximo_terminos: int,
        origen: str = "usuario",
    ) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("listar_terminos no debe dar de alta nada")

    async def desuscribir(self, negocio_id: UUID, termino_id: UUID) -> bool:
        raise AssertionError("listar_terminos no debe desuscribir nada")

    async def estado_termino(self, termino_id: UUID) -> Mapping[str, Any] | None:
        raise AssertionError("el listado no consulta el estado de uno solo")

    async def pendientes_de_ingesta(self, limite: int) -> Sequence[Mapping[str, Any]]:
        raise AssertionError("listar_terminos no debe mirar la cola de ingesta")


def _fila(texto: str, *, ultima: datetime | None = None, activo: bool = True) -> dict[str, Any]:
    return {
        "termino_id": uuid4(),
        "texto": texto,
        "texto_normalizado": normalizar_termino(texto),
        "prioridad": 0,
        "activo": activo,
        "ultima_ingesta_en": ultima,
    }


async def test_los_suscriptores_se_piden_una_sola_vez() -> None:
    """La prueba que impide que vuelva el N+1.

    Se cuentan las llamadas, no los milisegundos: un umbral de tiempo daría verde en la máquina de
    quien lo escriba y rojo en la de integración, que es exactamente la clase de prueba que se acaba
    desactivando.
    """
    filas = [_fila(f"termino {indice}") for indice in range(25)]
    repositorio = TerminosFalsos(filas)

    await listar_terminos(
        ACTOR, repositorio=repositorio, intervalo_min=INTERVALO_MIN, momento=AHORA
    )

    assert len(repositorio.llamadas_suscriptores) == 1, "una sola lectura para todos los términos"
    assert repositorio.llamadas_individuales == [], "no se pregunta término por término"
    assert repositorio.llamadas_suscriptores[0] == [fila["termino_id"] for fila in filas]


async def test_cada_termino_recibe_su_cuenta_de_suscriptores() -> None:
    """Pedirlos en lote no puede acabar asignándolos al término equivocado.

    Con un mapa por identificador el reparto es evidente; con una lista habría que confiar en que el
    orden devuelto es el mismo que el pedido, y la base no promete eso.
    """
    filas = [_fila("obras"), _fila("medicamentos"), _fila("software")]
    repositorio = TerminosFalsos(
        filas,
        {
            filas[0]["termino_id"]: 3,
            filas[1]["termino_id"]: 41,
            filas[2]["termino_id"]: 0,
        },
    )

    resultado = await listar_terminos(
        ACTOR, repositorio=repositorio, intervalo_min=INTERVALO_MIN, momento=AHORA
    )

    por_texto = {estado.texto: estado.suscriptores for estado in resultado}
    assert por_texto == {"obras": 3, "medicamentos": 41, "software": 0}


async def test_un_termino_sin_suscriptores_cuenta_cero() -> None:
    """Un término recién creado cuenta cero, y ese cero no es un dato que falte.

    El conteo llega con cero para todo lo que se pregunta, así que la pantalla no tiene que decidir
    qué hacer cuando un término no aparece en la respuesta.
    """
    filas = [_fila("recién puesto")]
    repositorio = TerminosFalsos(filas, {})

    resultado = await listar_terminos(
        ACTOR, repositorio=repositorio, intervalo_min=INTERVALO_MIN, momento=AHORA
    )

    assert resultado[0].suscriptores == 0


async def test_el_estado_de_la_cola_no_cambia_con_el_lote() -> None:
    """El otro dato del listado se calcula igual que antes.

    Se cambió **cómo** se piden los suscriptores, no **cuándo** un término está en cola. Si el
    arreglo hubiera movido esa regla, el panel diría que no hay nada pendiente y nadie volvería a
    consultar la fuente para los términos nuevos.
    """
    filas = [
        _fila("nunca consultado", ultima=None),
        _fila("al día", ultima=AHORA - timedelta(minutes=1)),
        _fila("atrasado", ultima=AHORA - timedelta(minutes=90)),
    ]

    resultado = await listar_terminos(
        ACTOR,
        repositorio=TerminosFalsos(filas),
        intervalo_min=INTERVALO_MIN,
        momento=AHORA,
    )

    en_cola = {estado.texto: estado.en_cola for estado in resultado}
    assert en_cola == {"nunca consultado": True, "al día": False, "atrasado": True}
