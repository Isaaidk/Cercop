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
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.dominio.busqueda import (
    FUENTES_POR_CATEGORIA,
    Filtros,
    ModoBusqueda,
    OrdenBusqueda,
    expresion_busqueda,
)
from contratacion.dominio.cpc import items_desde_crudos
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
# Tope de filas del reparto por provincia. **Doce era un error**: el Ecuador tiene veinticuatro
# provincias, así que el mapa y su gráfica solo recibían las doce con más contrataciones y las demás
# se pintaban con cero. Pulsar una de esas provincias filtraba la tabla —que no lleva tope— y
# aparecían filas: «dice 0 y me salen 74». El dominio está acotado (24 provincias más algún valor
# suelto como «NO DELIMITADO»), así que el tope solo está para que una fuente que publique basura en
# ese campo no devuelva miles de filas.
LIMITE_PROVINCIAS = 60

# Tope del reparto por tipo de proceso. Medido antes de ponerlo, que es como se evita repetir el
# defecto de las doce provincias: 18 valores distintos en 107.510 filas, más 10.110 sin el campo
# —las ínfimas no publican el tipo de proceso—. Con cuarenta hay margen de sobra para que el «las
# otras suman X» de la gráfica sea exacto, y el tope sigue estando por si la fuente algún día
# publica basura en ese campo.
LIMITE_DISTRIBUCION = 40

INDICE_TEXTO = "to_tsvector('simple', r.texto_busqueda)"

# El CPC se busca contra su propia columna y no se sumó a `texto_busqueda` a propósito: si
# compartieran columna, el filtro de palabras clave volvería a encontrar el objeto de compra y el
# problema que el CPC viene a resolver —traer todo lo que menciona la palabra— seguiría ahí.
INDICE_CPC = "to_tsvector('simple', r.cpc_busqueda)"

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
    parametros: dict[str, Any],
    terminos: Sequence[str],
    modo: ModoBusqueda,
    *,
    indice: str = INDICE_TEXTO,
    nombre_parametro: str = "expr",
) -> str | None:
    """Añade la condición de texto completo si hay algo que buscar.

    El índice y el nombre del parámetro se pueden cambiar porque hay **dos** búsquedas de texto
    completo: la del contenido del registro y la del CPC. Las dos usan exactamente la misma
    expresión y los mismos modos —salen de `expresion_busqueda`—, así que duplicar la función sería
    duplicar la definición de qué significa «todas» o «cualquiera», y las dos versiones acabarían
    separándose. Los nombres tienen que ser distintos porque los dos parámetros viajan en el mismo
    diccionario.
    """
    expresion = expresion_busqueda(terminos, modo)
    if expresion is None:
        return None
    parametros[nombre_parametro] = expresion
    return f"{indice} @@ to_tsquery('simple', :{nombre_parametro})"


def _condiciones(filtros: Filtros) -> tuple[list[str], dict[str, Any]]:
    """Condiciones y parámetros de una consulta, siempre parametrizados."""
    condiciones: list[str] = []
    parametros: dict[str, Any] = {}

    principal = _filtro_texto(parametros, filtros.terminos, filtros.modo)
    if principal:
        condiciones.append(principal)

    # El CPC es un criterio **aparte** y se suma con «y»: quien lo pida junto con términos quiere la
    # intersección de los dos. Comparte el modo —«todas» o «cualquiera»— porque la pregunta es la
    # misma: cómo se combinan entre sí varias palabras de la misma lista.
    if filtros.cpc:
        por_cpc = _filtro_texto(
            parametros,
            filtros.cpc,
            filtros.modo,
            indice=INDICE_CPC,
            nombre_parametro="expr_cpc",
        )
        if por_cpc:
            condiciones.append(por_cpc)

    # El texto libre se suma con «y»: es un filtro más, no una sustitución de los términos.
    if filtros.texto:
        libre = _filtro_texto(parametros, [filtros.texto], ModoBusqueda.TODAS)
        if libre:
            condiciones.append(libre)

    if filtros.fuente:
        condiciones.append("f.codigo = :fuente")
        parametros["fuente"] = filtros.fuente

    # La categoría se resuelve contra las fuentes que la alimentan. Se combina con «y» con la fuente
    # y con los permisos, y eso es lo correcto: si alguien pide ínfimas, solo tiene concedida una
    # fuente que no las trae y además pidió otra fuente concreta, el resultado tiene que quedar
    # vacío. Cualquier otra cosa —ampliar por su cuenta, ignorar el permiso— sería servir datos que
    # esa persona no puede ver.
    if filtros.categoria is not None:
        condiciones.append("f.codigo = ANY(:categoria_fuentes)")
        parametros["categoria_fuentes"] = list(FUENTES_POR_CATEGORIA[filtros.categoria])

    # Permiso de lectura por fuente. Si no hay ninguna concedida se añade una condición imposible
    # en lugar de omitir la condición: omitirla devolvería el histórico completo, que es el fallo
    # del lado peligroso. La aplicación ya lo impide antes de llegar aquí, pero la consulta no
    # depende de que se acuerde de hacerlo.
    if filtros.fuentes_permitidas:
        condiciones.append("f.codigo = ANY(:fuentes_permitidas)")
        parametros["fuentes_permitidas"] = list(filtros.fuentes_permitidas)
    else:
        condiciones.append("FALSE")

    if filtros.provincias:
        # El valor almacenado es «PROVINCIA - CANTÓN», tal y como lo publica la fuente, pero el
        # mapa del panel envía solo la provincia. Se aceptan las dos formas: comparar únicamente
        # contra el valor completo haría que pulsar una provincia no devolviera nada, porque la
        # igualdad compara «PICHINCHA - QUITO» con «PICHINCHA».
        #
        # Se corta por el guion y no por « - » porque la fuente no es constante con los espacios, y
        # se recorta el resultado para que «PICHINCHA» y «PICHINCHA » se traten igual.
        #
        # `ANY` con una lista y no una igualdad repetida: son las mismas dos comparaciones de
        # siempre, una sola vez, para cualquier número de provincias. Se mantienen las dos y no se
        # suma una tercera: la condición es la misma, lo que cambia es que el valor de la derecha es
        # un conjunto.
        completo = PROVINCIA_NORMALIZADA.format(columna="r.datos ->> 'provincia'")
        solo_provincia = PROVINCIA_NORMALIZADA.format(
            columna="btrim(split_part(r.datos ->> 'provincia', '-', 1))"
        )
        condiciones.append(
            f"({completo} = ANY(:provincias) OR {solo_provincia} = ANY(:provincias))"
        )
        parametros["provincias"] = [
            normalizar_ubicacion(provincia) for provincia in filtros.provincias
        ]

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
    # Los ítems del detalle van **fuera** de `datos` y por eso hay que añadirlos expresamente: no
    # son un campo de la fuente, son el resultado de ir a buscar la ficha. Se reconstruyen con la
    # misma función que los lee en cualquier otro sitio para que la forma del jsonb guardado no
    # tenga que conocerla nadie más.
    elemento["items"] = [
        item.como_diccionario() for item in items_desde_crudos(fila.get("items") or ())
    ]
    elemento["cpc_codigos"] = list(fila.get("cpc_codigos") or ())
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
                   r.datos, r.items, r.cpc_codigos, r.fecha_publicacion, r.primera_vez_visto,
                   r.ultima_vez_visto, r.es_vigente
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
                   r.datos, r.items, r.cpc_codigos, r.fecha_publicacion, r.primera_vez_visto,
                   r.ultima_vez_visto, r.es_vigente
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

        # Las condiciones **sin la familia**, para los totales por pestaña.
        #
        # El panel muestra un número junto a cada pestaña de familia —«Ínfimas cuantías» y
        # «Ofertas»— y los dos tienen que salir de los mismos filtros. La consulta de la tabla lleva
        # la familia puesta porque se está mirando una sola; aquí hay que quitarla, y eso no es un
        # descuido: es la única forma de contar las dos con los mismos criterios. Lo demás se
        # respeta —términos, provincias, fechas, permisos—, así que el número que sale responde a
        # «cuántas hay de esta familia con lo que tengo filtrado».
        #
        # Se devuelve el conteo **por fuente**, sin traducir a familias: esa traducción es una regla
        # del dominio y vive en el caso de uso, donde se puede probar sin base de datos.
        #
        # Las dos consultas llevan sus propios parámetros aunque compartan valores: `_condiciones`
        # escribe en el diccionario que recibe, y mezclarlos dejaría el `:categoria_fuentes` de una
        # en la consulta de la otra.
        condiciones_sin_familia, parametros_sin_familia = _condiciones(
            replace(filtros, categoria=None)
        )
        donde_sin_familia = (
            " AND ".join(condiciones_sin_familia) if condiciones_sin_familia else "TRUE"
        )

        # El reparto por provincia se cuenta **sin el filtro de provincia**, y es la otra mitad del
        # mismo defecto. Se contaba con él, así que al elegir una provincia todas las demás bajaban
        # a cero: el mapa dejaba de decir dónde hay contrataciones justo cuando se usaba como
        # selector, y no había forma de añadir una segunda sin quitar la primera. Lo demás se
        # respeta —términos, fechas, permisos, familia—, así que cada barra responde a «cuántas hay
        # aquí con lo que tengo filtrado».
        #
        # El total del conjunto **sí** lleva el filtro de provincia: lo calcula el caso de uso
        # sumando el conteo por fuente, que es el número que acompaña a la tabla.
        condiciones_sin_provincia, parametros_sin_provincia = _condiciones(
            replace(filtros, provincias=())
        )
        donde_sin_provincia = (
            " AND ".join(condiciones_sin_provincia) if condiciones_sin_provincia else "TRUE"
        )

        # El reparto por tipo de proceso, por la misma razón que el de provincia: se cuenta **sin su
        # propio criterio**, así que elegir un tipo no pone los demás a cero. Se agrupa por el
        # **texto crudo** y no por una versión normalizada porque es contra ese texto contra el que
        # compara el filtro (`r.datos ->> 'tipo_proceso' = :tipo_proceso`): la clave que devuelve
        # esta consulta se le puede devolver tal cual, y pulsar una barra filtraría exactamente esa
        # fila. Normalizarla obligaría a que el filtro normalizara también, y dos normalizaciones
        # distintas —una en cada mitad— dejarían barras que no encuentran nada al pulsarlas.
        #
        # Medido el 2026-10-01 antes de ponerle tope: 18 valores distintos en 107.510 filas, y
        # 10.110 sin el campo —son las ínfimas, que no lo publican—. Con el tope en 40 el «las
        # otras suman X» es exacto hoy y seguirá siéndolo mientras el catálogo de la fuente no
        # triplique su vocabulario.
        condiciones_sin_tipo, parametros_sin_tipo = _condiciones(
            replace(filtros, tipo_proceso=None)
        )
        donde_sin_tipo = " AND ".join(condiciones_sin_tipo) if condiciones_sin_tipo else "TRUE"

        # La clave del reparto es la **misma expresión normalizada** que el filtro, no el texto
        # crudo de la fuente. Agrupando por el crudo, una provincia se partía en dos:
        # «SANTO DOMINGO DE LOS TSÁCHILAS» y «…TSACHILAS» eran dos filas con su mitad del total cada
        # una, y con el tope de doce filas una de las mitades se quedaba fuera y la provincia entera
        # salía con cero. Normalizada, las dos grafías son una clave que el panel sabe traducir.
        provincia_normalizada = PROVINCIA_NORMALIZADA.format(
            columna="btrim(split_part(r.datos ->> 'provincia', '-', 1))"
        )

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
                            SELECT COALESCE(NULLIF({provincia_normalizada}, ''), 'sin provincia')
                                       AS provincia,
                                   count(*) AS total
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE {donde_sin_provincia}
                            GROUP BY 1
                            ORDER BY 2 DESC
                            LIMIT :limite
                            """
                        ),
                        {**parametros_sin_provincia, "limite": LIMITE_PROVINCIAS},
                    )
                )
                .mappings()
                .all()
            )

            por_fuente_sin_familia = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT f.codigo AS fuente, count(*) AS total
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE {donde_sin_familia}
                            GROUP BY f.codigo
                            """
                        ),
                        parametros_sin_familia,
                    )
                )
                .mappings()
                .all()
            )

            tipos = (
                (
                    await conexion.execute(
                        text(
                            f"""
                            SELECT COALESCE(NULLIF(btrim(r.datos ->> 'tipo_proceso'), ''),
                                            'sin clasificar') AS tipo_proceso,
                                   count(*) AS total
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE {donde_sin_tipo}
                            GROUP BY 1
                            ORDER BY 2 DESC, 1
                            LIMIT :limite
                            """
                        ),
                        {**parametros_sin_tipo, "limite": LIMITE_DISTRIBUCION},
                    )
                )
                .mappings()
                .all()
            )

        # El conteo bruto por fuente, con los mismos filtros y sin la familia. El caso de uso lo
        # convierte en totales por familia; aquí no se traduce nada.
        return {
            "fuente": filtros.fuente,
            "por_fuente": [dict(fila) for fila in por_fuente],
            "por_fuente_sin_familia": [dict(fila) for fila in por_fuente_sin_familia],
            "serie_mensual": [dict(fila) for fila in reversed(serie)],
            "por_provincia": [dict(fila) for fila in provincias],
            "por_tipo_proceso": [dict(fila) for fila in tipos],
        }

    async def estado_fuentes(self) -> Sequence[Mapping[str, Any]]:
        return await self._estado_fuentes(codigo=None)

    async def historial_sincronizaciones(self, por_fuente: int = 24) -> Sequence[Mapping[str, Any]]:
        """Los últimos ciclos de cada fuente, del más reciente al más antiguo.

        Va contra `sincronizacion`, que es el registro que ya escriben los ciclos: no hay que
        instrumentar nada nuevo para dibujar el trabajo del worker. El `LATERAL` con su propio tope
        por fuente es lo que permite pedir «veinticuatro de cada una» en una sola consulta; con un
        `LIMIT` global, la fuente que más ciclos escribe se quedaría con toda la ventana.
        """
        async with sin_contexto(self._motor) as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT f.codigo AS fuente, f.nombre, f.intervalo_min,
                                   s.iniciada_en, s.terminada_en, s.estado,
                                   s.nuevos, s.actualizados, s.errores, s.peticiones,
                                   s.avisos
                            FROM fuente f
                            JOIN LATERAL (
                                SELECT * FROM sincronizacion s
                                WHERE s.fuente_id = f.id
                                ORDER BY s.iniciada_en DESC
                                LIMIT :por_fuente
                            ) s ON TRUE
                            ORDER BY f.codigo, s.iniciada_en DESC
                            """
                        ),
                        {"por_fuente": por_fuente},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(dict(fila) for fila in filas)

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
