"""Pruebas de las reglas de acceso a vistas.

Estas pruebas defienden el modelo de suscripción y, sobre todo, la postura de seguridad. Las tres
que importan de verdad:

- `test_el_acceso_vencido_no_esta_vigente` — el vencimiento se comprueba al leer, no con un proceso
  que lo marque. Si esta prueba fallara, un acceso caducado seguiría abierto hasta que alguien se
  acordara de ejecutar la limpieza.
- `test_extender_nunca_acorta` — renovar es añadir, no sobrescribir. Un administrador que renueva no
  puede quitarle días sin querer a quien ya había pagado.
- `test_el_administrador_no_puede_actuar_sobre_otro_negocio` — es la primera barrera del
  aislamiento; la segunda la pone la base de datos con RLS.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from contratacion.dominio.acceso import (
    AccesoVista,
    Plazo,
    Vista,
    clave_permiso,
    concesion_vigente,
    generacion_de_acceso,
    negocio_objetivo,
    plazo_desde_codigo,
    puede_gestionar,
    puede_ver,
    tablero,
    vista_desde_codigo,
)
from contratacion.dominio.errores import ErrorDominio, SinPermiso

ENERO_31 = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)
ENERO_1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _acceso(
    vista: Vista = Vista.NECESIDADES,
    desde: datetime = ENERO_1,
    dias: int = 30,
    plazo: Plazo = Plazo.D30,
    revocado_en: datetime | None = None,
) -> AccesoVista:
    return AccesoVista(
        vista=vista,
        otorgado_en=desde,
        vence_en=desde + timedelta(days=dias),
        plazo=plazo,
        revocado_en=revocado_en,
    )


# --------------------------------------------------------------------------- #
# Cálculo del vencimiento
# --------------------------------------------------------------------------- #


def test_siete_dias_es_una_duracion_exacta() -> None:
    assert Plazo.D7.calcular(ENERO_1) == ENERO_1 + timedelta(days=7)


def test_treinta_dias_es_una_duracion_no_un_mes() -> None:
    """«30 días» es una cifra comercial: se cuentan 30 días de 24 horas, no un mes de calendario."""
    assert Plazo.D30.calcular(ENERO_1) == datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def test_tres_meses_desde_el_31_de_enero_terminan_el_30_de_abril() -> None:
    """Sin ajustar el día, el 31 de enero más tres meses desbordaría a marzo.

    Es el error clásico al sumar meses con una fecha fija: `replace(month=4)` con día 31 lanza una
    excepción, y sumar 90 días se iría al 1 de mayo. La regla correcta es el último día del mes de
    destino, que es lo que hace `Plazo.calcular`.
    """
    assert Plazo.M3.calcular(ENERO_31) == datetime(2026, 4, 30, 12, 0, tzinfo=UTC)


def test_seis_meses_desde_agosto_terminan_en_febrero_del_ano_siguiente() -> None:
    agosto = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
    assert Plazo.M6.calcular(agosto) == datetime(2027, 2, 15, 9, 0, tzinfo=UTC)


def test_un_ano_desde_el_29_de_febrero_termina_el_28() -> None:
    """2024 es bisiesto y 2025 no: el aniversario tiene que ser una fecha real."""
    bisiesto = datetime(2024, 2, 29, 8, 0, tzinfo=UTC)
    assert Plazo.A1.calcular(bisiesto) == datetime(2025, 2, 28, 8, 0, tzinfo=UTC)


def test_un_ano_conserva_el_mes_y_el_dia_cuando_existen() -> None:
    base = datetime(2026, 3, 10, 15, 30, tzinfo=UTC)
    assert Plazo.A1.calcular(base) == datetime(2027, 3, 10, 15, 30, tzinfo=UTC)


def test_los_plazos_largos_se_calculan_en_calendario() -> None:
    assert Plazo.M3.es_de_calendario
    assert Plazo.M6.es_de_calendario
    assert Plazo.A1.es_de_calendario
    assert not Plazo.D7.es_de_calendario
    assert not Plazo.D30.es_de_calendario


def test_se_ofrecen_exactamente_los_cinco_plazos_pedidos() -> None:
    assert [plazo.value for plazo in Plazo] == ["7d", "30d", "3m", "6m", "1a"]


def test_los_plazos_tienen_etiqueta_para_el_panel() -> None:
    assert Plazo.D7.etiqueta == "7 días"
    assert Plazo.A1.etiqueta == "1 año"


# --------------------------------------------------------------------------- #
# Catálogos cerrados
# --------------------------------------------------------------------------- #


def test_un_plazo_desconocido_se_rechaza() -> None:
    """No se cae a un valor por defecto: un código mal escrito no puede regalar una anualidad."""
    with pytest.raises(ErrorDominio):
        plazo_desde_codigo("99a")


def test_una_vista_desconocida_se_rechaza() -> None:
    with pytest.raises(ErrorDominio):
        vista_desde_codigo("facturacion")


def test_los_codigos_se_aceptan_sin_distinguir_mayusculas() -> None:
    assert plazo_desde_codigo(" 30D ") is Plazo.D30
    assert vista_desde_codigo("OFERTAS") is Vista.OFERTAS


def test_se_ofrecen_las_cuatro_vistas_del_panel() -> None:
    assert [vista.value for vista in Vista] == [
        "necesidades",
        "ofertas",
        "contrataciones",
        "graficas",
    ]


# --------------------------------------------------------------------------- #
# Vigencia
# --------------------------------------------------------------------------- #


def test_un_acceso_vigente_esta_vigente() -> None:
    assert _acceso().vigente(ENERO_1 + timedelta(days=1))


def test_el_acceso_vencido_no_esta_vigente() -> None:
    """El vencimiento se comprueba al leer: no depende de que ningún proceso lo marque."""
    acceso = _acceso(dias=30)
    assert not acceso.vigente(ENERO_1 + timedelta(days=31))


def test_el_acceso_retirado_no_esta_vigente_aunque_no_haya_vencido() -> None:
    retirado = _acceso(revocado_en=ENERO_1 + timedelta(days=1))
    assert not retirado.vigente(ENERO_1 + timedelta(days=2))


def test_el_instante_exacto_del_vencimiento_ya_no_concede() -> None:
    """La condición es `vence_en > ahora`: en el instante exacto, el acceso ya está cerrado."""
    acceso = _acceso(dias=30)
    assert not acceso.vigente(acceso.vence_en)


def test_sin_concesiones_no_hay_acceso() -> None:
    """Denegar por defecto: la ausencia de fila es la ausencia de permiso."""
    assert not puede_ver([], Vista.OFERTAS, ENERO_1)


# --------------------------------------------------------------------------- #
# Extensión
# --------------------------------------------------------------------------- #


def test_extender_nunca_acorta_el_acceso() -> None:
    """La concesión vigente es la de vencimiento más lejano, no la última que se creó.

    El administrador renueva y concede 7 días a quien ya tenía 30. El acceso no puede quedarse en 7:
    la renovación suma, no sustituye.
    """
    largo = _acceso(dias=30, plazo=Plazo.D30)
    corto = _acceso(dias=7, plazo=Plazo.D7)
    vigente = concesion_vigente([largo, corto], ENERO_1 + timedelta(days=1))
    assert vigente[Vista.NECESIDADES].vence_en == largo.vence_en


def test_la_concesion_mas_larga_manda_aunque_se_concediera_antes() -> None:
    corto = _acceso(dias=7, plazo=Plazo.D7)
    largo = _acceso(dias=365, plazo=Plazo.A1)
    vigente = concesion_vigente([largo, corto], ENERO_1 + timedelta(days=1))
    assert vigente[Vista.NECESIDADES].plazo is Plazo.A1


def test_cada_vista_tiene_su_propia_concesion() -> None:
    ofertas = _acceso(vista=Vista.OFERTAS, dias=7, plazo=Plazo.D7)
    graficas = _acceso(vista=Vista.GRAFICAS, dias=365, plazo=Plazo.A1)
    vigentes = concesion_vigente([ofertas, graficas], ENERO_1 + timedelta(days=1))
    assert set(vigentes) == {Vista.OFERTAS, Vista.GRAFICAS}
    assert puede_ver([ofertas, graficas], Vista.OFERTAS, ENERO_1 + timedelta(days=1))
    assert not puede_ver([ofertas, graficas], Vista.NECESIDADES, ENERO_1 + timedelta(days=1))


def test_una_concesion_vencida_no_tapa_a_una_vigente() -> None:
    vencida = _acceso(dias=1)
    vigente = _acceso(dias=30)
    resultado = concesion_vigente([vencida, vigente], ENERO_1 + timedelta(days=5))
    assert resultado[Vista.NECESIDADES].vence_en == vigente.vence_en


# --------------------------------------------------------------------------- #
# Días restantes y aviso
# --------------------------------------------------------------------------- #


def test_los_dias_restantes_redondean_hacia_arriba() -> None:
    """Doce horas restantes son «1 día» para quien tiene que renovar, no «0 días»."""
    acceso = _acceso(dias=1)
    momento = acceso.vence_en - timedelta(hours=12)
    assert acceso.dias_restantes(momento) == 1


def test_un_acceso_vencido_no_tiene_dias_restantes() -> None:
    acceso = _acceso(dias=1)
    assert acceso.dias_restantes(ENERO_1 + timedelta(days=10)) == 0


def test_avisa_cuando_esta_por_vencer() -> None:
    acceso = _acceso(dias=30)
    momento = acceso.vence_en - timedelta(days=5)
    assert acceso.por_vencer(momento, umbral_dias=7)


def test_no_avisa_cuando_queda_mucho() -> None:
    acceso = _acceso(dias=30)
    assert not acceso.por_vencer(ENERO_1 + timedelta(days=1), umbral_dias=7)


# --------------------------------------------------------------------------- #
# Tablero
# --------------------------------------------------------------------------- #


def test_el_tablero_incluye_todas_las_vistas_aunque_no_haya_acceso() -> None:
    """El panel necesita distinguir «sin acceso» de «vista inexistente»."""
    filas = tablero([], ENERO_1)
    assert len(filas) == len(list(Vista))
    assert all(not fila.vigente for fila in filas)


def test_el_tablero_marca_en_verde_lo_concedido_y_en_rojo_lo_demas() -> None:
    filas = tablero([_acceso(vista=Vista.OFERTAS)], ENERO_1 + timedelta(days=1))
    por_vista = {fila.vista: fila for fila in filas}
    assert por_vista[Vista.OFERTAS].vigente
    assert not por_vista[Vista.NECESIDADES].vigente


def test_el_tablero_lleva_la_etiqueta_y_los_dias_restantes() -> None:
    filas = tablero([_acceso(vista=Vista.OFERTAS, dias=5, plazo=Plazo.D30)], ENERO_1)
    fila = next(f for f in filas if f.vista is Vista.OFERTAS)
    assert fila.etiqueta == "Ofertas"
    assert fila.dias_restantes == 5
    assert fila.plazo is Plazo.D30
    assert fila.por_vencer


def test_el_tablero_no_marca_por_vencer_lo_que_no_esta_vigente() -> None:
    filas = tablero([_acceso(revocado_en=ENERO_1)], ENERO_1 + timedelta(days=1))
    assert all(not fila.por_vencer for fila in filas)


# --------------------------------------------------------------------------- #
# Autorización
# --------------------------------------------------------------------------- #


def test_los_roles_administrativos_pueden_gestionar() -> None:
    assert puede_gestionar("admin_negocio")
    assert puede_gestionar("super_admin")


def test_los_demas_roles_no_pueden_gestionar() -> None:
    assert not puede_gestionar("consultor")
    assert not puede_gestionar("lector")


def test_el_administrador_no_puede_actuar_sobre_otro_negocio() -> None:
    propio = uuid4()
    ajeno = uuid4()
    with pytest.raises(SinPermiso):
        negocio_objetivo("admin_negocio", propio, ajeno)


def test_el_administrador_actua_sobre_el_suyo_sin_indicarlo() -> None:
    propio = uuid4()
    assert negocio_objetivo("admin_negocio", propio, None) == propio


def test_el_administrador_puede_indicar_explicitamente_el_suyo() -> None:
    propio = uuid4()
    assert negocio_objetivo("admin_negocio", propio, propio) == propio


def test_el_super_administrador_puede_actuar_sobre_cualquier_negocio() -> None:
    ajeno = uuid4()
    assert negocio_objetivo("super_admin", uuid4(), ajeno) == ajeno


def test_el_super_administrador_sin_indicar_negocio_usa_el_suyo() -> None:
    propio = uuid4()
    assert negocio_objetivo("super_admin", propio, None) == propio


def test_un_consultor_no_puede_resolver_un_negocio() -> None:
    with pytest.raises(SinPermiso):
        negocio_objetivo("consultor", uuid4(), uuid4())


# --------------------------------------------------------------------------- #
# Claves de caché del permiso
# --------------------------------------------------------------------------- #


def test_la_generacion_de_acceso_es_propia_de_cada_usuario() -> None:
    uno, otro = uuid4(), uuid4()
    assert generacion_de_acceso(uno) != generacion_de_acceso(otro)


def test_la_clave_de_permiso_cambia_con_la_generacion() -> None:
    """Es lo que hace que retirar un acceso se note de inmediato y no al expirar el caché."""
    usuario = uuid4()
    assert clave_permiso(usuario, 1) != clave_permiso(usuario, 2)
