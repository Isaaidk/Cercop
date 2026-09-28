"""Pruebas de los datos de empresa.

Lo que se protege aquí es el **dígito verificador del RUC**. Un validador de RUC que solo cuente
trece dígitos deja pasar números inventados, y uno que tenga un coeficiente mal puesto **rechaza
empresas reales**: el registro queda bloqueado y el síntoma es «mi RUC es correcto y no me deja
entrar». Ninguno de los dos errores se ve leyendo el código.

Por eso las cuentas del dígito verificador están escritas en esta prueba **producto a
producto**, con los coeficientes a la vista, en lugar de recorrer la misma tabla que usa el
código. Si alguien cambia
un coeficiente en `dominio/negocios.py`, la suma de aquí sigue dando el valor que dice la
documentación del algoritmo y la comparación falla. Una prueba que reutilizara la tabla del código
daría por bueno cualquier cambio: comprobaría que el código coincide consigo mismo.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.negocios import (
    construir_datos_empresa,
    digito_verificador_ruc,
    limpiar_texto,
    normalizar_correo,
    normalizar_ruc,
    validar_ciudad,
    validar_correo,
    validar_direccion,
    validar_nombre,
    validar_ruc,
    validar_telefono,
)

# --------------------------------------------------------------------------- #
# Dígito verificador, calculado a mano
# --------------------------------------------------------------------------- #


def _ruc_de_sociedad(base: str) -> str:
    """RUC válido de sociedad: módulo 11 con los coeficientes del SRI escritos a mano.

    Los coeficientes de una sociedad son 4, 3, 2, 7, 6, 5, 4, 3, 2 sobre los nueve primeros dígitos.
    """
    suma = sum(
        int(digito) * int(coeficiente)
        for digito, coeficiente in zip(base, "432765432", strict=True)
    )
    residuo = suma % 11
    verificador = 11 - residuo
    if verificador == 11:
        verificador = 0
    elif verificador == 10:
        verificador = 1
    return f"{base}{verificador}001"


def _ruc_de_persona(base: str) -> str:
    """RUC válido de persona natural: algoritmo de la cédula.

    La regla es que cada dígito se multiplica por 2 o por 1 alternando, y **si el producto pasa de
    nueve se le resta nueve**. Esa resta es lo que distingue el algoritmo de la cédula de una suma
    normal, y es el punto donde una implementación se equivoca sin que salte nada.
    """
    suma = 0
    for digito, coeficiente in zip(base, "212121212", strict=True):
        producto = int(digito) * int(coeficiente)
        if producto > 9:
            producto -= 9
        suma += producto
    return f"{base}{(10 - suma % 10) % 10}001"


# --------------------------------------------------------------------------- #
# RUC
# --------------------------------------------------------------------------- #

BASE_SOCIEDAD = "179001234"
BASE_PERSONA = "171003406"


def test_acepta_un_ruc_de_sociedad_correcto() -> None:
    # Suma a mano: 1x4 + 7x3 + 9x2 + 0x7 + 0x6 + 1x5 + 2x4 + 3x3 + 4x2 = 4+21+18+0+0+5+8+9+8 = 73
    # 73 % 11 = 7, y 11 - 7 = 4. El décimo dígito tiene que ser 4.
    assert 1 * 4 + 7 * 3 + 9 * 2 + 0 * 7 + 0 * 6 + 1 * 5 + 2 * 4 + 3 * 3 + 4 * 2 == 73
    assert digito_verificador_ruc(BASE_SOCIEDAD) == 4
    assert validar_ruc("1790012344001") == "1790012344001"


def test_acepta_un_ruc_de_persona_natural_correcto() -> None:
    # 1x2 + 7x1 + 1x2 + 0x1 + 0x2 + 3x1 + 4x2 + 0x1 + 6x2, con la resta de nueve en 12 -> 3:
    # 2+7+2+0+0+3+8+0+3 = 25. 25 % 10 = 5, y (10 - 5) % 10 = 5. El décimo dígito tiene que ser 5.
    assert digito_verificador_ruc(BASE_PERSONA) == 5
    assert validar_ruc("1710034065001") == "1710034065001"


@pytest.mark.parametrize("generador", [_ruc_de_sociedad, _ruc_de_persona])
def test_la_cuenta_independiente_y_la_del_codigo_coinciden(
    generador: Callable[[str], str],
) -> None:
    """El mismo algoritmo escrito dos veces tiene que dar el mismo resultado.

    La de aquí sigue la documentación del SRI con los coeficientes a la vista; la del código es la
    que se usa de verdad. Si divergen, una de las dos tiene un coeficiente mal.
    """
    for base in ("179001234", "099234567", "019034567", "171003406", "060234567"):
        if generador is _ruc_de_sociedad and base[2] not in {"6", "9"}:
            continue
        if generador is _ruc_de_persona and base[2] in {"6", "9"}:
            continue
        esperado = generador(base)
        assert digito_verificador_ruc(base) == int(esperado[9])
        assert validar_ruc(esperado) == esperado


def test_rechaza_un_digito_verificador_equivocado() -> None:
    # Un dígito cambiado es el error más probable al teclear un RUC, y es justo el que la
    # comprobación de longitud no detecta.
    malo = "1790012345001"
    with pytest.raises(DatoInvalido, match="dígito verificador"):
        validar_ruc(malo)


def test_rechaza_una_provincia_inexistente() -> None:
    with pytest.raises(DatoInvalido, match="provincia"):
        validar_ruc("2590012344001")
    with pytest.raises(DatoInvalido, match="provincia"):
        validar_ruc("0090012344001")


def test_rechaza_un_tipo_de_contribuyente_inexistente() -> None:
    # El tercer dígito solo puede ser 0-5 (persona natural), 6 (entidad pública) o 9 (sociedad).
    with pytest.raises(DatoInvalido, match="tipo de contribuyente"):
        validar_ruc("1780012344001")


def test_rechaza_un_establecimiento_cero() -> None:
    with pytest.raises(DatoInvalido, match="establecimiento"):
        validar_ruc("1790012344000")


def test_rechaza_una_longitud_que_no_es_trece() -> None:
    with pytest.raises(DatoInvalido, match="13"):
        validar_ruc("1790012344")
    with pytest.raises(DatoInvalido, match="13"):
        validar_ruc("17900123440012")


def test_admite_el_ruc_vacio_porque_es_opcional() -> None:
    assert validar_ruc(None) is None
    assert validar_ruc("") is None
    assert validar_ruc("   ") is None


def test_limpia_los_separadores_antes_de_comprobar() -> None:
    # La gente escribe el RUC con guiones y con espacios. Rechazarlo por eso sería rechazar el dato
    # correcto por cómo está escrito.
    assert normalizar_ruc("179-001-234-4001") == "1790012344001"
    assert normalizar_ruc("179 001 234 4001") == "1790012344001"
    assert validar_ruc("179-001-234-4001") == "1790012344001"


# --------------------------------------------------------------------------- #
# Correo
# --------------------------------------------------------------------------- #


def test_normaliza_el_correo_a_minusculas() -> None:
    # Sin esto, `Ana@empresa.ec` y `ana@empresa.ec` serían dos cuentas para la misma persona.
    assert normalizar_correo("  Ana@Empresa.EC ") == "ana@empresa.ec"
    assert validar_correo("Ana@Empresa.EC") == "ana@empresa.ec"


@pytest.mark.parametrize(
    "correo",
    [
        "sin-arroba.ec",
        "dos@@arrobas.ec",
        "con espacio@empresa.ec",
        "sin@punto",
        "@empresa.ec",
        "a@",
    ],
)
def test_rechaza_correos_que_no_lo_son(correo: str) -> None:
    with pytest.raises(DatoInvalido):
        validar_correo(correo)


def test_admite_correos_con_punto_y_mas() -> None:
    # El caso laxo a propósito: `+` y subdominios son válidos y una expresión estricta los rechaza.
    assert validar_correo("ana+contratacion@sub.empresa.ec") == "ana+contratacion@sub.empresa.ec"


def test_el_correo_opcional_solo_falta_si_se_exige() -> None:
    assert validar_correo(None) is None
    with pytest.raises(DatoInvalido, match="correo de contacto"):
        validar_correo(None, obligatorio=True)


# --------------------------------------------------------------------------- #
# Teléfono
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("0991234567", "0991234567"),
        ("+593 99 123 4567", "+593991234567"),
        ("099-123-4567", "0991234567"),
        ("(02) 234-5678", "022345678"),
    ],
)
def test_admite_los_telefonos_que_la_gente_escribe(entrada: str, esperado: str) -> None:
    assert validar_telefono(entrada) == esperado


@pytest.mark.parametrize("telefono", ["12345", "abcdefghi", "+593 99 abc 4567"])
def test_rechaza_telefonos_que_no_lo_son(telefono: str) -> None:
    with pytest.raises(DatoInvalido):
        validar_telefono(telefono)


def test_el_telefono_vacio_es_ausencia_de_dato() -> None:
    assert validar_telefono(None) is None
    assert validar_telefono("   ") is None


# --------------------------------------------------------------------------- #
# Nombre, dirección y ciudad
# --------------------------------------------------------------------------- #


def test_exige_un_nombre_de_empresa() -> None:
    with pytest.raises(DatoInvalido, match="nombre de la empresa"):
        validar_nombre("  ")


def test_colapsa_los_espacios_del_nombre() -> None:
    # Un nombre con dobles espacios o con uno al final no es otro nombre, y guardarlo tal cual
    # haría que el mismo cliente apareciera dos veces en un listado.
    assert validar_nombre("  Constructora   del   Pacífico  ") == "Constructora del Pacífico"
    assert limpiar_texto("a   b") == "a b"


def test_acota_la_longitud_del_nombre() -> None:
    with pytest.raises(DatoInvalido, match="160"):
        validar_nombre("x" * 161)


def test_direccion_y_ciudad_admiten_vacio() -> None:
    assert validar_direccion(None) is None
    assert validar_ciudad("") is None
    assert validar_direccion("Av. Amazonas 1234 y Colón") == "Av. Amazonas 1234 y Colón"
    assert validar_ciudad("  Quito  ") == "Quito"


def test_acota_la_longitud_de_direccion_y_ciudad() -> None:
    with pytest.raises(DatoInvalido, match="dirección"):
        validar_direccion("x" * 201)
    with pytest.raises(DatoInvalido, match="ciudad"):
        validar_ciudad("x" * 81)


# --------------------------------------------------------------------------- #
# Bloque completo
# --------------------------------------------------------------------------- #


def test_construye_el_bloque_validado_y_normalizado() -> None:
    datos = construir_datos_empresa(
        nombre="  Constructora  del Pacífico ",
        ruc="179-001-234-4001",
        email_contacto="Avisos@Empresa.EC",
        telefono="+593 99 123 4567",
        direccion="Av. Amazonas 1234",
        ciudad="Quito",
    )
    assert datos.nombre == "Constructora del Pacífico"
    assert datos.ruc == "1790012344001"
    assert datos.email_contacto == "avisos@empresa.ec"
    assert datos.telefono == "+593991234567"
    assert datos.como_diccionario()["ciudad"] == "Quito"


def test_el_minimo_para_registrar_es_el_nombre() -> None:
    # Todo lo demás es opcional para poder registrar una empresa sin tener a mano el RUC o el
    # teléfono. Un dato ausente es mejor que un registro imposible.
    datos = construir_datos_empresa(nombre="Mi empresa")
    assert datos.ruc is None
    assert datos.email_contacto is None
    assert datos.telefono is None


def test_un_dato_malo_impide_construir_el_bloque_entero() -> None:
    # Se valida todo antes de devolver nada: el caso de uso no recibe nunca un objeto a medias.
    with pytest.raises(DatoInvalido, match="dígito verificador"):
        construir_datos_empresa(nombre="Mi empresa", ruc="1790012345001")
