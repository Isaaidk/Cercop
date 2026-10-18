"""El código del proceso no puede quedarse vacío, ni perderse lo que ya estaba.

Qué se protege aquí
-------------------
Dos fallos medidos el 2026-10-18 contra el histórico real, y los dos venían del mismo sitio: el
listado paginado escribe las ofertas con un payload **más pobre** que la descarga masiva —trae el
`ocid`, la entidad, la provincia, el cantón y la fecha, pero no el objeto de compra ni el
presupuesto—.

1. **198 filas sin código.** El código sale del campo `title` del payload, y el listado no siempre
   lo trae. Esas filas salían con «—» en la tabla y sin Código CercoApp, y no se podían encontrar
   pegando su identificador.
2. **El listado reescribía `datos` entero.** Cada vez que volvía a ver un proceso ya importado, los
   campos que no traía desaparecían de la fila. Solo se conservaba `estado`, con un caso especial.

Las pruebas de abajo fijan las dos cosas: que el hueco se rellena con el `ocid` —que contiene el
código— y que el `upsert` **funde** en lugar de reemplazar.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contratacion.aplicacion.casos_uso.ejecutar_ingesta import _completar_codigo, _texto_busqueda
from contratacion.infraestructura.adaptadores.salida.bd.consultas import _fila_a_elemento
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import DATOS_FUNDIDOS, TEXTO_FUNDIDO

# --------------------------------------------------------------------------- #
# El relleno al ingestar
# --------------------------------------------------------------------------- #


def test_el_codigo_se_rellena_desde_el_ocid_cuando_la_fuente_no_lo_trae() -> None:
    """El `ocid` contiene el código: `ocds-5wno2w-SIE-UC-2026-059-30951`."""
    datos: dict[str, Any] = {"ocid": "ocds-5wno2w-SIE-UC-2026-059-30951", "entidad": "X"}

    _completar_codigo(datos)

    assert datos["codigo"] == "ocds-5wno2w-SIE-UC-2026-059-30951"


def test_el_codigo_de_la_fuente_manda_sobre_el_ocid() -> None:
    """Si la fuente publica un título propio, no se sustituye por el identificador."""
    datos: dict[str, Any] = {"ocid": "ocds-5wno2w-X", "codigo": "SIE-UTA-2026-042"}

    _completar_codigo(datos)

    assert datos["codigo"] == "SIE-UTA-2026-042"


def test_sin_ocid_y_sin_codigo_no_se_inventa_nada() -> None:
    datos: dict[str, Any] = {"entidad": "Sin identificador"}

    _completar_codigo(datos)

    assert "codigo" not in datos


def test_un_codigo_vacio_es_un_hueco_y_se_rellena() -> None:
    """El mapeo omite las claves vacías, pero un `""` explícito también cuenta como hueco."""
    datos: dict[str, Any] = {"ocid": "ocds-5wno2w-Y", "codigo": ""}

    _completar_codigo(datos)

    assert datos["codigo"] == "ocds-5wno2w-Y"


def test_el_codigo_rellenado_entra_en_el_texto_de_busqueda() -> None:
    """Si no entrara, la fila no se podría encontrar por su identificador ni por palabras clave."""
    datos: dict[str, Any] = {"ocid": "ocds-5wno2w-SIE-UC-2026-059-30951", "entidad": "UNIVERSIDAD"}
    _completar_codigo(datos)

    assert "30951" in _texto_busqueda(datos)


# --------------------------------------------------------------------------- #
# El relleno al leer
#
# Las filas que ya están guardadas sin código no se reescriben solas: la lectura usa el `ocid` en
# lugar de mostrar un hueco. Es el mismo valor, resuelto en el único sitio por el que pasan todas
# las filas que salen de la base.
# --------------------------------------------------------------------------- #


def _fila(**datos: Any) -> dict[str, Any]:
    """Una fila de `registro` con las columnas que lee `_fila_a_elemento`."""
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "fuente": "OCDS",
        "fuente_url": "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA",
        "clave_natural": "ocds-5wno2w-SIE-UC-2026-059-30951",
        "datos": datos,
        "items": (),
        "cpc_codigos": (),
        "fecha_publicacion": None,
        "primera_vez_visto": None,
        "ultima_vez_visto": None,
        "es_vigente": True,
    }


def test_al_leer_se_usa_el_ocid_cuando_la_fila_no_tiene_codigo() -> None:
    elemento = _fila_a_elemento(_fila(ocid="ocds-5wno2w-SIE-UC-2026-059-30951"))

    assert elemento["codigo"] == "ocds-5wno2w-SIE-UC-2026-059-30951"
    assert elemento["codigo_cercoapp"] == "SIE-UC-2026-059"


def test_al_leer_manda_el_codigo_guardado() -> None:
    elemento = _fila_a_elemento(
        _fila(codigo="ocds-5wno2w-SIE-UTA-2026-0038-3205", ocid="ocds-5wno2w-OTRO")
    )

    assert elemento["codigo"] == "ocds-5wno2w-SIE-UTA-2026-0038-3205"
    assert elemento["codigo_cercoapp"] == "SIE-UTA-2026-0038"


def test_al_leer_sin_codigo_ni_ocid_queda_el_hueco() -> None:
    fila = _fila(entidad="Sin identificador")
    fila["clave_natural"] = "nco-123"

    elemento = _fila_a_elemento(fila)

    assert "codigo" not in elemento or not elemento["codigo"]
    assert elemento["codigo_cercoapp"] is None


# --------------------------------------------------------------------------- #
# El upsert funde en lugar de reemplazar
# --------------------------------------------------------------------------- #


def test_los_datos_se_funden_con_los_que_ya_habia() -> None:
    """Un payload parcial no puede borrar campos: solo añade o actualiza los suyos."""
    assert "registro.datos || EXCLUDED.datos" in DATOS_FUNDIDOS
    assert "jsonb_build_object" not in DATOS_FUNDIDOS


def test_el_texto_de_busqueda_no_se_acorta() -> None:
    """Fundir no basta para el texto: es una cadena, y el corto perdería la búsqueda por objeto."""
    assert "length(EXCLUDED.texto_busqueda) >= length(registro.texto_busqueda)" in TEXTO_FUNDIDO


def test_las_dos_sentencias_de_escritura_funden() -> None:
    """La de una fila y la del lote: si solo cambiara una, el fallo seguiría por el otro camino."""
    ruta = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "contratacion"
        / "infraestructura"
        / "adaptadores"
        / "salida"
        / "bd"
        / "ingesta.py"
    )
    texto = ruta.read_text(encoding="utf-8")

    assert texto.count("SET datos = {DATOS_FUNDIDOS},") == 2
    assert texto.count("texto_busqueda = {TEXTO_FUNDIDO},") == 2
    assert "DATOS_CONSERVANDO_ESTADO" not in texto
