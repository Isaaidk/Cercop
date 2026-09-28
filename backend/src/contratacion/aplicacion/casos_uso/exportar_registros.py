"""Caso de uso: exportar a Excel los registros que cumplen los filtros.

Tres decisiones gobiernan este módulo.

**El archivo lleva todo lo que cumple los filtros, no la página que se está viendo.** Exportar las
veinticinco filas de la página actual sería un botón que casi nunca sirve: quien exporta lo hace
para trabajar fuera de la plataforma, y para eso necesita el conjunto entero. Por eso la consulta
usa el mismo `WHERE` que la tabla pero sin paginar.

**Ningún campo se queda fuera.** Las columnas conocidas van primero, en el orden del cuadro que se
ve en pantalla, y después se añade cualquier clave que traiga un registro y no esté entre ellas. La
alternativa —una lista cerrada de columnas— convierte cada campo nuevo de la fuente en un dato que
se ingesta, se guarda y no se exporta, y eso no se nota hasta que alguien lo echa de menos.

**Lleva una hoja con los filtros aplicados.** Un archivo suelto sin decir con qué criterios se hizo
es un archivo que nadie puede reproducir ni auditar; con la hoja, quien lo recibe sabe exactamente
qué se pidió.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.dominio.acceso import momento_local
from contratacion.dominio.busqueda import Filtros
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.plazos import (
    NIVEL_AMARILLO,
    NIVEL_ROJO,
    NIVEL_VERDE,
    dias_para_proforma,
    nivel_de_plazo,
    texto_de_plazo,
)

# Tipo MIME del libro de Excel. Es el que hace que el navegador ofrezca abrirlo con Excel y no como
# un archivo desconocido.
TIPO_LIBRO = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Ancho de la columna del semáforo y de las de contexto, en caracteres.
ANCHO_PREDETERMINADO = 28

# Columnas del cuadro, en el mismo orden que en pantalla y con el mismo nombre que en la cabecera.
# El ancho es el de `ancho_excel` de los mapeos de la fuente, redondeado: la idea es que el archivo
# se pueda leer sin arrastrar columnas.
COLUMNAS: tuple[tuple[str, str, int], ...] = (
    ("codigo", "Código", 32),
    ("tipo_necesidad", "Tipo de compra", 20),
    ("entidad", "Razón social", 45),
    ("objeto_compra", "Objeto de compra", 70),
    ("funcionario", "Responsable de asuntos administrativos", 40),
    ("provincia", "Provincia", 24),
    ("canton", "Cantón", 22),
    ("estado", "Estado", 16),
    ("fecha_publicacion", "Fecha de publicación", 20),
    ("fecha_limite_proformas", "Límite de proformas", 20),
)

# La columna que se calcula aquí y no viene de la fuente. Es la que responde a «¿me da tiempo?».
COLUMNA_PLAZO: tuple[str, str, int] = ("dias_proforma", "Días para proforma", 20)

# Clave de la columna del código: es la que lleva el enlace a la ficha del proceso en el portal, así
# que se nombra una vez en lugar de repetir la cadena por el módulo.
COLUMNA_CODIGO = "codigo"
CLAVE_ENLACE = "enlace_publico"

# Procedencia del dato: sirve para saber de dónde salió cada fila y cuándo se vio.
COLUMNAS_CONTEXTO: tuple[tuple[str, str, int], ...] = (
    ("fuente", "Fuente", 10),
    ("clave_natural", "Clave natural", 30),
    ("primera_vez_visto", "Visto por primera vez", 24),
    ("ultima_vez_visto", "Visto por última vez", 24),
    ("es_vigente", "Vigente", 10),
)

# Claves que no son contenido del registro. `datos` es el objeto anidado del que ya se han extraído
# las columnas, y las otras dos son la maquinaria interna de la búsqueda: sacarlas solo añadiría
# ruido y, en el caso del texto de búsqueda, repetiría media fila.
#
# `enlace` y `enlace_publico` tampoco salen como columna. El primero es el enlace **relativo** que
# publica la fuente (`../NCO/NCORegistroDetalle.cpe?...`), que fuera del portal no lleva a ninguna
# parte y no sirve ni para copiar; el segundo es ese mismo enlace ya resuelto, y su sitio es el
# hipervínculo de la columna del código, no una columna de texto que repita la dirección.
CLAVES_INTERNAS = frozenset(
    {"id", "datos", "texto_busqueda", "hash_contenido", "enlace", CLAVE_ENLACE}
)

# Colores del semáforo, los mismos que usa Excel para «bueno», «atención» y «malo». Se eligen los
# suyos y no los del panel porque en un archivo abierto con Excel el usuario espera sus tonos, y un
# verde cualquiera se leería como un resaltado manual sin significado.
_VERDE = "FFC6EFCE"
_AMARILLO = "FFFFEB9C"
_ROJO = "FFFFC7CE"
RELLENOS: dict[str, PatternFill] = {
    NIVEL_VERDE: PatternFill(fill_type="solid", start_color=_VERDE, end_color=_VERDE),
    NIVEL_AMARILLO: PatternFill(fill_type="solid", start_color=_AMARILLO, end_color=_AMARILLO),
    NIVEL_ROJO: PatternFill(fill_type="solid", start_color=_ROJO, end_color=_ROJO),
}

_CABECERA = PatternFill(fill_type="solid", start_color="FF1F2937", end_color="FF1F2937")
_ETIQUETA_CABECERA = Font(bold=True, color="FFFFFFFF")


@dataclass(frozen=True, slots=True)
class ResultadoExportacion:
    """El archivo listo para enviar, con su nombre y cuántas filas lleva."""

    nombre: str
    contenido: bytes
    filas: int

    @property
    def bytes_totales(self) -> int:
        return len(self.contenido)


async def exportar(
    filtros: Filtros,
    *,
    repositorio: RepositorioConsultas,
    limite: int,
    momento: datetime | None = None,
) -> ResultadoExportacion:
    """Genera el libro con todos los registros que cumplen los filtros.

    Se pide **una fila de más** que el tope. Si llega, es que hay más de las que se permite
    exportar, y entonces se rechaza con un mensaje que dice qué hacer. Entregar el archivo cortado
    en silencio sería lo peor: quien lo recibe no tiene forma de saber que le falta la mitad.
    """
    instante = momento or datetime.now(UTC)
    filas = await repositorio.todos(filtros, limite + 1)

    if len(filas) > limite:
        raise DatoInvalido(
            f"Con estos filtros hay más de {limite:,} contrataciones y el archivo se generaría "
            "demasiado grande. Acota el rango de fechas o quita alguna palabra clave y vuelve a "
            "intentarlo."
        )

    contenido = construir_libro(filas, filtros=filtros, generado_en=instante)
    etiqueta = momento_local(instante).strftime("%Y%m%d-%H%M")
    return ResultadoExportacion(
        nombre=f"contrataciones-{etiqueta}.xlsx",
        contenido=contenido,
        filas=len(filas),
    )


def construir_libro(
    filas: Sequence[Mapping[str, Any]],
    *,
    filtros: Filtros,
    generado_en: datetime,
) -> bytes:
    """Arma el libro en memoria y devuelve sus bytes.

    Está separado de `exportar` para poder probarlo sin base de datos: recibe filas ya resueltas y
    no consulta nada.
    """
    columnas = columnas_del_libro(filas)

    libro = Workbook()
    hoja = libro.active
    hoja.title = "Contrataciones"
    _escribir_contrataciones(hoja, filas, columnas, generado_en=generado_en)

    criterios = libro.create_sheet("Filtros aplicados")
    _escribir_criterios(criterios, filtros, filas=len(filas), generado_en=generado_en)

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def columnas_del_libro(
    filas: Sequence[Mapping[str, Any]],
) -> tuple[tuple[str, str, int], ...]:
    """Columnas del archivo: las conocidas primero y después las que aparezcan en los datos.

    El orden de las extras es el de primera aparición, que es estable para el mismo conjunto de
    filas y hace que dos exportaciones seguidas tengan la misma forma.
    """
    conocidas = {clave for clave, _, _ in COLUMNAS}
    conocidas.add(COLUMNA_PLAZO[0])
    conocidas.update(clave for clave, _, _ in COLUMNAS_CONTEXTO)
    conocidas |= CLAVES_INTERNAS

    extras: list[tuple[str, str, int]] = []
    vistas: set[str] = set()
    for fila in filas:
        for clave in fila:
            if clave in conocidas or clave in vistas:
                continue
            vistas.add(clave)
            extras.append((clave, _etiqueta_legible(clave), ANCHO_PREDETERMINADO))

    # El semáforo va justo detrás del límite de proformas, que es la fecha de la que sale: leer
    # «2026-09-28T17:09» y a continuación «Vence hoy» es una sola idea. Puesto entre el responsable
    # y la provincia cortaría en dos el bloque de identificación del registro.
    return (*COLUMNAS, COLUMNA_PLAZO, *extras, *COLUMNAS_CONTEXTO)


def _etiqueta_legible(clave: str) -> str:
    """Nombre de columna para una clave que no está en el catálogo conocido.

    Se compone a partir de la clave en lugar de dejarla cruda porque `valor_unitario` se lee mejor
    como «Valor unitario» que como `valor_unitario`, y porque así una clave nueva de la fuente no
    aparece en el archivo con pinta de error.
    """
    return clave.replace("_", " ").strip().capitalize()


def _escribir_contrataciones(
    hoja: Worksheet,
    filas: Sequence[Mapping[str, Any]],
    columnas: Sequence[tuple[str, str, int]],
    *,
    generado_en: datetime,
) -> None:
    for indice, (_, etiqueta, ancho) in enumerate(columnas, start=1):
        celda = hoja.cell(row=1, column=indice, value=etiqueta)
        celda.font = _ETIQUETA_CABECERA
        celda.fill = _CABECERA
        celda.alignment = Alignment(vertical="center")
        hoja.column_dimensions[get_column_letter(indice)].width = ancho

    for numero_fila, fila in enumerate(filas, start=2):
        dias = dias_para_proforma(fila.get("fecha_limite_proformas"), ahora=generado_en)
        for indice, (clave, _, _) in enumerate(columnas, start=1):
            if clave == COLUMNA_PLAZO[0]:
                celda = hoja.cell(row=numero_fila, column=indice, value=texto_de_plazo(dias))
                relleno = RELLENOS.get(nivel_de_plazo(dias))
                if relleno is not None:
                    celda.fill = relleno
                continue
            celda = hoja.cell(row=numero_fila, column=indice, value=_valor_celda(fila.get(clave)))
            if clave == COLUMNA_CODIGO:
                _marcar_enlace(celda, fila.get(CLAVE_ENLACE))

    # La fila de cabecera queda fija y el filtro cubre todo el cuadro: sin esto, desplazarse por un
    # archivo de mil filas deja de tener referencia de qué columna se está mirando.
    hoja.freeze_panes = "A2"
    hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}"


def _marcar_enlace(celda: Any, url: Any) -> None:
    """Convierte la celda del código en un enlace que abre la ficha en el portal de la fuente.

    El texto sigue siendo el código, que es lo que hay que poder leer y copiar; lo que cambia es que
    además se puede pulsar, y así el archivo sirve para trabajar sin volver a buscar cada proceso a
    mano. Las filas cuya fuente no publica dirección se quedan como texto: un enlace que no lleva a
    ninguna parte es peor que no tener enlace, porque quien lo pulsa cree que el proceso no existe.

    Se usa el estilo «Hyperlink» que trae Excel en lugar de pintar el azul y el subrayado a mano,
    para que herede el color del tema de quien abra el archivo —en modo oscuro no es el mismo azul—.
    """
    if not url:
        return
    celda.hyperlink = str(url)
    celda.style = "Hyperlink"


def _escribir_criterios(
    hoja: Worksheet,
    filtros: Filtros,
    *,
    filas: int,
    generado_en: datetime,
) -> None:
    hoja.column_dimensions["A"].width = 32
    hoja.column_dimensions["B"].width = 70

    for indice, etiqueta in enumerate(("Criterio", "Valor"), start=1):
        celda = hoja.cell(row=1, column=indice, value=etiqueta)
        celda.font = _ETIQUETA_CABECERA
        celda.fill = _CABECERA

    parejas: tuple[tuple[str, str], ...] = (
        ("Generado", momento_local(generado_en).strftime("%d/%m/%Y %H:%M")),
        ("Contrataciones en el archivo", f"{filas:,}".replace(",", ".")),
        ("Palabras clave", ", ".join(filtros.terminos) if filtros.terminos else "ninguna"),
        ("Combinación", "todas las palabras" if filtros.modo.value == "todas" else "cualquiera"),
        ("Texto libre", filtros.texto or "—"),
        ("Fuente", filtros.fuente or "todas las permitidas"),
        ("Provincia", filtros.provincia or "todas"),
        ("Estado", filtros.estado or "todos"),
        ("Publicadas desde", filtros.desde.isoformat() if filtros.desde else "—"),
        ("Publicadas hasta", filtros.hasta.isoformat() if filtros.hasta else "—"),
        ("Solo lo detectado hace poco", "sí" if filtros.solo_nuevos else "no"),
        ("Ocultar lo ya vencido", "sí" if filtros.solo_con_plazo else "no"),
        ("Orden", str(filtros.orden)),
    )

    for indice, (etiqueta, valor) in enumerate(parejas, start=2):
        hoja.cell(row=indice, column=1, value=etiqueta).font = Font(bold=True)
        hoja.cell(row=indice, column=2, value=valor)


def _valor_celda(valor: Any) -> Any:
    """Adapta un valor del registro a algo que Excel pueda guardar.

    Dos conversiones que no son cosméticas:

    - **Los `datetime` con zona no se pueden escribir.** openpyxl lanza un error explícito porque
      Excel no tiene concepto de zona horaria; hay que quitarle el `tzinfo` o la exportación entera
      falla por un solo campo con zona. Las fechas ya vienen normalizadas a UTC por la ingesta, así
      que quitar la zona no cambia el instante.
    - **Un objeto anidado se guarda como texto JSON.** Ninguna de las dos fuentes actuales produce
      uno, pero una que lo hiciera reventaría la exportación con un error de tipo en lugar de dejar
      el dato a la vista.
    """
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None) if valor.tzinfo else valor
    if isinstance(valor, str | int | float | bool):
        return valor
    return json.dumps(valor, ensure_ascii=False, default=str)
