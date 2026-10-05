"""Reglas de la plantilla de Excel que sube una empresa.

Este módulo existe por una razón concreta: **un archivo que sube un cliente es la única entrada del
sistema que no controlamos nosotros**. Todo lo demás —SERCOP, la base, el caché— lo ponemos
nosotros; esto no. Y si se abre sin mirarlo, el fallo no es cosmético.

Qué se comprueba, y por qué cada cosa
-------------------------------------
- **El tamaño**, antes de nada. Es lo primero porque es lo único que se puede comprobar sin leer el
  contenido, y porque un archivo enorme agota la memoria del proceso antes de que ninguna otra
  comprobación llegue a ejecutarse.

- **Que sea un ZIP de verdad.** Un `.xlsx` es un ZIP. Comprobar la extensión del nombre no vale: se
  renombra y ya está. Se miran los cuatro primeros bytes.

- **Que sea un libro de Excel**, no un ZIP cualquiera. Un ZIP con fotos dentro pasa la comprobación
  anterior y falla después al abrirlo, con un error de librería que no dice nada a quien lo subió.

- **Que no traiga macros.** Un `.xlsm` renombrado a `.xlsx` es un ZIP de Excel perfectamente válido
  con un `xl/vbaProject.bin` dentro, y ese archivo es **código ejecutable**. Se detecta por su
  presencia en el índice del ZIP, sin extraerlo y sin abrirlo. La razón para rechazarlo no es
  técnica: es que este sistema entrega los archivos que genera a personas que no han subido la
  plantilla —compañeros, clientes, gestorías—, y regalarles un libro con macros que alguien subió
  convierte una función cómoda en un vector de ataque que no controlamos.

- **Que tenga alguna hoja.** Un libro sin hojas no se puede rellenar, y fallaría al exportar en vez
  de al subir, que es el peor momento para enterarse.
"""

from __future__ import annotations

import io
import logging
import zipfile

from openpyxl import load_workbook

from contratacion.dominio.errores import DatoInvalido

registro = logging.getLogger(__name__)

# Nombre de la hoja donde el sistema escribe los datos.
#
# Se elige un nombre **por convención** y no una celda marcadora porque la plantilla decide el
# diseño, no el contenido: quien prepara el archivo añade una hoja, la llama «Datos» y deja el
# resto del libro con su logo y sus tablas. Una celda marcadora obligaría a acordarse de escribirla
# en cada plantilla nueva y a saber que existe.
HOJA_DE_DATOS = "Datos"

# Tope del archivo subido. Es cómodo y generoso —una plantilla con logotipo no llega a un megabyte—
# y a la vez corta un abuso. El proxy tiene el suyo (10 MB) como red de seguridad, porque un límite
# en el borde no exime de comprobarlo aquí.
TAMANO_MAXIMO_BYTES = 8 * 1024 * 1024

# Los cuatro primeros bytes de cualquier ZIP: `PK\x03\x04`. Se comprueba esto y no el nombre porque
# el nombre lo elige quien sube.
FIRMA_ZIP = b"PK\x03\x04"

# Ruta interna donde Excel guarda el proyecto de macros. Buscarlo en el índice del ZIP es suficiente
# y no hay que extraer nada.
RUTA_MACROS = "xl/vbaProject.bin"

# Componentes que tiene cualquier libro de Excel y no tiene un ZIP cualquiera.
RUTA_LIBRO = "xl/workbook.xml"


def revisar_plantilla(nombre: str, contenido: bytes) -> None:
    """Comprueba que el archivo sirve como plantilla. Lanza `DatoInvalido` explicando por qué no.

    El mensaje es para la persona que lo subió, no para quien depure: dice **qué** pasa y **qué**
    hacer. Un «archivo no válido» a secas obliga a adivinar si el problema es el formato, el
    tamaño o que el archivo esté corrupto.
    """
    etiqueta = (nombre or "el archivo").strip() or "el archivo"

    if not contenido:
        raise DatoInvalido("El archivo llegó vacío. Vuelve a seleccionarlo y súbelo otra vez.")

    if len(contenido) > TAMANO_MAXIMO_BYTES:
        megas = len(contenido) / (1024 * 1024)
        tope = TAMANO_MAXIMO_BYTES / (1024 * 1024)
        raise DatoInvalido(
            f"{etiqueta} pesa {megas:.1f} MB y el máximo son {tope:.0f} MB. "
            "Suele venir de imágenes muy grandes incrustadas: reduce su tamaño en Excel "
            "y vuelve a subirla."
        )

    if not contenido.startswith(FIRMA_ZIP):
        raise DatoInvalido(
            f"{etiqueta} no es un archivo de Excel. Sube un libro guardado en formato "
            "«Libro de Excel (.xlsx)»; si lo tienes en formato antiguo (.xls), ábrelo y guárdalo "
            "de nuevo con el formato nuevo."
        )

    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as paquete:
            componentes = set(paquete.namelist())
    except zipfile.BadZipFile as exc:
        # La firma está bien pero el resto no: el archivo se cortó al subirlo o al copiarlo.
        raise DatoInvalido(
            f"{etiqueta} está dañado o se ha subido a medias. Vuelve a subirlo."
        ) from exc

    if RUTA_MACROS in componentes:
        raise DatoInvalido(
            f"{etiqueta} es un libro con macros (.xlsm), y por seguridad no se admiten. "
            "Los archivos con macros pueden ejecutar código en el equipo de quien los abre, y "
            "este sistema entrega los Excel generados a otras personas. Guárdalo como "
            "«Libro de Excel (.xlsx)» —sin macros— y vuelve a subirlo."
        )

    if RUTA_LIBRO not in componentes:
        raise DatoInvalido(
            f"{etiqueta} es un archivo comprimido, pero no un libro de Excel. "
            "Sube la plantilla guardada desde Excel con el formato «Libro de Excel (.xlsx)»."
        )

    # La última comprobación es la única que abre el archivo de verdad, así que va al final: si algo
    # se ha rechazado antes, no se ha gastado tiempo en analizar un libro que no iba a usarse.
    try:
        libro = load_workbook(io.BytesIO(contenido), read_only=True)
        hojas = list(libro.sheetnames)
        libro.close()
    except Exception as exc:  # cualquier fallo de openpyxl es «no sirve»
        registro.warning("No se pudo leer la plantilla subida: %s", exc, exc_info=False)
        raise DatoInvalido(
            f"{etiqueta} no se ha podido leer como libro de Excel. Ábrelo con Excel y comprueba "
            "que no esté dañado; si lo abre bien, guárdalo otra vez y súbelo."
        ) from exc

    if not hojas:
        raise DatoInvalido(
            f"{etiqueta} no tiene ninguna hoja. Añade una hoja llamada «{HOJA_DE_DATOS}» "
            "y vuelve a subirlo."
        )
