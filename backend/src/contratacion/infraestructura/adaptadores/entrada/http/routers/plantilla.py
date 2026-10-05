"""Enrutador de la plantilla de Excel de la empresa.

Cuatro rutas: consultar qué plantilla hay, subir una nueva, quitarla y elegir las columnas que
llevan las exportaciones. La que cambia algo del archivo es la de subir, y es la única de todo el
sistema que recibe un archivo de fuera, así que se explica sola en su docstring.

Las columnas van en esta misma familia de rutas —y no en un enrutador propio— porque son la otra
mitad de la misma decisión: qué se ve y qué se lleva cada archivo que la empresa manda fuera.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from contratacion.aplicacion.casos_uso.analizar_plantilla import analizar
from contratacion.aplicacion.casos_uso.exportar_registros import GRUPOS_DE_COLUMNAS
from contratacion.aplicacion.casos_uso.gestionar_columnas import (
    consultar as consultar_columnas,
)
from contratacion.aplicacion.casos_uso.gestionar_columnas import (
    guardar as guardar_columnas,
)
from contratacion.aplicacion.casos_uso.gestionar_plantilla import (
    consultar,
    leer_contenido,
    nombre_de_la_hoja,
    quitar,
    subir,
)
from contratacion.aplicacion.plantillas import HOJA_DE_DATOS, TAMANO_MAXIMO_BYTES
from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AlmacenPlantillasDep,
    ColumnasDep,
    PlantillasDep,
)

router = APIRouter(prefix="/v1/plantilla", tags=["Plantilla de Excel"])

registro = logging.getLogger(__name__)


class SeleccionDeColumnasPedida(BaseModel):
    """Las columnas que la empresa quiere en sus exportaciones.

    Una lista **vacía** no es un error: significa «todas», y es lo que envía el botón que deshace la
    selección. Lo que se rechaza es una clave que no exista en el catálogo, y de eso se encarga el
    caso de uso, que es donde está la lista de la que se puede elegir.
    """

    columnas: list[str] = Field(default_factory=list, examples=[["codigo", "entidad", "monto"]])


def _catalogo() -> list[dict[str, Any]]:
    """Las columnas elegibles, agrupadas como se muestran en la pantalla.

    Se arma desde el módulo que escribe el libro —las mismas tuplas que deciden qué columnas tiene
    el archivo— y no desde una lista copiada aquí: una copia se quedaría corta el día que se añada
    una columna, y el síntoma sería una columna que sale en el Excel y no se puede elegir.
    """
    return [
        {
            "grupo": grupo,
            "columnas": [{"clave": clave, "etiqueta": etiqueta} for clave, etiqueta in columnas],
        }
        for grupo, columnas in GRUPOS_DE_COLUMNAS
    ]


@router.get("", summary="Ver la plantilla de Excel de la empresa")
async def ver_plantilla(
    actor: ActorDep,
    plantillas: PlantillasDep,
    columnas: ColumnasDep,
) -> dict[str, Any]:
    """Dice si la empresa tiene plantilla, cuál es y qué columnas salen en sus exportaciones.

    Lo puede consultar cualquier rol. No hay nada reservado en un nombre de archivo y una fecha, y
    saber que existe evita la pregunta de «¿por qué mi Excel sale distinto que el de mi compañero?».
    La selección de columnas se consulta junto a la plantilla porque las dos deciden lo mismo: cómo
    sale el archivo.
    """
    guardada = await consultar(actor, repositorio=plantillas)
    elegidas = await consultar_columnas(actor, repositorio=columnas)
    return cuerpo_json(
        {
            "tiene_plantilla": guardada is not None,
            "plantilla": None if guardada is None else guardada.como_diccionario(),
            "hoja_de_datos": nombre_de_la_hoja(),
            "tamano_maximo_bytes": TAMANO_MAXIMO_BYTES,
            "columnas_disponibles": _catalogo(),
            "columnas_elegidas": None if elegidas is None else list(elegidas),
        }
    )


@router.put("/columnas", summary="Elegir las columnas que llevan las exportaciones")
async def elegir_columnas(
    cuerpo: SeleccionDeColumnasPedida,
    actor: ActorDep,
    columnas: ColumnasDep,
) -> dict[str, Any]:
    """Reemplaza la selección de columnas de la empresa.

    El cuerpo se manda **entero**, no como un cambio parcial: aceptar «añade esta y quita aquella»
    obligaría a distinguir «no lo envíes» de «bórralo», y con esa ambigüedad acabas con dos
    navegadores que se pisan la selección sin que ninguno se entere.

    Solo un rol administrativo: son las columnas de todos los archivos que la empresa manda fuera.
    """
    limpias = await guardar_columnas(actor, columnas=cuerpo.columnas, repositorio=columnas)
    return cuerpo_json({"columnas_elegidas": list(limpias)})


@router.get("/analisis", summary="Comprobar dónde entrarán los datos en la plantilla")
async def analizar_plantilla(
    actor: ActorDep,
    plantillas: PlantillasDep,
    almacen: AlmacenPlantillasDep,
) -> dict[str, Any]:
    """Dice, hoja por hoja, qué haría el sistema con la plantilla que la empresa tiene subida.

    Responde a la pregunta que no se puede contestar mirando el archivo: dónde encuentra el sistema
    la fila de títulos, en qué fila empezarían los datos y a qué hoja va cada familia. Un título
    escrito de otra manera —«Descripción» en vez de «Objeto de compra»— o una hoja que no se llama
    como el sistema espera dejan de ser un misterio: se ven aquí.

    Se calcula a petición y no al abrir la pestaña porque **abre el libro entero**, y la pantalla de
    la plantilla también se consulta para saber una fecha.
    """
    contenido = await leer_contenido(actor, repositorio=plantillas, almacen=almacen)
    if contenido is None:
        # Sin plantilla, o con una que no se puede leer. No es un error de la petición: la pantalla
        # pregunta «¿dónde entrarían mis datos?» y la respuesta honesta es «no hay plantilla».
        return cuerpo_json(
            {
                "hay_plantilla": False,
                "hojas": [],
                "destinos": {},
                "familias_sin_hoja_propia": [],
            }
        )

    try:
        informe = analizar(contenido)
    except Exception as exc:  # se traduce a algo que el usuario entiende
        raise DatoInvalido(
            "No se ha podido leer la plantilla guardada. Vuelve a subirla y, si se repite, "
            "avisa al administrador."
        ) from exc
    return cuerpo_json({"hay_plantilla": True, **informe.como_diccionario()})


@router.post(
    "",
    summary="Subir la plantilla de Excel de la empresa",
    status_code=status.HTTP_201_CREATED,
)
async def subir_plantilla(
    actor: ActorDep,
    plantillas: PlantillasDep,
    almacen: AlmacenPlantillasDep,
    archivo: Annotated[UploadFile, File(description="Libro .xlsx sin macros")],
) -> dict[str, Any]:
    """Reemplaza la plantilla de la empresa por el archivo que se sube.

    Tres decisiones en el borde, y las tres son deliberadas:

    - **Se limita el tamaño al recibir, no solo al guardar.** El archivo se lee entero en memoria
      —una plantilla no llega a ocho megas— y leer sin tope algo que sube cualquiera es la forma más
      directa de tumbar el proceso. El tope se comprueba **antes** de tener el contenido entero, así
      que un archivo de dos gigas se rechaza sin llegar a leerlo.

    - **Se lee en trozos y se corta al pasarse**, en vez de confiar en la cabecera
      `Content-Length`. Esa cabecera la pone el cliente: quien quiera mandar más de la cuenta
      simplemente no la pondría, o pondría un número pequeño y mandaría el doble.

    - **El nombre del archivo solo se usa como etiqueta.** La ruta en el disco la compone el almacén
      a partir del identificador del negocio, así que un nombre con barras o con `..` no puede
      escribir fuera de su sitio. El nombre original se guarda para poder decirle a la persona cuál
      subió.

    Que el rol sea administrativo lo comprueba el caso de uso y no esta función: la regla es de
    negocio, y aquí solo se traduce el archivo.
    """
    contenido = await _leer_con_tope(archivo)

    guardada = await subir(
        actor,
        nombre_archivo=archivo.filename or "plantilla.xlsx",
        contenido=contenido,
        repositorio=plantillas,
        almacen=almacen,
    )
    return cuerpo_json({"plantilla": guardada.como_diccionario()})


@router.delete("", summary="Quitar la plantilla de Excel de la empresa")
async def quitar_plantilla(
    actor: ActorDep,
    plantillas: PlantillasDep,
    almacen: AlmacenPlantillasDep,
) -> dict[str, Any]:
    """Deja la empresa sin plantilla: las exportaciones vuelven al libro genérico.

    **No falla si no había ninguna.** El botón que la quita puede pulsarse dos veces —una persona
    impaciente, una red que reintenta— y la segunda vez el resultado correcto es «ya no hay», no un
    error que haga pensar que no se quitó.
    """
    quitada = await quitar(actor, repositorio=plantillas, almacen=almacen)
    return cuerpo_json({"quitada": quitada})


async def _leer_con_tope(archivo: UploadFile) -> bytes:
    """Lee el archivo y corta si pasa del máximo, sin haberlo leído entero.

    Se lee por trozos y se va sumando: así un archivo enorme se rechaza cuando llega al tope, no
    cuando ya está todo en memoria. Es la diferencia entre rechazar la petición y quedarse sin
    memoria mientras se la rechaza.
    """
    trozo = 64 * 1024
    partes: list[bytes] = []
    leidos = 0

    while True:
        bloque = await archivo.read(trozo)
        if not bloque:
            break
        leidos += len(bloque)
        if leidos > TAMANO_MAXIMO_BYTES:
            megas = TAMANO_MAXIMO_BYTES / (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"El archivo pasa del máximo de {megas:.0f} MB. "
                    "Suele venir de imágenes muy grandes incrustadas en la hoja."
                ),
            )
        partes.append(bloque)

    # `HOJA_DE_DATOS` se importa para que el contrato de la ruta quede documentado en el propio
    # módulo: es el nombre que la persona tiene que poner en su plantilla.
    registro.debug("Plantilla recibida para la hoja %s (%s bytes)", HOJA_DE_DATOS, leidos)
    return b"".join(partes)
