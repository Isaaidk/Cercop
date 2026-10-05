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
from collections.abc import Mapping, Sequence

from contratacion.aplicacion.generaciones import leer_generacion
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.consultas import RepositorioConsultas
from contratacion.dominio.busqueda import (
    FUENTES_POR_CATEGORIA,
    TTL_CATALOGO_SEG,
    TTL_ESTADISTICAS_SEG,
    TTL_RESULTADOS_SEG,
    Categoria,
    Filtros,
    PaginaResultados,
    categoria_de_fuente,
    clave_catalogo,
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

# Nombre con el que se guarda el catálogo de los desplegables. Forma parte de la clave de caché, así
# que cambiarlo equivale a invalidar lo guardado; se escribe una vez para no tener dos cadenas que
# deban coincidir.
CATALOGO_DE_FILTROS = "filtros"


async def buscar(
    filtros: Filtros,
    *,
    cache: Cache,
    repositorio: RepositorioConsultas,
    ttl_seg: int = TTL_RESULTADOS_SEG,
    ttl_memo_seg: int = 0,
) -> PaginaResultados:
    """Devuelve una página de resultados, sirviéndola desde el caché cuando es posible.

    `ttl_memo_seg` es el tiempo que este proceso recuerda la generación del caché. Llega desde los
    ajustes y vale cero en las pruebas: un memo entre casos haría que una prueba viera la generación
    que dejó la anterior.
    """
    validados = filtros.validado()

    # Sin fuentes permitidas no se consulta nada. Se comprueba aquí, en el caso de uso, para que
    # la garantía no dependa de que cada enrutador se acuerde: cualquier llamador queda cubierto.
    if not validados.fuentes_permitidas:
        raise SinPermiso(MENSAJE_SIN_FUENTES)

    avisos: list[str] = []

    generacion = await leer_generacion(cache, ttl_memo_seg=ttl_memo_seg)
    clave = clave_resultados(validados, generacion)

    # El caché solo se mira —y solo se escribe— cuando la consulta puede repetirse. Una búsqueda con
    # texto libre casi nunca se repite, así que guardarla no acierta nada y ocupa sitio hasta que
    # caduque: ver `Filtros.cacheable`.
    if validados.cacheable:
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

    if validados.cacheable:
        await _guardar_cache(cache, clave, pagina, ttl_seg)
    return pagina


async def obtener_estadisticas(
    filtros: Filtros,
    *,
    cache: Cache,
    repositorio: RepositorioConsultas,
    ttl_seg: int = TTL_ESTADISTICAS_SEG,
    ttl_memo_seg: int = 0,
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

    generacion = await leer_generacion(cache, ttl_memo_seg=ttl_memo_seg)
    clave = clave_estadisticas(validados, generacion)

    # La misma regla que en la búsqueda: con texto libre no se busca la entrada ni se escribe. Ver
    # `Filtros.cacheable`.
    if validados.cacheable:
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
    # El conteo por fuente sin la familia deja de ser un dato de la respuesta y pasa a ser el total
    # de cada pestaña. Se quita del diccionario porque su sitio no es el contrato: el panel consume
    # `por_categoria`, que ya dice «ínfimas» y «ofertas» y no obliga a nadie a saber qué fuente
    # alimenta a cuál.
    datos["por_categoria"] = _totales_por_categoria(datos.pop("por_fuente_sin_familia", []))
    if validados.cacheable:
        try:
            await cache.guardar(clave, a_json(datos), ttl_seg)
        except Exception:  # noqa: BLE001 - no guardar no impide responder
            registro.warning("No se pudieron guardar las estadísticas en caché", exc_info=False)
    return datos


def _totales_por_categoria(por_fuente: object) -> list[dict[str, object]]:
    """Total de cada familia a partir del conteo por fuente, **sin la familia filtrada**.

    Existe porque el número que va junto a cada pestaña del panel tiene que ser el de **su** familia
    y salir de los mismos filtros que la tabla. Si se usara el total de la consulta en curso, al
    abrir la pestaña de ofertas el número de las ínfimas pasaría a mostrar el de las ofertas, que es
    exactamente lo que hacía antes.

    Se responde con **las dos familias siempre**, y con cero cuando no hay nada: así el panel
    distingue «esta familia no tiene nada con tus filtros» de «no se pudo calcular», y las pestañas
    no aparecen con un número distinto en cada carga por el mero hecho de que una falte.

    El orden es el del dominio —ínfimas y después ofertas—, el mismo de las pestañas y de las hojas
    del Excel, para que dos consultas seguidas se lean igual.

    Las filas de una fuente que no pertenece a ninguna familia no se cuentan aquí: no son de ninguna
    pestaña. Tampoco se inventan: siguen apareciendo en `por_fuente`.
    """
    totales: dict[Categoria, int] = {categoria: 0 for categoria in FUENTES_POR_CATEGORIA}
    if isinstance(por_fuente, list):
        for fila in por_fuente:
            if not isinstance(fila, Mapping):
                continue
            suya = categoria_de_fuente(str(fila.get("fuente") or ""))
            if suya is not None:
                totales[suya] += int(fila.get("total") or 0)
    return [
        {"categoria": categoria.value, "total": totales[categoria]}
        for categoria in FUENTES_POR_CATEGORIA
    ]


async def obtener_catalogos(
    *,
    cache: Cache,
    repositorio: RepositorioConsultas,
    ttl_seg: int = TTL_CATALOGO_SEG,
    ttl_memo_seg: int = 0,
) -> Mapping[str, Sequence[str]]:
    """Valores de los desplegables del panel, servidos del caché.

    Es la consulta más cara del sistema: recorre el histórico entero sacando los valores distintos
    de cada campo. Y se dispara **al abrir cada panel**, así que sin caché cada persona que entra
    paga el recorrido completo —aunque su contenido cambie como mucho una vez por ciclo de ingesta.

    La clave **no** depende de los criterios, y no es un olvido: un desplegable ofrece lo que hay en
    el histórico, no lo que cumple un filtro, y `catalogos()` no recibe ninguno. Por eso una sola
    entrada sirve a todos los usuarios y a todas las pantallas, que es exactamente lo contrario de
    lo que pasa con los resultados.

    El permiso lo comprueba quien llama, **antes** de llegar aquí: al revés, quien no tuviera
    ninguna vista recibiría la respuesta que cacheó otro.
    """
    generacion = await leer_generacion(cache, ttl_memo_seg=ttl_memo_seg)
    clave = clave_catalogo(CATALOGO_DE_FILTROS, generacion)

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
            registro.warning("Catálogos ilegibles en caché; se recalculan", exc_info=False)

    datos = dict(await repositorio.catalogos())
    try:
        await cache.guardar(clave, a_json(datos), ttl_seg)
    except Exception:  # noqa: BLE001 - no guardar no impide responder
        registro.warning("No se pudieron guardar los catálogos en caché", exc_info=False)
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
