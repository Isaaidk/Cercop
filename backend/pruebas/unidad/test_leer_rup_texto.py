"""Leer el RUP a partir del texto que el navegador sacó por OCR (`POST /leer-rup-texto`).

`datos/rup_y_ruc_ocr.txt` es lo que `frontend/src/utils/ocr.js` (pdf.js + Tesseract en español)
devolvió de verdad al reconocer un PDF **escaneado** —solo imagen, sin capa de texto— hecho con el
texto de `rup_y_ruc_ejemplo.txt`. Trae los errores reales del OCR: líneas en blanco de más, «*» por
«•», la «G» de la sección CIIU leída como «6» y la arroba del correo leída como «Q» o «QM».
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.gestionar_perfil import (
    AVISO_OCR,
    TEXTO_OCR_MAXIMO,
    leer_rup_texto,
    normalizar_texto_ocr,
)
from contratacion.dominio.errores import DatoInvalido, SinPermiso
from contratacion.dominio.rup import leer_rup

DATOS = Path(__file__).parent / "datos"
EJEMPLO = (DATOS / "rup_y_ruc_ejemplo.txt").read_text(encoding="utf-8")
OCR_REAL = (DATOS / "rup_y_ruc_ocr.txt").read_text(encoding="utf-8")


def _actor(rol: str = "dueno_empresa") -> Actor:
    return Actor(usuario_id=uuid4(), negocio_id=uuid4(), rol=rol)


def _leer(texto: str, rol: str = "dueno_empresa") -> dict[str, object]:
    return asyncio.run(leer_rup_texto(_actor(rol), texto=texto))


def _ruidoso(texto: str) -> str:
    """El texto de ejemplo como lo dejaría un OCR mediocre."""
    lineas = [linea for linea in texto.splitlines() if linea.strip()]  # sin líneas en blanco
    sucio = "\n".join(lineas)
    sucio = sucio.replace(
        "FRENTE AL PARQUE", "\u201cFRENTE AL PARQUE\u201d"
    )  # comillas tipográficas
    sucio = sucio.replace(" ", "  ")  # espacios dobles
    sucio = sucio.replace("INSTRUMENTOS", "|NSTRUMENTOS").replace("MUSICALES", "MUS|CALES")
    sucio = sucio.replace("Calle:", "Calle:\u00a0").replace("Cantón:", "Cantón:\u2009")
    sucio = sucio.replace(" - ", " \u2013 ")  # guion largo en las actividades
    sucio = sucio.replace("•", "*").replace("* G4", "* 64")  # viñeta y «G» leída como «6»
    sucio = sucio.replace("contacto@ejemplo.ec", "contacto Qejemplo.ec")
    return sucio.replace("\n", "\r\n") + "\n| |"  # finales de Windows y un borde de tabla


def test_la_normalizacion_no_cambia_lo_que_se_lee_del_texto_limpio() -> None:
    assert leer_rup(normalizar_texto_ocr(EJEMPLO)) == leer_rup(EJEMPLO)


def test_el_texto_ruidoso_se_lee_igual_que_el_limpio() -> None:
    limpio = leer_rup(EJEMPLO)
    resultado = _leer(_ruidoso(EJEMPLO))

    assert resultado["avisos"] == [AVISO_OCR]
    sin_avisos = {clave: valor for clave, valor in resultado.items() if clave != "avisos"}
    esperado = {clave: valor for clave, valor in limpio.items() if clave != "avisos"}
    # Las comillas tipográficas quedan rectas; el resto, idéntico al texto limpio.
    direccion = sin_avisos["identidad"].pop("direccion")  # type: ignore[attr-defined]
    assert direccion == esperado["identidad"].pop("direccion").replace(  # type: ignore[attr-defined]
        "(frente al parque)", '("frente al parque")'
    )
    assert sin_avisos == esperado


def test_el_ocr_real_de_un_pdf_escaneado() -> None:
    resultado = _leer(OCR_REAL)

    assert resultado["ruc"] == "1712345678001"
    assert resultado["documentos"] == ["RUP", "RUC del SRI"]
    assert resultado["identidad"] == {
        "razon_social": "Perez Lopez Juan Carlos",
        "tipo_persona": "natural",
        "regimen_tributario": "General",
        "estado_rup": "habilitado",
        "email_contacto": "contacto@ejemplo.ec",
        "telefono": "0990000000",
        "direccion": "Av. Siempre Viva S1-100 y Carlos Alvarez (frente al parque)",
        "ciudad": "Quito",
        "capacidad_ejecucion": "Categoría RUP: Micro 0-300000",
        "obligado_contabilidad": False,
    }
    cpc = resultado["cpc"]
    assert [fila["codigo"] for fila in cpc] == [
        "73210",
        "85970",
        "85990",
        "96111",
        "96220",
        "96320",
    ]  # type: ignore[index]
    assert cpc[0]["descripcion"].endswith("EQUIPOS DE AMPLIFICACION Y DE ESCENARIOS")  # type: ignore[index]
    # La página escaneada del SRI se cortó en la novena actividad; las nueve llegan, con su «G».
    ciiu = [fila["ciiu"] for fila in resultado["actividades"]]  # type: ignore[attr-defined]
    assert ciiu[:2] == ["G46491102", "G46499903"] and len(ciiu) == 9


def test_un_cpc_con_o_por_cero_no_se_adivina() -> None:
    """Límite conocido: «7321O» no es un código y no se corrige; la fila se pierde.

    Cambiar letras por cifras dentro de un código inventaría CPC que la empresa no tiene. Por eso
    la respuesta siempre trae `AVISO_OCR` y la persona revisa la lista antes de cargarla.
    """
    resultado = _leer(EJEMPLO.replace("73210 SERVICIOS", "7321O SERVICIOS"))
    codigos = [fila["codigo"] for fila in resultado["cpc"]]  # type: ignore[attr-defined]
    assert "73210" not in codigos and "7321O" not in codigos
    assert codigos == ["85970", "85990", "96111", "96220", "96320"]
    assert AVISO_OCR in resultado["avisos"]  # type: ignore[operator]


def test_un_cpc_que_empieza_por_cifra_parecida_a_letra_no_se_toca() -> None:
    # La regla de la «G» leída como «6» solo mira actividades con viñeta y guion, no la tabla CPC.
    texto = normalizar_texto_ocr(
        "Código Producto\n85970 - SERVICIOS DE FERIAS\n• 646491102 - VENTA"
    )
    assert texto.splitlines() == [
        "Código Producto",
        "85970 - SERVICIOS DE FERIAS",
        "• G46491102 - VENTA",
    ]


def test_la_barra_suelta_sobra_y_la_pegada_es_una_i() -> None:
    assert (
        normalizar_texto_ocr("| VENTA DE |NSTRUMENTOS MUS|CALES |")
        == "VENTA DE INSTRUMENTOS MUSICALES"
    )


def test_una_arroba_bien_leida_no_se_toca() -> None:
    texto = "Email: ventas@empresa.ec\nOtro: contacto Qejemplo.ec"
    assert normalizar_texto_ocr(texto) == texto


def test_poco_texto_o_demasiado_se_rechaza() -> None:
    with pytest.raises(DatoInvalido, match="texto suficiente"):
        _leer("   RUP   ")
    with pytest.raises(DatoInvalido, match="demasiado largo"):
        _leer("a" * (TEXTO_OCR_MAXIMO + 1))


def test_exige_el_mismo_permiso_que_leer_el_pdf() -> None:
    with pytest.raises(SinPermiso):
        _leer(EJEMPLO, rol="usuario")


def test_la_ruta_existe_y_valida_el_cuerpo() -> None:
    from contratacion.infraestructura.adaptadores.entrada.http.routers.perfil import (
        TextoRup,
        router,
    )

    rutas = {(ruta.path, tuple(sorted(ruta.methods))) for ruta in router.routes}  # type: ignore[attr-defined]
    assert ("/v1/empresa/perfil/leer-rup-texto", ("POST",)) in rutas
    assert TextoRup(texto=EJEMPLO).texto == EJEMPLO
    with pytest.raises(ValidationError):
        TextoRup(texto="corto")
    with pytest.raises(ValidationError):
        TextoRup(texto="a" * (TEXTO_OCR_MAXIMO + 1))
