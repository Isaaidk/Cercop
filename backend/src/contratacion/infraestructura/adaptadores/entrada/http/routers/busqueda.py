"""Enrutador de búsqueda y consulta del histórico.

Es la puerta de CU-03 y CU-05. Todas las rutas de aquí cumplen una restricción que conviene tener
presente leyéndolas: **ninguna origina tráfico hacia la fuente oficial** (R-01). Si el usuario pide
palabras clave que aún no se han ingestado, la respuesta llega con lo que hay y el aviso de que la
consulta se hará en el próximo ciclo; para pedir una ingesta hay que ir a `/v1/terminos`.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from contratacion.aplicacion.actor import Actor
from contratacion.aplicacion.casos_uso.buscar_registros import (
    buscar,
    obtener_catalogos,
    obtener_estadisticas,
)
from contratacion.aplicacion.casos_uso.exportar_registros import TIPO_LIBRO, exportar
from contratacion.aplicacion.casos_uso.gestionar_plantilla import leer_contenido
from contratacion.aplicacion.puertos.exportacion import RepositorioColumnasExportacion
from contratacion.aplicacion.puertos.plantillas import AlmacenPlantillas, RepositorioPlantillas
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.busqueda import (
    TAMANO_MAXIMO,
    TAMANO_PREDETERMINADO,
    Categoria,
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    normalizar_provincias,
    normalizar_terminos,
)
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AjustesDep,
    AlmacenPlantillasDep,
    ColumnasDep,
    ConsentimientoDep,
    ConsultasDep,
    PlantillasDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.salida.cache.cliente import obtener_cache

router = APIRouter(prefix="/v1", tags=["Búsqueda"])

registro = logging.getLogger(__name__)


async def _columnas_elegidas(
    actor: Actor,
    *,
    columnas: RepositorioColumnasExportacion,
) -> tuple[str, ...] | None:
    """Las columnas que la empresa eligió, o `None` si no se puede saber.

    **Nunca lanza**, por el mismo motivo que `_plantilla_si_la_hay`: un fallo al leer la selección
    no puede dejar a alguien sin su Excel. Si no se puede leer, se exporta con todas las columnas,
    que es lo que se ha hecho siempre y es un archivo más ancho, no un archivo mal formado. Se avisa
    en el registro para que se pueda arreglar.

    Una selección guardada que mencione una columna que ya no existe no es un error aquí: el
    catálogo decide qué se escribe, así que la columna desconocida simplemente no aparece. Rechazar
    la descarga por eso sería castigar al usuario por un cambio nuestro.
    """
    try:
        guardada = await columnas.obtener(negocio_id=actor.negocio_id)
    except Exception:  # noqa: BLE001 - una selección ilegible no puede impedir exportar
        registro.warning(
            "No se pudo leer la selección de columnas del negocio %s; se exportarán todas",
            actor.negocio_id,
            exc_info=False,
        )
        return None
    if guardada is None or not guardada.columnas:
        return None
    return guardada.columnas


async def _plantilla_si_la_hay(
    actor: Actor,
    *,
    plantillas: RepositorioPlantillas,
    almacen: AlmacenPlantillas,
) -> bytes | None:
    """Los bytes de la plantilla de la empresa, ya resueltos por el caso de uso.

    Se conserva como envoltorio con nombre propio porque en este enrutador la pregunta es «¿hay
    algo con lo que rellenar el libro?», y el nombre del caso de uso —«leer contenido»— describe la
    mecánica, no la intención. La lógica, en cambio, está en un solo sitio.
    """
    return await leer_contenido(actor, repositorio=plantillas, almacen=almacen)


def _filtros_compartidos(
    *,
    termino: list[str] | None,
    cpc: list[str] | None,
    modo: ModoBusqueda,
    fuente: str | None,
    categoria: Categoria | None,
    provincia: list[str] | None,
    estado: str | None,
    entidad: str | None,
    tipo_proceso: str | None,
    tipo_necesidad: str | None,
    codigo: str | None,
    desde: date | None,
    hasta: date | None,
    solo_nuevos: bool,
    solo_con_plazo: bool,
    vistas: frozenset[Vista],
    intervalo_ingesta_min: int,
) -> Filtros:
    """Construye los criterios a partir de los parámetros, resolviendo el permiso por fuente.

    Es una función y no un bloque repetido porque la usan **la tabla y las gráficas**. Tenerla aquí,
    en un solo sitio, es lo que garantiza que las dos vean exactamente el mismo conjunto de datos:
    si cada endpoint armara sus filtros por su cuenta, el día que uno cambiara el otro seguiría con
    los criterios viejos y el panel mostraría un total que no corresponde a las filas de debajo.

    **El permiso decide qué se puede leer.** Si se pide una fuente concreta y no está concedida, la
    petición se rechaza; si no se pide ninguna, el resultado se limita a las permitidas. Ese límite
    viaja dentro de la clave de caché, así que dos usuarios con permisos distintos nunca comparten
    resultado.
    """
    permitidas = fuentes_para_vistas(vistas)
    if fuente:
        elegida = fuente.strip().upper()
        if elegida not in permitidas:
            raise SinPermiso(
                f"No tienes acceso a la fuente {elegida!r}. Pide al administrador que te "
                "conceda la vista correspondiente."
            )
        fuentes: tuple[str, ...] = (elegida,)
        fuente = elegida
    else:
        fuentes = permitidas

    return Filtros(
        terminos=normalizar_terminos(termino),
        cpc=normalizar_terminos(cpc),
        modo=modo,
        fuente=fuente,
        categoria=categoria,
        fuentes_permitidas=fuentes,
        provincias=normalizar_provincias(provincia),
        estado=estado,
        entidad=entidad,
        tipo_proceso=tipo_proceso,
        tipo_necesidad=tipo_necesidad,
        codigo=codigo,
        desde=desde,
        hasta=hasta,
        solo_nuevos=solo_nuevos,
        solo_con_plazo=solo_con_plazo,
        ventana_nuevos_min=max(60, intervalo_ingesta_min * 4),
    )


async def criterios(
    ajustes: AjustesDep,
    vistas: VistasDep,
    termino: Annotated[
        list[str] | None,
        Query(
            description=(
                "Palabra clave. Se puede repetir para combinar varias: "
                "`?termino=obras&termino=viales`."
            )
        ),
    ] = None,
    modo: Annotated[
        ModoBusqueda,
        Query(
            description=(
                "«cualquiera» suma los resultados de cada término; «todas» exige que se cumplan "
                "todos. Con «todas», dos palabras que por separado devuelven datos suelen devolver "
                "cero."
            )
        ),
    ] = ModoBusqueda.TODAS,
    cpc: Annotated[
        list[str] | None,
        Query(
            description=(
                "Busca en el CPC de los ítems de la necesidad —el código y su nombre estándar— "
                "y no en el texto libre de la convocatoria. Se puede repetir para combinar "
                "varias: `?cpc=871410032&cpc=lavado`. Es independiente de `termino`; si se "
                "envían los dos, se exigen ambos."
            )
        ),
    ] = None,
    fuente: Annotated[str | None, Query(description="Código de fuente: NCO u OCDS.")] = None,
    categoria: Annotated[
        Categoria | None,
        Query(
            description=(
                "Familia de contratación. «infimas» son las necesidades de compra (NCO) e "
                "«ofertas» los procesos con oferta (OCDS). En la exportación, cada categoría sale "
                "en su propia hoja; sin este parámetro salen todas, una hoja por categoría."
            )
        ),
    ] = None,
    provincia: Annotated[
        list[str] | None,
        Query(
            description=(
                "Provincia o provincias por las que filtrar. Se puede repetir el parámetro para "
                "elegir varias: `?provincia=Azuay&provincia=Pichincha`. Sin él, todas."
            )
        ),
    ] = None,
    estado: str | None = None,
    entidad: Annotated[
        str | None,
        Query(description="Fragmento de la razón social de la entidad contratante."),
    ] = None,
    tipo_proceso: Annotated[
        str | None,
        Query(description="Tipo de contratación, tal y como aparece en el catálogo."),
    ] = None,
    tipo_necesidad: Annotated[
        str | None,
        Query(description="Tipo de compra, tal y como aparece en el catálogo."),
    ] = None,
    codigo: Annotated[str | None, Query(description="Fragmento del código del proceso.")] = None,
    desde: Annotated[
        date | None, Query(description="Fecha de publicación inicial (incluida).")
    ] = None,
    hasta: Annotated[
        date | None, Query(description="Fecha de publicación final (incluida).")
    ] = None,
    solo_nuevos: Annotated[
        bool, Query(description="Solo lo detectado en la última hora de ingesta.")
    ] = False,
    solo_con_plazo: Annotated[
        bool,
        Query(description="Oculta lo que ya no admite entrega de proformas."),
    ] = False,
    texto: Annotated[
        str | None, Query(description="Búsqueda libre, además de los términos.")
    ] = None,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamano: Annotated[int, Query(ge=1, le=TAMANO_MAXIMO)] = TAMANO_PREDETERMINADO,
    orden: OrdenBusqueda = OrdenBusqueda.RECIENTES,
) -> Filtros:
    """Los criterios de la petición, validados y con el permiso por fuente ya resuelto.

    Es una dependencia y no un bloque repetido porque **los tres endpoints de datos —tabla, gráficas
    y exportación— tienen que filtrar exactamente lo mismo**. Copiar la lista de parámetros en cada
    uno garantiza que el día que se añada un filtro habrá dos endpoints que lo ignoren, y el síntoma
    sería el peor: un archivo de Excel con filas que la pantalla no muestra.

    FastAPI la resuelve igual en los tres sitios, así que el contrato de parámetros es
    literalmente el mismo objeto de código.
    """
    return replace(
        _filtros_compartidos(
            termino=termino,
            cpc=cpc,
            modo=modo,
            fuente=fuente,
            categoria=categoria,
            provincia=provincia,
            estado=estado,
            entidad=entidad,
            tipo_proceso=tipo_proceso,
            tipo_necesidad=tipo_necesidad,
            codigo=codigo,
            desde=desde,
            hasta=hasta,
            solo_nuevos=solo_nuevos,
            solo_con_plazo=solo_con_plazo,
            vistas=vistas,
            intervalo_ingesta_min=ajustes.intervalo_ingesta_min,
        ),
        texto=texto,
        pagina=pagina,
        tamano=tamano,
        orden=orden,
    )


# Los criterios ya resueltos. El texto libre, la ventana y la paginación entran en la huella de
# caché, así que van aquí y no en cada endpoint.
CriteriosDep = Annotated[Filtros, Depends(criterios)]


@router.get("/registros", summary="Buscar en el histórico de contrataciones")
async def buscar_registros(
    consultas: ConsultasDep,
    ajustes: AjustesDep,
    filtros: CriteriosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Devuelve una página de resultados, servida desde el caché cuando es posible.

    La respuesta incluye `desde_cache` y `generacion`: son la forma de comprobar, sin herramientas
    internas, que el caché está haciendo su trabajo y que la invalidación tras un ciclo funciona.
    """
    resultado = await buscar(
        filtros,
        cache=obtener_cache(),
        repositorio=consultas,
        ttl_seg=ajustes.ttl_resultados_seg,
        ttl_memo_seg=ajustes.cache_proceso_seg,
    )
    return cuerpo_json(resultado.como_diccionario())


@router.get(
    "/registros/exportacion",
    summary="Descargar en Excel los registros que cumplen los filtros",
    response_class=Response,
    responses={
        200: {
            "content": {TIPO_LIBRO: {}},
            "description": "Libro de Excel con todos los resultados, no solo la página visible.",
        }
    },
)
async def exportar_registros(
    consultas: ConsultasDep,
    ajustes: AjustesDep,
    actor: ActorDep,
    filtros: CriteriosDep,
    plantillas: PlantillasDep,
    almacen: AlmacenPlantillasDep,
    columnas_guardadas: ColumnasDep,
    _: ConsentimientoDep,
) -> Response:
    """Genera y devuelve el archivo `.xlsx` con **todo** lo que cumple los filtros.

    Tres cosas que conviene tener presentes:

    - **Recibe los mismos criterios que la tabla**, de la misma dependencia. Sin eso, el archivo
      podría contener un conjunto distinto del que se está viendo, y el usuario no tendría forma de
      saber cuál de los dos está mal.
    - **No se pagina.** Un archivo con las veinticinco filas de la página en curso no sirve para
      trabajar fuera de la plataforma, que es justo para lo que se exporta. El tope que sí se aplica
      es el de configuración, y si se supera se rechaza en lugar de entregar un archivo incompleto.
    - **Pide permiso de exportación, no de consulta.** Un lector ve la tabla y no descarga el
      archivo: lo que sale de la plataforma deja de estar bajo nuestro control.

    El nombre del archivo va entre comillas dobles en la cabecera porque los navegadores lo esperan
    así cuando puede contener caracteres especiales, y `X-Contenido-Filas` permite avisar de
    cuántas contrataciones se han llevado sin volver a contar el archivo.
    """
    actor.exigir_exportador()

    # Si la empresa subió su propia plantilla, el archivo sale con su diseño: el logo, sus hojas y
    # sus estilos se conservan y los datos se escriben dentro. Si no hay ninguna, o si el archivo
    # ya no está en el disco, se genera el libro genérico.
    #
    # **Un fallo al leer la plantilla no puede impedir la exportación.** Si el archivo se borró del
    # disco o el disco falla, quedarse sin descargar nada sería peor que descargar el libro de
    # siempre: el dato es lo que la persona necesita, y el diseño es una comodidad. Se avisa en el
    # registro y se sigue, en vez de convertir un problema de presentación en uno de acceso.
    plantilla = await _plantilla_si_la_hay(actor, plantillas=plantillas, almacen=almacen)
    # Y qué columnas quiere la empresa. Las dos cosas son «cómo sale el archivo»: el diseño lo pone
    # la plantilla y el ancho lo pone la selección.
    columnas = await _columnas_elegidas(actor, columnas=columnas_guardadas)

    resultado = await exportar(
        filtros,
        repositorio=consultas,
        limite=ajustes.export_async_umbral_filas,
        plantilla=plantilla,
        columnas=columnas,
    )

    return Response(
        content=resultado.contenido,
        media_type=TIPO_LIBRO,
        headers={
            "Content-Disposition": f'attachment; filename="{resultado.nombre}"',
            "X-Contenido-Filas": str(resultado.filas),
            # Sin esto, un proxy intermedio podría cachear el archivo y servir a otro usuario el de
            # los filtros de este. Son datos de negocio y van firmados por la sesión de quien pide.
            "Cache-Control": "no-store",
        },
    )


@router.get("/catalogos", summary="Valores disponibles para los filtros")
async def catalogos(
    consultas: ConsultasDep,
    ajustes: AjustesDep,
    vistas: VistasDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Pobla los desplegables del panel con lo que realmente hay en el histórico.

    Sin ninguna vista que dé acceso a datos no hay desplegables que ofrecer: devolver los catálogos
    revelaría qué provincias y entidades hay, aunque el usuario no pueda ver los registros.

    El permiso se comprueba **antes** de mirar el caché, y eso importa: si se consultara primero, un
    usuario sin ninguna vista recibiría la respuesta que dejó cacheada otro y la puerta no serviría
    de nada. Es el mismo cuidado que con los resultados, aplicado a una entrada que comparten todos
    los usuarios.
    """
    if not fuentes_para_vistas(vistas):
        raise SinPermiso("No tienes ninguna vista concedida que dé acceso al histórico.")

    datos = await obtener_catalogos(
        cache=obtener_cache(),
        repositorio=consultas,
        ttl_seg=ajustes.ttl_catalogo_seg,
        ttl_memo_seg=ajustes.cache_proceso_seg,
    )
    return cuerpo_json(dict(datos))


@router.get("/estadisticas", summary="Agregados para las gráficas")
async def estadisticas(
    consultas: ConsultasDep,
    ajustes: AjustesDep,
    vistas: VistasDep,
    filtros: CriteriosDep,
    _: ConsentimientoDep,
) -> dict[str, Any]:
    """Totales por fuente, serie mensual y reparto por provincia, **según los filtros activos**.

    Acepta los mismos criterios que `/registros` a propósito, y no solo la fuente. Es lo que evita
    que el panel muestre un reparto por provincia que no corresponde a las contrataciones de las
    palabras clave seleccionadas: si las gráficas ignoraran los términos, la tabla y el gráfico
    contarían conjuntos distintos y el usuario no tendría forma de saber cuál de los dos números es
    el equivocado.

    Se exige la vista de gráficas, además del consentimiento: los agregados revelan la existencia y
    el volumen de los datos, así que están sujetos a la misma puerta que la tabla.
    """
    if Vista.GRAFICAS not in vistas:
        raise SinPermiso("La vista de gráficas no está incluida en tu suscripción.")

    datos = await obtener_estadisticas(
        filtros,
        cache=obtener_cache(),
        repositorio=consultas,
        ttl_seg=ajustes.ttl_estadisticas_seg,
        ttl_memo_seg=ajustes.cache_proceso_seg,
    )
    return cuerpo_json(dict(datos))
