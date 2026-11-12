"""La proforma usa todos los anexos (PDF, Word, Excel, ZIP) y su título no se repite."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook
from pruebas.unidad.test_preparar_anexos import (
    ACTOR,
    REGISTRO,
    TDR,
    _correr,
    _Documentos,
    _ficha,
    _Tdr,
)

from contratacion.aplicacion.casos_uso import preparar_documentos as caso
from contratacion.dominio.anexos import CONTEXTO, contexto_de_anexos, recorte_de_contexto
from contratacion.dominio.errores import EstadoInvalido
from contratacion.dominio.titulos import normalizar_titulo, titulo_libre, titulo_repetido
from contratacion.infraestructura.adaptadores.salida.texto_anexos import (
    FormatoNoLegible,
    texto_de_archivo,
)


def _docx(cuerpo: str, encabezado: str = "") -> bytes:
    def parrafos(texto: str) -> str:
        return "".join(f"<w:p><w:r><w:t>{linea}</w:t></w:r></w:p>" for linea in texto.splitlines())

    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as libro:
        libro.writestr("[Content_Types].xml", "<Types/>")
        libro.writestr(
            "word/document.xml", f"<w:document><w:body>{parrafos(cuerpo)}</w:body></w:document>"
        )
        if encabezado:
            libro.writestr("word/header1.xml", f"<w:hdr>{parrafos(encabezado)}</w:hdr>")
    return salida.getvalue()


def _xlsx(filas: list[list[object]]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    assert hoja is not None
    hoja.title = "Formulario"
    for fila in filas:
        hoja.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


# --- Formatos -------------------------------------------------------------------------------------


def test_lee_word_con_su_encabezado() -> None:
    texto = texto_de_archivo(
        "tdr.docx",
        _docx(
            "OBJETO DE LA CONTRATACIÓN: Sillas &amp; mesas",
            encabezado="GAD Facundo Vela RUC 0260008780001",
        ),
    )
    assert texto.index("GAD Facundo Vela") < texto.index("OBJETO")
    assert "Sillas & mesas" in texto


def test_lee_excel_fila_por_fila() -> None:
    texto = texto_de_archivo(
        "formulario.xlsx", _xlsx([["Ítem", "Cantidad"], ["Silla ergonómica", 10]])
    )
    assert "Hoja: Formulario" in texto
    assert "Silla ergonómica | 10" in texto


def test_abre_un_zip_y_lee_lo_que_trae() -> None:
    paquete = io.BytesIO()
    with zipfile.ZipFile(paquete, "w") as zip_:
        zip_.writestr("pliegos/TDR.docx", _docx("PLAZO DE ENTREGA: 15 días"))
        zip_.writestr("../fuera.txt", "no se lee")
        zip_.writestr("nota.txt", "Lugar de entrega: bodega central")
    texto = texto_de_archivo("anexos.zip", paquete.getvalue())
    assert "=== TDR.docx ===" in texto and "15 días" in texto
    assert "bodega central" in texto
    assert "no se lee" not in texto


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1resto", "antiguo"),
        (b"Rar!\x1a\x07\x00", "rar"),
        (b"PKroto", "dañado"),
    ],
)
def test_avisa_lo_que_no_puede_leer(contenido: bytes, mensaje: str) -> None:
    with pytest.raises(FormatoNoLegible, match=mensaje):
        texto_de_archivo("anexo.bin", contenido)


# --- Contexto ------------------------------------------------------------------------------------


def test_el_contexto_lleva_cada_anexo_con_su_tipo_y_tiene_tope() -> None:
    contexto = contexto_de_anexos(
        [
            (
                {"etiqueta_tipo": "Términos de referencia (TDR)", "nombre": "TDR.pdf"},
                "Objeto\n\n  sillas  ",
            ),
            ({"etiqueta_tipo": "Otro anexo", "nombre": "formulario.xlsx"}, "x" * 50_000),
        ]
    )
    assert contexto.startswith("### Términos de referencia (TDR): TDR.pdf\nObjeto\nsillas")
    assert "### Otro anexo: formulario.xlsx" in contexto
    assert len(contexto) <= 24_000
    assert recorte_de_contexto("a\n" * 10, tope=6).endswith("[…]")


def test_el_anexo_sin_apartados_tambien_entra_a_la_proforma(tmp_path: Path) -> None:
    documentos_ficha = [
        {"nombre": "TDR.txt", "enlace": "BajarArchivo?t"},
        {"nombre": "formulario.xlsx", "enlace": "BajarArchivo?f"},
    ]
    (tmp_path / "TDR.txt").write_text(TDR, encoding="utf-8")
    (tmp_path / "formulario.xlsx").write_bytes(
        _xlsx([["Ítem", "Cantidad", "Unidad"], ["Silla giratoria con brazos", 12, "u"]])
    )
    documentos = _Documentos(_ficha(documentos_ficha))
    tdr = _Tdr({d["nombre"]: tmp_path / d["nombre"] for d in documentos_ficha})
    _correr(documentos, tdr)  # pide los anexos
    resultado = _correr(documentos, tdr)
    assert resultado["estado"] == "listo"
    contexto = resultado["secciones"][CONTEXTO]
    assert "Silla giratoria con brazos | 12 | u" in contexto
    assert "Adquisición de sillas de oficina" in contexto
    leidos = {anexo["nombre"]: anexo["leido"] for anexo in resultado["anexos"]}
    assert leidos == {"TDR.txt": True, "formulario.xlsx": True}


def test_el_anexo_que_no_se_puede_leer_dice_por_que(tmp_path: Path) -> None:
    documentos_ficha = [
        {"nombre": "TDR.txt", "enlace": "BajarArchivo?t"},
        {"nombre": "viejo.doc", "enlace": "BajarArchivo?v"},
    ]
    (tmp_path / "TDR.txt").write_text(TDR, encoding="utf-8")
    (tmp_path / "viejo.doc").write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1resto")
    documentos = _Documentos(_ficha(documentos_ficha))
    tdr = _Tdr({d["nombre"]: tmp_path / d["nombre"] for d in documentos_ficha})
    _correr(documentos, tdr)
    resultado = _correr(documentos, tdr)
    viejo = next(a for a in resultado["anexos"] if a["nombre"] == "viejo.doc")
    assert viejo["estado"] == "sin_texto"
    assert "guárdalo como PDF" in viejo["motivo"]


# --- Títulos -------------------------------------------------------------------------------------


def test_titulos_iguales_sin_importar_tildes_mayusculas_ni_guiones() -> None:
    assert normalizar_titulo("Proforma — Sillas  de Oficina") == normalizar_titulo(
        "proforma - sillas de oficina"
    )
    assert titulo_repetido("PROFORMA \u2013 Sillas", ["Proforma - sillas"])
    assert not titulo_repetido("Proforma — Mesas", ["Proforma — Sillas"])


def test_titulo_libre_numera_el_siguiente() -> None:
    usados = ["Proforma — Sillas", "Proforma — Sillas (2)"]
    assert titulo_libre("Proforma — Sillas", usados) == "Proforma — Sillas (3)"
    assert titulo_libre("Proforma — Sillas (2)", usados) == "Proforma — Sillas (3)"
    assert titulo_libre("Proforma — Mesas", usados) == "Proforma — Mesas"


def test_no_se_guarda_una_proforma_con_un_titulo_ya_usado() -> None:
    documentos = _Documentos(_ficha([]))
    campos = {
        "titulo": "Proforma — Sillas · NIC-1",
        "impuesto_porcentaje": 15,
        "lineas": [{"descripcion": "Silla", "cantidad": 1, "precio_unitario": 10}],
        "registro_id": str(REGISTRO),
    }
    asyncio.run(caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma"))  # type: ignore[arg-type]
    with pytest.raises(EstadoInvalido, match=r"«Proforma — Sillas · NIC-1 \(2\)»"):
        asyncio.run(
            caso.crear_proforma(ACTOR, documentos=documentos, campos=dict(campos), tipo="proforma")  # type: ignore[arg-type]
        )
    assert len(documentos.proformas) == 1


# --- Datos de la entidad en la proforma guardada -------------------------------------------------

_FICHA_PASAJE = {
    "codigo": "NIC-0760000770001-2026-00169",
    "direccion": "BOLIVAR ENTRE MUNICIPALIDAD Y JUAN MONTALVO",
    "canton": "PASAJE",
    "provincia": "EL ORO",
    "contacto": "Funcionario Encargado: KARLA MEDINA | Email: karla.medina@pasaje.gob.ec",
    "telefono": "",
    "contexto_anexos": "### TDR\nMUNICIPIO DEL CANTÓN PASAJE\nTeléfono: 07 291 5100\n",
}


def test_la_proforma_guarda_la_entidad_de_la_ficha_y_los_anexos() -> None:
    documentos = _Documentos(_ficha([]))
    documentos.entidad_ficha = dict(_FICHA_PASAJE)
    campos = {
        "titulo": "Proforma — Pasaje",
        "impuesto_porcentaje": 15,
        "lineas": [{"descripcion": "Silla", "cantidad": 1, "precio_unitario": 10}],
        "registro_id": str(REGISTRO),
        "extras": {"entidad": {"ruc": "", "direccion": "", "telefono": ""}, "numero": "PF-01"},
    }
    asyncio.run(caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma"))  # type: ignore[arg-type]
    extras = documentos.proformas[0]["extras"]
    assert extras["entidad"] == {
        "ruc": "0760000770001",
        "direccion": "BOLIVAR ENTRE MUNICIPALIDAD Y JUAN MONTALVO, PASAJE, EL ORO",
        "telefono": "07 291 5100",
        "correo": "karla.medina@pasaje.gob.ec",
    }
    assert extras["numero"] == "PF-01"


def test_lo_que_escribe_la_persona_manda_sobre_la_ficha() -> None:
    documentos = _Documentos(_ficha([]))
    documentos.entidad_ficha = dict(_FICHA_PASAJE)
    campos = {
        "titulo": "Proforma — Pasaje 2",
        "impuesto_porcentaje": 15,
        "lineas": [{"descripcion": "Silla", "cantidad": 1, "precio_unitario": 10}],
        "registro_id": str(REGISTRO),
        "extras": {"entidad": {"direccion": "Av. Bolívar y Olmedo"}},
    }
    asyncio.run(caso.crear_proforma(ACTOR, documentos=documentos, campos=campos, tipo="proforma"))  # type: ignore[arg-type]
    entidad = documentos.proformas[0]["extras"]["entidad"]
    assert entidad["direccion"] == "Av. Bolívar y Olmedo"
    assert entidad["ruc"] == "0760000770001"


def test_una_proforma_vieja_se_completa_al_abrirla() -> None:
    documentos = _Documentos(_ficha([]))
    documentos.entidad_ficha = dict(_FICHA_PASAJE)
    documentos.guardada = {
        "id": REGISTRO,
        "tipo": "proforma",
        "registro_id": REGISTRO,
        "extras": {"fecha": "12/11/2026"},
    }
    documento = asyncio.run(
        caso.proforma_guardada(ACTOR, documentos=documentos, proforma_id=REGISTRO)  # type: ignore[arg-type]
    )
    assert documento is not None
    assert documento["extras"]["entidad"]["ruc"] == "0760000770001"
    assert documento["extras"]["entidad"]["telefono"] == "07 291 5100"
