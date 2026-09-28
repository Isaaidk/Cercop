"""Pruebas de la regla de verde y rojo.

Lo que se defiende aquí no es una función, son dos afirmaciones que el panel le enseña a una
persona que decide con ellas:

- **Un verde nunca es falso.** Verde significa «está delante, ahora», y las dos pruebas que más
  importan son las que comprueban que ni la señal sola ni la sesión sola bastan. Fallar por arriba
  aquí es lo peor que puede hacer esta pantalla: alguien llama a un compañero que lleva media hora
  fuera.
- **Un rojo siempre se explica.** «No está» sin más obliga a preguntar por teléfono. Cada motivo que
  esta capa puede afirmar tiene su prueba, y el orden de preferencia entre ellos también, porque ahí
  es donde estaba el error interesante.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from contratacion.dominio.presencia import (
    DESCRIPCION_MOTIVO,
    EstadoPresencia,
    Latido,
    Motivo,
    Presencia,
    canal_de_negocio,
    clave_latido,
    evaluar_presencia,
    latido_vivo,
    latidos_vivos,
    prefijo_de_negocio,
)
from contratacion.dominio.sesiones import EstadoSesion, MotivoRevocacion, Sesion

AHORA = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
TTL = 60  # segundos de vigencia de una señal

USUARIO = UUID("11111111-1111-1111-1111-111111111111")
NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")


def _sesion(
    *,
    sesion_id: UUID | None = None,
    expira_en: datetime | None = None,
    estado: EstadoSesion = EstadoSesion.ACTIVA,
    motivo: MotivoRevocacion | None = None,
    ultimo_uso_en: datetime | None = None,
) -> Sesion:
    return Sesion(
        id=sesion_id or uuid4(),
        usuario_id=USUARIO,
        negocio_id=NEGOCIO,
        creada_en=AHORA - timedelta(hours=1),
        ultimo_uso_en=ultimo_uso_en or AHORA - timedelta(minutes=5),
        expira_en=expira_en or AHORA + timedelta(days=7),
        estado=estado,
        motivo_revocacion=motivo,
    )


def _evaluar(
    *,
    estado_cuenta: str = "activo",
    sesiones: list[Sesion] | None = None,
    latidos: list[Latido] | None = None,
    momento: datetime = AHORA,
) -> Presencia:
    return evaluar_presencia(
        usuario_id=USUARIO,
        estado_cuenta=estado_cuenta,
        sesiones=sesiones or [],
        latidos=latidos or [],
        momento=momento,
        ttl_seg=TTL,
    )


def _latido(sesion: Sesion, *, hace_seg: int = 0) -> Latido:
    momento = AHORA - timedelta(seconds=hace_seg)
    return Latido(usuario_id=USUARIO, sesion_id=sesion.id, momento=momento)


# --------------------------------------------------------------------------- #
# Hacen falta las dos cosas: señal y sesión
# --------------------------------------------------------------------------- #


def test_senal_viva_y_sesion_vigente_es_verde() -> None:
    sesion = _sesion()
    presencia = _evaluar(sesiones=[sesion], latidos=[_latido(sesion)])
    assert presencia.estado is EstadoPresencia.VERDE
    assert presencia.motivo is Motivo.CONECTADO
    assert presencia.sesion_id == sesion.id
    assert presencia.ultimo_latido_en == AHORA


def test_una_sesion_revocada_no_es_verde_aunque_siga_latiendo() -> None:
    """La prueba más importante del archivo.

    Si el color dependiera solo de la señal, revocar a alguien no tendría ningún efecto visible
    hasta que cerrara la pestaña. El administrador pulsa «cerrar sesión», el panel sigue en verde, y
    la herramienta le está diciendo que su acción no sirvió. Y no solo eso: mientras el navegador
    siguiera abierto, la persona ausente aparecería como presente.
    """
    sesion = _sesion(estado=EstadoSesion.REVOCADA, motivo=MotivoRevocacion.ADMIN)
    presencia = _evaluar(sesiones=[sesion], latidos=[_latido(sesion)])

    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.CIERRE_ADMIN


def test_una_sesion_caducada_no_es_verde_aunque_siga_latiendo() -> None:
    sesion = _sesion(expira_en=AHORA - timedelta(minutes=1))
    presencia = _evaluar(sesiones=[sesion], latidos=[_latido(sesion)])

    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.SESION_EXPIRADA


def test_una_sesion_sin_senal_no_es_verde() -> None:
    """Sin latido, la fila sigue en la base pero la persona se fue: ese es el caso del portátil
    apagado, y por eso la sesión sola no basta."""
    presencia = _evaluar(sesiones=[_sesion()], latidos=[])
    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.SIN_SENAL


def test_la_senal_de_otra_sesion_no_pone_en_verde_a_la_revocada() -> None:
    """El cruce es por identificador de sesión, no por usuario.

    Con dos dispositivos abiertos y uno de ellos revocado, mirar solo «¿hay alguna señal de este
    usuario?» daría verde. Hay que casar la señal con **su** sesión, que es justo lo que hace el
    diccionario de sesiones vigentes.
    """
    viva = _sesion()
    revocada = _sesion(estado=EstadoSesion.REVOCADA, motivo=MotivoRevocacion.ADMIN)

    # Solo llega la señal de la revocada; la viva no la tiene.
    presencia = _evaluar(sesiones=[viva, revocada], latidos=[_latido(revocada)])

    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.SIN_SENAL


# --------------------------------------------------------------------------- #
# Cómo expira una señal
# --------------------------------------------------------------------------- #


def test_una_senal_justo_dentro_de_su_vigencia_sigue_viva() -> None:
    sesion = _sesion()
    latido = _latido(sesion, hace_seg=TTL - 1)
    assert latido_vivo(latido, AHORA, TTL) is True


def test_una_senal_que_agoto_su_vigencia_esta_muerta() -> None:
    """El piso de detección: lo único que se puede saber si el navegador se cierra de golpe."""
    sesion = _sesion()
    latido = _latido(sesion, hace_seg=TTL)
    assert latido_vivo(latido, AHORA, TTL) is False


def test_el_rojo_por_senal_vencida_se_explica() -> None:
    """Y no se puede decir cuándo se le vio por última vez, porque ese dato ya no existe.

    La señal es una clave con caducidad: cuando vence, se borra. Conservar una copia con más vida
    —para poder mostrar «visto hace un minuto»— significaría mantener un registro de quién estuvo
    conectado y cuándo, que es exactamente el tipo de dato que no conviene acumular para ganar un
    detalle cosmético. El motivo del rojo ya explica lo que hace falta saber.
    """
    sesion = _sesion()
    presencia = _evaluar(sesiones=[sesion], latidos=[_latido(sesion, hace_seg=TTL + 1)])

    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.SIN_SENAL
    assert presencia.ultimo_latido_en is None
    assert presencia.dispositivos == 0


def test_las_senales_vivas_se_ordenan_de_la_mas_reciente_a_la_mas_vieja() -> None:
    a, b = _sesion(), _sesion()
    vivas = latidos_vivos([_latido(a, hace_seg=40), _latido(b, hace_seg=5)], AHORA, TTL)
    assert [latido.sesion_id for latido in vivas] == [b.id, a.id]


def test_las_senales_vencidas_no_aparecen_entre_las_vivas() -> None:
    a, b = _sesion(), _sesion()
    vivas = latidos_vivos([_latido(a, hace_seg=5), _latido(b, hace_seg=TTL + 1)], AHORA, TTL)
    assert [latido.sesion_id for latido in vivas] == [a.id]


# --------------------------------------------------------------------------- #
# Los motivos del rojo, y su orden de preferencia
# --------------------------------------------------------------------------- #


def test_sin_ninguna_sesion_el_motivo_es_que_nunca_entro() -> None:
    presencia = _evaluar(sesiones=[], latidos=[])
    assert presencia.motivo is Motivo.SIN_ACCESO


def test_una_sesion_abierta_sin_senal_le_gana_a_una_revocacion_antigua() -> None:
    """El error que casi se cuela, con su prueba.

    A alguien con la pestaña abierta y una expulsión de hace tres días se le habría explicado «entró
    desde otro dispositivo» cuando lo que pasa es que se le fue el wifi. Se informa de lo que sigue
    siendo cierto, no de lo que pasó alguna vez.
    """
    abierta = _sesion(ultimo_uso_en=AHORA - timedelta(minutes=1))
    antigua = _sesion(
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.EVICCION,
        ultimo_uso_en=AHORA - timedelta(days=3),
    )

    presencia = _evaluar(sesiones=[abierta, antigua], latidos=[])

    assert presencia.motivo is Motivo.SIN_SENAL


def test_sin_sesiones_abiertas_gana_lo_que_alguien_decidio() -> None:
    """Sin sesión abierta ya no hay duda: una revocación tiene responsable y explicación."""
    antigua = _sesion(
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.EVICCION,
        ultimo_uso_en=AHORA - timedelta(days=3),
    )
    presencia = _evaluar(sesiones=[antigua], latidos=[])
    assert presencia.motivo is Motivo.EVICCION


def test_entre_varias_revocaciones_se_explica_la_mas_reciente() -> None:
    vieja = _sesion(
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.LOGOUT,
        ultimo_uso_en=AHORA - timedelta(days=9),
    )
    reciente = _sesion(
        estado=EstadoSesion.REVOCADA,
        motivo=MotivoRevocacion.ADMIN,
        ultimo_uso_en=AHORA - timedelta(hours=2),
    )
    presencia = _evaluar(sesiones=[vieja, reciente], latidos=[])
    assert presencia.motivo is Motivo.CIERRE_ADMIN


def test_cada_motivo_de_revocacion_tiene_su_explicacion() -> None:
    """Ninguna revocación del catálogo puede quedar sin traducir: sería un rojo sin motivo."""
    casos = {
        MotivoRevocacion.LOGOUT: Motivo.SESION_CERRADA,
        MotivoRevocacion.CIERRE_VENTANA: Motivo.SESION_CERRADA,
        MotivoRevocacion.EVICCION: Motivo.EVICCION,
        MotivoRevocacion.ADMIN: Motivo.CIERRE_ADMIN,
        MotivoRevocacion.REUSO_DETECTADO: Motivo.SESION_CERRADA,
    }
    for motivo, esperado in casos.items():
        sesion = _sesion(estado=EstadoSesion.REVOCADA, motivo=motivo)
        assert _evaluar(sesiones=[sesion], latidos=[]).motivo is esperado


def test_todos_los_motivos_tienen_texto_para_mostrar() -> None:
    """Un motivo sin texto saldría como un hueco en la interfaz."""
    assert set(DESCRIPCION_MOTIVO) == set(Motivo)


def test_una_senal_sin_sesion_que_la_respalde_se_informa_como_cierre() -> None:
    # No puede quedar en verde ni decir «conectado» sin sesión vigente.
    sesion = _sesion()
    presencia = _evaluar(sesiones=[], latidos=[_latido(sesion)])

    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.SESION_CERRADA


# --------------------------------------------------------------------------- #
# La cuenta deshabilitada
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("estado", ["inactivo", "bloqueado"])
def test_una_cuenta_deshabilitada_es_roja_aunque_este_latiendo(estado: str) -> None:
    """Y esto importa operativamente: desactivar una cuenta tiene que apagar el punto **ya**.

    Es la forma más rápida que tiene un administrador de cortar un acceso indebido. Si el color
    esperase al latido, durante un minuto el panel seguiría diciendo que esa persona trabaja.
    """
    sesion = _sesion()
    presencia = _evaluar(estado_cuenta=estado, sesiones=[sesion], latidos=[_latido(sesion)])
    assert presencia.estado is EstadoPresencia.ROJO
    assert presencia.motivo is Motivo.CUENTA_INACTIVA


def test_un_usuario_pendiente_si_puede_estar_conectado() -> None:
    """Está pendiente de aceptar los términos, y entra precisamente para aceptarlos."""
    sesion = _sesion()
    presencia = _evaluar(estado_cuenta="pendiente", sesiones=[sesion], latidos=[_latido(sesion)])
    assert presencia.estado is EstadoPresencia.VERDE


# --------------------------------------------------------------------------- #
# Varios dispositivos
# --------------------------------------------------------------------------- #


def test_dos_dispositivos_se_cuentan_y_no_se_pisan() -> None:
    """Con una clave por sesión, cerrar el portátil no apaga el móvil."""
    portatil, movil = _sesion(), _sesion()
    presencia = _evaluar(sesiones=[portatil, movil], latidos=[_latido(portatil), _latido(movil)])
    assert presencia.estado is EstadoPresencia.VERDE
    assert presencia.dispositivos == 2


def test_con_la_senal_de_otro_dispositivo_no_se_cuenta_dos_veces() -> None:
    """Un dispositivo conectado nunca puede informar de dos."""
    portatil = _sesion()
    presencia = _evaluar(sesiones=[portatil], latidos=[_latido(portatil)])
    assert presencia.dispositivos == 1


def test_si_solo_uno_de_los_dos_late_sigue_conectado() -> None:
    portatil, movil = _sesion(), _sesion()
    presencia = _evaluar(
        sesiones=[portatil, movil],
        latidos=[_latido(portatil), _latido(movil, hace_seg=TTL + 1)],
    )
    assert presencia.estado is EstadoPresencia.VERDE
    assert presencia.dispositivos == 1


# --------------------------------------------------------------------------- #
# Las claves y el canal: dónde vive el aislamiento entre negocios
# --------------------------------------------------------------------------- #


def test_la_clave_de_una_senal_incluye_el_negocio() -> None:
    otro_negocio = uuid4()
    sesion = uuid4()
    assert clave_latido(NEGOCIO, sesion) != clave_latido(otro_negocio, sesion)


def test_el_prefijo_de_un_negocio_no_es_prefijo_de_otro() -> None:
    """Este es el aislamiento de verdad.

    Las señales se listan recorriendo claves por prefijo. Si el prefijo de un negocio pudiera ser el
    comienzo del de otro, un recorrido traería señales ajenas —y el fallo sería silencioso, porque
    llegarían identificadores que parecen válidos—. El prefijo termina en `:`, y un identificador
    nunca lo contiene, así que dos negocios distintos no pueden anidarse.
    """
    prefijo = prefijo_de_negocio(NEGOCIO)
    assert prefijo.endswith(":")
    assert prefijo_de_negocio(uuid4()).startswith(prefijo) is False


def test_cada_negocio_tiene_su_canal() -> None:
    assert canal_de_negocio(NEGOCIO) != canal_de_negocio(uuid4())


def test_la_descripcion_del_verde_lo_dice_claramente() -> None:
    assert "Conectado" in DESCRIPCION_MOTIVO[Motivo.CONECTADO]
