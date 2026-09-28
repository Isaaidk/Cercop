"""Adaptador de salida: consultas sobre el histórico ya ingestado.

El histórico de contrataciones es del **plano compartido**: no lleva `negocio_id` porque se ingesta
una sola vez para todos los negocios. Por eso estas consultas no necesitan contexto de negocio, y
usarlas no debilita el aislamiento: lo que es privado de cada negocio son sus usuarios, sus
suscripciones y sus concesiones, y esas tablas sí están protegidas por RLS.

La búsqueda usa el índice de texto completo. **Los índices GIN de `tsvector` no aceleran
`LIKE '%texto%'`**, así que la coincidencia se expresa con `@@` y prefijos (`palabra:*`): consigue
el mismo efecto que una búsqueda por subcadena y sí aprovecha el índice.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.busqueda import (
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    expresion_busqueda,
)
from contratacion.dominio.enlaces import enlace_publico
from contratacion.dominio.palabras import normalizar_termino
from contratacion.infraestructura.adaptadores.salida.bd.contexto import sin_contexto

registro = logging.getLogger(__name__)

# El orden nunca se interpola desde la petición: se traduce desde el enumerado del dominio a una
# expresión fija. Es la diferencia entre ordenar y permitir ejecutar SQL arbitrario.
ORDENES: dict[OrdenBusqueda, str] = {
    OrdenBusqueda.RECIENTES: "r.fecha_publicacion DESC NULLS LAST, r.id",
    OrdenBusqueda.ANTIGUOS: "r.fecha_publicacion ASC NULLS FIRST, r.id",
    OrdenBusqueda.NUEVOS: "r.primera_vez_visto DESC, r.id",
}

# Campos de los datos canónicos que se ofrecen como desplegable de filtro.
CAMPOS_CATALOGO = ("provincia", "estado", "tipo_proceso", "tipo_necesidad", "entidad")

LIMITE_CATALOGO = 500
MESES_SERIE = 24
LIMITE_PROVINCIAS = 12

INDICE_TEXTO = "to_tsvector('simple', r.texto_busqueda)"

#
# Comparación de provincias tolerante a tildes y mayúsculas.
#
# La fuente publica la provincia en mayúsculas y sin tildes («MANABI», «LOS RIOS»), mientras
# que el panel la pide con la grafía oficial («Manabí», «Los Ríos»), porque es la que se lee
# en un mapa. Una igualdad exacta entre las dos formas no encuentra nada, y el síntoma es el
# peor posible: pulsar Manabí en el mapa devuelve cero contrataciones sin ningún error, como
# si esa provincia no tuviera datos.
#
# El sistema anterior ya lo resolvía normalizando los dos lados —minúsculas y sin acentos—,
# así que esto no es una interpretación nueva: es recuperar una regla que existía y se perdió
# al reescribir.
#
# Se hace con `translate` y no con la extensión `unaccent` porque `translate` no exige
# instalar nada: una extensión que no esté disponible en el servidor de producción
# convertiría este filtro en un error de consulta, que es peor que el problema que resuelve.
#
PROVINCIA_NORMALIZADA = (
    "lower(translate(COALESCE({columna}, ''), 'áéíóúüñÁÉÍÓÚÜÑ', 'aeiouunAEIOUUN'))"
)

# La misma expresión, aplicada a cualquier columna de texto. Se reutiliza en lugar de escribir
# otra igual a propósito: dos expresiones que **deben** coincidir acaban separándose en el primer
# arreglo, y el síntoma sería un filtro que encuentra unas filas con tilde y otras no.
NORMALIZADO = PROVINCIA_NORMALIZADA


# Tabla de tildes a quitar en Python. Se escribe entera y no con `unicodedata` porque los
# caracteres que aparecen en nombres de lugares del Ecuador son pocos y conocidos, y una tabla
# explícita se puede comparar a simple vista con la del SQL de arriba.
_TILDES = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")


def normalizar_ubicacion(valor: str | None) -> str:
    """Minúsculas y sin tildes, igual que la expresión SQL de `PROVINCIA_NORMALIZADA`.

    Las dos formas tienen que coincidir carácter a carácter: si la de aquí quitara algo que la
    de SQL no quita, el filtro dejaría de encontrar resultados y el fallo aparecería solo con
    las provincias cuyo nombre lleva tilde, que son siete de veinticuatro.
    """
    return (valor or "").translate(_TILDES).strip().lower()


def _patron(valor: str) -> str:
    """Texto de entrada convertido en patrón de `LIKE`, con los comodines escapados.

    Sin escaparlos, quien escribiera un `%` en el código de un proceso estaría pidiendo «cualquier
    cosa» sin saberlo, y el filtro devolvería el listado entero en lugar de no encontrar nada. `_`
    es peor todavía: aparece de verdad en los códigos y en SQL significa «un carácter cualquiera»,
    así que una búsqueda por el código exacto podría traer procesos de otro año.
    """
    escapado = valor.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


def _filtro_texto(
    parametros: dict[str, Any], terminos: Sequence[str], modo: ModoBusqueda
) -> str | None:
    """Añade la condición de texto completo si hay algo que buscar."""
    expresion = expresion_busqueda(terminos, modo)
    if expresion is None:
        return None
    parametros["expr"] = expresion
    return f"{INDICE_TEXTO} @@ to_tsquery('simple', :expr)"


def _condiciones(filtros: Filtros) -> tuple[list[str], dict[str, Any]]:
    """Condiciones y parámetros de una consulta, siempre parametrizados."""
    condiciones: list[str] = []
    parametros: dict[str, Any] = {}

    principal = _filtro_texto(parametros, filtros.terminos, filtros.modo)
    if principal:
        condiciones.append(principal)

    # El texto libre se suma con «y»: es un filtro más, no una sustitución de los términos.
    if filtros.texto:
        libre = _filtro_texto(parametros, [filtros.texto], ModoBusqueda.TODAS)
        if libre:
            condiciones.append(libre)

    if filtros.fuente:
        condiciones.append("f.codigo = :fuente")
        parametros["fuente"] = filtros.fuente

    # Permiso de lectura por fuente. Si no hay ninguna concedida se añade una condición imposible
    # en lugar de omitir la condición: omitirla devolvería el histórico completo, que es el fallo
    # del lado peligroso. La aplicación ya lo impide antes de llegar aquí, pero la consulta no
    # depende de que se acuerde de hacerlo.
    if filtros.fuentes_permitidas:
        condiciones.append("f.codigo = ANY(:fuentes_permitidas)")
        parametros["fuentes_permitidas"] = list(filtros.fuentes_permitidas)
    else:
        condiciones.append("FALSE")

    if filtros.provincia:
        # El valor almacenado es «PROVINCIA - CANTÓN», tal y como lo publica la fuente, pero el
        # mapa del panel envía solo la provincia. Se aceptan las dos formas: comparar únicamente
        # contra el valor completo haría que pulsar una provincia no devolviera nada, porque la
        # igualdad compara «PICHINCHA - QUITO» con «PICHINCHA».
        #
        # Se corta por el guion y no por « - » porque la fuente no es constante con los espacios, y
        # se recorta el resultado para que «PICHINCHA» y «PICHINCHA » se traten igual.
        completo = PROVINCIA_NORMALIZADA.format(columna="r.datos ->> 'provincia'")
        solo_provincia = PROVINCIA_NORMALIZADA.format(
            columna="btrim(split_part(r.datos ->> 'provincia', '-', 1))"
        )
        condiciones.append(f"({completo} = :provincia OR {solo_provincia} = :provincia)")
        parametros["provincia"] = normalizar_ubicacion(filtros.provincia)

    if filtros.estado:
        condiciones.append("r.datos ->> 'estado' = :estado")
        parametros["estado"] = filtros.estado

    # --- Filtros del listado de ofertas ---------------------------------------
    #
    # Ninguno usa `texto_busqueda`. Ese campo es el índice de palabras clave y está pensado para
    # encontrar por significado; estos cuatro acotan un listado, y hacerlos pasar por el índice
    # haría que buscar la entidad «TGP» devolviera todo lo que menciona esas siglas en el objeto.
    if filtros.entidad:
        columna = NORMALIZADO.format(columna="r.datos ->> 'entidad'")
        condiciones.append(f"{columna} LIKE :entidad")
        parametros["entidad"] = _patron(normalizar_ubicacion(filtros.entidad))

    if filtros.tipo_proceso:
        condiciones.append("r.datos ->> 'tipo_proceso' = :tipo_proceso")
        parametros["tipo_proceso"] = filtros.tipo_proceso

    if filtros.tipo_necesidad:
        condiciones.append("r.datos ->> 'tipo_necesidad' = :tipo_necesidad")
        parametros["tipo_necesidad"] = filtros.tipo_necesidad

    if filtros.codigo:
        condiciones.append("COALESCE(r.datos ->> 'codigo', '') ILIKE :codigo")
        parametros["codigo"] = _patron(filtros.codigo)

    if filtros.desde:
        condiciones.append("r.fecha_publicacion >= :desde")
        parametros["desde"] = filtros.desde

    if filtros.hasta:
        # El límite superior es el final del día indicado, no su comienzo: quien filtra «hasta el
        # 30» espera incluir lo publicado ese día.
        #
        # `CAST(:hasta AS date)` y **no** `:hasta::date`. El reconocedor de parámetros de SQLAlchemy
        # exige que el nombre no vaya seguido de dos puntos: en `:hasta::date` no veía ningún
        # parámetro: mandaba el texto literal `:hasta` a PostgreSQL y la consulta moría con un error
        # de sintaxis. El filtro «hasta» no funcionaba nunca, y con él la consulta entera.
        condiciones.append("r.fecha_publicacion < (CAST(:hasta AS date) + INTERVAL '1 day')")
        parametros["hasta"] = filtros.hasta

    if filtros.solo_nuevos:
        condiciones.append("r.primera_vez_visto >= now() - make_interval(mins => :ventana_nuevos)")
        parametros["ventana_nuevos"] = filtros.ventana_nuevos_min

    if filtros.solo_con_plazo:
        # Se exige que el texto **empiece** por una fecha antes de convertirlo. El valor guardado es
        # ISO 8601 porque así lo normaliza el mapeo, pero un registro sin fecha límite deja `NULL` y
        # una fuente que cambie de formato dejaría un texto cualquiera: sin esta guarda, el CAST
        # reventaría la consulta entera en vez de descartar esa fila.
        condiciones.append(
            "((r.datos ->> 'fecha_limite_proformas') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' "
            "AND (r.datos ->> 'fecha_limite_proformas')::timestamptz >= now())"
        )

    return condiciones, parametros


def _fila_a_elemento(fila: Mapping[Any, Any]) -> Mapping[str, Any]:
    """Funde los datos canónicos con la información de procedencia del registro."""
    elemento: dict[str, Any] = dict(fila["datos"] or {})
    elemento.update(
        {
            "id": fila["id"],
            "fuente": fila["fuente"],
            "clave_natural": fila["clave_natural"],
            "fecha_publicacion": fila["fecha_publicacion"],
            "primera_vez_visto": fila["primera_vez_visto"],
            "ultima_vez_visto": fila["ultima_vez_visto"],
            "es_vigente": fila["es_vigente"],
        }
    )
    # El enlace se calcula aquí, en el único sitio por el que pasan todas las filas que salen de la
    # base, para que la tabla, el listado del mapa y el archivo de Excel ofrezcan exactamente la
    # misma dirección. Resolverlo en el panel obligaría a repetir la regla en cada pantalla, y la
    # primera que se quedara atrás daría un enlace que no abre.
    elemento["enlace_publico"] = enlace_publico(elemento.get("enlace"), fila.get("fuente_url"))
    return elemento


class RepositorioConsultasBd:
    """Implementación sobre PostgreSQL."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    async def buscar(self, filtros: Filtros) -> tuple[tuple[Mapping[str, Any], ...], int]:
        condiciones, parametros = _condiciones(filtros)
        where = " AND ".join(condiciones) if condiciones else "TRUE"
        orden = ORDENES[filtros.orden]

        consulta_pagina = text(
            f"""
            SELECT r.id, f.codigo AS fuente, f.endpoint_base AS fuente_url, r.clave_natural,
                   r.datos, r.fecha_publicacion, r.primera_vez_visto, r.ultima_vez_visto,
                   r.es_vigente
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {where}
            ORDER BY {orden}
            LIMIT :limite OFFSET :desplazamiento
            """
        )
        consulta_total = text(
            f"""
            SELECT count(*)
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {where}
            """
        )

        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        consulta_pagina,
                        {
                            **parametros,
                            "limite": filtros.tamano,
                            "desplazamiento": filtros.desplazamiento,
                        },
                    )
                )
                .mappings()
                .all()
            )
            total = int((await conexion.execute(consulta_total, parametros)).scalar_one())

        return tuple(_fila_a_elemento(fila) for fila in filas), total

    async def todos(self, filtros: Filtros, limite: int) -> tuple[Mapping[str, Any], ...]:
        """Todas las filas que cumplen los filtros, sin paginar, hasta `limite`.

        Comparte `_condiciones` con `buscar` a propósito: un `WHERE` propio acabaría separándose del
        de la tabla, y entonces el archivo tendría filas que la pantalla no muestra o al revés. Como
        el filtrado es la misma función, la única forma de que discrepen es dejar de serlo, y eso se
        ve leyendo el código.
        """
        condiciones, parametros = _condiciones(filtros)
        where = " AND ".join(condiciones) if condiciones else "TRUE"
        orden = ORDENES[filtros.orden]

        consulta = text(
            f"""
            SELECT r.id, f.codigo AS fuente, f.endpoint_base AS fuente_url, r.clave_natural,
                   r.datos, r.fecha_publicacion, r.primera_vez_visto, r.ultima_vez_visto,
                   r.es_vigente
            FROM registro r
            JOIN fuente f ON f.id = r.fuente_id
            WHERE {where}
            ORDER BY {orden}
            LIMIT :limite
            """
        )

        async with sin_contexto(self._motor) as conexion:
            filas = (
                (await conexion.execute(consulta, {**parametros, "limite": limite}))
                .mappings()
                .all()
            )

        return tuple(_fila_a_elemento(fila) for fila in filas)

    async def catalogos(self) -> Mapping[str, Sequence[str]]:

        resultado: dict[str, list[str]] = {}

        async with sin_contexto(self._motor) as conexion:
            # Todo el catálogo en **una** consulta. Antes eran seis —una por campo más la de
            # fuentes— y, como la base es remota y cada viaje ronda los 95 ms medidos, el
            # desplegable de filtros gastaba más de medio segundo solo en presentarse.
            #
            # Los cinco campos se recorren con `unnest` sobre un parámetro de tipo array, así que
            # no se interpola nada: los nombres de los campos siguen viajando como dato.
            #
            # `jsonb_exists` es la forma de función del operador `?`. Se usa así porque el símbolo
            # `?` choca con la sintaxis de marcadores de posición de algunos controladores y acaba
            # interpretándose como un parámetro.
            #
            # El `row_number` reproduce el tope por campo que antes aplicaba cada `LIMIT`: sin él,
            # un campo con miles de valores distintos llenaría el desplegable entero.
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT campo, valor FROM (
                                SELECT campo, valor,
                                       row_number() OVER (PARTITION BY campo ORDER BY valor) AS n
                                FROM (
                                    SELECT 'fuente' AS campo, f.codigo AS valor FROM fuente f
                                    UNION ALL
                                    SELECT c.campo, r.datos ->> c.campo
                                    FROM unnest(CAST(:campos AS text[])) AS c(campo)
                                    JOIN registro r ON jsonb_exists(r.datos, c.campo)
                                    WHERE COALESCE(r.datos ->> c.campo, '') <> ''
                                ) AS crudos
                                GROUP BY campo, valor
                            ) AS numerados
                            WHERE n <= :limite
                            ORDER BY campo, valor
                            """
                        ),
                        {"campos": list(CAMPOS_CATALOGO), "limite": LIMITE_CATALOGO},
                    )
                )
                .mappings()
                .all()
            )

        for fila in filas:
            resultado.setdefault(str(fila["campo"]), []).append(str(fila["valor"]))

        # Un campo sin ningún valor también aparece, para que el panel sepa que existe y no lo
        # confunda con «el filtro no está disponible».
        for campo in CAMPOS_CATALOGO:
            resultado.setdefault(campo, [])

        return resultado

    async def estadisticas(self, filtros: Filtros) -> Mapping[str, Any]:
        """Agregados sobre el resultado filtrado, con las mismas condiciones que la búsqueda.

        Se reutiliza `_condiciones` en lugar de escribir un `WHERE` propio. Es la decisión que
        importa: dos formas de filtrar lo mismo acaban separándose, y entonces las gráficas resumen
        un conjunto distinto del que muestra la tabla. Reutilizándolo, la única manera de que
        discrepen es que dejen de ser la misma consulta, y eso se ve al leer el código.

        La paginación no se aplica: los agregados resumen todo lo que cumple los criterios, no la
        página que se esté viendo.
        """
        condiciones, parametros = _condiciones(filtros)
        donde = " AND ".join(condiciones) if condiciones else "TRUE"

        async with sin_contexto(self._motor) as conexion:
            por_fuente = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT f.codigo AS fuente,
                                   count(*) AS total,
                                   max(r.fecha_publicacion) AS ultima_publicacion
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE {donde}
                            GROUP BY f.codigo
                            ORDER BY f.codigo
                            """
                        ),
                        parametros,
                    )
                )
                .mappings()
                .all()
            )

            serie = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT date_trunc('month', r.fecha_publicacion) AS mes,
                                   count(*) AS total
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE r.fecha_publicacion IS NOT NULL AND {donde}
                            GROUP BY 1
                            ORDER BY 1 DESC
                            LIMIT :meses
                            """
                        ),
                        {**parametros, "meses": MESES_SERIE},
                    )
                )
                .mappings()
                .all()
            )

            provincias = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT COALESCE(r.datos ->> 'provincia', 'sin provincia') AS provincia,
                                   count(*) AS total
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE {donde}
                            GROUP BY 1
                            ORDER BY 2 DESC
                            LIMIT :limite
                            """
                        ),
                        {**parametros, "limite": LIMITE_PROVINCIAS},
                    )
                )
                .mappings()
                .all()
            )

        return {
            "fuente": filtros.fuente,
            "por_fuente": [dict(fila) for fila in por_fuente],
            "serie_mensual": [dict(fila) for fila in reversed(serie)],
            "por_provincia": [dict(fila) for fila in provincias],
        }

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        return await self._estado_fuentes(codigo=None)

    async def estado_fuente(self, codigo: str) -> Mapping[str, Any] | None:
        filas = await self._estado_fuentes(codigo=codigo)
        return filas[0] if filas else None

    async def _estado_fuentes(self, codigo: str | None) -> tuple[Mapping[str, Any], ...]:
        """Último ciclo de cada fuente, o de una concreta."""
        filtro = "WHERE f.codigo = :codigo" if codigo else ""
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT f.codigo, f.nombre, f.activa, f.intervalo_min,
                                   f.esquema_version, f.hash_claves,
                                   s.id AS sincronizacion_id, s.estado, s.iniciada_en,
                                   s.terminada_en, s.nuevos, s.actualizados, s.errores,
                                   s.peticiones, s.avisos, s.watermark_fecha
                            FROM fuente f
                            LEFT JOIN LATERAL (
                                SELECT * FROM sincronizacion s
                                WHERE s.fuente_id = f.id
                                ORDER BY s.iniciada_en DESC
                                LIMIT 1
                            ) s ON TRUE
                            {filtro}
                            ORDER BY f.codigo
                            """
                        ),
                        {"codigo": codigo} if codigo else {},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

    async def ultima_ingesta_de(self, terminos: Sequence[str]) -> datetime | None:
        normalizados = [normalizar_termino(termino) for termino in terminos if termino.strip()]
        if not normalizados:
            return None

        async with sin_contexto(self._motor) as conexion:
            valor: Any = (
                await conexion.execute(
                    text(
                        """
                        SELECT max(t.ultima_ingesta_en)
                        FROM termino t
                        WHERE t.texto_normalizado = ANY(:normalizados)
                        """
                    ),
                    {"normalizados": normalizados},
                )
            ).scalar_one()

        return valor if isinstance(valor, datetime) else None
