"""Enrutador de búsqueda y consulta del histórico.

Es la puerta de CU-03 y CU-05. Todas las rutas de aquí cumplen una restricción que conviene tener
presente leyéndolas: **ninguna origina tráfico hacia la fuente oficial** (R-01). Si el usuario pide
palabras clave que aún no se han ingestado, la respuesta llega con lo que hay y el aviso de que la
consulta se hará en el próximo ciclo; para pedir una ingesta hay que ir a `/v1/terminos`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response

from contratacion.aplicacion.casos_uso.buscar_registros import buscar, obtener_estadisticas
from contratacion.aplicacion.casos_uso.exportar_registros import TIPO_LIBRO, exportar
from contratacion.dominio.acceso import Vista, fuentes_para_vistas
from contratacion.dominio.busqueda import (
    TAMANO_MAXIMO,
    TAMANO_PREDETERMINADO,
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    normalizar_terminos,
)
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.serializacion import cuerpo_json
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import (
    ActorDep,
    AjustesDep,
    ConsentimientoDep,
    ConsultasDep,
    VistasDep,
)
from contratacion.infraestructura.adaptadores.salida.cache.cliente import obtener_cache

router = APIRouter(prefix="/v1", tags=["Búsqueda"])


def _filtros_compartidos(
    *,
    termino: list[str] | None,
    modo: ModoBusqueda,
    fuente: str | None,
    provincia: str | None,
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
        modo=modo,
        fuente=fuente,
        fuentes_permitidas=fuentes,
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
    fuente: Annotated[str | None, Query(description="Código de fuente: NCO u OCDS.")] = None,
    provincia: str | None = None,
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
            modo=modo,
            fuente=fuente,
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

    resultado = await exportar(
        filtros,
        repositorio=consultas,
        limite=ajustes.export_async_umbral_filas,
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
    consultas: ConsultasDep, vistas: VistasDep, _: ConsentimientoDep
) -> dict[str, Any]:
    """Pobla los desplegables del panel con lo que realmente hay en el histórico.

    Sin ninguna vista que dé acceso a datos no hay desplegables que ofrecer: devolver los catálogos
    revelaría qué provincias y entidades hay, aunque el usuario no pueda ver los registros.
    """
    if not fuentes_para_vistas(vistas):
        raise SinPermiso("No tienes ninguna vista concedida que dé acceso al histórico.")
    return cuerpo_json(dict(await consultas.catalogos()))


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
    )
    return cuerpo_json(dict(datos))
