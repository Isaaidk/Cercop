"""Notificaciones web: avisos por perfil y envío de los avisos pendientes.

Corre **solo en el worker**, después de revisar las alertas. El API no hace nada de esto, así que
no añade consultas a las peticiones de las personas.

Dos pasos:

1. `avisos_de_perfil`: para cada empresa con alguien suscrito, las ínfimas abiertas que encajan con
   su perfil (CPC, lo que ofrece, cobertura). Una consulta por **empresa**, no por persona, y como
   mucho cada `CADA_PERFIL`. Lo que ya estaba abierto al suscribirse se guarda sin notificar.
2. `notificar_pendientes`: junta los avisos sin notificar de cada persona en **un** mensaje (no diez
   notificaciones seguidas) y lo manda a cada navegador suyo.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from contratacion.aplicacion.puertos.cpc import RepositorioCpc
from contratacion.aplicacion.puertos.perfil import RepositorioPerfil
from contratacion.aplicacion.puertos.radar import InfimasAbiertas
from contratacion.dominio.propuestas import evaluar, zonas_desde_perfil
from contratacion.dominio.radar import criterios_desde_perfil, unir_duplicados

registro = logging.getLogger(__name__)

CADA_PERFIL = timedelta(minutes=15)
TOPE_INFIMAS = 1000
MAX_AVISOS_PERFIL = 30
# El panel no tiene rutas por pestaña: la notificación abre (o enfoca) el panel, y el aviso está en
# el inicio, en «Avisos».
URL_AVISOS = "/"


class Notificaciones(Protocol):
    async def suscripciones(self) -> list[dict[str, Any]]: ...
    async def avisos_por_notificar(self, tope: int = 500) -> list[dict[str, Any]]: ...
    async def marcar_notificados(
        self, *, negocio_id: UUID, ids: list[UUID], momento: datetime
    ) -> None: ...
    async def anotar_resultado(
        self, *, negocio_id: UUID, suscripcion_id: UUID, ok: bool, caducada: bool
    ) -> None: ...
    async def anotar_perfil_revisado(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None: ...
    async def crear_avisos_de_perfil(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        avisos: list[dict[str, Any]],
        ya_notificados: bool,
    ) -> int: ...


class Enviador(Protocol):
    @property
    def activo(self) -> bool: ...
    async def enviar(self, suscripcion: dict[str, Any], carga: dict[str, Any]) -> Any: ...


def _corto(texto: str, maximo: int = 140) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= maximo else texto[: maximo - 1].rstrip() + "…"


def armar_mensaje(avisos: list[dict[str, Any]]) -> dict[str, Any]:
    """Un solo mensaje claro para los avisos nuevos de una persona."""
    primero = avisos[0]
    if len(avisos) == 1:
        if primero.get("origen") == "perfil":
            titulo = "Nueva ínfima cuantía para tu empresa"
        elif primero.get("alerta_id"):
            nombre = _corto(primero.get("alerta_nombre") or "", 40)
            titulo = f"Nueva oportunidad · alerta «{nombre}»" if nombre else "Nueva oportunidad"
        else:
            titulo = "Recordatorio de tu oferta"
        cuerpo = _corto(primero.get("titulo") or "")
    else:
        titulo = f"{len(avisos)} oportunidades nuevas para ti"
        nombres = [_corto(a.get("titulo") or "", 60) for a in avisos[:2]]
        resto = len(avisos) - len(nombres)
        cuerpo = " · ".join(nombres) + (f" y {resto} más" if resto > 0 else "")
    return {
        "titulo": titulo,
        "cuerpo": cuerpo,
        "url": URL_AVISOS,
        # Mismo `tag`: una notificación nueva reemplaza a la anterior en vez de apilarse.
        "tag": "cercoapp-avisos",
        "cantidad": len(avisos),
    }


async def notificar_pendientes(
    repo: Notificaciones, enviador: Enviador, *, ahora: datetime | None = None
) -> int:
    """Manda los avisos sin notificar. Devuelve cuántas personas recibieron mensaje."""
    if not enviador.activo:
        return 0
    momento = ahora or datetime.now(UTC)
    pendientes = await repo.avisos_por_notificar()
    if not pendientes:
        return 0
    navegadores: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
    for suscripcion in await repo.suscripciones():
        clave = (suscripcion["negocio_id"], suscripcion["usuario_id"])
        navegadores.setdefault(clave, []).append(suscripcion)
    por_persona: dict[tuple[UUID, UUID], list[dict[str, Any]]] = {}
    for aviso in pendientes:
        por_persona.setdefault((aviso["negocio_id"], aviso["usuario_id"]), []).append(aviso)

    personas = 0
    for (negocio_id, usuario_id), avisos in por_persona.items():
        mensaje = armar_mensaje(avisos)
        enviado = False
        for suscripcion in navegadores.get((negocio_id, usuario_id), []):
            resultado = await enviador.enviar(suscripcion, mensaje)
            enviado = enviado or bool(getattr(resultado, "ok", False))
            await repo.anotar_resultado(
                negocio_id=negocio_id,
                suscripcion_id=suscripcion["id"],
                ok=bool(getattr(resultado, "ok", False)),
                caducada=bool(getattr(resultado, "caducada", False)),
            )
        # Se marcan aunque el envío fallara: reintentar en cada vuelta acabaría mandando avisos
        # viejos horas después. El aviso sigue en el panel.
        await repo.marcar_notificados(
            negocio_id=negocio_id, ids=[a["id"] for a in avisos], momento=momento
        )
        personas += int(enviado)
    if personas:
        registro.info(
            "Notificaciones: %s personas avisadas (%s avisos).", personas, len(pendientes)
        )
    return personas


def _le_toca(suscripciones: list[dict[str, Any]], momento: datetime) -> bool:
    for suscripcion in suscripciones:
        revisado = suscripcion.get("perfil_revisado_en")
        if revisado is None:
            return True
        if revisado.tzinfo is None:
            revisado = revisado.replace(tzinfo=UTC)
        if momento - revisado >= CADA_PERFIL:
            return True
    return False


async def avisos_de_perfil(
    repo: Notificaciones,
    *,
    perfil: RepositorioPerfil,
    cpc: RepositorioCpc,
    infimas: InfimasAbiertas,
    puede_ver_infimas: Callable[[UUID, UUID], Awaitable[bool]],
    ahora: datetime | None = None,
) -> int:
    """Crea avisos de ínfimas abiertas que encajan con el perfil. Devuelve los creados."""
    momento = ahora or datetime.now(UTC)
    por_empresa: dict[UUID, list[dict[str, Any]]] = {}
    for suscripcion in await repo.suscripciones():
        if suscripcion.get("avisar_perfil"):
            por_empresa.setdefault(suscripcion["negocio_id"], []).append(suscripcion)

    creados = 0
    for negocio_id, suscripciones in por_empresa.items():
        if not _le_toca(suscripciones, momento):
            continue
        try:
            creados += await _una_empresa(
                repo,
                negocio_id,
                suscripciones,
                perfil=perfil,
                cpc=cpc,
                infimas=infimas,
                puede_ver_infimas=puede_ver_infimas,
                momento=momento,
            )
        except Exception:  # noqa: BLE001 - una empresa con datos raros no para a las demás
            registro.exception("No se pudieron revisar los avisos de perfil de %s", negocio_id)
    return creados


async def _una_empresa(
    repo: Notificaciones,
    negocio_id: UUID,
    suscripciones: list[dict[str, Any]],
    *,
    perfil: RepositorioPerfil,
    cpc: RepositorioCpc,
    infimas: InfimasAbiertas,
    puede_ver_infimas: Callable[[UUID, UUID], Awaitable[bool]],
    momento: datetime,
) -> int:
    ficha = await perfil.leer(negocio_id)
    claves = await cpc.listar(negocio_id=negocio_id)
    criterios = criterios_desde_perfil(ficha, [clave.texto for clave in claves])
    propuestas: list[dict[str, Any]] = []
    if criterios.tiene_interes:
        zonas = zonas_desde_perfil(ficha)
        filas = await infimas.infimas_abiertas(
            provincias=tuple(dict.fromkeys(zona.provincia for zona in zonas)),
            cpc=criterios.cpc,
            palabras=criterios.palabras,
            incluir_sin_plazo=False,
            limite=TOPE_INFIMAS,
        )
        unidas, _ = unir_duplicados(filas)
        propuestas = [p for p in (evaluar(criterios, zonas, fila) for fila in unidas) if p]
        propuestas.sort(key=lambda p: p.get("puntos") or 0, reverse=True)
    avisos = [
        {
            "registro_id": str(p["id"]),
            "titulo": _corto(p.get("objeto") or p.get("codigo") or "Ínfima cuantía", 240),
            "detalle": _corto(" · ".join(x for x in (p.get("entidad"), p.get("provincia")) if x)),
            "puntuacion": p.get("puntos"),
        }
        for p in propuestas[:MAX_AVISOS_PERFIL]
        if p.get("id")
    ]

    creados = 0
    personas = {s["usuario_id"]: s for s in suscripciones}
    for usuario_id, suscripcion in personas.items():
        if avisos and await puede_ver_infimas(negocio_id, usuario_id):
            creados += await repo.crear_avisos_de_perfil(
                negocio_id=negocio_id,
                usuario_id=usuario_id,
                avisos=avisos,
                ya_notificados=suscripcion.get("perfil_revisado_en") is None,
            )
        await repo.anotar_perfil_revisado(
            negocio_id=negocio_id, usuario_id=usuario_id, momento=momento
        )
    return creados
