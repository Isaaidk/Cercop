"""Pruebas de los casos de uso de autenticación.

Se usan dobles en memoria de los cuatro puertos, así que no hace falta ni base de datos ni
criptografía real. Es lo que permite probar las reglas de seguridad —expulsión de la sesión más
antigua, detección de reutilización de token, bloqueo temporal— de forma rápida y determinista.

Lo que estas pruebas defienden, en una frase cada una:

- El mensaje de fallo es el mismo para todas las causas y no se puede averiguar qué correos existen.
- Al tercer inicio de sesión se expulsa la de **último uso** más lejano, no la más antigua.
- Renovar rota el token, y presentar uno viejo cierra **todas** las sesiones.
- Renovar a quien acaban de desactivar no deja la puerta abierta.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from contratacion.aplicacion.casos_uso.autenticar import (
    MENSAJE_CREDENCIALES,
    cerrar_sesion,
    iniciar_sesion,
    renovar_sesion,
)
from contratacion.aplicacion.puertos.cuentas import Cuenta, SesionGuardada
from contratacion.aplicacion.puertos.seguridad import Claims, TipoToken
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
HUELLA_DESCARTE = "falso:contrasena-de-descarte"
ACCESO_TTL = 900
REFRESCO_TTL = 86_400
MAX_SESIONES = 2
# Ventana en la que el token de renovación anterior sigue valiendo después de una rotación. Es la
# misma cifra que el ajuste por defecto del servidor: si aquí fuera otra, las pruebas dirían cosas
# que en producción no pasan.
GRACIA = 30


# --------------------------------------------------------------------------- #
# Dobles de los puertos
# --------------------------------------------------------------------------- #


class ContrasenasFalsas:
    """Derivación de mentira: reversible y reconocible a simple vista."""

    def __init__(self, *, rehash: bool = False) -> None:
        self.rehash = rehash
        self.verificaciones: list[str] = []

    def hash(self, texto: str) -> str:
        return f"falso:{texto}"

    def verificar(self, huella: str, texto: str) -> bool:
        self.verificaciones.append(huella)
        return huella == f"falso:{texto}"

    def necesita_rehash(self, huella: str) -> bool:
        return self.rehash


class TokensFalsos:
    """Tokens de mentira con la misma forma: texto legible con las declaraciones dentro."""

    def emitir(self, claims: Claims, ttl_seg: int) -> str:
        return "|".join(
            [
                str(claims.tipo),
                str(claims.usuario_id),
                str(claims.negocio_id),
                claims.rol,
                str(claims.sesion_id),
                str(int(claims.expira_en.timestamp())),
            ]
        )

    def verificar(self, token: str, tipo: TipoToken) -> Claims:
        partes = token.split("|")
        if len(partes) != 6 or partes[0] != str(tipo):
            raise SinPermiso("Token inservible.")
        return Claims(
            usuario_id=UUID(partes[1]),
            negocio_id=UUID(partes[2]),
            rol=partes[3],
            sesion_id=UUID(partes[4]),
            tipo=tipo,
            expira_en=datetime.fromtimestamp(int(partes[5]), tz=UTC),
        )

    def huella(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CuentasFalsas:
    """Repositorio de cuentas en memoria."""

    def __init__(self, cuentas: Sequence[Cuenta] = ()) -> None:
        self.cuentas = {cuenta.usuario_id: cuenta for cuenta in cuentas}
        self.auditoria: list[str] = []
        self.accesos_correctos = 0
        self.fallos_registrados = 0

    async def resolver(self, email: str) -> tuple[UUID, UUID] | None:
        for cuenta in self.cuentas.values():
            if cuenta.email.lower() == email.strip().lower():
                return cuenta.usuario_id, cuenta.negocio_id
        return None

    async def obtener(self, *, negocio_id: UUID, usuario_id: UUID) -> Cuenta | None:
        cuenta = self.cuentas.get(usuario_id)
        if cuenta is None or cuenta.negocio_id != negocio_id:
            return None
        return cuenta

    async def registrar_acceso_correcto(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> None:
        self.accesos_correctos += 1

    async def registrar_fallo(
        self,
        *,
        negocio_id: UUID,
        usuario_id: UUID,
        intentos: int,
        bloqueado_hasta: datetime | None,
    ) -> None:
        self.fallos_registrados += 1
        self.cuentas[usuario_id] = replace(
            self.cuentas[usuario_id],
            intentos_fallidos=intentos,
            bloqueado_hasta=bloqueado_hasta,
        )

    async def actualizar_huella(self, *, negocio_id: UUID, usuario_id: UUID, huella: str) -> None:
        self.cuentas[usuario_id] = replace(self.cuentas[usuario_id], hash_password=huella)

    async def cambiar_estado(
        self, *, negocio_id: UUID, usuario_id: UUID, estado: str, momento: datetime
    ) -> None:
        self.cuentas[usuario_id] = replace(self.cuentas[usuario_id], estado=estado)

    async def listar(
        self, *, negocio_id: UUID, estado: str | None = None
    ) -> Sequence[dict[str, Any]]:
        return [
            {"usuario_id": cuenta.usuario_id, "estado": cuenta.estado}
            for cuenta in self.cuentas.values()
            if cuenta.negocio_id == negocio_id
        ]

    async def auditar(
        self,
        *,
        accion: str,
        negocio_id: UUID,
        usuario_id: UUID | None = None,
        entidad: str | None = None,
        entidad_id: str | None = None,
        resultado: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        detalle: dict[str, Any] | None = None,
    ) -> None:
        self.auditoria.append(accion)


class SesionesFalsas:
    """Repositorio de sesiones en memoria."""

    def __init__(self) -> None:
        self.guardadas: dict[UUID, SesionGuardada] = {}
        self.revocaciones: list[tuple[int, MotivoRevocacion]] = []

    async def vigentes(
        self, *, negocio_id: UUID, usuario_id: UUID, momento: datetime
    ) -> Sequence[Sesion]:
        return [
            guardada.sesion
            for guardada in self.guardadas.values()
            if guardada.sesion.usuario_id == usuario_id
            and guardada.sesion.negocio_id == negocio_id
            and guardada.sesion.vigente(momento)
        ]

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
        self.guardadas[sesion_id] = SesionGuardada(
            sesion=Sesion(
                id=sesion_id,
                usuario_id=usuario_id,
                negocio_id=negocio_id,
                creada_en=momento,
                ultimo_uso_en=momento,
                expira_en=expira_en,
            ),
            refresh_hash=refresh_hash,
        )
        return sesion_id

    async def por_id(self, *, negocio_id: UUID, sesion_id: UUID) -> SesionGuardada | None:
        guardada = self.guardadas.get(sesion_id)
        if guardada is None or guardada.sesion.negocio_id != negocio_id:
            return None
        return guardada

    async def rotar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        refresh_hash: str,
        ultimo_uso_en: datetime,
    ) -> None:
        """Desplaza la huella igual que el repositorio real.

        Si el doble no guardara la anterior, el camino de la ventana de gracia no se podría recorrer
        nunca en una prueba: las que lo comprueban fallarían siempre, y no por un error del código
        sino porque el doble no se parece al original. Un doble que no imita lo que se está probando
        no prueba nada.
        """
        guardada = self.guardadas[sesion_id]
        self.guardadas[sesion_id] = replace(
            guardada,
            refresh_hash=refresh_hash,
            refresh_hash_anterior=guardada.refresh_hash,
            refresh_anterior_desde=ultimo_uso_en,
            sesion=replace(guardada.sesion, ultimo_uso_en=ultimo_uso_en),
        )

    async def revocar(
        self,
        *,
        negocio_id: UUID,
        sesion_id: UUID,
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> None:
        await self.revocar_varias(
            negocio_id=negocio_id, sesion_ids=[sesion_id], motivo=motivo, momento=momento
        )

    async def revocar_varias(
        self,
        *,
        negocio_id: UUID,
        sesion_ids: Sequence[UUID],
        motivo: MotivoRevocacion,
        momento: datetime,
    ) -> int:
        tocadas = 0
        for sesion_id in sesion_ids:
            guardada = self.guardadas.get(sesion_id)
            if guardada is None or guardada.sesion.estado is not EstadoSesion.ACTIVA:
                continue
            self.guardadas[sesion_id] = replace(
                guardada,
                sesion=replace(guardada.sesion, estado=EstadoSesion.REVOCADA),
            )
            tocadas += 1
        self.revocaciones.append((tocadas, motivo))
        return tocadas

    async def revocar_todas(
        self, *, negocio_id: UUID, usuario_id: UUID, motivo: MotivoRevocacion, momento: datetime
    ) -> int:
        ids = [
            guardada.sesion.id
            for guardada in self.guardadas.values()
            if guardada.sesion.usuario_id == usuario_id and guardada.sesion.negocio_id == negocio_id
        ]
        return await self.revocar_varias(
            negocio_id=negocio_id, sesion_ids=ids, motivo=motivo, momento=momento
        )


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _cuenta(
    *,
    negocio_id: UUID | None = None,
    email: str = "ana@constructora.ec",
    contrasena: str = "una-contrasena-larga",
    estado: str = "activo",
    rol: str = "admin_negocio",
    intentos: int = 0,
    bloqueado_hasta: datetime | None = None,
    politica: int | None = None,
) -> Cuenta:
    return Cuenta(
        usuario_id=uuid4(),
        negocio_id=negocio_id or uuid4(),
        email=email,
        nombre="Ana",
        rol=rol,
        estado=estado,
        hash_password=f"falso:{contrasena}",
        intentos_fallidos=intentos,
        bloqueado_hasta=bloqueado_hasta,
        debe_aceptar_politica_version=politica,
    )


def _piezas(cuenta: Cuenta | None = None) -> dict[str, Any]:
    return {
        "cuentas": CuentasFalsas([cuenta] if cuenta else []),
        "sesiones": SesionesFalsas(),
        "contrasenas": ContrasenasFalsas(),
        "tokens": TokensFalsos(),
    }


async def _entrar(
    cuenta: Cuenta,
    piezas: dict[str, Any],
    *,
    contrasena: str | None = None,
    momento: datetime | None = None,
) -> Any:
    return await iniciar_sesion(
        cuenta.email,
        contrasena or "una-contrasena-larga",
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        contrasenas=piezas["contrasenas"],
        tokens=piezas["tokens"],
        huella_descarte=HUELLA_DESCARTE,
        max_sesiones=MAX_SESIONES,
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        momento=momento or AHORA,
    )


# --------------------------------------------------------------------------- #
# Inicio de sesión
# --------------------------------------------------------------------------- #


async def test_un_inicio_correcto_devuelve_los_dos_tokens() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)

    resultado = await _entrar(cuenta, piezas)

    assert resultado.usuario_id == cuenta.usuario_id
    assert resultado.acceso.startswith("acceso|")
    assert resultado.refresco.startswith("refresco|")
    assert resultado.sesiones_abiertas == 1


async def test_al_iniciar_se_crea_una_sesion() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)

    resultado = await _entrar(cuenta, piezas)

    assert resultado.sesion_id in piezas["sesiones"].guardadas
    assert piezas["cuentas"].accesos_correctos == 1
    assert "sesion_iniciada" in piezas["cuentas"].auditoria


async def test_un_correo_desconocido_no_revela_que_no_existe() -> None:
    """El mensaje es el mismo que con la contraseña mal, y se gasta el mismo tiempo."""
    piezas = _piezas()

    with pytest.raises(SinPermiso) as fallo:
        await iniciar_sesion(
            "nadie@desconocido.ec",
            "lo-que-sea-largo",
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            contrasenas=piezas["contrasenas"],
            tokens=piezas["tokens"],
            huella_descarte=HUELLA_DESCARTE,
            max_sesiones=MAX_SESIONES,
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            momento=AHORA,
        )

    assert str(fallo.value) == MENSAJE_CREDENCIALES
    # Se comprobó contra la huella de descarte: sin esto, el tiempo delataría la causa.
    assert piezas["contrasenas"].verificaciones == [HUELLA_DESCARTE]


async def test_una_contrasena_incorrecta_no_dice_cual_es_el_motivo() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)

    with pytest.raises(SinPermiso) as fallo:
        await _entrar(cuenta, piezas, contrasena="otra-cosa-larga")

    assert str(fallo.value) == MENSAJE_CREDENCIALES
    assert piezas["cuentas"].fallos_registrados == 1
    assert piezas["sesiones"].guardadas == {}


async def test_los_fallos_repetidos_bloquean_la_cuenta_temporalmente() -> None:
    from contratacion.dominio.credenciales import INTENTOS_ANTES_DE_BLOQUEO

    cuenta = _cuenta(intentos=INTENTOS_ANTES_DE_BLOQUEO - 1)
    piezas = _piezas(cuenta)

    with pytest.raises(SinPermiso):
        await _entrar(cuenta, piezas, contrasena="otra-cosa-larga")

    bloqueada = piezas["cuentas"].cuentas[cuenta.usuario_id]
    assert bloqueada.bloqueado_hasta is not None
    assert bloqueada.bloqueado_hasta > AHORA


async def test_una_cuenta_bloqueada_lo_dice_si_la_contrasena_es_correcta() -> None:
    """Quien conoce la contraseña ya sabía que la cuenta existe: merece un mensaje útil."""
    cuenta = _cuenta(bloqueado_hasta=AHORA + timedelta(minutes=10))
    piezas = _piezas(cuenta)

    with pytest.raises(SinPermiso) as fallo:
        await _entrar(cuenta, piezas)

    assert "bloqueada" in str(fallo.value).lower()
    assert piezas["sesiones"].guardadas == {}


async def test_una_cuenta_inactiva_no_revela_su_estado() -> None:
    cuenta = _cuenta(estado="inactivo")
    piezas = _piezas(cuenta)

    with pytest.raises(SinPermiso) as fallo:
        await _entrar(cuenta, piezas)

    assert str(fallo.value) != MENSAJE_CREDENCIALES
    assert "inactivo" not in str(fallo.value).lower()
    assert piezas["sesiones"].guardadas == {}


async def test_una_cuenta_pendiente_puede_entrar_para_aceptar_los_terminos() -> None:
    """Es la única forma de que un usuario recién creado llegue a la pantalla de aceptación."""
    cuenta = _cuenta(estado="pendiente", politica=1)
    piezas = _piezas(cuenta)

    resultado = await _entrar(cuenta, piezas)

    assert resultado.debe_aceptar_terminos
    assert resultado.debe_aceptar_politica_version == 1


async def test_sin_politica_pendiente_no_hace_falta_aceptar() -> None:
    cuenta = _cuenta(politica=None)
    piezas = _piezas(cuenta)

    resultado = await _entrar(cuenta, piezas)
    assert not resultado.debe_aceptar_terminos


async def test_una_huella_antigua_se_recalcula_al_entrar() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    piezas["contrasenas"].rehash = True

    await _entrar(cuenta, piezas)

    actualizada = piezas["cuentas"].cuentas[cuenta.usuario_id]
    assert actualizada.hash_password.startswith("falso:")


# --------------------------------------------------------------------------- #
# Límite de sesiones simultáneas
# --------------------------------------------------------------------------- #


async def test_la_tercera_sesion_expulsa_la_de_ultimo_uso_mas_lejano() -> None:
    """No la más antigua por creación: la que el usuario tiene delante no se toca."""
    cuenta = _cuenta()
    piezas = _piezas(cuenta)

    primera = await _entrar(cuenta, piezas, momento=AHORA - timedelta(hours=2))
    segunda = await _entrar(cuenta, piezas, momento=AHORA - timedelta(minutes=5))
    # El último uso lo fija el momento del inicio de sesión, así que la primera ya es la que lleva
    # más tiempo sin usarse aunque se creara antes. Es justo el caso que hay que resolver.

    tercera = await _entrar(cuenta, piezas)

    assert tercera.sesiones_expulsadas == 1
    assert piezas["sesiones"].guardadas[primera.sesion_id].sesion.estado is EstadoSesion.REVOCADA
    assert piezas["sesiones"].guardadas[segunda.sesion_id].sesion.estado is EstadoSesion.ACTIVA
    assert (1, MotivoRevocacion.EVICCION) in piezas["sesiones"].revocaciones


async def test_con_una_sola_sesion_abierta_no_se_expulsa_nada() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)

    await _entrar(cuenta, piezas)
    segunda = await _entrar(cuenta, piezas)

    assert segunda.sesiones_expulsadas == 0


# --------------------------------------------------------------------------- #
# Renovación
# --------------------------------------------------------------------------- #


async def test_renovar_devuelve_un_par_nuevo_y_rota_el_token() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)

    renovada = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=5),
    )

    assert renovada.refresco != inicial.refresco
    assert renovada.sesion_id == inicial.sesion_id
    guardada = piezas["sesiones"].guardadas[inicial.sesion_id]
    assert guardada.refresh_hash == piezas["tokens"].huella(renovada.refresco)
    # La huella que acaba de dejar de ser la vigente se conserva: es lo que permite reconocer un
    # reintento en los segundos siguientes.
    assert guardada.refresh_hash_anterior == piezas["tokens"].huella(inicial.refresco)


async def test_presentar_un_token_de_renovacion_viejo_cierra_todo() -> None:
    """Es la detección de reutilización, y es la prueba más importante de este archivo.

    Si alguien conserva una copia del token anterior y la usa **cuando ya no puede ser un
    reintento**, hay dos copias en circulación y no se puede saber cuál es la legítima. Se cierra
    todo y el dueño vuelve a entrar con su contraseña.
    """
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=1),
    )

    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.refresco,  # el viejo, rotado hace un minuto: fuera de la ventana
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            tokens=piezas["tokens"],
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            gracia_seg=GRACIA,
            momento=AHORA + timedelta(minutes=2),
        )

    assert piezas["sesiones"].guardadas[inicial.sesion_id].sesion.estado is EstadoSesion.REVOCADA
    assert "reuso_de_token_detectado" in piezas["cuentas"].auditoria


async def test_un_reintento_inmediato_no_cierra_la_sesion() -> None:
    """La respuesta perdida no puede echar a nadie de su cuenta.

    Es el fallo que se veía en producción: el servidor rota el token, la respuesta no llega —se
    corta la conexión, se duerme el portátil— y el navegador reintenta con el viejo. Con detección
    estricta eso cerraba **todas** las sesiones de la cuenta y el usuario aparecía en la pantalla de
    acceso con un aviso que hablaba de tokens. Pasó tres veces en un día.
    """
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    primera = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=1),
    )

    # El reintento llega diez segundos después, con el token que ya no es el vigente.
    segunda = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=1, seconds=10),
    )

    guardada = piezas["sesiones"].guardadas[inicial.sesion_id]
    assert guardada.sesion.estado is EstadoSesion.ACTIVA
    assert "reuso_de_token_detectado" not in piezas["cuentas"].auditoria
    # Al reintento no se le devuelve el par del primero: se le emite uno nuevo y **se desplaza la
    # huella otra vez**, de modo que el par que sí llegó a su destino sigue sirviendo. Sin esto, el
    # cliente que recibió la respuesta buena se quedaría con un token que ya no valdría.
    assert segunda.refresco != primera.refresco
    assert guardada.refresh_hash_anterior == piezas["tokens"].huella(primera.refresco)


async def test_el_par_que_si_llego_sigue_sirviendo_tras_el_reintento() -> None:
    """Las dos copias conviven durante la ventana, que es justo lo que se busca.

    Es el caso de la segunda pestaña del mismo navegador: tiene el token viejo, lo presenta, y en
    lugar de cerrar la cuenta entera se le atiende. Y el que ya estaba renovado tampoco se queda
    fuera.
    """
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    primera = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA,
    )
    segunda = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(seconds=5),
    )

    # Y ahora la pestaña primera vuelve a renovar con el par que recibió. Sigue dentro de la ventana
    # contada desde la última rotación, así que se le atiende.
    tercera = await renovar_sesion(
        primera.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(seconds=20),
    )

    assert tercera.sesion_id == inicial.sesion_id
    assert segunda.refresco != tercera.refresco


async def test_con_la_ventana_apagada_el_reintento_vuelve_a_cerrar_todo() -> None:
    """Poner la gracia a cero restaura el comportamiento estricto.

    Se comprueba porque es la salida de emergencia: si algún día la ventana se considerara un riesgo
    demasiado grande, apagarla tiene que bastar, y eso hay que poder demostrarlo.

    Los dos instantes van separados **un minuto** a propósito. Rotar dentro del mismo segundo emite
    el mismo token —las declaraciones son idénticas—, así que la rotación no cambiaría nada y la
    prueba estaría comprobando algo distinto de lo que dice su nombre.
    """
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=0,
        momento=AHORA + timedelta(minutes=1),
    )

    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.refresco,
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            tokens=piezas["tokens"],
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            gracia_seg=0,
            momento=AHORA + timedelta(minutes=1, seconds=1),
        )

    assert piezas["sesiones"].guardadas[inicial.sesion_id].sesion.estado is EstadoSesion.REVOCADA


async def test_una_huella_de_otra_generacion_no_entra_por_la_ventana() -> None:
    """La ventana admite **la anterior**, no cualquier cosa que se parezca.

    Si admitiera más de una generación hacia atrás, un token robado y guardado seguiría sirviendo
    indefinidamente y la detección de reutilización no existiría.
    """
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    primera = await renovar_sesion(
        inicial.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=1),
    )
    # Se vuelve a rotar, así que el token inicial queda **dos** generaciones atrás.
    await renovar_sesion(
        primera.refresco,
        cuentas=piezas["cuentas"],
        sesiones=piezas["sesiones"],
        tokens=piezas["tokens"],
        acceso_ttl_seg=ACCESO_TTL,
        refresco_ttl_seg=REFRESCO_TTL,
        gracia_seg=GRACIA,
        momento=AHORA + timedelta(minutes=2),
    )

    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.refresco,
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            tokens=piezas["tokens"],
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            gracia_seg=GRACIA,
            momento=AHORA + timedelta(minutes=2, seconds=5),
        )


async def test_no_se_renueva_a_quien_acaban_de_desactivar() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)

    piezas["cuentas"].cuentas[cuenta.usuario_id] = replace(
        piezas["cuentas"].cuentas[cuenta.usuario_id], estado="inactivo"
    )

    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.refresco,
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            tokens=piezas["tokens"],
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            gracia_seg=GRACIA,
            momento=AHORA + timedelta(minutes=1),
        )

    assert piezas["sesiones"].guardadas[inicial.sesion_id].sesion.estado is EstadoSesion.REVOCADA


async def test_un_token_de_acceso_no_sirve_para_renovar() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)

    with pytest.raises(SinPermiso):
        await renovar_sesion(
            inicial.acceso,
            cuentas=piezas["cuentas"],
            sesiones=piezas["sesiones"],
            tokens=piezas["tokens"],
            acceso_ttl_seg=ACCESO_TTL,
            refresco_ttl_seg=REFRESCO_TTL,
            gracia_seg=GRACIA,
            momento=AHORA,
        )


# --------------------------------------------------------------------------- #
# Cierre
# --------------------------------------------------------------------------- #


async def test_cerrar_sesion_revoca_la_sesion_del_token() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)

    claims = piezas["tokens"].verificar(inicial.acceso, TipoToken.ACCESO)
    cerradas = await cerrar_sesion(
        claims,
        sesiones=piezas["sesiones"],
        cuentas=piezas["cuentas"],
        momento=AHORA + timedelta(minutes=1),
    )

    assert cerradas == 1
    assert piezas["sesiones"].guardadas[inicial.sesion_id].sesion.estado is EstadoSesion.REVOCADA
    assert "sesion_cerrada" in piezas["cuentas"].auditoria


async def test_el_cierre_por_ventana_queda_registrado_con_su_motivo() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)

    claims = piezas["tokens"].verificar(inicial.refresco, TipoToken.REFRESCO)
    await cerrar_sesion(
        claims,
        sesiones=piezas["sesiones"],
        cuentas=piezas["cuentas"],
        motivo=MotivoRevocacion.CIERRE_VENTANA,
        momento=AHORA,
    )

    assert (1, MotivoRevocacion.CIERRE_VENTANA) in piezas["sesiones"].revocaciones


async def test_cerrar_sin_sesiones_activas_no_falla() -> None:
    cuenta = _cuenta()
    piezas = _piezas(cuenta)
    inicial = await _entrar(cuenta, piezas)
    claims = piezas["tokens"].verificar(inicial.acceso, TipoToken.ACCESO)

    assert (
        await cerrar_sesion(
            claims, sesiones=piezas["sesiones"], cuentas=piezas["cuentas"], momento=AHORA
        )
        == 1
    )
    assert (
        await cerrar_sesion(
            claims, sesiones=piezas["sesiones"], cuentas=piezas["cuentas"], momento=AHORA
        )
        == 0
    )
