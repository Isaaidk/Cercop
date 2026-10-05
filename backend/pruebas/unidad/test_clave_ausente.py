"""Pruebas de la clave de sesión que desaparece del almacén.

El caso que resuelve este archivo se veía desde fuera como «de vez en cuando me saca y no entiendo
por qué, si eso está puesto para ocho horas». La causa: el sistema daba por hecho que **lo único**
que borra la clave de una sesión sin cambiar su estado es el plazo de inactividad. No es cierto —una
política de memoria que desaloje claves, un reinicio del almacén o un cambio de instancia también la
borran— y cuando pasaba, se echaba a la persona diciéndole que había estado inactiva, que era falso.

La decisión que se comprueba aquí distingue los dos finales: si la sesión se usó hace poco, la clave
se perdió y se repone; si no se usó en todo el plazo, la inactividad hizo su trabajo y se cierra.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.puertos.cuentas import SesionGuardada
from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
from contratacion.dominio.errores import SesionRevocada
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion
from contratacion.dominio.sesiones_vivas import clave_de_sesion
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    _resolver_clave_ausente,
)

INACTIVIDAD = 480 * 60  # Las ocho horas del ajuste por defecto.

NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")
OTRO = UUID("44444444-4444-4444-4444-444444444444")
SESION = UUID("55555555-5555-5555-5555-555555555555")


def hace(segundos: int) -> datetime:
    """Un instante del pasado reciente, medido contra el reloj real.

    La función comprobada lee el reloj del sistema, así que las pruebas no pueden fijar una fecha:
    lo que importa es la **distancia** hasta el presente. Es la única forma de comprobarla sin
    inyectarle un instante que en producción no existe.
    """
    return datetime.now(UTC) - timedelta(seconds=segundos)


class CacheFalso:
    """Almacén en memoria que apunta el tiempo de vida de lo que se guarda."""

    habilitada = True

    def __init__(self, *, falla_al_guardar: bool = False) -> None:
        self.contenido: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self._falla_al_guardar = falla_al_guardar

    async def obtener(self, clave: str) -> str | None:
        return self.contenido.get(clave)

    async def obtener_renovando(self, clave: str, ttl_seg: int) -> str | None:
        return self.contenido.get(clave)

    async def guardar(self, clave: str, valor: str, ttl_seg: int) -> None:
        if self._falla_al_guardar:
            raise RuntimeError("el almacén no responde")
        self.contenido[clave] = valor
        self.ttls[clave] = ttl_seg

    async def eliminar(self, clave: str) -> None:
        self.contenido.pop(clave, None)

    async def incrementar(self, clave: str) -> int:
        raise AssertionError("la comprobación de la sesión no incrementa contadores")

    async def ping(self) -> bool:
        return True

    async def cerrar(self) -> None:
        return None


class SesionesFalsas:
    """Repositorio que solo sabe leer una sesión por identificador, filtrando por negocio.

    Reproduce el filtro por negocio del repositorio real. Un doble que lo omitiera daría por bueno
    un camino que en producción no existe.
    """

    def __init__(self, guardada: SesionGuardada | None) -> None:
        self.guardada = guardada
        self.consultas = 0

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        self.consultas += 1
        if self.guardada is None:
            return None
        if self.guardada.sesion.negocio_id != negocio_id or self.guardada.sesion.id != sesion_id:
            return None
        return self.guardada


def _claims() -> Claims:
    return Claims(
        usuario_id=USUARIO,
        negocio_id=NEGOCIO,
        rol="consultor",
        sesion_id=SESION,
        tipo=TipoToken.ACCESO,
        expira_en=hace(-900),
    )


def _guardada(
    *,
    ultimo_uso: datetime,
    estado: EstadoSesion = EstadoSesion.ACTIVA,
    motivo: MotivoRevocacion | None = None,
    usuario_id: UUID = USUARIO,
    negocio_id: UUID = NEGOCIO,
    expira_en: datetime | None = None,
) -> SesionGuardada:
    return SesionGuardada(
        sesion=Sesion(
            id=SESION,
            usuario_id=usuario_id,
            negocio_id=negocio_id,
            creada_en=hace(86_400),
            ultimo_uso_en=ultimo_uso,
            expira_en=expira_en or (datetime.now(UTC) + timedelta(days=30)),
            estado=estado,
            motivo_revocacion=motivo,
        ),
        refresh_hash="huella",
    )


async def resolver(
    guardada: SesionGuardada | None, *, falla_al_guardar: bool = False
) -> tuple[CacheFalso, SesionesFalsas]:
    """Ejecuta la comprobación y devuelve los dobles para poder mirarlos después."""
    cache = CacheFalso(falla_al_guardar=falla_al_guardar)
    sesiones = SesionesFalsas(guardada)
    await _resolver_clave_ausente(
        cache=cache,
        sesiones=sesiones,
        claims=_claims(),
        inactividad_seg=INACTIVIDAD,
    )
    return cache, sesiones


# --------------------------------------------------------------------------- #
# La clave perdida mientras la persona trabajaba
# --------------------------------------------------------------------------- #


async def test_una_clave_perdida_con_la_sesion_en_uso_se_repone() -> None:
    """Es el caso que sacaba a la gente del panel sin motivo.

    La sesión se usó hace un minuto, o sea que la persona estaba trabajando, y la clave ya no está.
    Eso no es inactividad: es que el almacén la perdió. Se repone y se la deja pasar.
    """
    cache, sesiones = await resolver(_guardada(ultimo_uso=hace(60)))

    assert sesiones.consultas == 1, "se pregunta a la base, porque el almacén no supo responder"
    assert cache.contenido[clave_de_sesion(SESION)] == str(USUARIO)


async def test_la_clave_repuesta_no_alarga_el_plazo() -> None:
    """El detalle que impide que la sesión se vuelva inmortal.

    Si al reponer se guardara el plazo entero, cada pérdida desplazaría el vencimiento hacia delante
    y una sesión que se pierde de vez en cuando acabaría sin cerrarse nunca por inactividad. Se
    guarda **lo que queda**, contado desde el último uso real: con una hora ya gastada de ocho, se
    reponen siete.
    """
    gastado = 3600
    cache, _ = await resolver(_guardada(ultimo_uso=hace(gastado)))

    ttl = cache.ttls[clave_de_sesion(SESION)]
    assert INACTIVIDAD - gastado - 5 <= ttl <= INACTIVIDAD - gastado + 5


async def test_la_sesion_que_casi_agoto_el_plazo_repone_muy_poco() -> None:
    """El extremo del cálculo anterior, que es donde un error se notaría.

    Queda un segundo de plazo: se repone un segundo, no ocho horas. Si aquí se repusiera el plazo
    completo, la comprobación no serviría de nada justo cuando más importa.
    """
    cache, _ = await resolver(_guardada(ultimo_uso=hace(INACTIVIDAD - 1)))

    assert cache.ttls[clave_de_sesion(SESION)] <= 2


# --------------------------------------------------------------------------- #
# Los cierres de verdad
# --------------------------------------------------------------------------- #


async def test_pasado_el_plazo_sin_usarse_la_sesion_se_cierra() -> None:
    """La inactividad sigue cerrando sesiones, que es para lo que está.

    Ocho horas y un minuto sin que nadie pida nada: la clave se había ido por su tiempo de vida y la
    sesión se cierra con su motivo. Reponerla aquí convertiría el plazo en decorativo.
    """
    with pytest.raises(SesionRevocada) as fallo:
        await resolver(_guardada(ultimo_uso=hace(INACTIVIDAD + 60)))

    assert fallo.value.motivo == "inactividad"


async def test_una_sesion_revocada_se_cierra_con_su_motivo() -> None:
    """Una revocación no se repone: si un administrador cerró la sesión, cerró la sesión."""
    with pytest.raises(SesionRevocada) as fallo:
        await resolver(
            _guardada(
                ultimo_uso=hace(30),
                estado=EstadoSesion.REVOCADA,
                motivo=MotivoRevocacion.ADMIN,
            )
        )

    assert fallo.value.motivo == "admin"


async def test_una_sesion_que_ya_no_existe_se_cierra() -> None:
    """La fila desapareció: no hay nada que reponer."""
    with pytest.raises(SesionRevocada) as fallo:
        await resolver(None)

    assert fallo.value.motivo == "inexistente"


async def test_la_sesion_de_otra_persona_no_se_anuncia_distinto() -> None:
    """Ser de otro y no existir dan el mismo mensaje.

    Distinguirlos permitiría averiguar qué sesiones existen probando identificadores, que es
    información de otra cuenta.
    """
    with pytest.raises(SesionRevocada) as ajena:
        await resolver(_guardada(usuario_id=OTRO, ultimo_uso=hace(30)))

    assert ajena.value.motivo == "inexistente"


async def test_un_negocio_que_no_es_el_del_token_se_rechaza() -> None:
    """El negocio sale del token, nunca de la fila (regla R-04)."""
    with pytest.raises(SesionRevocada):
        await resolver(_guardada(ultimo_uso=hace(30), negocio_id=uuid4()))


async def test_una_sesion_pasada_de_fecha_se_cierra_aunque_se_usara_ayer() -> None:
    """El vencimiento absoluto del token manda sobre el último uso.

    Es la segunda red: una sesión puede usarse hasta el final y caducar igualmente, porque el token
    de renovación tiene su propia fecha. Mirar solo el último uso la dejaría viva para siempre.
    """
    with pytest.raises(SesionRevocada) as fallo:
        await resolver(_guardada(ultimo_uso=hace(60), expira_en=hace(10)))

    assert fallo.value.motivo == "expirada"


async def test_un_almacen_que_no_deja_guardar_no_disimula_el_fallo() -> None:
    """Si el almacén falla, la reposición no se puede completar, y eso se nota.

    Silenciarlo daría por buena una sesión que no se ha podido anotar y la siguiente petición
    volvería a preguntar a la base; se prefiere el error visible a la apariencia de que todo va
    bien.
    """
    with pytest.raises(RuntimeError):
        await resolver(_guardada(ultimo_uso=hace(60)), falla_al_guardar=True)


async def test_la_fila_leida_no_se_toca_al_reponer() -> None:
    """Reponer es escribir la clave, nada más: no se reescribe la sesión ni su último uso.

    Si al reponer se actualizara `ultimo_uso_en`, cada pérdida de la clave contaría como actividad y
    la sesión de una pestaña olvidada no se cerraría jamás.
    """
    guardada = _guardada(ultimo_uso=hace(120))
    antes = (
        guardada.sesion.ultimo_uso_en,
        guardada.sesion.estado,
        guardada.sesion.expira_en,
    )

    await resolver(guardada)

    assert (
        guardada.sesion.ultimo_uso_en,
        guardada.sesion.estado,
        guardada.sesion.expira_en,
    ) == antes
