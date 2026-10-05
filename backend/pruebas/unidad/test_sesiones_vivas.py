"""Pruebas de las sesiones vivas.

Lo que se defiende aquí no es que una clave se escriba, sino **las decisiones que sostienen el
cierre por inactividad**:

1. Que el almacén caído degrade a la base de datos y no eche a todo el mundo. Es la prueba que
   separa «no consta» de «no hay dónde apuntarlo», que es justo lo que un booleano no distingue.
2. Que **el refresco de token no rearme el plazo**. Si lo rearmara, una pestaña olvidada —que se
   renueva sola cada cuarto de hora— no se cerraría nunca, y el cierre por inactividad sería una
   función que existe y no hace nada.
3. Que **ninguna forma de revocar deje la clave viva**. Es lo que convierte un cierre de sesión en
   un cierre de sesión, en lugar de una fila marcada mientras el usuario sigue dentro.

La tercera se prueba sobre el envoltorio y no sobre cada caso de uso, y esa es la razón de probarla
así: el envoltorio existe precisamente para que no haya cinco sitios donde acordarse.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.puertos.cuentas import SesionGuardada
from contratacion.aplicacion.sesiones_vivas import (
    SesionesConVida,
    VidaDeSesion,
    abrir,
    olvidar,
    seguir,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion
from contratacion.dominio.sesiones_vivas import (
    clave_de_sesion,
    usuario_de_sesion,
    valor_de_sesion,
)

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
INACTIVIDAD = 480 * 60

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
OTRO_USUARIO = UUID("44444444-4444-4444-4444-444444444444")


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


class CacheFalso:
    """Almacén en memoria que además apunta **cómo** se le llamó.

    Distinguir `obtener` de `obtener_renovando` es el punto: son la misma lectura con un efecto
    distinto, y solo una de las dos puede usarse en las rutas que se repiten solas.
    """

    def __init__(
        self,
        *,
        habilitada: bool = True,
        falla: bool = False,
        inicial: dict[str, str] | None = None,
    ) -> None:
        self._habilitada = habilitada
        self._falla = falla
        self.contenido: dict[str, str] = dict(inicial or {})
        self.ttls: dict[str, int] = {}
        self.renovaciones: list[str] = []
        self.borradas: list[str] = []

    @property
    def habilitada(self) -> bool:
        return self._habilitada

    def _comprobar(self) -> None:
        if self._falla:
            raise RuntimeError("el almacén no responde")

    async def obtener(self, clave: str) -> str | None:
        self._comprobar()
        return self.contenido.get(clave)

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        self._comprobar()
        valor = self.contenido.get(clave)
        if valor is not None:
            self.renovaciones.append(clave)
            self.ttls[clave] = ttl_seg
        return valor

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        self._comprobar()
        self.contenido[clave] = valor
        self.ttls[clave] = ttl_seg

    async def eliminar(self, clave: str) -> None:
        self._comprobar()
        self.borradas.append(clave)
        self.contenido.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        raise AssertionError("incrementar no se debe llamar desde las sesiones vivas")

    async def ping(self) -> bool:
        return not self._falla

    async def cerrar(self) -> None:
        return None


def _sesion(sesion_id: UUID, usuario_id: UUID = USUARIO) -> Sesion:
    return Sesion(
        id=sesion_id,
        usuario_id=usuario_id,
        negocio_id=NEGOCIO,
        creada_en=AHORA,
        ultimo_uso_en=AHORA,
        expira_en=AHORA,
        estado=EstadoSesion.ACTIVA,
    )


class SesionesFalsas:
    """Repositorio de sesiones con registro de llamadas.

    Implementa el puerto completo aunque cada prueba use una parte: los métodos que no se usan
    revientan si alguien los llama, y así el doble avisa el día que el envoltorio toque algo que no
    debía.
    """

    def __init__(self, *, orden: list[str] | None = None, vigentes: list[Sesion] | None = None):
        self.orden = orden if orden is not None else []
        self.llamadas: list[str] = []
        self._vigentes = vigentes or []
        self.creadas: list[UUID] = []
        self.revocadas_varias: list[list[UUID]] = []
        self.rotadas: list[UUID] = []

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> list[Sesion]:
        self.orden.append("vigentes")
        self.llamadas.append("vigentes")
        return list(self._vigentes)

    async def crear(
        self,
        *,
        sesion_id: UUID,
        negocio_id: UUID,
        usuario_id: UUID,
        refresh_hash: str,
        expira_en: datetime,
        momento: datetime,
        dispositivo: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> UUID:
        self.orden.append("crear")
        self.creadas.append(sesion_id)
        return sesion_id

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        raise AssertionError("por_id no se debe llamar desde estas pruebas")

    async def rotar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        refresh_hash: str,
        ultimo_uso_en: datetime,
    ) -> None:
        self.orden.append("rotar")
        self.rotadas.append(sesion_id)

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        self.orden.append("revocar")
        self.revocadas_varias.append([sesion_id])

    async def revocar_varias(
        self,
        *,
        negocio_id: UUID,
        sesion_ids: Sequence[UUID],
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        self.orden.append("revocar_varias")
        self.revocadas_varias.append(list(sesion_ids))
        return len(sesion_ids)

    async def revocar_todas(
        self, *, negocio_id: UUID, usuario_id: UUID, motivo: MotivoRevocacion, momento: datetime
    ) -> int:
        raise AssertionError("revocar_todas no se debe llamar: el envoltorio usa revocar_varias")

    async def revocar_todas_salvo(self, **_: Any) -> int:
        raise AssertionError(
            "revocar_todas_salvo no se debe llamar: el envoltorio usa revocar_varias"
        )

    async def activas_del_negocio(self, *, negocio_id: UUID, momento: datetime) -> list[Sesion]:
        raise AssertionError("activas_del_negocio no se usa aquí")

    async def revocadas_del_negocio(self, *, negocio_id: UUID, limite: int = 500) -> list[Sesion]:
        raise AssertionError("revocadas_del_negocio no se usa aquí")


# --------------------------------------------------------------------------- #
# El nombre y el contenido de una clave
# --------------------------------------------------------------------------- #


def test_la_clave_lleva_el_identificador_de_la_sesion() -> None:
    sesion_id = uuid4()

    assert clave_de_sesion(sesion_id) == f"sesion_viva:{sesion_id}"


def test_el_contenido_de_la_clave_es_el_dueno() -> None:
    valor = valor_de_sesion(USUARIO)

    assert usuario_de_sesion(valor) == USUARIO


def test_un_contenido_que_no_es_un_identificador_no_revienta() -> None:
    """Una clave escrita por una versión anterior no puede tumbar la petición de alguien."""
    assert usuario_de_sesion("cualquier-cosa") is None


# --------------------------------------------------------------------------- #
# Las tres respuestas
# --------------------------------------------------------------------------- #


async def test_sin_almacen_la_respuesta_es_que_no_hay_respuesta() -> None:
    """Un despliegue sin Redis no puede quedarse sin sesiones ni cerrarlas todas."""
    cache = CacheFalso(habilitada=False)

    assert (
        await seguir(cache, sesion_id=uuid4(), usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)
        is VidaDeSesion.SIN_RESPUESTA
    )


async def test_una_sesion_anotada_y_del_dueno_esta_viva() -> None:
    sesion_id = uuid4()
    cache = CacheFalso(inicial={clave_de_sesion(sesion_id): valor_de_sesion(USUARIO)})

    assert (
        await seguir(cache, sesion_id=sesion_id, usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)
        is VidaDeSesion.VIVA
    )


async def test_sin_anotacion_la_sesion_esta_cerrada() -> None:
    """Con el almacén funcionando, la ausencia sí es una respuesta."""
    cache = CacheFalso()

    assert (
        await seguir(cache, sesion_id=uuid4(), usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)
        is VidaDeSesion.CERRADA
    )


async def test_una_sesion_de_otro_usuario_esta_cerrada() -> None:
    sesion_id = uuid4()
    cache = CacheFalso(inicial={clave_de_sesion(sesion_id): valor_de_sesion(OTRO_USUARIO)})

    assert (
        await seguir(cache, sesion_id=sesion_id, usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)
        is VidaDeSesion.CERRADA
    )


async def test_un_almacen_roto_no_echa_a_nadie() -> None:
    """Es la prueba que evita el peor final: apagar Redis y dejar fuera a todo el mundo."""
    cache = CacheFalso(falla=True)

    assert (
        await seguir(cache, sesion_id=uuid4(), usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)
        is VidaDeSesion.SIN_RESPUESTA
    )


# --------------------------------------------------------------------------- #
# Rearmar el plazo
# --------------------------------------------------------------------------- #


async def test_una_peticion_de_verdad_rearma_el_plazo() -> None:
    sesion_id = uuid4()
    cache = CacheFalso(inicial={clave_de_sesion(sesion_id): valor_de_sesion(USUARIO)})

    await seguir(
        cache,
        sesion_id=sesion_id,
        usuario_id=USUARIO,
        inactividad_seg=INACTIVIDAD,
        renovar=True,
    )

    assert cache.ttls[clave_de_sesion(sesion_id)] == INACTIVIDAD


async def test_una_ruta_que_se_repite_sola_no_rearma_el_plazo() -> None:
    """El latido y el flujo de eventos se repiten sin nadie delante: no son actividad."""
    sesion_id = uuid4()
    cache = CacheFalso(inicial={clave_de_sesion(sesion_id): valor_de_sesion(USUARIO)})

    vida = await seguir(
        cache,
        sesion_id=sesion_id,
        usuario_id=USUARIO,
        inactividad_seg=INACTIVIDAD,
        renovar=False,
    )

    assert vida is VidaDeSesion.VIVA
    assert cache.renovaciones == []


# --------------------------------------------------------------------------- #
# Abrir y olvidar
# --------------------------------------------------------------------------- #


async def test_abrir_falla_ruidosamente_si_no_se_puede_anotar() -> None:
    """Una sesión sin anotación responde 401 en la petición siguiente: es mejor fallar al entrar."""
    cache = CacheFalso(falla=True)

    with pytest.raises(RuntimeError):
        await abrir(cache, sesion_id=uuid4(), usuario_id=USUARIO, inactividad_seg=INACTIVIDAD)


async def test_olvidar_borra_las_claves() -> None:
    primera, segunda = uuid4(), uuid4()
    cache = CacheFalso()

    await olvidar(cache, sesion_ids=[primera, segunda])

    assert cache.borradas == [clave_de_sesion(primera), clave_de_sesion(segunda)]


async def test_olvidar_falla_ruidosamente_si_no_se_puede_borrar() -> None:
    """Dejar la clave viva es el peor final de un cierre: decir que se cierra y no cerrarlo."""
    cache = CacheFalso(falla=True)

    with pytest.raises(RuntimeError):
        await olvidar(cache, sesion_ids=[uuid4()])


async def test_olvidar_sin_almacen_no_hace_nada() -> None:
    await olvidar(CacheFalso(habilitada=False), sesion_ids=[uuid4()])


# --------------------------------------------------------------------------- #
# El envoltorio
# --------------------------------------------------------------------------- #


def _envoltorio(
    cache: CacheFalso,
    *,
    orden: list[str] | None = None,
    vigentes: list[Sesion] | None = None,
) -> tuple[SesionesConVida, SesionesFalsas]:
    interno = SesionesFalsas(orden=orden, vigentes=vigentes)
    return SesionesConVida(interno, cache, inactividad_seg=INACTIVIDAD), interno


async def test_crear_anota_la_sesion_despues_de_registrarla() -> None:
    """El orden no es indiferente: una clave sin fila sería una sesión que nadie puede revocar."""
    orden: list[str] = []
    cache = CacheFalso()
    envuelto, interno = _envoltorio(cache, orden=orden)
    sesion_id = uuid4()

    await envuelto.crear(
        sesion_id=sesion_id,
        negocio_id=NEGOCIO,
        usuario_id=USUARIO,
        refresh_hash="h",
        expira_en=AHORA,
        momento=AHORA,
    )

    assert interno.creadas == [sesion_id]
    assert cache.contenido[clave_de_sesion(sesion_id)] == valor_de_sesion(USUARIO)


async def test_crear_anota_con_el_plazo_de_inactividad() -> None:
    cache = CacheFalso()
    envuelto, _ = _envoltorio(cache)
    sesion_id = uuid4()

    await envuelto.crear(
        sesion_id=sesion_id,
        negocio_id=NEGOCIO,
        usuario_id=USUARIO,
        refresh_hash="h",
        expira_en=AHORA,
        momento=AHORA,
    )

    assert cache.ttls[clave_de_sesion(sesion_id)] == INACTIVIDAD


async def test_rotar_no_toca_la_clave() -> None:
    """Es la prueba que protege el cierre por inactividad de una pestaña olvidada.

    Una pestaña sin nadie delante renueva su token cada cuarto de hora porque el latido recibe un
    401 y el cliente renueva en silencio. Si el refresco rearmara el plazo, esa pestaña no se
    cerraría jamás.
    """
    sesion_id = uuid4()
    cache = CacheFalso()
    envuelto, interno = _envoltorio(cache)

    await envuelto.rotar(
        negocio_id=NEGOCIO, sesion_id=sesion_id, refresh_hash="h", ultimo_uso_en=AHORA
    )

    assert interno.rotadas == [sesion_id]
    assert cache.contenido == {}
    assert cache.renovaciones == []
    assert cache.borradas == []


async def test_revocar_una_borra_su_clave() -> None:
    sesion_id = uuid4()
    cache = CacheFalso(inicial={clave_de_sesion(sesion_id): valor_de_sesion(USUARIO)})
    envuelto, _ = _envoltorio(cache)

    await envuelto.revocar(
        negocio_id=NEGOCIO, sesion_id=sesion_id, motivo=MotivoRevocacion.LOGOUT, momento=AHORA
    )

    assert cache.borradas == [clave_de_sesion(sesion_id)]


async def test_revocar_varias_borra_todas_las_claves() -> None:
    """Es el camino de la expulsión por superar el máximo de sesiones."""
    primera, segunda = uuid4(), uuid4()
    cache = CacheFalso(
        inicial={
            clave_de_sesion(primera): valor_de_sesion(USUARIO),
            clave_de_sesion(segunda): valor_de_sesion(USUARIO),
        }
    )
    envuelto, _ = _envoltorio(cache)

    await envuelto.revocar_varias(
        negocio_id=NEGOCIO,
        sesion_ids=[primera, segunda],
        motivo=MotivoRevocacion.EVICCION,
        momento=AHORA,
    )

    assert set(cache.borradas) == {clave_de_sesion(primera), clave_de_sesion(segunda)}
    assert cache.contenido == {}


async def test_revocar_todas_borra_las_de_la_cuenta() -> None:
    """Es el camino del cambio de contraseña y del reuso de token detectado."""
    primera, segunda = uuid4(), uuid4()
    vigentes = [_sesion(primera), _sesion(segunda)]
    cache = CacheFalso(
        inicial={
            clave_de_sesion(primera): valor_de_sesion(USUARIO),
            clave_de_sesion(segunda): valor_de_sesion(USUARIO),
        }
    )
    envuelto, interno = _envoltorio(cache, vigentes=vigentes)

    revocadas = await envuelto.revocar_todas(
        negocio_id=NEGOCIO,
        usuario_id=USUARIO,
        motivo=MotivoRevocacion.REUSO_DETECTADO,
        momento=AHORA,
    )

    assert revocadas == 2
    assert interno.revocadas_varias == [[primera, segunda]]
    assert cache.contenido == {}


async def test_revocar_todas_salvo_conserva_la_clave_de_la_sesion_actual() -> None:
    """Quien cambia su contraseña no puede echarse a sí mismo."""
    actual, otra = uuid4(), uuid4()
    vigentes = [_sesion(otra), _sesion(actual)]
    cache = CacheFalso(
        inicial={
            clave_de_sesion(actual): valor_de_sesion(USUARIO),
            clave_de_sesion(otra): valor_de_sesion(USUARIO),
        }
    )
    envuelto, interno = _envoltorio(cache, vigentes=vigentes)

    revocadas = await envuelto.revocar_todas_salvo(
        negocio_id=NEGOCIO,
        usuario_id=USUARIO,
        excepto=actual,
        motivo=MotivoRevocacion.ADMIN,
        momento=AHORA,
    )

    assert revocadas == 1
    assert interno.revocadas_varias == [[otra]]
    assert set(cache.contenido) == {clave_de_sesion(actual)}
