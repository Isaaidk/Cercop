"""Pruebas de la plantilla de Excel: lo que se acepta, lo que se rechaza y dónde se escribe.

Lo que se defiende aquí son tres cosas que, si fallan, fallan en silencio:

1. **Que un archivo con macros no entre.** Es un ZIP de Excel válido con código ejecutable dentro, y
   el sistema entrega los Excel que genera a otras personas. Un `.xlsm` que pasara el filtro
   convertiría una función cómoda en un vector de ataque repartido con nuestro nombre.
2. **Que el orden de escritura sea el correcto.** Se comprueba que el archivo se valida **antes** de
   tocar el disco: si la validación fuera después, una plantilla inválida habría sustituido ya a la
   buena y la empresa se quedaría sin ninguna por un intento fallido.
3. **Que ningún dato acabe bajo la cabecera equivocada.** El sistema escribe su propia cabecera, y
   esa es la garantía de que el orden de las columnas coincide con el de los valores.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.exportar_registros import construir_libro
from contratacion.aplicacion.casos_uso.gestionar_plantilla import quitar, subir
from contratacion.aplicacion.plantillas import HOJA_DE_DATOS, revisar_plantilla
from contratacion.aplicacion.puertos.plantillas import PlantillaGuardada
from contratacion.dominio.busqueda import Categoria, Filtros
from contratacion.dominio.errores import DatoInvalido, SinPermiso

GENERADO = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
NEGOCIO = UUID("22222222-2222-2222-2222-222222222222")
USUARIO = UUID("11111111-1111-1111-1111-111111111111")

ADMIN = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="admin_negocio")
LECTOR = Actor(usuario_id=USUARIO, negocio_id=NEGOCIO, rol="lector")


# --------------------------------------------------------------------------- #
# Archivos de prueba
# --------------------------------------------------------------------------- #


def _libro(hojas: tuple[str, ...] = (HOJA_DE_DATOS,)) -> bytes:
    """Un `.xlsx` de verdad, con las hojas indicadas."""
    libro = Workbook()
    libro.remove(libro.active)
    for nombre in hojas:
        libro.create_sheet(nombre)
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


def _con_macros() -> bytes:
    """Un ZIP con la forma de un libro de Excel **y** un proyecto de macros dentro.

    Se construye a mano y no con openpyxl porque openpyxl no escribe macros: lo que hay que probar
    es justo el caso de un `.xlsm` renombrado a `.xlsx`, que es lo que llega de verdad.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as paquete:
        paquete.writestr("xl/workbook.xml", "<workbook/>")
        paquete.writestr("xl/vbaProject.bin", b"codigo ejecutable")
    return buffer.getvalue()


def _zip_cualquiera() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as paquete:
        paquete.writestr("fotos/playa.jpg", b"no soy un libro")
    return buffer.getvalue()


def _fila(fuente: str, codigo: str) -> dict[str, Any]:
    return {
        "fuente": fuente,
        "codigo": codigo,
        "entidad": "Municipio de prueba",
        "objeto_compra": "Objeto",
        "fecha_limite_proformas": None,
    }


def _fila_completa(fuente: str, codigo: str, **campos: Any) -> dict[str, Any]:
    """Una fila con los campos que usan las plantillas de verdad —provincia y cantón incluidos—."""
    fila: dict[str, Any] = {
        "fuente": fuente,
        "codigo": codigo,
        "entidad": "Municipio de prueba",
        "objeto_compra": "Objeto",
        "provincia": "PICHINCHA",
        "canton": "QUITO",
        "fecha_publicacion": datetime(2026, 9, 20, 10, 0, tzinfo=UTC),
        "fecha_limite_proformas": None,
    }
    fila.update(campos)
    return fila


def _plantilla(hojas: dict[str, list[list[Any]]]) -> bytes:
    """Un `.xlsx` con el contenido indicado: una lista de filas por cada hoja."""
    libro = Workbook()
    libro.remove(libro.active)
    for nombre, filas in hojas.items():
        hoja = libro.create_sheet(nombre)
        for fila in filas:
            hoja.append(fila)
    buffer = io.BytesIO()
    libro.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Lo que se acepta y lo que no
# --------------------------------------------------------------------------- #


def test_un_libro_valido_se_acepta() -> None:
    revisar_plantilla("mi-plantilla.xlsx", _libro())


def test_un_archivo_vacio_se_rechaza() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        revisar_plantilla("vacio.xlsx", b"")
    assert "vacío" in str(fallo.value)


def test_algo_que_no_es_un_zip_se_rechaza_nombrando_el_formato() -> None:
    with pytest.raises(DatoInvalido) as fallo:
        revisar_plantilla("notas.xlsx", b"esto es texto, no un libro")
    assert "no es un archivo de Excel" in str(fallo.value)


def test_un_zip_que_no_es_un_libro_se_rechaza() -> None:
    """Pasar la comprobación de ZIP no basta: hay que ser un libro."""
    with pytest.raises(DatoInvalido) as fallo:
        revisar_plantilla("fotos.xlsx", _zip_cualquiera())
    assert "no un libro de Excel" in str(fallo.value)


def test_un_libro_con_macros_se_rechaza_explicando_el_riesgo() -> None:
    """Es la comprobación que más importa de este archivo.

    El archivo es un ZIP de Excel perfectamente válido: lo único que lo delata es la presencia de
    `xl/vbaProject.bin`. Si esta prueba fallara, el sistema estaría repartiendo macros con su nombre
    a todas las personas a las que alguien manda una exportación.
    """
    with pytest.raises(DatoInvalido) as fallo:
        revisar_plantilla("plantilla.xlsx", _con_macros())

    mensaje = str(fallo.value)
    assert "macros" in mensaje
    assert ".xlsm" in mensaje


def test_un_archivo_demasiado_grande_se_rechaza_antes_de_leerlo() -> None:
    from contratacion.aplicacion.plantillas import TAMANO_MAXIMO_BYTES

    grande = b"x" * (TAMANO_MAXIMO_BYTES + 1)
    with pytest.raises(DatoInvalido) as fallo:
        revisar_plantilla("enorme.xlsx", grande)
    assert "MB" in str(fallo.value)


def test_un_zip_truncado_se_rechaza_sin_reventar() -> None:
    """Un archivo cortado al subirlo tiene la firma bien y el resto mal."""
    entero = _libro()
    with pytest.raises(DatoInvalido):
        revisar_plantilla("cortado.xlsx", entero[: len(entero) // 2])


# --------------------------------------------------------------------------- #
# Dónde se escribe dentro de la plantilla
# --------------------------------------------------------------------------- #


def _libro_con(filas: list[dict[str, Any]], plantilla: bytes, **cambios: Any) -> Any:
    contenido = construir_libro(
        filas, filtros=Filtros(**cambios), generado_en=GENERADO, plantilla=plantilla
    )
    return load_workbook(io.BytesIO(contenido))


def test_los_datos_entran_en_la_hoja_datos() -> None:
    libro = _libro_con([_fila("NCO", "A-1")], _libro(("Portada", HOJA_DE_DATOS)))

    datos = libro[HOJA_DE_DATOS]
    assert datos.cell(row=1, column=1).value == "Código"
    assert datos.cell(row=2, column=1).value == "A-1"


def test_las_demas_hojas_de_la_plantilla_se_conservan() -> None:
    """El diseño de la empresa no se toca: para eso subió su plantilla."""
    libro = _libro_con([_fila("NCO", "A-1")], _libro(("Portada", HOJA_DE_DATOS)))

    assert "Portada" in libro.sheetnames


def test_sin_hoja_datos_los_datos_entran_en_la_primera_hoja() -> None:
    """Una plantilla de una sola hoja recibe los datos ahí, y **no se crea ninguna otra**.

    Antes se creaba una hoja «Datos» al no encontrarla, y por eso una plantilla sencilla acababa con
    dos pestañas nuevas —esa y la de criterios— que nadie había diseñado. El resultado era un libro
    con las hojas de la empresa más dos de más, que es lo contrario de lo que se espera cuando uno
    sube su propia plantilla.
    """
    libro = _libro_con([_fila("NCO", "A-1")], _libro(("Portada",)))

    assert libro.sheetnames == ["Portada"], "no se añade ninguna hoja a la plantilla"
    assert libro["Portada"].cell(row=1, column=1).value == "Código"
    assert libro["Portada"].cell(row=2, column=1).value == "A-1"


def test_el_nombre_de_la_hoja_no_distingue_mayusculas_ni_espacios() -> None:
    """Quien prepara la plantilla escribe el nombre a mano, y la hoja manda sobre la posición."""
    libro = _libro_con([_fila("NCO", "A-1")], _libro(("Portada", " datos ")))

    assert libro.sheetnames == ["Portada", " datos "], "no se crea una segunda hoja"
    assert libro[" datos "].cell(row=1, column=1).value == "Código"
    assert libro["Portada"].cell(row=1, column=1).value is None


def test_los_datos_van_debajo_de_lo_que_ya_tenia_la_hoja() -> None:
    """Un logotipo o un título arriba no se pisan."""
    plantilla = _libro((HOJA_DE_DATOS,))
    libro = load_workbook(io.BytesIO(plantilla))
    libro[HOJA_DE_DATOS]["A1"] = "INFORME DE CONTRATACIONES"
    buffer = io.BytesIO()
    libro.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A1"].value == "INFORME DE CONTRATACIONES"
    assert datos["A2"].value == "Código"  # la cabecera va justo debajo
    assert datos["A3"].value == "A-1"


def test_la_hoja_de_criterios_no_se_añade_a_la_plantilla() -> None:
    """La trazabilidad no se impone: se añade a la plantilla solo si la empresa la diseñó.

    Es la segunda de las dos hojas que el sistema creaba por su cuenta. Un libro que sale de una
    plantilla tiene que tener **exactamente** las pestañas de esa plantilla; si alguien quiere el
    registro de con qué filtros se hizo el archivo, añade la hoja «Filtros aplicados» a su plantilla
    y se rellena sola.
    """
    libro = _libro_con([_fila("NCO", "A-1")], _libro(("Portada", HOJA_DE_DATOS)))

    assert libro.sheetnames == ["Portada", HOJA_DE_DATOS]


def test_los_datos_van_bajo_los_titulos_de_la_empresa() -> None:
    """La plantilla decide las columnas y su orden; el sistema rellena debajo de cada título.

    Es la prueba que define el comportamiento nuevo. La empresa ha puesto «Fecha de publicación»
    primero y «Código» segunda —al revés que el archivo genérico—, y cada dato tiene que caer bajo
    **su** encabezado. Escribir un orden propio debajo de una cabecera ajena pondría cada valor bajo
    un título equivocado, y el archivo seguiría abriéndose sin ningún error: es el peor final
    posible, porque nadie lo detecta.
    """
    plantilla = _libro((HOJA_DE_DATOS,))
    borrador = load_workbook(io.BytesIO(plantilla))
    hoja = borrador[HOJA_DE_DATOS]
    hoja["A1"] = "Fecha de publicación"
    hoja["B1"] = "Código"
    hoja["C1"] = "Objeto de compra"
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A1"].value == "Fecha de publicación", "la cabecera de la empresa no se toca"
    assert datos["B1"].value == "Código"
    assert datos["B2"].value == "A-1"
    assert datos["C2"].value == "Objeto"
    # «Municipio de prueba» es la entidad, y la plantilla no tiene esa columna: no aparece.
    fila = [datos.cell(row=2, column=columna).value for columna in range(1, datos.max_column + 1)]
    assert "Municipio de prueba" not in fila


def test_lo_que_la_empresa_escribio_sobre_la_cabecera_no_se_pisa() -> None:
    """El diseño que va **encima** de la cabecera sobrevive; lo que está en la zona de datos, no.

    El reparto es deliberado y conviene tenerlo escrito. Los datos entran justo debajo de la fila de
    encabezados, y esa zona se vacía antes, porque es donde quedaron las filas de la descarga
    anterior —una plantilla nace casi siempre de una descarga a la que la empresa dio formato—.
    Escribiendo debajo sin vaciar, cada descarga arrastraría todo lo anterior.

    El precio es que una nota puesta **en la zona de datos** se sustituye, así que las instrucciones
    van encima de la cabecera —que es lo que se conserva, como el logotipo o el título del informe—
    o en otra hoja.
    """
    plantilla = _libro((HOJA_DE_DATOS,))
    borrador = load_workbook(io.BytesIO(plantilla))
    hoja = borrador[HOJA_DE_DATOS]
    hoja["A1"] = "REGISTRO DE COMPRAS 2026"
    hoja["A2"] = "Código"
    hoja["B2"] = "Provincia"
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila_completa("NCO", "A-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A1"].value == "REGISTRO DE COMPRAS 2026", "el título de la empresa no se toca"
    assert datos["A2"].value == "Código", "la cabecera sigue donde estaba"
    assert datos["A3"].value == "A-1", "los datos empiezan justo debajo de la cabecera"


def test_las_filas_de_una_descarga_anterior_no_se_arrastran() -> None:
    """La descarga trae **solo** lo que cumplen los filtros, no lo que ya venía en la plantilla.

    Es la razón de ser del vaciado: la plantilla subida tiene 1.406 filas de una descarga anterior,
    y sin vaciarlas el archivo «con los filtros aplicados» llevaría media base histórica dentro.
    """
    plantilla = _plantilla(
        {HOJA_DE_DATOS: [["Código", "Provincia"], ["VIEJO-1", "AZUAY"], ["VIEJO-2", "AZUAY"]]}
    )

    resultado = _libro_con([_fila_completa("NCO", "NUEVO-1")], plantilla)
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A2"].value == "NUEVO-1"
    assert datos["B2"].value == "PICHINCHA"
    assert datos["A3"].value is None, "la fila de la descarga anterior se sustituye"
    assert datos["B3"].value is None


def test_el_formato_de_la_zona_de_datos_sobrevive_al_vaciado() -> None:
    """Se vacían celdas, no se borran filas: borrar se llevaría por delante el diseño.

    El alto de fila, los bordes y el color de la zona de datos son parte de lo que la empresa diseñó
    al dar formato a su plantilla, y perderlos en cada descarga sería deshacerle el trabajo.
    """
    plantilla = _plantilla({HOJA_DE_DATOS: [["Código"], ["VIEJO-1"]]})
    borrador = load_workbook(io.BytesIO(plantilla))
    hoja = borrador[HOJA_DE_DATOS]
    hoja.row_dimensions[2].height = 33
    hoja["A1"].font = Font(bold=True)
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila_completa("NCO", "NUEVO-1")], buffer.getvalue())

    assert resultado[HOJA_DE_DATOS].row_dimensions[2].height == 33
    assert resultado[HOJA_DE_DATOS]["A1"].font.bold is True


def test_los_enlaces_de_la_descarga_anterior_no_se_heredan() -> None:
    """Al vaciar se quita también el hipervínculo de la celda del código.

    Sin esto, la fila nueva heredaría la dirección de la ficha que ocupaba esa celda antes, y pulsar
    el código abriría un proceso que no es el suyo: un enlace equivocado y creíble, que es la peor
    combinación posible.
    """
    plantilla = _plantilla({HOJA_DE_DATOS: [["Código", "Provincia"], ["VIEJO-1", "AZUAY"]]})
    borrador = load_workbook(io.BytesIO(plantilla))
    borrador[HOJA_DE_DATOS]["A2"].hyperlink = "https://portal.example.com/viejo"
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila_completa("NCO", "NUEVO-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A2"].value == "NUEVO-1"
    assert datos["A2"].hyperlink is None


def test_la_cabecera_no_tiene_que_estar_en_la_primera_fila() -> None:
    """Los títulos de verdad pueden estar debajo del nombre del informe.

    Es la forma de la plantilla real «ÍNFIMAS / OFERTAS / PARTICIPACION»: tres filas de título y los
    encabezados en la cuarta. Buscando solo en la primera fila no se reconocía nada, y el sistema
    escribía su propia cabecera al final del archivo.
    """
    plantilla = _plantilla(
        {
            HOJA_DE_DATOS: [
                ["PUBLICACIONES 2026"],
                [],
                ["ÍNFIMA CUANTÍA"],
                ["Entidad Contratante", "Código Necesidad de Contratación"],
                ["VIEJO", "VIEJO-1"],
            ]
        }
    )

    resultado = _libro_con([_fila_completa("NCO", "NIC-001")], plantilla)
    datos = resultado[HOJA_DE_DATOS]

    assert [datos.cell(row=fila, column=1).value for fila in (1, 2, 3)] == [
        "PUBLICACIONES 2026",
        None,
        "ÍNFIMA CUANTÍA",
    ], "los títulos del informe se conservan"
    assert datos["A4"].value == "Entidad Contratante", "la cabecera de la empresa no se pisa"
    assert datos["B4"].value == "Código Necesidad de Contratación"
    assert datos["A5"].value == "Municipio de prueba", "cada dato bajo su propio título"
    assert datos["B5"].value == "NIC-001"
    assert datos["A6"].value is None, "la fila anterior se sustituye"


def test_se_admiten_los_titulos_que_usan_las_plantillas_reales() -> None:
    """Un título con otro nombre no es un título desconocido.

    Las plantillas subidas escriben «Entidad Contratante», «Estado de la Necesidad» o «Descripción
    del Objeto de compra», y ninguna de esas cadenas coincide con la etiqueta del archivo genérico.
    Reconocerlas es lo que evita que el sistema escriba su cabecera debajo del diseño de la empresa.
    """
    plantilla = _plantilla(
        {
            HOJA_DE_DATOS: [
                [
                    "Tipo de Necesidad",
                    "Descripción del Objeto de compra",
                    "Estado de la Necesidad",
                    "Fecha de Publicación",
                    "Interés",
                ]
            ]
        }
    )

    resultado = _libro_con(
        [_fila_completa("NCO", "NIC-001", tipo_necesidad="Ínfimas Cuantías")], plantilla
    )
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A2"].value == "Ínfimas Cuantías"
    assert datos["B2"].value == "Objeto"
    assert datos["C2"].value is None, "el estado no viene en la fila de prueba"
    assert datos["D2"].value == datetime(2026, 9, 20, 10, 0), "la fecha, sin zona horaria"
    assert datos["E1"].value == "Interés", "una columna propia se queda como está"
    assert datos["E2"].value is None, "y el sistema no le escribe nada"


def test_una_columna_de_ubicacion_recibe_provincia_y_canton() -> None:
    """Algunas plantillas juntan provincia y cantón en una sola celda, y hay que respetarlo.

    El separador lo decide el propio título de la plantilla —guion o barra— para no cambiarle el
    estilo a quien ya lo tenía decidido. Con un solo dato se escribe ese, y no «PICHINCHA - »: medio
    dato con un guion colgando se lee como un error de la aplicación.
    """
    plantilla = _plantilla({HOJA_DE_DATOS: [["Código", "Provincia - Cantón"]]})

    resultado = _libro_con([_fila_completa("NCO", "NIC-001")], plantilla)

    assert resultado[HOJA_DE_DATOS]["B2"].value == "PICHINCHA - QUITO"

    sin_canton = _libro_con([_fila_completa("NCO", "NIC-001", canton=None)], plantilla)
    assert sin_canton[HOJA_DE_DATOS]["B2"].value == "PICHINCHA"


def test_cada_familia_va_a_la_hoja_que_la_plantilla_le_dedica() -> None:
    """Una pestaña por familia, si la plantilla las tiene: no es lo mismo una ínfima que una oferta.

    Sus columnas no son las mismas —la de ínfimas lleva el plazo de proformas y la de ofertas el
    presupuesto—, así que mandar las ofertas a la hoja de ínfimas las dejaría bajo una cabecera que
    no les corresponde, con las columnas de la otra familia vacías y sin saber por qué.
    """
    plantilla = _plantilla(
        {
            "ÍNFIMAS": [["Código", "Provincia"]],
            "OFERTAS ": [["Código", "Objeto de compra"]],
        }
    )

    resultado = _libro_con(
        [_fila_completa("NCO", "NIC-001"), _fila_completa("OCDS", "SIE-001")], plantilla
    )

    assert resultado.sheetnames == ["ÍNFIMAS", "OFERTAS "], "no se añade ni se quita ninguna"
    assert resultado["ÍNFIMAS"]["A2"].value == "NIC-001"
    assert resultado["ÍNFIMAS"]["B2"].value == "PICHINCHA"
    assert resultado["OFERTAS "]["A2"].value == "SIE-001"
    assert resultado["OFERTAS "]["B2"].value == "Objeto"


def test_una_columna_que_la_plantilla_no_tiene_no_se_añade() -> None:
    """Las columnas que la empresa no diseñó no se añaden por la derecha.

    Añadirlas parecería más completo y es peor: una tabla de la empresa suele tener totales o
    fórmulas justo a la derecha, y meter columnas nuevas las desplaza sin avisar. Un dato que falta
    se ve y se arregla añadiendo la columna a la plantilla; una fórmula descolocada da un número
    equivocado y nadie lo nota.
    """
    plantilla = _libro((HOJA_DE_DATOS,))
    borrador = load_workbook(io.BytesIO(plantilla))
    hoja = borrador[HOJA_DE_DATOS]
    hoja["A1"] = "Código"
    hoja["B1"] = "Provincia"
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A2"].value == "A-1", "los datos empiezan justo debajo de la cabecera"
    assert datos["C1"].value is None, "no se añade la columna que la empresa no puso"
    assert datos["C2"].value is None, "ni su dato"


def test_un_solo_titulo_reconocido_no_basta_para_creer_que_es_una_cabecera() -> None:
    """Una palabra suelta en la primera fila no convierte esa fila en encabezados.

    Cualquier informe puede empezar con «Estado de la contratación 2026» en la celda A1. Si eso
    bastara, el sistema daría por buena una cabecera de una sola columna y escribiría todos los
    datos apilados en la columna A, sin cabecera y sin que nada fallara.
    """
    plantilla = _libro((HOJA_DE_DATOS,))
    borrador = load_workbook(io.BytesIO(plantilla))
    borrador[HOJA_DE_DATOS]["A1"] = "Estado de la contratación 2026"
    buffer = io.BytesIO()
    borrador.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())
    datos = resultado[HOJA_DE_DATOS]

    assert datos["A1"].value == "Estado de la contratación 2026"
    assert datos["A2"].value == "Código", "se escribe la cabecera propia debajo"
    assert datos["A3"].value == "A-1"


def test_la_hoja_de_criterios_de_la_plantilla_se_reescribe_no_se_duplica() -> None:
    """Si la plantilla trae una hoja con ese nombre, se vacía en vez de añadir otra."""
    plantilla = _libro(("Filtros aplicados", HOJA_DE_DATOS))
    libro = load_workbook(io.BytesIO(plantilla))
    libro["Filtros aplicados"]["A1"] = "texto fijo que no debe quedarse"
    buffer = io.BytesIO()
    libro.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())

    assert resultado.sheetnames.count("Filtros aplicados") == 1
    assert resultado["Filtros aplicados"]["A1"].value == "Criterio"


def test_las_dos_categorias_van_al_mismo_libro_separadas() -> None:
    """Con plantilla no se crean hojas nuevas; se separan con un título y una fila en blanco."""
    libro = _libro_con([_fila("NCO", "A-1"), _fila("OCDS", "B-1")], _libro((HOJA_DE_DATOS,)))
    datos = libro[HOJA_DE_DATOS]

    columna_a = [datos.cell(row=fila, column=1).value for fila in range(1, datos.max_row + 1)]
    assert "Ínfimas cuantías" in columna_a
    assert "Ofertas" in columna_a


def test_con_una_categoria_no_se_pone_titulo_de_bloque() -> None:
    """Con una sola no hace falta separar nada: el título sobraría."""
    libro = _libro_con(
        [_fila("NCO", "A-1")],
        _libro((HOJA_DE_DATOS,)),
        categoria=Categoria.INFIMAS,
    )
    datos = libro[HOJA_DE_DATOS]

    assert datos["A1"].value == "Código"
    assert datos["A2"].value == "A-1"


def test_el_ancho_de_columna_de_la_plantilla_no_se_pisa() -> None:
    """Quien diseñó la plantilla ya decidió cómo de anchas quiere las columnas."""
    plantilla = _libro((HOJA_DE_DATOS,))
    libro = load_workbook(io.BytesIO(plantilla))
    libro[HOJA_DE_DATOS].column_dimensions["A"].width = 7
    buffer = io.BytesIO()
    libro.save(buffer)

    resultado = _libro_con([_fila("NCO", "A-1")], buffer.getvalue())

    assert resultado[HOJA_DE_DATOS].column_dimensions["A"].width == 7


# --------------------------------------------------------------------------- #
# Dobles para los casos de uso
# --------------------------------------------------------------------------- #


class RepositorioFalso:
    def __init__(self, *, orden: list[str] | None = None) -> None:
        self.orden = orden if orden is not None else []
        self.fila: PlantillaGuardada | None = None
        self.reemplazos: list[dict[str, Any]] = []

    async def obtener(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        return self.fila

    async def reemplazar(self, **datos: Any) -> None:
        self.orden.append("repositorio.reemplazar")
        self.reemplazos.append(datos)
        self.fila = PlantillaGuardada(
            negocio_id=datos["negocio_id"],
            nombre_archivo=datos["nombre_archivo"],
            ruta=datos["ruta"],
            hash_contenido=datos["hash_contenido"],
            tamano_bytes=datos["tamano_bytes"],
            actualizado_en=datos["momento"],
        )

    async def eliminar(self, *, negocio_id: UUID) -> PlantillaGuardada | None:
        self.orden.append("repositorio.eliminar")
        quitada, self.fila = self.fila, None
        return quitada


class AlmacenFalso:
    def __init__(self, *, orden: list[str] | None = None) -> None:
        self.orden = orden if orden is not None else []
        self.escrito: bytes | None = None
        self.borradas: list[str] = []

    async def guardar(self, *, negocio_id: UUID, contenido: bytes) -> str:
        self.orden.append("almacen.guardar")
        self.escrito = contenido
        return f"/plantillas/{negocio_id}.xlsx"

    async def leer(self, *, ruta: str) -> bytes:
        if self.escrito is None:
            raise FileNotFoundError(ruta)
        return self.escrito

    async def borrar(self, *, ruta: str) -> None:
        self.orden.append("almacen.borrar")
        self.borradas.append(ruta)


# --------------------------------------------------------------------------- #
# Casos de uso
# --------------------------------------------------------------------------- #


async def test_subir_valida_antes_de_tocar_el_disco() -> None:
    """Si se validara después, una plantilla inválida ya habría sustituido a la buena."""
    orden: list[str] = []
    repositorio, almacen = RepositorioFalso(orden=orden), AlmacenFalso(orden=orden)

    with pytest.raises(DatoInvalido):
        await subir(
            ADMIN,
            nombre_archivo="malo.xlsx",
            contenido=b"no soy un libro",
            repositorio=repositorio,
            almacen=almacen,
        )

    assert orden == []
    assert almacen.escrito is None


async def test_subir_escribe_el_archivo_y_despues_la_fila() -> None:
    orden: list[str] = []
    repositorio, almacen = RepositorioFalso(orden=orden), AlmacenFalso(orden=orden)

    guardada = await subir(
        ADMIN,
        nombre_archivo="mi-plantilla.xlsx",
        contenido=_libro(),
        repositorio=repositorio,
        almacen=almacen,
    )

    assert orden == ["almacen.guardar", "repositorio.reemplazar"]
    assert guardada.nombre_archivo == "mi-plantilla.xlsx"
    assert guardada.tamano_bytes > 0


async def test_subir_guarda_la_huella_del_archivo() -> None:
    repositorio, almacen = RepositorioFalso(), AlmacenFalso()

    guardada = await subir(
        ADMIN,
        nombre_archivo="p.xlsx",
        contenido=_libro(),
        repositorio=repositorio,
        almacen=almacen,
    )

    # `sha256` tiene 64 caracteres hexadecimales; lo que importa es que sea una huella y no el
    # contenido ni una cadena vacía.
    assert len(guardada.hash_contenido) == 64


async def test_un_rol_de_lectura_no_puede_subir_plantilla() -> None:
    """La plantilla decide cómo se ve todo lo que la empresa exporta."""
    repositorio, almacen = RepositorioFalso(), AlmacenFalso()

    with pytest.raises(SinPermiso):
        await subir(
            LECTOR,
            nombre_archivo="p.xlsx",
            contenido=_libro(),
            repositorio=repositorio,
            almacen=almacen,
        )

    assert almacen.escrito is None


async def test_un_rol_de_lectura_no_puede_quitar_la_plantilla() -> None:
    repositorio, almacen = RepositorioFalso(), AlmacenFalso()

    with pytest.raises(SinPermiso):
        await quitar(LECTOR, repositorio=repositorio, almacen=almacen)

    assert almacen.borradas == []


async def test_quitar_borra_la_fila_antes_que_el_archivo() -> None:
    orden: list[str] = []
    repositorio, almacen = RepositorioFalso(orden=orden), AlmacenFalso(orden=orden)
    await subir(
        ADMIN,
        nombre_archivo="p.xlsx",
        contenido=_libro(),
        repositorio=repositorio,
        almacen=almacen,
    )
    orden.clear()

    quitada = await quitar(ADMIN, repositorio=repositorio, almacen=almacen)

    assert quitada is True
    assert orden == ["repositorio.eliminar", "almacen.borrar"]


async def test_quitar_sin_plantilla_no_es_un_error() -> None:
    """El botón puede pulsarse dos veces, y la segunda el resultado correcto es «ya no hay»."""
    quitada = await quitar(ADMIN, repositorio=RepositorioFalso(), almacen=AlmacenFalso())

    assert quitada is False


async def test_subir_dos_veces_reemplaza_y_no_acumula() -> None:
    """Es la regla acordada: una plantilla por empresa, la última gana."""
    repositorio, almacen = RepositorioFalso(), AlmacenFalso()

    await subir(
        ADMIN,
        nombre_archivo="primera.xlsx",
        contenido=_libro(),
        repositorio=repositorio,
        almacen=almacen,
    )
    await subir(
        ADMIN,
        nombre_archivo="segunda.xlsx",
        contenido=_libro(("Portada", HOJA_DE_DATOS)),
        repositorio=repositorio,
        almacen=almacen,
    )

    assert len(repositorio.reemplazos) == 2
    assert repositorio.fila is not None
    assert repositorio.fila.nombre_archivo == "segunda.xlsx"


async def test_el_almacen_local_nombra_el_archivo_con_el_identificador(tmp_path: Any) -> None:
    """El nombre que subió el cliente no entra en la ruta, y por eso no hay nada que sanear.

    Se prueba contra el almacén de verdad y no contra un doble porque es justo aquí donde puede
    colarse un camino construido con texto del usuario. El puerto **no acepta** un nombre: solo el
    identificador del negocio, que lo genera el sistema.
    """
    from contratacion.infraestructura.adaptadores.salida.archivos.local import AlmacenLocal

    almacen = AlmacenLocal(tmp_path)
    negocio = uuid4()

    ruta = await almacen.guardar(negocio_id=negocio, contenido=b"contenido de prueba")

    assert ruta == str(tmp_path / f"{negocio}.xlsx")
    assert await almacen.leer(ruta=ruta) == b"contenido de prueba"


async def test_el_almacen_local_reemplaza_sin_dejar_restos(tmp_path: Any) -> None:
    """El archivo se sustituye de forma atómica y no queda el temporal al lado."""
    from contratacion.infraestructura.adaptadores.salida.archivos.local import AlmacenLocal

    almacen = AlmacenLocal(tmp_path)
    negocio = uuid4()

    await almacen.guardar(negocio_id=negocio, contenido=b"primera")
    ruta = await almacen.guardar(negocio_id=negocio, contenido=b"segunda")

    assert await almacen.leer(ruta=ruta) == b"segunda"
    assert [p.name for p in tmp_path.iterdir()] == [f"{negocio}.xlsx"]


async def test_borrar_un_archivo_que_ya_no_esta_no_falla(tmp_path: Any) -> None:
    """Se llama justo después de quitar la fila, y que ya no esté es el objetivo cumplido."""
    from contratacion.infraestructura.adaptadores.salida.archivos.local import AlmacenLocal

    almacen = AlmacenLocal(tmp_path)

    await almacen.borrar(ruta=str(tmp_path / "no-existe.xlsx"))
