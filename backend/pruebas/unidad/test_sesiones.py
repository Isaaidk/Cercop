"""Pruebas de las reglas de sesiones simultáneas.

Lo que se defiende aquí es la decisión de producto que más se equivoca al implementar: expulsar la
sesión de **último uso** más lejano, no la creada primero. Si se ordenara por fecha de creación, el
usuario que entra desde un segundo dispositivo se quedaría sin la sesión que tiene delante.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from contratacion.dominio.sesiones import (
    MAX_SESIONES_ABSOLUTO,
    EstadoSesion,
    Sesion,
    sesion_mas_reciente,
    sesiones_a_expulsar,
)

AHORA = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _sesion(
    *,
    creada: datetime = AHORA,
    usado: datetime = AHORA,
    estado: EstadoSesion = EstadoSesion.ACTIVA,
    identificador: UUID | None = None,
) -> Sesion:
    return Sesion(
        id=identificador or uuid4(),
        usuario_id=uuid4(),
        negocio_id=uuid4(),
        creada_en=creada,
        ultimo_uso_en=usado,
        expira_en=AHORA + timedelta(days=30),
        estado=estado,
    )


def test_una_sesion_nueva_esta_vigente() -> None:
    assert _sesion().vigente(AHORA)


def test_una_sesion_revocada_no_esta_vigente() -> None:
    assert not _sesion(estado=EstadoSesion.REVOCADA).vigente(AHORA)


def test_una_sesion_caducada_no_esta_vigente() -> None:
    caducada = Sesion(
        id=uuid4(),
        usuario_id=uuid4(),
        negocio_id=uuid4(),
        creada_en=AHORA - timedelta(days=60),
        ultimo_uso_en=AHORA - timedelta(days=40),
        expira_en=AHORA - timedelta(seconds=1),
    )
    assert not caducada.vigente(AHORA)


def test_por_debajo_del_maximo_no_se_expulsa_a_nadie() -> None:
    assert sesiones_a_expulsar([_sesion()], 2) == ()


def test_sin_sesiones_no_se_expulsa_a_nadie() -> None:
    assert sesiones_a_expulsar([], 2) == ()


def test_al_llegar_al_maximo_hay_que_expulsar_una() -> None:
    vigentes = [_sesion(usado=AHORA - timedelta(hours=1)), _sesion()]
    assert len(sesiones_a_expulsar(vigentes, 2)) == 1


def test_se_expulsa_la_de_ultimo_uso_mas_lejano() -> None:
    la_que_estorba = _sesion(usado=AHORA - timedelta(hours=5))
    la_que_se_usa = _sesion(usado=AHORA - timedelta(minutes=1))

    a_expulsar = sesiones_a_expulsar([la_que_estorba, la_que_se_usa], 2)

    assert a_expulsar == (la_que_estorba.id,)


def test_la_creada_primero_se_conserva_si_se_usa_ahora() -> None:
    """El orden es por último uso, no por creación. Es la razón de ser de esta regla."""
    creada_antes_pero_en_uso = _sesion(
        creada=AHORA - timedelta(days=1), usado=AHORA - timedelta(seconds=30)
    )
    creada_despues_pero_abandonada = _sesion(
        creada=AHORA - timedelta(hours=2), usado=AHORA - timedelta(hours=1)
    )

    a_expulsar = sesiones_a_expulsar([creada_antes_pero_en_uso, creada_despues_pero_abandonada], 2)

    assert a_expulsar == (creada_despues_pero_abandonada.id,)


def test_con_tres_abiertas_se_expulsan_dos() -> None:
    vigentes = [_sesion(usado=AHORA - timedelta(hours=i)) for i in range(3)]
    assert len(sesiones_a_expulsar(vigentes, 2)) == 2


def test_un_maximo_absurdo_se_acota_por_arriba() -> None:
    """Un valor disparatado en la base no puede dejar al usuario sin poder entrar."""
    vigentes = [_sesion(usado=AHORA - timedelta(minutes=i)) for i in range(5)]
    assert sesiones_a_expulsar(vigentes, MAX_SESIONES_ABSOLUTO) == ()


def test_un_maximo_de_cero_se_trata_como_uno() -> None:
    assert len(sesiones_a_expulsar([_sesion()], 0)) == 1


def test_la_mas_reciente_es_la_de_uso_mas_nuevo() -> None:
    vieja = _sesion(usado=AHORA - timedelta(hours=3))
    nueva = _sesion(usado=AHORA - timedelta(seconds=5))
    assert sesion_mas_reciente([vieja, nueva]) is nueva


def test_sin_sesiones_no_hay_mas_reciente() -> None:
    assert sesion_mas_reciente([]) is None
