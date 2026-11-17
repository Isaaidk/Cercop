"""Notificaciones web: un mensaje por persona, sin repetir y sin tumbar nada si algo falla."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from contratacion.aplicacion.casos_uso.notificar import (
    armar_mensaje,
    avisos_de_perfil,
    notificar_pendientes,
)
from contratacion.infraestructura.adaptadores.salida.push import Resultado


class RepoFalso:
    def __init__(
        self, suscripciones: list[dict[str, Any]], pendientes: list[dict[str, Any]]
    ) -> None:
        self._suscripciones = suscripciones
        self._pendientes = pendientes
        self.notificados: list[UUID] = []
        self.resultados: list[tuple[UUID, bool, bool]] = []
        self.creados: list[tuple[UUID, int, bool]] = []
        self.revisados: list[UUID] = []

    async def suscripciones(self) -> list[dict[str, Any]]:
        return self._suscripciones

    async def avisos_por_notificar(self, tope: int = 500) -> list[dict[str, Any]]:
        return self._pendientes

    async def marcar_notificados(
        self, *, negocio_id: UUID, ids: list[UUID], momento: datetime
    ) -> None:
        self.notificados.extend(ids)

    async def anotar_resultado(
        self, *, negocio_id: UUID, suscripcion_id: UUID, ok: bool, caducada: bool
    ) -> None:
        self.resultados.append((suscripcion_id, ok, caducada))

    async def anotar_perfil_revisado(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None:
        self.revisados.append(usuario_id)

    async def crear_avisos_de_perfil(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        avisos: list[dict[str, Any]],
        ya_notificados: bool,
    ) -> int:
        self.creados.append((usuario_id, len(avisos), ya_notificados))
        return len(avisos)


class EnviadorFalso:
    def __init__(self, resultado: Resultado | None = None) -> None:
        self.mensajes: list[tuple[str, dict[str, Any]]] = []
        self._resultado = resultado or Resultado(ok=True)

    @property
    def activo(self) -> bool:
        return True

    async def enviar(self, suscripcion: dict[str, Any], carga: dict[str, Any]) -> Resultado:
        self.mensajes.append((suscripcion["endpoint"], carga))
        return self._resultado


def _aviso(negocio: UUID, usuario: UUID, titulo: str, **extra: Any) -> dict[str, Any]:
    return {"id": uuid4(), "negocio_id": negocio, "usuario_id": usuario, "titulo": titulo, **extra}


def _suscripcion(negocio: UUID, usuario: UUID, **extra: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "negocio_id": negocio,
        "usuario_id": usuario,
        "endpoint": f"https://push.ejemplo/{uuid4()}",
        "p256dh": "x" * 40,
        "auth": "y" * 16,
        "avisar_perfil": True,
        "perfil_revisado_en": None,
        **extra,
    }


def test_un_aviso_de_perfil_dice_que_es_una_infima() -> None:
    mensaje = armar_mensaje([{"titulo": "Compra de guantes de nitrilo", "origen": "perfil"}])
    assert mensaje["titulo"] == "Nueva ínfima cuantía para tu empresa"
    assert mensaje["cuerpo"] == "Compra de guantes de nitrilo"


def test_un_aviso_de_alerta_nombra_la_alerta() -> None:
    mensaje = armar_mensaje(
        [{"titulo": "Limpieza", "alerta_id": uuid4(), "alerta_nombre": "Limpieza Guayas"}]
    )
    assert mensaje["titulo"] == "Nueva oportunidad · alerta «Limpieza Guayas»"


def test_varios_avisos_van_en_un_solo_mensaje() -> None:
    mensaje = armar_mensaje([{"titulo": f"Proceso {i}"} for i in range(5)])
    assert mensaje["titulo"] == "5 oportunidades nuevas para ti"
    assert mensaje["cuerpo"] == "Proceso 0 · Proceso 1 y 3 más"


async def test_cada_persona_recibe_un_mensaje_en_cada_navegador() -> None:
    negocio, ana, luis = uuid4(), uuid4(), uuid4()
    repo = RepoFalso(
        [_suscripcion(negocio, ana), _suscripcion(negocio, ana), _suscripcion(negocio, luis)],
        [
            _aviso(negocio, ana, "A1"),
            _aviso(negocio, ana, "A2"),
            _aviso(negocio, luis, "L1"),
        ],
    )
    enviador = EnviadorFalso()

    personas = await notificar_pendientes(repo, enviador)

    assert personas == 2
    assert len(enviador.mensajes) == 3  # dos navegadores de Ana + uno de Luis
    assert len(repo.notificados) == 3


async def test_un_envio_fallido_igual_marca_el_aviso_para_no_repetirlo() -> None:
    negocio, ana = uuid4(), uuid4()
    repo = RepoFalso([_suscripcion(negocio, ana)], [_aviso(negocio, ana, "A1")])

    personas = await notificar_pendientes(repo, EnviadorFalso(Resultado(ok=False, caducada=True)))

    assert personas == 0
    assert len(repo.notificados) == 1
    assert repo.resultados[0][2] is True  # caducada: el repositorio la borra


class _Clave:
    def __init__(self, texto: str) -> None:
        self.texto = texto


class PerfilFalso:
    async def leer(self, negocio_id: UUID) -> dict[str, Any]:
        return {"cobertura": [], "ofertas": [], "experiencia": [], "palabras": []}


class CpcFalso:
    async def listar(self, *, negocio_id: UUID) -> tuple[_Clave, ...]:
        return (_Clave("35321"),)


class InfimasFalsas:
    def __init__(self) -> None:
        self.consultas = 0

    async def infimas_abiertas(self, **_: Any) -> list[dict[str, Any]]:
        self.consultas += 1
        return [
            {
                "id": uuid4(),
                "codigo": "NC-1",
                "objeto": "Desinfectante",
                "entidad": "Hospital",
                "provincia": "GUAYAS",
                "cpc_codigos": ["353210011"],
                "plazo": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            }
        ]


async def _siempre(_n: UUID, _u: UUID) -> bool:
    return True


async def test_perfil_una_consulta_por_empresa_y_la_primera_vuelta_en_silencio() -> None:
    negocio, ana, luis = uuid4(), uuid4(), uuid4()
    repo = RepoFalso([_suscripcion(negocio, ana), _suscripcion(negocio, luis)], [])
    infimas = InfimasFalsas()

    await avisos_de_perfil(
        repo,
        perfil=cast(Any, PerfilFalso()),
        cpc=cast(Any, CpcFalso()),
        infimas=infimas,
        puede_ver_infimas=_siempre,
    )

    assert infimas.consultas == 1
    assert {usuario for usuario, _, _ in repo.creados} == {ana, luis}
    assert all(silencio for _, _, silencio in repo.creados)


async def test_perfil_revisado_hace_poco_no_consulta() -> None:
    negocio, ana = uuid4(), uuid4()
    reciente = datetime.now(UTC) - timedelta(minutes=2)
    repo = RepoFalso([_suscripcion(negocio, ana, perfil_revisado_en=reciente)], [])
    infimas = InfimasFalsas()

    await avisos_de_perfil(
        repo,
        perfil=cast(Any, PerfilFalso()),
        cpc=cast(Any, CpcFalso()),
        infimas=infimas,
        puede_ver_infimas=_siempre,
    )

    assert infimas.consultas == 0
