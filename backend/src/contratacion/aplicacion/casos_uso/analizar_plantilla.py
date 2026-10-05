"""Caso de uso: decir qué va a hacer el sistema con la plantilla de Excel de la empresa.

Existe porque el comportamiento de la plantilla es difícil de deducir mirándola. El sistema busca su
fila de encabezados en cada hoja —no tiene por qué ser la primera—, coloca cada dato bajo **su**
título, manda cada familia a la hoja que le dedicó la empresa, y si no la hay la deja en la hoja de
datos. Nada de eso se ve al abrir el archivo: «¿por qué mis datos no caen donde esperaba?» no se
contesta leyendo la documentación, hay que mirar **su** archivo.

Esto es esa mirada, hecha por el mismo código que rellena la plantilla. No adivina ni promete: dice
qué hoja recibiría cada familia, dónde está la fila de títulos que se reconoce en cada una, en qué
fila empezarían los datos y qué columnas del catálogo se van a rellenar en cada hoja. Con eso, un
título escrito de otra manera o una hoja con otro nombre dejan de ser un misterio y pasan a ser algo
que se puede arreglar.

Se calcula a petición y no en cada consulta de la plantilla: abrir el libro entero para responder
«¿hay plantilla?» haría lenta la pantalla que solo quiere decir una fecha.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from contratacion.aplicacion.casos_uso.exportar_registros import (
    _encabezado_de_la_plantilla,
    _hoja_de_la_familia,
    _hoja_destino,
    _primera_fila_de_datos,
)
from contratacion.dominio.busqueda import FUENTES_POR_CATEGORIA


@dataclass(frozen=True, slots=True)
class AnalisisDePlantilla:
    """Qué haría el sistema con esta plantilla, hoja por hoja."""

    hojas: tuple[dict[str, Any], ...]
    destinos: dict[str, str]

    def como_diccionario(self) -> dict[str, Any]:
        return {
            "hojas": [dict(hoja) for hoja in self.hojas],
            "destinos": dict(self.destinos),
            # Las familias que caerían en la hoja de datos porque la plantilla no les dedica una.
            # Es la causa más frecuente de «los datos no están donde los busco»: el archivo tiene
            # una sola hoja de datos y las dos familias van ahí, cada una con su rótulo delante.
            "familias_sin_hoja_propia": [
                familia
                for familia in self.destinos
                if not any(hoja["recibe"] == [familia] for hoja in self.hojas)
            ],
        }


def analizar(contenido: bytes) -> AnalisisDePlantilla:
    """Analiza la plantilla y devuelve su reparto, usando el mismo criterio que la exportación.

    Se abre el libro **en modo normal** (no `read_only`) porque hace falta leer celdas sueltas de
    las primeras filas para encontrar los encabezados; en modo lectura, `cell()` recorre la hoja
    desde el principio cada vez y el análisis se vuelve cuadrático.
    """
    libro = load_workbook(BytesIO(contenido))

    # A qué hoja iría cada familia. Es la misma decisión que toma la exportación: la hoja que la
    # plantilla le dedica por su nombre y, si no la hay, la hoja de datos.
    destinos: dict[str, str] = {}
    for categoria in FUENTES_POR_CATEGORIA:
        destino = _hoja_de_la_familia(libro, categoria) or _hoja_destino(libro)
        destinos[categoria.value] = destino.title

    hojas = tuple(_analizar_hoja(hoja, destinos=destinos) for hoja in libro.worksheets)
    return AnalisisDePlantilla(hojas=hojas, destinos=destinos)


def _analizar_hoja(hoja: Worksheet, *, destinos: dict[str, str]) -> dict[str, Any]:
    encabezado = _encabezado_de_la_plantilla(hoja)
    # La familia se deduce del destino y no de las columnas: una hoja puede recibir datos de las dos
    # —es lo que pasa cuando la plantilla no dedica una hoja a cada familia— y decir «recibe
    # ínfimas» a secas sería mentira.
    recibe = [familia for familia, destino in destinos.items() if destino == hoja.title]
    return {
        "hoja": hoja.title,
        "recibe": recibe,
        "fila_de_encabezado": None if encabezado is None else encabezado.fila,
        "primera_fila_de_datos": _primera_fila_de_datos(hoja, encabezado),
        # Las columnas **en el orden en que están en la hoja**, con el número de columna, para que
        # se pueda comparar con lo que se ve al abrir el archivo.
        "columnas_reconocidas": [
            {"clave": clave, "columna": columna}
            for clave, columna in sorted(
                (encabezado.posiciones if encabezado else {}).items(), key=lambda par: par[1]
            )
        ],
    }
