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

**Si la empresa subió una plantilla, el archivo es su plantilla.** Los datos entran en sus hojas,
bajo sus títulos y con sus columnas; su fila de encabezados se busca —no siempre está en la primera,
y no siempre se llama cada columna como la llamamos nosotros— y su zona de datos se sustituye en
cada descarga. Lo que su plantilla no tenga no se inventa: se calla y se explica en la respuesta.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from contratacion.aplicacion.plantillas import HOJA_DE_DATOS
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.dominio.acceso import momento_local
from contratacion.dominio.busqueda import (
    ETIQUETA_OTRAS,
    ETIQUETA_POR_CATEGORIA,
    FUENTES_POR_CATEGORIA,
    Categoria,
    Filtros,
    categoria_de_fuente,
)
from contratacion.dominio.cpc import items_desde_crudos, resumen_cpc
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.exportacion import revisar_ventana
from contratacion.dominio.palabras import normalizar
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

# La clasificación del CPC, también calculada aquí y por el mismo motivo: el listado de necesidades
# no la publica, la trae la ficha de cada una y se guarda aparte de los datos canónicos. Va junto al
# objeto de compra porque es su complemento: uno dice qué se compra en palabras de la entidad y la
# otra, cómo lo clasifica el Estado.
COLUMNA_CPC: tuple[str, str, int] = ("cpc", "CPC", 60)

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

# Las columnas que la empresa puede elegir, agrupadas como se muestran en la pantalla.
#
# Se arma a partir de **las mismas tuplas que escribe el libro** y no de una lista aparte: una lista
# paralela se quedaría corta el día que se añada una columna, y el síntoma sería una columna que
# sale en el archivo pero no se puede elegir —o al revés, una elegible que nunca aparece—. El orden
# es el del archivo, que es el orden en que se leen los datos.
GRUPOS_DE_COLUMNAS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Datos de la contratación",
        (
            *((clave, etiqueta) for clave, etiqueta, _ in COLUMNAS),
            (COLUMNA_CPC[0], COLUMNA_CPC[1]),
        ),
    ),
    ("Plazo de proformas", ((COLUMNA_PLAZO[0], COLUMNA_PLAZO[1]),)),
    (
        "Procedencia del dato",
        tuple((clave, etiqueta) for clave, etiqueta, _ in COLUMNAS_CONTEXTO),
    ),
)

# Las claves que se pueden pedir. Se calcula una vez al importar: la validación compara contra este
# conjunto en cada petición, y armarlo de nuevo cada vez sería recorrer el catálogo para nada.
CLAVES_EXPORTABLES: frozenset[str] = frozenset(
    clave for _, columnas in GRUPOS_DE_COLUMNAS for clave, _ in columnas
)


def revisar_columnas(claves: Sequence[str]) -> tuple[str, ...]:
    """Comprueba que las columnas pedidas existen y devuelve las válidas, sin repetir ni vacías.

    Una clave desconocida **se rechaza** en lugar de ignorarse. Callarse devolvería un archivo al
    que le falta justo lo que se pidió —por un error de la interfaz o de un cliente escrito a
    mano— y quien lo recibe no tendría forma de saber que le falta una columna: la vería ausente y
    daría por hecho que no hay datos.

    El orden de la respuesta es el de la petición. Ordenarlas aquí escondería cualquier cambio de
    orden que hiciera quien llama, y el orden con el que se escribe el libro lo decide el catálogo,
    no esta función.
    """
    limpias: list[str] = []
    desconocidas: list[str] = []
    for clave in claves:
        nombre = str(clave).strip()
        if not nombre or nombre in limpias:
            continue
        if nombre not in CLAVES_EXPORTABLES:
            desconocidas.append(nombre)
            continue
        limpias.append(nombre)

    if desconocidas:
        raise DatoInvalido(
            f"Estas columnas no existen: {', '.join(sorted(desconocidas))}. "
            "Elige entre las que ofrece la pantalla de la plantilla."
        )
    return tuple(limpias)


# Claves que no son contenido del registro. `datos` es el objeto anidado del que ya se han extraído
# las columnas, y las otras dos son la maquinaria interna de la búsqueda: sacarlas solo añadiría
# ruido y, en el caso del texto de búsqueda, repetiría media fila.
#
# `enlace` y `enlace_publico` tampoco salen como columna. El primero es el enlace **relativo** que
# publica la fuente (`../NCO/NCORegistroDetalle.cpe?...`), que fuera del portal no lleva a ninguna
# parte y no sirve ni para copiar; el segundo es ese mismo enlace ya resuelto, y su sitio es el
# hipervínculo de la columna del código, no una columna de texto que repita la dirección.
#
# `items` y `cpc_codigos` son la maquinaria del CPC y se quedan fuera por lo mismo: los ítems son
# una lista de objetos con seis campos cada uno, y volcarla en una celda daría texto de `json` que
# nadie lee. Lo que sí sale es su resumen, en la columna del CPC; cada ítem con su descripción está
# en el panel, al abrir el registro.
CLAVES_INTERNAS = frozenset(
    {
        "id",
        "datos",
        "texto_busqueda",
        "hash_contenido",
        "enlace",
        CLAVE_ENLACE,
        "cpc_codigos",
        "items",
    }
)

# La columna que algunas plantillas usan en lugar de dos: «PICHINCHA - QUITO» en una sola celda. No
# es un campo de la fuente —se compone con la provincia y el cantón— así que no está en `COLUMNAS`
# ni se suma a las columnas del archivo genérico: solo se rellena si la plantilla la pide.
CAMPO_UBICACION = "ubicacion"

# Separadores con los que se ha visto escrita la ubicación en una sola celda. Se elige el que use el
# propio título de la plantilla para no cambiarle el estilo a quien ya lo tenía decidido.
SEPARADORES_UBICACION = (" / ", " - ", "/", "-")

# Títulos con los que las plantillas reales nombran cada campo. Las dos plantillas que hay subidas
# usan «Entidad Contratante», «Estado de la Necesidad» o «Provincia - Cantón», y ninguna de esas
# cadenas coincide con la etiqueta que el sistema escribe en su propio archivo. Sin esta tabla, esas
# plantillas no se reconocían y el sistema acababa escribiendo su cabecera **debajo** del diseño de
# la empresa: el archivo salía con dos cabeceras y nadie entendía por qué.
ALIAS_DE_TITULO: Mapping[str, tuple[str, ...]] = {
    "codigo": (
        "Código Necesidad de Contratación",
        "Código de la necesidad",
        "Código del proceso",
        "Código de proceso",
    ),
    "tipo_necesidad": ("Tipo de Necesidad", "Tipo de la necesidad"),
    "entidad": ("Entidad Contratante", "Entidad", "Entidad pública", "Entidad convocante"),
    "objeto_compra": (
        "Descripción del Objeto de compra",
        "Descripción del objeto",
        "Objeto del proceso",
        "Objeto de la contratación",
    ),
    "funcionario": ("Funcionario encargado", "Responsable", "Administrador del contrato"),
    "estado": ("Estado de la necesidad", "Estado del proceso", "Estado de la contratación"),
    "fecha_publicacion": ("Fecha publicación", "Fecha de publicación de la necesidad"),
    "fecha_limite_proformas": (
        "Fecha límite para la entrega de proformas",
        "Fecha límite de entrega de proformas",
        "Fecha límite proformas",
        "Fecha máxima de entrega de proformas",
    ),
    CAMPO_UBICACION: (
        "Provincia - Cantón",
        "Provincia / Cantón",
        "Provincia/Cantón",
        "Ubicación",
        "Provincia y cantón",
    ),
}


def _indice_de_titulos() -> dict[str, str]:
    """Título normalizado → campo. Se arma una vez, al importar el módulo.

    Primero las etiquetas y las claves del catálogo, y después los alias: así, si un alias coincide
    con una etiqueta oficial, gana la oficial. Se construye aquí y no en cada celda porque leer una
    plantilla recorre decenas de encabezados y comparar contra una lista cada vez sería repetir el
    mismo trabajo en cada exportación.
    """
    indice: dict[str, str] = {}
    for clave, etiqueta, _ in (*COLUMNAS, COLUMNA_CPC, COLUMNA_PLAZO, *COLUMNAS_CONTEXTO):
        indice[normalizar(etiqueta)] = clave
        indice[normalizar(clave)] = clave
    for campo, alias in ALIAS_DE_TITULO.items():
        for texto in alias:
            indice.setdefault(normalizar(texto), campo)
    return indice


TITULOS: Mapping[str, str] = _indice_de_titulos()

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

# Encabezado que separa los bloques de categoría cuando el libro sale de una plantilla. Se usa el
# mismo tratamiento que la cabecera de la tabla para que se lean como lo que son —un rótulo— y no
# como un dato de la primera columna.
_ETIQUETA_BLOQUE = Font(bold=True, color="FF1F2937", size=12)


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
    plantilla: bytes | None = None,
    columnas: Sequence[str] | None = None,
    momento: datetime | None = None,
) -> ResultadoExportacion:
    """Genera el libro con todos los registros que cumplen los filtros.

    Se pide **una fila de más** que el tope. Si llega, es que hay más de las que se permite
    exportar, y entonces se rechaza con un mensaje que dice qué hacer. Entregar el archivo cortado
    en silencio sería lo peor: quien lo recibe no tiene forma de saber que le falta la mitad.

    `plantilla` son los bytes del `.xlsx` propio de la empresa, si tiene uno subido. Se recibe como
    parámetro y no se busca aquí dentro a propósito: este caso de uso no sabe de negocios —el
    aislamiento lo aplica la base de datos— y darle un identificador para que consultara la
    plantilla por su cuenta le añadiría una responsabilidad que no tiene.

    `columnas` es la selección guardada por la empresa, ya validada. `None` o vacía significa
    «todas», que es como se ha exportado siempre; quien llama es quien decide qué hacer si la fila
    de la selección no se puede leer, y por eso se recibe hecha y no se consulta aquí.

    La **ventana** de la descarga se comprueba antes de consultar nada: cubre como mucho los últimos
    tres meses y una petición que se remonte más atrás se rechaza con el motivo (ver
    `dominio/exportacion.py`). Es la única operación del sistema que lee el histórico entero sin
    paginar, y con 110.000 registros eso son minutos de base ocupada por un archivo que casi nunca
    se necesita completo.
    """
    instante = momento or datetime.now(UTC)
    # Se valida también aquí, y no solo en la búsqueda: la exportación es el camino por el que los
    # datos salen de la plataforma, y el único que no pasa por `buscar`. Dos criterios que se
    # contradicen tienen que dar una explicación, no un archivo vacío.
    filtros = filtros.validado()
    # El rechazo va **antes** de tocar la base: sin esto, una petición fuera de ventana seguiría
    # lanzando la consulta cara y solo después se quejaría.
    revisar_ventana(filtros.desde, momento=instante)
    filas = await repositorio.todos(filtros, limite + 1)

    if len(filas) > limite:
        raise DatoInvalido(
            f"Con estos filtros hay más de {limite:,} contrataciones y el archivo se generaría "
            "demasiado grande. Acota el rango de fechas o quita alguna palabra clave y vuelve a "
            "intentarlo."
        )

    contenido = construir_libro(
        filas,
        filtros=filtros,
        generado_en=instante,
        plantilla=plantilla,
        columnas=columnas,
    )
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
    plantilla: bytes | None = None,
    columnas: Sequence[str] | None = None,
) -> bytes:
    """Arma el libro en memoria y devuelve sus bytes.

    Está separado de `exportar` para poder probarlo sin base de datos: recibe filas ya resueltas y
    no consulta nada.

    El libro lleva **una hoja por categoría**, no una hoja con todo. Las ínfimas cuantías y las
    ofertas no se leen igual ni se trabajan igual: la primera es una necesidad con proforma y la
    segunda un proceso con oferta, y quien recibe el archivo abre una u otra según lo que tenga que
    hacer. Mezclarlas obliga a filtrar a mano en cada uso, que es justo el trabajo que la
    exportación venía a ahorrar.

    Cuando la consulta ya venía restringida a una categoría, sale una sola hoja.

    **Con plantilla, el archivo es la plantilla y nada más.** No se crea ninguna hoja: los datos
    entran en las hojas de la empresa y lo que ella no haya diseñado no aparece. Esto sustituye a un
    comportamiento anterior que sí creaba dos —«Datos» y «Filtros aplicados»— y el resultado era un
    libro con las pestañas de la empresa más dos que nadie había pedido, que es justo lo contrario
    de lo que se espera de una plantilla propia.

    Cada familia va a la hoja que la plantilla le dedique, y el reparto se conserva con su título
    cuando varias familias caen en la misma hoja. Si se prefieren hojas separadas, la exportación
    sin plantilla las da.
    """
    if plantilla is not None:
        libro = load_workbook(io.BytesIO(plantilla))
        _volcar_en_la_plantilla(
            libro,
            filas,
            filtros=filtros,
            generado_en=generado_en,
            elegidas=columnas,
        )
        # La hoja de criterios se rellena **solo si la plantilla la trae**. Añadirla sería crear una
        # pestaña que la empresa no diseñó, y una plantilla con una pestaña de más deja de ser su
        # plantilla. Quien quiera la trazabilidad la añade a su plantilla y se rellena sola.
        criterios = _hoja_de_criterios_si_existe(libro)
        if criterios is not None:
            _escribir_criterios(criterios, filtros, filas=len(filas), generado_en=generado_en)
    else:
        libro = Workbook()
        # `Workbook()` nace con una hoja vacía llamada «Sheet» que hay que quitar: si se dejara, el
        # archivo tendría una pestaña en blanco delante de las de verdad.
        libro.remove(libro.active)
        for nombre, suyas in _hojas_del_libro(filas, categoria=filtros.categoria):
            hoja = libro.create_sheet(nombre)
            de_la_hoja = columnas_del_libro(suyas, elegidas=columnas)
            _escribir_contrataciones(hoja, suyas, de_la_hoja, generado_en=generado_en)
        # Sin plantilla sí se añade la hoja de trazabilidad: es un libro que arma el sistema, y ahí
        # el registro de con qué criterios se hizo es parte del entregable, no una intromisión.
        _escribir_criterios(
            _hoja_de_criterios(libro), filtros, filas=len(filas), generado_en=generado_en
        )

    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


# Excel no admite más de 31 caracteres en el nombre de una hoja y lanza una excepción si se pasa.
# Se recorta aquí, en un sitio, en vez de confiar en que las etiquetas nunca crezcan.
LARGO_MAXIMO_HOJA = 31


def _hojas_del_libro(
    filas: Sequence[Mapping[str, Any]],
    *,
    categoria: Categoria | None,
) -> tuple[tuple[str, tuple[Mapping[str, Any], ...]], ...]:
    """Reparte las filas en las hojas del libro, una por categoría.

    El orden es fijo —ínfimas, ofertas y, al final, lo que no sea de ninguna— para que dos
    exportaciones seguidas tengan las pestañas en el mismo sitio. Un orden que dependiera de qué
    categoría apareció primero cambiaría las pestañas de un archivo a otro con los mismos filtros,
    y quien lo abre cada mañana tendría que buscarlas.

    Cuando la consulta ya venía restringida a una categoría, las demás no aparecen ni vacías: sale
    esa y nada más. Si aun así llegara alguna fila de otro sitio —lo que solo puede pasar si el
    filtro de la consulta se hubiera roto— **no se disfraza** metiéndola en la hoja equivocada ni se
    tira: se va a «Otras fuentes», donde se ve. Un reparto que se fiara de lo que dice el llamador
    escondería justamente el fallo que hay que detectar, y tirar la fila sería peor: el archivo
    parecería completo.
    """
    grupos: dict[Categoria | None, list[Mapping[str, Any]]] = {}
    for fila in filas:
        grupos.setdefault(categoria_de_fuente(fila.get("fuente")), []).append(fila)

    if categoria is not None:
        propias = tuple(grupos.pop(categoria, ()))
        hojas: list[tuple[str, tuple[Mapping[str, Any], ...]]] = [
            (ETIQUETA_POR_CATEGORIA[categoria][:LARGO_MAXIMO_HOJA], propias)
        ]
        # Todo lo que no sea de la categoría pedida, junto. Aquí no vale recorrer el mapa por
        # categorías: si se hiciera, las filas de la **otra** categoría —que tienen su propia clave
        # y no la de `None`— se quedarían fuera del libro sin que nada lo dijera.
        resto = tuple(fila for suyas in grupos.values() for fila in suyas)
        if resto:
            hojas.append((ETIQUETA_OTRAS[:LARGO_MAXIMO_HOJA], resto))
        return tuple(hojas)

    hojas = []
    for cual in (*FUENTES_POR_CATEGORIA, None):
        suyas = grupos.get(cual)
        if not suyas:
            continue
        etiqueta = ETIQUETA_POR_CATEGORIA[cual] if cual else ETIQUETA_OTRAS
        hojas.append((etiqueta[:LARGO_MAXIMO_HOJA], tuple(suyas)))

    if not hojas:
        # Una exportación sin resultados tiene que seguir produciendo un archivo válido: Excel no
        # sabe abrir un libro sin ninguna hoja, y un botón que a veces devuelve un error confuso es
        # peor que uno que devuelve una tabla vacía con su cabecera.
        hojas.append(("Contrataciones", ()))

    return tuple(hojas)


def _hoja_destino(libro: Workbook) -> Worksheet:
    """La hoja de la plantilla donde entran los datos. **Nunca se crea una.**

    Se prefiere la que se llama «Datos» —así lo espera quien preparó la plantilla siguiendo esta
    documentación— y si no existe, **la primera hoja del libro**, que es lo que espera cualquiera
    que haya hecho una plantilla sin leer nada: si tiene una sola hoja, los datos van ahí.

    Se busca por nombre **sin distinguir mayúsculas ni espacios sobrantes**, porque quien prepara la
    plantilla escribe «Datos» a mano y «datos » o « Datos» son la misma intención. No se acepta
    ninguna otra variante: suponer que «Datos1» era la hoja buena escribiría en un sitio que nadie
    esperaba, y el resultado —un archivo con los datos en una pestaña invisible— parecería un fallo
    de la aplicación.

    Antes esta función **creaba** una hoja «Datos» cuando no la encontraba, y por eso una plantilla
    de una sola hoja acababa con dos pestañas nuevas: la de datos y la de criterios.
    """
    buscado = HOJA_DE_DATOS.strip().lower()
    for hoja in libro.worksheets:
        if hoja.title.strip().lower() == buscado:
            return hoja
    return libro.worksheets[0]


def _hoja_de_la_familia(libro: Workbook, categoria: Categoria | None) -> Worksheet | None:
    """La hoja que la plantilla dedica a una familia de contratación, si la tiene.

    Una empresa que trabaja con las dos familias suele preparar **una pestaña para cada una** —es lo
    que hace la plantilla «ÍNFIMAS / OFERTAS / PARTICIPACION» que hay subida—, y sus columnas no son
    las mismas en las dos: la de ínfimas lleva el plazo de proformas y la de ofertas el presupuesto.
    Mandar las ofertas a la hoja de ínfimas las dejaría bajo una cabecera que no les corresponde,
    con las columnas propias de la otra familia vacías y sin saber por qué.

    Se compara el nombre de la hoja con la etiqueta de la familia («Ínfimas cuantías»), con su clave
    interna (`infimas`) y con su raíz («ínfima»), ignorando mayúsculas, acentos y espacios
    sobrantes, porque la plantilla real se llama «ÍNFIMAS» y «OFERTAS ».

    La raíz se busca **al principio** del nombre y no en cualquier posición: una hoja llamada
    «Resumen de ofertas recibidas» también empieza por su raíz y es correcto que reciba ofertas,
    pero una llamada «Comparativa ínfimas y ofertas» no es la hoja de ninguna de las dos, y meterle
    los datos de una familia elegiría por ella en un sitio donde las dos aparecen.
    """
    etiqueta = ETIQUETA_POR_CATEGORIA[categoria] if categoria is not None else ETIQUETA_OTRAS
    completa = normalizar(etiqueta)
    raiz = completa.split(" ")[0].rstrip("s")
    admitidos = {completa, raiz}
    if categoria is not None:
        admitidos.add(normalizar(categoria.value))

    for hoja in libro.worksheets:
        titulo = normalizar(hoja.title)
        if titulo in admitidos or titulo.startswith(raiz):
            return hoja
    return None


# Hasta qué fila se busca la cabecera de la plantilla. Un informe suele llevar dos o tres filas de
# título antes de la tabla; buscar por todo el alto de la hoja encontraría la cabecera de una
# segunda tabla a mitad del archivo y escribiría los datos allí.
FILAS_DE_BUSQUEDA = 10

# Cuántos títulos hay que reconocer para creerse que una fila es la cabecera de la tabla.
TITULOS_MINIMOS = 2


@dataclass(frozen=True, slots=True)
class EncabezadoDeLaPlantilla:
    """Dónde están los encabezados de una hoja de la plantilla y qué campo va en cada columna."""

    fila: int
    posiciones: Mapping[str, int]


def _encabezado_de_la_plantilla(hoja: Worksheet) -> EncabezadoDeLaPlantilla | None:
    """La fila de encabezados de la planta y el reparto de columnas. `None` si no la reconoce.

    **Esta es la pieza que hace que la plantilla sea de verdad la plantilla.** La empresa escribe
    sus encabezados —en el orden que quiere y con las columnas que quiere— y el sistema coloca cada
    dato debajo de su título. Da igual que «Razón social» esté en la columna 3 o en la 7, que
    falten columnas, o que haya columnas propias que el sistema no conoce: esas se quedan como
    están, con lo que la empresa haya puesto.

    La fila de los encabezados **no tiene por qué ser la primera.** La plantilla
    «ÍNFIMAS / OFERTAS / PARTICIPACION» que hay subida lleva el nombre del informe y el de la
    familia en las filas 1 a 3, con los títulos de verdad en la 4; buscar solo en la primera fila
    dejaba esa plantilla sin reconocer, y el sistema acababa escribiendo su propia cabecera debajo
    del diseño de la empresa.

    Se elige la fila que reconozca **más** títulos de entre las primeras `FILAS_DE_BUSQUEDA`, y
    hacen falta al menos `TITULOS_MINIMOS`: cualquier informe puede tener la palabra «Estado» en
    una celda suelta, y creerse esa fila escribiría todos los datos apilados en una sola columna.

    Cuando dos columnas llevan el mismo título gana la primera y la segunda se queda con lo que la
    empresa hubiera puesto: escribir en las dos duplicaría el dato, y una edición posterior en el
    archivo editaría solo una de las copias.

    Si no se reconoce ninguna fila se devuelve `None` y el sistema escribe su propia cabecera debajo
    de todo. Es lo correcto: en una plantilla que solo aporta estilos no hay títulos que respetar, y
    adivinar que una celda cualquiera era un encabezado pondría cada columna bajo un título
    equivocado.
    """
    candidato: EncabezadoDeLaPlantilla | None = None
    for fila in range(1, min(hoja.max_row, FILAS_DE_BUSQUEDA) + 1):
        posiciones: dict[str, int] = {}
        for columna in range(1, hoja.max_column + 1):
            titulo = hoja.cell(row=fila, column=columna).value
            if titulo is None:
                continue
            campo = _campo_del_titulo(str(titulo))
            if campo is None or campo in posiciones:
                continue
            posiciones[campo] = columna
        if len(posiciones) < TITULOS_MINIMOS:
            continue
        if candidato is None or len(posiciones) > len(candidato.posiciones):
            candidato = EncabezadoDeLaPlantilla(fila=fila, posiciones=posiciones)
    return candidato


def _campo_del_titulo(titulo: str) -> str | None:
    """El campo al que corresponde un título, o `None` si no es ninguno.

    Se admiten la etiqueta del archivo genérico, la clave interna y los alias que usan las
    plantillas reales; la comparación ignora mayúsculas, acentos y espacios de más, porque
    «Código», «codigo» y «CÓDIGO  » son lo mismo para quien lo escribe a mano.
    """
    return TITULOS.get(normalizar(titulo))


def _primera_fila_de_datos(hoja: Worksheet, encabezado: EncabezadoDeLaPlantilla | None) -> int:
    """Fila donde empiezan los datos de este bloque.

    Con cabecera reconocida, **justo debajo de ella**: el hueco que hubiera entre la cabecera y los
    datos es de la plantilla, y respetarlo dejaría el archivo con un salto raro; además, esa zona es
    justo la que se vacía antes de escribir, así que un hueco ahí no se conservaría de todos modos.

    Sin cabecera reconocida, debajo de todo lo que la hoja ya tuviera: ahí no se distingue el diseño
    del contenido, y escribir encima borraría lo que la empresa puso.
    """
    if encabezado is None:
        return _primera_fila_libre(hoja)
    return encabezado.fila + 1


def _vaciar_bajo_la_cabecera(hoja: Worksheet, fila_cabecera: int) -> None:
    """Deja en blanco **toda** la zona de datos: es lo que hace que la descarga traiga solo el
    resultado actual.

    Una plantilla suele nacer de una descarga anterior a la que la empresa dio formato, así que ya
    trae filas de entonces —la plantilla subida tiene 1.406—. Escribiendo debajo sin vaciar, cada
    descarga arrastraría todo lo anterior y el archivo «con los filtros aplicados» llevaría media
    base histórica dentro, que es justo lo contrario de lo que se pide al descargar.

    La frontera es la fila de encabezados, y es tajante: **por encima es de la empresa y no se
    toca** —logotipo, título del informe, instrucciones—, y por debajo es del sistema y se vacía
    entero. Las dos alternativas que se consideraron dejan el archivo peor:

    - **Conservar las celdas con fórmula**, para no borrar un total del pie, deja ese total sin su
      etiqueta: «TOTAL» es texto y se vacía, así que la fila queda con un número huérfano. Y no se
      arregla volviendo a subir la plantilla, porque la etiqueta vive siempre en la zona que se
      vacía.
    - **No vaciar ninguna fila que contenga una fórmula** convierte una fórmula suelta —una empresa
      que calcula algo por fila— en la razón por la que no se vacía nada, y entonces la descarga
      vuelve a traer todo sin que nada lo advierta. Un fallo silencioso del comportamiento que se
      está arreglando es peor que una etiqueta perdida.

    Se vacían celdas y **no se borran filas**: borrar filas se lleva por delante su formato —alto,
    bordes, color, formato de fecha—, y ese formato es parte de lo que la empresa diseñó. Vaciar lo
    conserva, así que la zona de datos sigue viéndose como la diseñó aunque esté vacía.

    Los enlaces se quitan junto con el valor: si se dejaran, cada fila nueva heredaría la dirección
    de la ficha que ocupaba esa celda en la descarga anterior, y pulsar un código abriría un proceso
    que no es el suyo.
    """
    for fila in range(fila_cabecera + 1, hoja.max_row + 1):
        for columna in range(1, hoja.max_column + 1):
            celda = hoja.cell(row=fila, column=columna)
            if celda.value is None and celda.hyperlink is None:
                continue
            celda.value = None
            celda.hyperlink = None


def _separador_de_ubicacion(hoja: Worksheet, encabezado: EncabezadoDeLaPlantilla) -> str:
    """El separador con el que la plantilla escribe «Provincia - Cantón» en una sola celda.

    Se lee del propio título en lugar de imponer uno: la plantilla real usa el guion en la hoja de
    ínfimas y la barra en la de ofertas, y cambiarle el signo a quien ya lo tenía decidido es
    retocarle el diseño sin motivo.
    """
    columna = encabezado.posiciones.get(CAMPO_UBICACION)
    if columna is None:
        return SEPARADORES_UBICACION[1]
    titulo = str(hoja.cell(row=encabezado.fila, column=columna).value or "")
    for separador in SEPARADORES_UBICACION:
        if separador in titulo:
            return separador
    return SEPARADORES_UBICACION[1]


def _ubicacion(fila: Mapping[str, Any], separador: str) -> str:
    """«PICHINCHA - QUITO» a partir de los dos campos, sin dejar un separador suelto.

    Si solo hay uno de los dos se devuelve ese, y no «PICHINCHA - »: medio dato con un guion
    colgando se lee como un error de la aplicación y estropea la columna para quien la use después.
    """
    provincia = fila.get("provincia")
    canton = fila.get("canton")
    partes = [str(parte).strip() for parte in (provincia, canton) if parte]
    return separador.join(partes)


# Nombre de la hoja de trazabilidad. Va como constante porque se busca en la plantilla por su
# nombre, y dos cadenas escritas por separado acabarían separándose.
NOMBRE_HOJA_CRITERIOS = "Filtros aplicados"


def _hoja_de_criterios_si_existe(libro: Workbook) -> Worksheet | None:
    """La hoja de trazabilidad de la plantilla, si la trae. **No se crea.**"""
    buscado = NOMBRE_HOJA_CRITERIOS.strip().lower()
    for hoja in libro.worksheets:
        if hoja.title.strip().lower() == buscado:
            return hoja
    return None


def _hoja_de_criterios(libro: Workbook) -> Worksheet:
    """La hoja de trazabilidad para un libro que arma el sistema, vaciándola si ya existía.

    Se vacía en lugar de respetarla: esa hoja **es el registro de con qué criterios se hizo el
    archivo**. Dejarla con el contenido fijo que diseñó la plantilla convertiría un dato en un
    adorno: diría siempre lo mismo aunque la exportación fuera de otra cosa. Lo que sí se conserva
    es el formato de la hoja, porque vaciar no es sustituir.
    """
    existente = _hoja_de_criterios_si_existe(libro)
    if existente is None:
        return libro.create_sheet(NOMBRE_HOJA_CRITERIOS)
    if existente.max_row > 1 or existente.cell(row=1, column=1).value is not None:
        existente.delete_rows(1, existente.max_row)
    return existente


def _primera_fila_libre(hoja: Worksheet) -> int:
    """Primera fila sin nada, contando desde arriba.

    El caso de la hoja vacía tiene truco: `max_row` de una hoja recién creada vale 1 aunque no tenga
    nada, así que hay que mirar la celda. Sin esa comprobación, la primera fila libre de una hoja
    vacía saldría 2 y el archivo empezaría con una fila en blanco.
    """
    if hoja.max_row == 1 and hoja.cell(row=1, column=1).value is None:
        return 1
    return int(hoja.max_row) + 1


def _volcar_en_la_plantilla(
    libro: Workbook,
    filas: Sequence[Mapping[str, Any]],
    *,
    filtros: Filtros,
    generado_en: datetime,
    elegidas: Sequence[str] | None = None,
) -> None:
    """Reparte los datos por las hojas de la plantilla, respetando lo que la empresa diseñó.

    Cada familia va a la hoja que la plantilla le dedique —«ÍNFIMAS» y «OFERTAS» en la plantilla
    real— y lo que no tenga hoja propia va a la hoja de datos. Cuando una hoja recibe más de un
    bloque, cada uno lleva delante el nombre de su familia y una fila en blanco de separación: sin
    eso, dos tablas seguidas con columnas distintas se leerían como una sola.

    Lo que decide cómo se escribe cada bloque es la cabecera de **su** hoja, y son dos formas que no
    se pueden confundir:

    - **Con encabezados reconocibles** cada dato va a la columna de **su** título y no se escribe
      ninguna cabecera. La empresa manda sobre las columnas.
    - **Sin ellos** el sistema escribe su propia cabecera y sus columnas. Es el caso de una
      plantilla que solo aporta estilos, donde no hay títulos que respetar: fiarse de una cabecera
      escrita a mano que no cuadrara pondría cada columna bajo un título equivocado, y el archivo
      seguiría abriéndose sin ningún error.

    **Los datos anteriores se sustituyen**, no se arrastran; el porqué y los cuidados están en
    `_vaciar_bajo_la_cabecera`.
    """
    grupos = _hojas_del_libro(filas, categoria=filtros.categoria)

    # Primero se decide todo y después se escribe. Hace falta saber cuántos bloques caen en cada
    # hoja —el título de separación solo se pone cuando de verdad separa algo— y qué hojas tienen
    # cabecera reconocible, para vaciarlas una sola vez: dos bloques en la misma hoja no pueden
    # vaciarla cada uno por su cuenta, porque el segundo se llevaría por delante lo que escribió el
    # primero.
    reparto: list[tuple[Worksheet, str, tuple[Mapping[str, Any], ...]]] = []
    for nombre, suyas in grupos:
        # La categoría del bloque se deduce de sus propias filas y no de lo que pidió el llamador:
        # así un bloque que llegara de otra fuente por un fallo del filtro busca la hoja que le toca
        # y no la de la familia pedida.
        categoria = filtros.categoria if not suyas else categoria_de_fuente(suyas[0].get("fuente"))
        reparto.append(
            (_hoja_de_la_familia(libro, categoria) or _hoja_destino(libro), nombre, suyas)
        )

    bloques: dict[str, int] = {}
    for hoja, _, _ in reparto:
        bloques[hoja.title] = bloques.get(hoja.title, 0) + 1

    encabezados: dict[str, EncabezadoDeLaPlantilla | None] = {}
    for hoja, _, _ in reparto:
        encabezados.setdefault(hoja.title, _encabezado_de_la_plantilla(hoja))

    for titulo, encabezado in encabezados.items():
        if encabezado is not None:
            _vaciar_bajo_la_cabecera(libro[titulo], encabezado.fila)

    siguiente: dict[str, int] = {}
    for hoja, nombre, suyas in reparto:
        encabezado = encabezados[hoja.title]
        inicio = _primera_fila_de_datos(hoja, encabezado)
        fila = siguiente.get(hoja.title, inicio)
        if fila > inicio:
            fila += 1  # una fila en blanco entre bloques, para que se vean separados
        if bloques[hoja.title] > 1:
            hoja.cell(row=fila, column=1, value=nombre).font = _ETIQUETA_BLOQUE
            fila += 1
        columnas = columnas_del_libro(suyas, elegidas=elegidas)
        if encabezado is None:
            _escribir_contrataciones(
                hoja,
                suyas,
                columnas,
                generado_en=generado_en,
                fila_cabecera=fila,
            )
            siguiente[hoja.title] = fila + len(suyas) + 1
        else:
            _escribir_en_columnas(
                hoja, suyas, columnas, encabezado, generado_en=generado_en, primera=fila
            )
            siguiente[hoja.title] = fila + len(suyas)


def _escribir_en_columnas(
    hoja: Worksheet,
    filas: Sequence[Mapping[str, Any]],
    columnas: Sequence[tuple[str, str, int]],
    encabezado: EncabezadoDeLaPlantilla,
    *,
    generado_en: datetime,
    primera: int,
) -> None:
    """Escribe las filas cada una en la columna que la plantilla le dio, sin cabecera.

    **Lo que la plantilla no tenga, no se escribe**, y es una decisión con un coste que conviene
    tener escrito: si su tabla no tiene «Cantón», ese dato no aparece en el archivo, aunque sí esté
    en la pantalla y en la exportación sin plantilla. Lo mismo con un campo que la fuente publique
    mañana y la plantilla no pueda conocer.

    La alternativa —añadir las columnas que faltan a la derecha de la tabla— se descartó porque es
    peor de lo que parece: una tabla de la empresa suele tener totales, fórmulas o columnas propias
    justo a la derecha, y meter datos en medio las desplaza sin avisar. Un dato que falta se ve y se
    repara añadiendo la columna a la plantilla; una fórmula descolocada da un número equivocado y
    nadie lo nota.

    No se escribe la fila de cabecera porque ya está: la puso la empresa, y es la que dice dónde va
    cada cosa. Solo se escriben los datos.
    """
    posiciones = encabezado.posiciones
    pide_ubicacion = CAMPO_UBICACION in posiciones
    separador = _separador_de_ubicacion(hoja, encabezado) if pide_ubicacion else ""

    for numero_fila, fila in enumerate(filas, start=primera):
        dias = dias_para_proforma(fila.get("fecha_limite_proformas"), ahora=generado_en)
        for clave, _, _ in columnas:
            columna = posiciones.get(clave)
            if columna is None:
                continue
            if clave == COLUMNA_PLAZO[0]:
                celda = hoja.cell(row=numero_fila, column=columna, value=texto_de_plazo(dias))
                relleno = RELLENOS.get(nivel_de_plazo(dias))
                if relleno is not None:
                    celda.fill = relleno
                continue
            if clave == COLUMNA_CPC[0]:
                hoja.cell(row=numero_fila, column=columna, value=_texto_cpc(fila))
                continue
            celda = hoja.cell(row=numero_fila, column=columna, value=_valor_celda(fila.get(clave)))
            if clave == COLUMNA_CODIGO:
                _marcar_enlace(celda, fila.get(CLAVE_ENLACE))

        # La ubicación va aparte del bucle anterior a propósito: no es una columna del registro
        # sino una que se compone con dos, así que no está entre las claves que traen los datos y
        # el bucle —que recorre `columnas`— nunca la vería.
        if pide_ubicacion:
            texto = _ubicacion(fila, separador)
            if texto:
                hoja.cell(row=numero_fila, column=posiciones[CAMPO_UBICACION], value=texto)


def columnas_del_libro(
    filas: Sequence[Mapping[str, Any]],
    elegidas: Sequence[str] | None = None,
) -> tuple[tuple[str, str, int], ...]:
    """Columnas del archivo: las conocidas primero y después las que aparezcan en los datos.

    El orden de las extras es el de primera aparición, que es estable para el mismo conjunto de
    filas y hace que dos exportaciones seguidas tengan la misma forma.

    `elegidas` es la selección que la empresa guardó en su pantalla de plantilla. **Manda sobre
    todo lo demás**: se escribe lo elegido y nada más, en el orden del catálogo. Es lo que convierte
    «esta columna no me interesa» en algo que se cumple, y como la selección es por empresa, vale
    para todas las descargas sin que nadie tenga que acordarse de nada.

    Sin selección se mantiene el comportamiento de siempre, **incluidas las columnas que aparezcan
    en los datos y no estén en el catálogo**. Es deliberado que la selección desactive esa parte:
    quien elige columnas quiere un archivo predecible, y añadirle una columna nueva de la fuente por
    su cuenta rompería justo eso. Con la lista vacía se ve todo, que es lo que hace que una empresa
    pueda empezar sin tocar nada.
    """
    conocidas = {clave for clave, _, _ in COLUMNAS}
    conocidas.add(COLUMNA_PLAZO[0])
    conocidas.add(COLUMNA_CPC[0])
    conocidas.update(clave for clave, _, _ in COLUMNAS_CONTEXTO)
    conocidas |= CLAVES_INTERNAS

    if elegidas:
        permitidas = set(elegidas)
        return tuple(
            columna
            for columna in (*COLUMNAS, COLUMNA_CPC, COLUMNA_PLAZO, *COLUMNAS_CONTEXTO)
            if columna[0] in permitidas
        )

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
    return (*COLUMNAS, COLUMNA_CPC, COLUMNA_PLAZO, *extras, *COLUMNAS_CONTEXTO)


def _texto_cpc(fila: Mapping[str, Any]) -> str:
    """CPC de una fila, ya resumido: «871410032 LAVADO Y ENGRASADO DE AUTOMOTORES».

    Una necesidad puede tener varias clasificaciones distintas y todas caben en la celda separadas
    por una barra. Los códigos repetidos salen una sola vez: una necesidad con diecisiete líneas del
    mismo servicio tiene **un** CPC, no diecisiete.

    Vacío significa «no se ha leído la ficha todavía», y es información: no es lo mismo que una
    necesidad sin detalle.
    """
    return resumen_cpc(items_desde_crudos(fila.get("items") or ()))


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
    fila_cabecera: int = 1,
) -> None:
    """Escribe una tabla: cabecera, filas y el formato que las hace legibles.

    `fila_cabecera` existe para poder escribir **debajo** de lo que ya haya en la hoja, que es
    lo que pasa cuando el libro sale de una plantilla con un logotipo o un título arriba.
    """
    for indice, (_, etiqueta, ancho) in enumerate(columnas, start=1):
        celda = hoja.cell(row=fila_cabecera, column=indice, value=etiqueta)
        celda.font = _ETIQUETA_CABECERA
        celda.fill = _CABECERA
        celda.alignment = Alignment(vertical="center")
        letra = get_column_letter(indice)
        # El ancho lo pone el sistema **solo si no había ninguno**. En una plantilla, quien la
        # diseñó ya decidió cómo de anchas quiere las columnas, y pisárselo sería deshacerle el
        # trabajo en cada exportación.
        if not hoja.column_dimensions[letra].width:
            hoja.column_dimensions[letra].width = ancho

    for numero_fila, fila in enumerate(filas, start=fila_cabecera + 1):
        dias = dias_para_proforma(fila.get("fecha_limite_proformas"), ahora=generado_en)
        for indice, (clave, _, _) in enumerate(columnas, start=1):
            if clave == COLUMNA_PLAZO[0]:
                celda = hoja.cell(row=numero_fila, column=indice, value=texto_de_plazo(dias))
                relleno = RELLENOS.get(nivel_de_plazo(dias))
                if relleno is not None:
                    celda.fill = relleno
                continue
            if clave == COLUMNA_CPC[0]:
                hoja.cell(row=numero_fila, column=indice, value=_texto_cpc(fila))
                continue
            celda = hoja.cell(row=numero_fila, column=indice, value=_valor_celda(fila.get(clave)))
            if clave == COLUMNA_CODIGO:
                _marcar_enlace(celda, fila.get(CLAVE_ENLACE))

    # La fila de cabecera queda fija y el filtro cubre toda la tabla: sin esto, desplazarse por un
    # archivo de mil filas deja de tener referencia de qué columna se está mirando.
    #
    # Solo se ponen cuando la tabla **empieza en la primera fila**, que es el caso de la exportación
    # normal. En una plantilla con contenido encima, o con varios bloques de categoría, Excel solo
    # admite un filtro por hoja y congelar en la fila 2 dejaría quieta justo la fila equivocada.
    # Decidir ahí por nuestra cuenta sería peor que no ponerlo.
    if fila_cabecera == 1:
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
        (
            "Categoría",
            ETIQUETA_POR_CATEGORIA[filtros.categoria]
            if filtros.categoria
            else "todas (una hoja por categoría)",
        ),
        (
            "Provincias",
            ", ".join(filtros.provincias) if filtros.provincias else "todas",
        ),
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
