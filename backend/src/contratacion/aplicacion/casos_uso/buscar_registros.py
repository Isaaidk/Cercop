"""Caso de uso: consultar el histórico, con la caché por delante.

Es el camino que recorre CU-03 y el que hace que aplicar filtros no cueste más: la combinación de
criterios se reduce a una huella, la huella se busca en el caché y solo si no está se va a la base.

Tres reglas gobiernan este caso de uso:

- **Nunca se habla con la fuente oficial** (R-01). Si el usuario quiere datos que no están, se
  encolan; aquí no se consulta el SERCOP jamás.
- **La caché nunca rompe la consulta.** Si el almacén falla, se va a la base y se devuelve un aviso;
  perder el caché cuesta latencia, no corrección (RNF-04).
- **La generación viaja en la clave.** Cuando un ciclo de ingesta encuentra cambios sube el
  contador, así que las páginas antiguas dejan de encontrarse sin borrar una sola clave.
"""

from __future__ import annotations

import logging

from contratacion.aplicacion.generaciones import leer_generacion
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.dominio.busqueda import (
    TTL_ESTADISTICAS_SEG,
    TTL_RESULTADOS_SEG,
    Filtros,
    PaginaResultados,
    clave_estadisticas,
    clave_resultados,
)
from contratacion.dominio.errores import SinPermiso
from contratacion.dominio.serializacion import a_json, de_json

registro = logging.getLogger(__name__)

AVISO_SIN_CACHE = "El caché no respondió; el resultado se obtuvo de la base de datos."
MENSAJE_SIN_FUENTES = (
    "No hay ninguna vista concedida que dé acceso al histórico. Pide al administrador que active "
    "al menos una."
)


async def buscar(
    filtros: Filtros,
    *,
    cache: Cache,
    repositorio: RepositorioConsultas,
    ttl_seg: int = TTL_RESULTADOS_SEG,
) -> PaginaResultados:
    """Devuelve una página de resultados, sirviéndola desde el caché cuando es posible."""
    validados = filtros.validado()

    # Sin fuentes permitidas no se consulta nada. Se comprueba aquí, en el caso de uso, para que
    # la garantía no dependa de que cada enrutador se acuerde: cualquier llamador queda cubierto.
    if not validados.fuentes_permitidas:
        raise SinPermiso(MENSAJE_SIN_FUENTES)

    avisos: list[str] = []

    generacion = await leer_generacion(cache)
    clave = clave_resultados(validados, generacion)

    guardado = await _leer_cache(cache, clave, avisos)
    if guardado is not None:
        return _reconstruir(guardado, validados, generacion, avisos)

    elementos, total = await repositorio.buscar(validados)
    pagina = PaginaResultados(
        elementos=elementos,
        total=total,
        pagina=validados.pagina,
        tamano=validados.tamano,
        generacion=generacion,
        desde_cache=False,
        avisos=tuple(avisos),
    )

    await _guardar_cache(cache, clave, pagina, ttl_seg)
    return pagina


async def obtener_estadisticas(
    filtros: Filtros,
    *,
    cache: Cache,
    repositorio: RepositorioConsultas,
    ttl_seg: int = TTL_ESTADISTICAS_SEG,
) -> dict[str, object]:
    """Agregados de las gráficas, calculados sobre el resultado filtrado y cacheados.

    Recibe los mismos criterios que la búsqueda para que la tabla y las gráficas cuenten lo mismo.
    La paginación se ignora: un reparto por provincia que cambiara al pasar de página sería un
    sinsentido.

    Se comprueba el permiso igual que en la búsqueda, y con la misma negativa si no hay ninguna
    fuente concedida. Las gráficas revelan la existencia y el volumen de los datos —cuántas
    contrataciones hay en cada provincia— así que están sujetas a la misma puerta que la tabla;
    abrirlas «porque solo son totales» dejaría un camino para deducir lo que no se puede leer.
    """
    validados = filtros.validado()
    if not validados.fuentes_permitidas:
        raise SinPermiso(MENSAJE_SIN_FUENTES)

    generacion = await leer_generacion(cache)
    clave = clave_estadisticas(validados, generacion)

    try:
        guardado = await cache.obtener(clave)
    except Exception:  # noqa: BLE001 - la caché nunca rompe la consulta
        guardado = None

    if guardado is not None:
        try:
            datos = de_json(guardado)
            if isinstance(datos, dict):
                return datos
        except Exception:  # noqa: BLE001 - una entrada ilegible equivale a no tenerla
            registro.warning("Estadísticas ilegibles en caché; se recalculan", exc_info=False)

    datos = dict(await repositorio.estadisticas(validados))
    try:
        await cache.guardar(clave, a_json(datos), ttl_seg)
    except Exception:  # noqa: BLE001 - no guardar no impide responder
        registro.warning("No se pudieron guardar las estadísticas en caché", exc_info=False)
    return datos


async def _leer_cache(cache: Cache, clave: str, avisos: list[str]) -> PaginaResultados | None:
    """Intenta resolver la consulta desde el caché. Devuelve `None` si no hay acierto."""
    try:
        contenido = await cache.obtener(clave)
    except Exception:  # noqa: BLE001
        registro.warning("Fallo al leer del caché", exc_info=False)
        avisos.append(AVISO_SIN_CACHE)
        return None
    if contenido is None:
        return None
    try:
        return _pagina_desde_json(contenido)
    except Exception:  # noqa: BLE001 - una entrada corrupta equivale a un fallo de acierto
        registro.warning("Entrada de caché ilegible; se ignora", exc_info=False)
        return None


def _pagina_desde_json(contenido: str) -> PaginaResultados:
    datos = de_json(contenido)
    return PaginaResultados(
        elementos=tuple(datos["elementos"]),
        total=int(datos["total"]),
        pagina=int(datos["pagina"]),
        tamano=int(datos["tamano"]),
        generacion=int(datos["generacion"]),
        desde_cache=True,
    )


def _reconstruir(
    pagina: PaginaResultados, filtros: Filtros, generacion: int, avisos: list[str]
) -> PaginaResultados:
    """Ajusta la página servida desde caché al formato final de la respuesta."""
    return PaginaResultados(
        elementos=pagina.elementos,
        total=pagina.total,
        pagina=filtros.pagina,
        tamano=filtros.tamano,
        generacion=generacion,
        desde_cache=True,
        avisos=tuple(avisos),
    )


async def _guardar_cache(cache: Cache, clave: str, pagina: PaginaResultados, ttl_seg: int) -> None:
    """Guarda la página. Un fallo aquí no afecta a la respuesta que ya se va a devolver."""
    try:
        await cache.guardar(
            clave,
            a_json(
                {
                    "elementos": list(pagina.elementos),
                    "total": pagina.total,
                    "pagina": pagina.pagina,
                    "tamano": pagina.tamano,
                    "generacion": pagina.generacion,
                }
            ),
            ttl_seg,
        )
    except Exception:  # noqa: BLE001 - el caché es una optimización, no un requisito
        registro.warning("No se pudo guardar en el caché", exc_info=False)
