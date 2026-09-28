"""Casos de uso: conceder, retirar y consultar el acceso a las vistas.

El administrador elige un plazo de una lista y pulsa «dar acceso»; **el backend calcula la fecha**.
El cliente no envía fechas nunca: si pudiera, un error de zona horaria o un cliente manipulado
podrían conceder un acceso de diez años.

Retirar no borra: marca. Así queda el rastro de quién quitó el acceso y cuándo, que es exactamente
lo que hace falta cuando un cliente reclama.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.generaciones import leer_generacion, subir_generacion
from contratacion.aplicacion.puertos.accesos import RepositorioAccesos
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.dominio.acceso import (
    ETIQUETAS_PLAZO,
    TTL_PERMISO_SEG,
    AccesoVista,
    EstadoVista,
    Plazo,
    Vista,
    clave_permiso,
    concesion_vigente,
    generacion_de_acceso,
    negocio_objetivo,
    plazo_desde_codigo,
    tablero,
    vista_desde_codigo,
)
from contratacion.dominio.errores import NoEncontrado, SinPermiso
from contratacion.dominio.serializacion import a_json, de_json

registro = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ResultadoConcesion:
    """Confirmación de un acceso concedido, con el estado completo resultante."""

    negocio_id: UUID
    usuario_id: UUID
    vista: Vista
    plazo: Plazo
    otorgado_en: datetime
    vence_en: datetime
    tablero: tuple[EstadoVista, ...]

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "negocio_id": str(self.negocio_id),
            "usuario_id": str(self.usuario_id),
            "vista": str(self.vista),
            "plazo": str(self.plazo),
            "plazo_etiqueta": ETIQUETAS_PLAZO[self.plazo],
            "otorgado_en": self.otorgado_en.isoformat(),
            "vence_en": self.vence_en.isoformat(),
            "tablero": [vista_a_diccionario(fila) for fila in self.tablero],
        }


@dataclass(frozen=True, slots=True)
class ResultadoTablero:
    """Estado de todas las vistas de un usuario."""

    negocio_id: UUID
    usuario_id: UUID
    tablero: tuple[EstadoVista, ...]

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "negocio_id": str(self.negocio_id),
            "usuario_id": str(self.usuario_id),
            "vistas": [vista_a_diccionario(fila) for fila in self.tablero],
        }


@dataclass(frozen=True, slots=True)
class UsuarioConVistas:
    """Un usuario registrado del negocio con el estado de sus vistas."""

    usuario_id: UUID
    email: str
    nombre: str
    rol: str
    estado: str
    tablero: tuple[EstadoVista, ...]

    def como_diccionario(self) -> dict[str, Any]:
        vigentes = [fila for fila in self.tablero if fila.vigente]
        return {
            "usuario_id": str(self.usuario_id),
            "email": self.email,
            "nombre": self.nombre,
            "rol": self.rol,
            "estado": self.estado,
            "vistas_vigentes": [str(fila.vista) for fila in vigentes],
            "vistas": [vista_a_diccionario(fila) for fila in self.tablero],
        }


def vista_a_diccionario(fila: EstadoVista) -> dict[str, Any]:
    """Traduce el estado de una vista a la forma que pinta el panel.

    El color se calcula aquí, no en el frontend: si la interfaz tuviera que decidir cuándo una vista
    está activa, habría dos sitios donde equivocarse y el de la interfaz sería el equivocado.
    """
    return {
        "vista": str(fila.vista),
        "etiqueta": fila.etiqueta,
        "vigente": fila.vigente,
        "color": "verde" if fila.vigente else "rojo",
        "vence_en": fila.vence_en.isoformat() if fila.vence_en else None,
        "dias_restantes": fila.dias_restantes,
        "plazo": str(fila.plazo) if fila.plazo else None,
        "plazo_etiqueta": ETIQUETAS_PLAZO[fila.plazo] if fila.plazo else None,
        "por_vencer": fila.por_vencer,
    }


async def conceder_acceso(
    actor: Actor,
    *,
    usuario_id: UUID,
    vista_codigo: str,
    plazo_codigo: str,
    repositorio: RepositorioAccesos,
    cache: Cache,
    negocio_solicitado: UUID | None = None,
    momento: datetime | None = None,
) -> ResultadoConcesion:
    """Concede (o extiende) el acceso de un usuario a una vista durante un plazo."""
    actor.exigir_administrativo()
    negocio_id = negocio_objetivo(actor.rol, actor.negocio_id, negocio_solicitado)
    vista = vista_desde_codigo(vista_codigo)
    plazo = plazo_desde_codigo(plazo_codigo)
    instante = momento or datetime.now(UTC)

    if await repositorio.usuario(negocio_id=negocio_id, usuario_id=usuario_id) is None:
        raise NoEncontrado("El usuario no existe en este negocio.")

    vence = plazo.calcular(instante)
    await repositorio.conceder(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        vista=vista,
        plazo=plazo,
        otorgado_en=instante,
        vence_en=vence,
        otorgado_por=actor.usuario_id,
    )
    await _invalidar_permisos(cache, usuario_id)

    registro.info(
        "Acceso concedido: negocio=%s usuario=%s vista=%s plazo=%s",
        negocio_id,
        usuario_id,
        vista,
        plazo,
    )
    return ResultadoConcesion(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        vista=vista,
        plazo=plazo,
        otorgado_en=instante,
        vence_en=vence,
        tablero=await _tablero_de(negocio_id, usuario_id, repositorio, instante),
    )


async def retirar_acceso(
    actor: Actor,
    *,
    usuario_id: UUID,
    vista_codigo: str,
    repositorio: RepositorioAccesos,
    cache: Cache,
    negocio_solicitado: UUID | None = None,
    momento: datetime | None = None,
) -> ResultadoTablero:
    """Retira el acceso de un usuario a una vista, de inmediato."""
    actor.exigir_administrativo()
    negocio_id = negocio_objetivo(actor.rol, actor.negocio_id, negocio_solicitado)
    vista = vista_desde_codigo(vista_codigo)
    instante = momento or datetime.now(UTC)

    if await repositorio.usuario(negocio_id=negocio_id, usuario_id=usuario_id) is None:
        raise NoEncontrado("El usuario no existe en este negocio.")

    retiradas = await repositorio.retirar(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        vista=vista,
        momento=instante,
        retirado_por=actor.usuario_id,
    )
    if retiradas == 0:
        raise NoEncontrado("Ese usuario no tiene acceso concedido a esta vista.")

    # Se sube la generación: sin esto, el permiso cacheado seguiría concediendo la vista hasta un
    # minuto. Retirar el acceso tiene que notarse en la siguiente petición, no «en un rato».
    await _invalidar_permisos(cache, usuario_id)

    registro.info(
        "Acceso retirado: negocio=%s usuario=%s vista=%s filas=%s",
        negocio_id,
        usuario_id,
        vista,
        retiradas,
    )
    return ResultadoTablero(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        tablero=await _tablero_de(negocio_id, usuario_id, repositorio, instante),
    )


async def consultar_accesos(
    actor: Actor,
    *,
    usuario_id: UUID,
    repositorio: RepositorioAccesos,
    negocio_solicitado: UUID | None = None,
    momento: datetime | None = None,
) -> ResultadoTablero:
    """Estado de las vistas de un usuario.

    Cualquiera puede consultar **las suyas**, porque el panel necesita saber qué mostrar; consultar
    las de otro exige ser administrador.
    """
    instante = momento or datetime.now(UTC)
    negocio_id = _negocio_para_consulta(actor, usuario_id, negocio_solicitado)

    if await repositorio.usuario(negocio_id=negocio_id, usuario_id=usuario_id) is None:
        raise NoEncontrado("El usuario no existe en este negocio.")

    return ResultadoTablero(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        tablero=await _tablero_de(negocio_id, usuario_id, repositorio, instante),
    )


async def listar_usuarios(
    actor: Actor,
    *,
    repositorio: RepositorioAccesos,
    negocio_solicitado: UUID | None = None,
    momento: datetime | None = None,
) -> tuple[UsuarioConVistas, ...]:
    """Usuarios **registrados** del negocio, con el estado de sus vistas.

    Son los usuarios que existen, no los que están conectados: la presencia se resuelve con el caché
    y llega en la fase 4. Mezclar ambas cosas aquí daría un listado que cambia de contenido según el
    tráfico, que no es lo que un administrador necesita para gestionar suscripciones.
    """
    actor.exigir_administrativo()
    negocio_id = negocio_objetivo(actor.rol, actor.negocio_id, negocio_solicitado)
    instante = momento or datetime.now(UTC)

    filas = await repositorio.usuarios(negocio_id=negocio_id)
    resultado: list[UsuarioConVistas] = []
    for fila in filas:
        identificador = _uuid(fila.get("usuario_id") or fila.get("id"))
        if identificador is None:
            continue
        resultado.append(
            UsuarioConVistas(
                usuario_id=identificador,
                email=str(fila.get("email", "")),
                nombre=str(fila.get("nombre", "")),
                rol=str(fila.get("rol", "")),
                estado=str(fila.get("estado", "")),
                tablero=await _tablero_de(negocio_id, identificador, repositorio, instante),
            )
        )
    return tuple(resultado)


async def vistas_vigentes(
    *,
    negocio_id: UUID,
    usuario_id: UUID,
    repositorio: RepositorioAccesos,
    cache: Cache,
    momento: datetime | None = None,
) -> frozenset[Vista]:
    """Conjunto de vistas concedidas en este instante.

    Se cachea un minuto como mucho. Es corto a propósito: si el permiso se guardara más tiempo,
    un acceso recién retirado seguiría abriendo la vista. La retirada sube además la generación, de
    modo que en la práctica el cambio se nota en la petición siguiente.
    """
    instante = momento or datetime.now(UTC)
    generacion = await leer_generacion(cache, generacion_de_acceso(usuario_id))
    clave = clave_permiso(usuario_id, generacion)

    guardado = await _leer_permiso(cache, clave)
    if guardado is not None:
        return guardado

    accesos = await repositorio.obtener(negocio_id=negocio_id, usuario_id=usuario_id)
    vigentes = frozenset(concesion_vigente(accesos, instante))
    await _guardar_permiso(cache, clave, vigentes)
    return vigentes


async def exigir_acceso_a_vista(
    *,
    negocio_id: UUID,
    usuario_id: UUID,
    vista: Vista,
    repositorio: RepositorioAccesos,
    cache: Cache,
    momento: datetime | None = None,
) -> None:
    """Lanza `SinPermiso` si el usuario no tiene la vista concedida.

    Es la puerta que la fase 4 conectará al token: cuando exista autenticación, cada endpoint de
    lectura la llamará antes de consultar.
    """
    vigentes = await vistas_vigentes(
        negocio_id=negocio_id,
        usuario_id=usuario_id,
        repositorio=repositorio,
        cache=cache,
        momento=momento,
    )
    if vista not in vigentes:
        raise SinPermiso(
            f"Este usuario no tiene acceso a la vista «{vista}». Pide al administrador que lo "
            "conceda."
        )


def _negocio_para_consulta(actor: Actor, usuario_id: UUID, negocio_solicitado: UUID | None) -> UUID:
    """Ámbito de una consulta: el propio usuario, o el que un administrador indique."""
    if usuario_id == actor.usuario_id:
        return actor.negocio_id
    actor.exigir_administrativo()
    return negocio_objetivo(actor.rol, actor.negocio_id, negocio_solicitado)


async def _tablero_de(
    negocio_id: UUID,
    usuario_id: UUID,
    repositorio: RepositorioAccesos,
    momento: datetime,
) -> tuple[EstadoVista, ...]:
    accesos: tuple[AccesoVista, ...] = tuple(
        await repositorio.obtener(negocio_id=negocio_id, usuario_id=usuario_id)
    )
    return tablero(accesos, momento)


async def _invalidar_permisos(cache: Cache, usuario_id: UUID) -> None:
    """Sube la generación de permisos del usuario para que el cambio se note de inmediato."""
    await subir_generacion(cache, generacion_de_acceso(usuario_id))


async def _leer_permiso(cache: Cache, clave: str) -> frozenset[Vista] | None:
    try:
        contenido = await cache.obtener(clave)
    except Exception:  # noqa: BLE001
        registro.warning("Fallo al leer el permiso del caché", exc_info=False)
        return None
    if contenido is None:
        return None
    try:
        return frozenset(Vista(codigo) for codigo in de_json(contenido))
    except Exception:  # noqa: BLE001 - un permiso cacheado ilegible se recalcula
        registro.warning("Permiso cacheado ilegible; se recalcula", exc_info=False)
        return None


async def _guardar_permiso(cache: Cache, clave: str, vistas: frozenset[Vista]) -> None:
    try:
        await cache.guardar(clave, a_json(sorted(str(vista) for vista in vistas)), TTL_PERMISO_SEG)
    except Exception:  # noqa: BLE001
        registro.warning("No se pudo cachear el permiso", exc_info=False)


def _uuid(valor: Any) -> UUID | None:
    """Normaliza un identificador, venga como `UUID` o como texto."""
    if valor is None:
        return None
    return valor if isinstance(valor, UUID) else UUID(str(valor))
