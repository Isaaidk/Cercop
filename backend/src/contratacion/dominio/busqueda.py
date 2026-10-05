"""Reglas de la búsqueda multi-palabra y de las claves de caché.

Vive en el dominio porque son decisiones de negocio, no de infraestructura: qué significa «todas»,
cuándo dos búsquedas son la misma consulta y qué se considera una página válida. Al no depender de
nada externo se puede probar sin base de datos ni caché.

El objetivo de la fase 3 es que **añadir filtros no cueste más**: la combinación de criterios se
reduce a una huella estable que identifica el resultado dentro de la caché. Dos peticiones con los
mismos criterios —aunque lleguen con los términos en otro orden, o con «Gestión» y «gestion»—
comparten la misma entrada y, por tanto, la misma respuesta.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

from contratacion.dominio.errores import DatoInvalido
from contratacion.dominio.palabras import (
    LONGITUD_MINIMA_TERMINO,
    SEPARADOR_TERMINOS,
    normalizar,
)

# --- Paginación ---------------------------------------------------------------
TAMANO_PREDETERMINADO = 25
TAMANO_MAXIMO = 100
# Tope de profundidad: sin él, un desplazamiento enorme obliga a la base a recorrer y descartar
# filas, que es una forma barata de tumbar el servicio desde fuera.
PAGINA_MAXIMA = 500

# --- Nombres de las claves de caché -------------------------------------------
# El contrato de nombres es compartido: la ingesta sube la generación y el lector compone la clave.
PREFIJO_GENERACION = "generacion"
PREFIJO_RESULTADOS = "res"
PREFIJO_CATALOGO = "cat"
PREFIJO_ESTADISTICAS = "est"
PREFIJO_TABLERO = "tab"  # tablero de estado de las fuentes

# Generación compartida por todos los resultados de búsqueda. Cualquier ciclo que cambie datos
# invalida el buscador entero, porque una consulta puede abarcar varias fuentes a la vez. Las claves
# propias de cada fuente usan su propio contador, para invalidar solo lo suyo.
GENERACION_GLOBAL = "global"

# --- Tiempos de vida, en segundos --------------------------------------------
# Los resultados caducan en un ciclo de ingesta: así nunca se sirve una página más vieja que el
# propio ciclo que la invalidó. El catálogo cambia poco y aguanta más.
TTL_RESULTADOS_SEG = 900
TTL_CATALOGO_SEG = 3600
TTL_ESTADISTICAS_SEG = 900


class ModoBusqueda(StrEnum):
    """Cómo se combinan varios términos."""

    TODAS = "todas"
    CUALQUIERA = "cualquiera"


class OrdenBusqueda(StrEnum):
    """Criterio de ordenación del resultado."""

    RECIENTES = "recientes"
    ANTIGUOS = "antiguos"
    NUEVOS = "nuevos"


class Categoria(StrEnum):
    """Las dos familias de contratación que el panel trata por separado.

    No son «fuentes» aunque hoy coincidan con ellas, y la distinción importa. Una fuente es por
    dónde entra el dato; una categoría es **qué es** el proceso para quien lo lee, y es lo que
    decide en qué hoja del Excel acaba. Si hoy se confundieran, el día que una fuente publicara las
    dos cosas habría que cambiar la API, el panel y las claves de caché a la vez.
    """

    INFIMAS = "infimas"
    OFERTAS = "ofertas"


# Qué fuentes alimentan cada categoría.
#
# «Ínfimas cuantías» se identifica hoy por la fuente, y está comprobado contra los datos reales: las
# 2.210 filas de NCO traen `tipo_necesidad = "Ínfimas Cuantías"` y las demás lo traen vacío. Se
# filtra por `fuente` y no por ese campo porque la fuente está indexada y el campo vive dentro de un
# `jsonb`; el día que NCO publique necesidades que no sean ínfimas, el criterio pasa a
# `tipo_necesidad` y **solo se cambia aquí**.
FUENTES_POR_CATEGORIA: dict[Categoria, tuple[str, ...]] = {
    Categoria.INFIMAS: ("NCO",),
    Categoria.OFERTAS: ("OCDS",),
}

# Nombre de la hoja de cada categoría. Es lo que verá quien abra el archivo, así que va en el idioma
# del negocio y no en el del código.
ETIQUETA_POR_CATEGORIA: dict[Categoria, str] = {
    Categoria.INFIMAS: "Ínfimas cuantías",
    Categoria.OFERTAS: "Ofertas",
}

# Las filas cuya fuente no pertenece a ninguna categoría no se tiran ni se disfrazan: van a su
# propia hoja. Puede pasar con una fuente nueva antes de clasificarla, y esconderla sería peor que
# un nombre raro: quien exporta da por hecho que el archivo lleva todo lo que cumple los filtros.
ETIQUETA_OTRAS = "Otras fuentes"


def categoria_de_fuente(fuente: str | None) -> Categoria | None:
    """A qué categoría pertenece una fila según de dónde vino. `None` si no es de ninguna."""
    codigo = (fuente or "").strip().upper()
    for categoria, fuentes in FUENTES_POR_CATEGORIA.items():
        if codigo in fuentes:
            return categoria
    return None


# Todo lo que no sea letra o dígito se descarta antes de tocar el motor de búsqueda. No es
# cosmética: en `tsquery` los símbolos `&`, `|`, `!`, `(`, `)`, `:` y `*` tienen significado propio,
# así que un término como «a|b» dejaría de ser una búsqueda y pasaría a ser otra consulta distinta.
PALABRA_VALIDA = re.compile(r"[^a-z0-9]+")


def palabras_de(termino: str) -> tuple[str, ...]:
    """Divide un término en las palabras que se pueden buscar con seguridad.

    Esta función es la pieza que impide que la comprobación en memoria y la consulta SQL se separen:
    las dos llaman aquí, de modo que no pueden interpretar un término de forma distinta.
    """
    return tuple(palabra for palabra in PALABRA_VALIDA.split(termino.lower()) if palabra)


def normalizar_terminos(entrada: Iterable[str] | str | None) -> tuple[str, ...]:
    """Términos normalizados, sin repetir y en orden estable.

    Se ordenan a propósito: «obras viales» y «viales obras» deben producir la misma clave de caché,
    y el orden alfabético es la forma más simple de conseguirlo sin perder información.

    Las palabras **dentro** de un término también se ordenan, porque el término se evalúa como una
    conjunción y por tanto el orden no cambia su significado: «obras viales» y «viales obras» buscan
    exactamente lo mismo. Sin ordenarlas, serían dos consultas distintas y ocuparían dos entradas de
    caché para devolver el mismo resultado.

    Un término con espacios **sigue siendo un término**: sus palabras se exigen todas. Partirlo en
    varios cambiaría el significado de la consulta, porque en modo «cualquiera» bastaría con que
    apareciera una de ellas. Lo que sí se separa es una lista pegada por el usuario, que llega con
    comas, puntos y coma o saltos de línea.

    Un término que no deje ninguna palabra buscable —«###», por ejemplo— se descarta en lugar de
    provocar una consulta que no filtraría nada.
    """
    if entrada is None:
        return ()
    partes: list[str] = [entrada] if isinstance(entrada, str) else [str(p) for p in entrada]

    unicos: set[str] = set()
    for parte in partes:
        for crudo in SEPARADOR_TERMINOS.split(parte):
            texto = normalizar(crudo)
            if len(texto) < LONGITUD_MINIMA_TERMINO:
                continue
            palabras = palabras_de(texto)
            if palabras:
                unicos.add(" ".join(sorted(palabras)))
    return tuple(sorted(unicos))


def normalizar_provincias(entrada: Iterable[str] | str | None) -> tuple[str, ...]:
    """Provincias normalizadas, sin repetir y en orden estable.

    Se ordenan por el mismo motivo que los términos: el mapa permite elegir varias y el orden en
    que se pulsan no cambia el resultado. Sin ordenar, «Azuay y Pichincha» y «Pichincha y Azuay»
    serían dos consultas distintas y ocuparían dos entradas de caché para lo mismo.

    Se recortan y se descartan las vacías: una provincia en blanco no filtra nada, y dejarla pasar
    añadiría una condición que no se corresponde con lo que pidió nadie.
    """
    if entrada is None:
        return ()
    partes: list[str] = [entrada] if isinstance(entrada, str) else [str(p) for p in entrada]
    return tuple(sorted({parte.strip() for parte in partes if parte and parte.strip()}))


def _coincide_termino(palabras_texto: Sequence[str], termino: str) -> bool:
    """¿Alguna palabra del texto empieza por cada palabra del término?

    Se compara por **prefijo de palabra**, no por subcadena, para que «vial» encuentre «viales» sin
    que «oral» encuentre «moral». Es la misma semántica que aplica la base de datos con `palabra:*`,
    y por eso ambas coinciden.
    """
    necesarias = palabras_de(termino)
    if not necesarias:
        return False
    return all(
        any(palabra.startswith(necesaria) for palabra in palabras_texto) for necesaria in necesarias
    )


def coincide(texto_normalizado: str, terminos: Sequence[str], modo: ModoBusqueda) -> bool:
    """¿El texto de búsqueda satisface los términos?

    Es la definición de referencia de los modos: la comprobación en memoria y la consulta de la base
    de datos parten de las mismas palabras saneadas, así que no pueden discrepar.
    """
    if not terminos:
        return True
    palabras_texto = palabras_de(texto_normalizado)
    if not palabras_texto:
        return False
    if modo is ModoBusqueda.TODAS:
        return all(_coincide_termino(palabras_texto, termino) for termino in terminos)
    return any(_coincide_termino(palabras_texto, termino) for termino in terminos)


def expresion_busqueda(terminos: Sequence[str], modo: ModoBusqueda) -> str | None:
    """Expresión de `tsquery` que aplica los mismos criterios en la base de datos.

    Cada término se convierte en una conjunción de prefijos (`obras:* & viales:*`) y los términos se
    combinan según el modo. Devuelve `None` cuando no hay nada que filtrar, para que el llamador no
    tenga que construir una condición inútil.

    Las palabras ya vienen saneadas por `palabras_de`, así que no pueden inyectar operadores.
    """
    grupos: list[str] = []
    for termino in terminos:
        palabras = palabras_de(termino)
        if palabras:
            prefijos = " & ".join(f"{palabra}:*" for palabra in palabras)
            grupos.append(f"({prefijos})")
    if not grupos:
        return None
    union = " & " if modo is ModoBusqueda.TODAS else " | "
    return union.join(grupos)


@dataclass(frozen=True, slots=True)
class Filtros:
    """Criterios de una consulta, en forma canónica.

    Es inmutable para que la huella y la consulta no puedan divergir: quien construye los filtros
    los valida una sola vez y el resto del camino los trata como un valor.
    """

    terminos: tuple[str, ...] = ()
    modo: ModoBusqueda = ModoBusqueda.TODAS
    # Términos que se buscan **solo** en el CPC: el código y el nombre estándar de cada ítem de la
    # necesidad. Es un filtro aparte de `terminos` y no una variante suya por una razón de negocio:
    # `terminos` busca en el texto libre de la convocatoria —el objeto de compra, la entidad— y por
    # eso trae todo lo que menciona la palabra, tenga o no que ver con lo que se busca. Quien vigila
    # «lavado» recibe así desde un servicio de lavado de vehículos hasta una capacitación sobre
    # prevención de lavado de activos. El CPC es la clasificación normalizada del Estado: filtrar
    # por él deja fuera lo que solo lo menciona de pasada.
    #
    # Los dos criterios **se suman**, no se sustituyen: quien envíe los dos pide la intersección, y
    # el panel decide cuál usar.
    cpc: tuple[str, ...] = ()
    fuente: str | None = None
    # Familia de contratación. Es un filtro de verdad —restringe las filas— y no una opción de
    # presentación, y por eso vive aquí con los demás criterios y no en el exportador.
    categoria: Categoria | None = None
    # Una o **varias** provincias. Es una tupla y no un valor suelto porque el mapa del panel
    # permite elegir varias a la vez: comparar cómo se comporta lo mismo en tres provincias es un
    # uso real, y con un valor único esa comparación obligaría a tres consultas separadas y a
    # sumar mentalmente los resultados.
    provincias: tuple[str, ...] = ()
    estado: str | None = None
    # Criterios del listado de ofertas, que reproduce los filtros del buscador del portal.
    #
    # `entidad` y `codigo` comparan por **fragmento**, porque son datos que nadie recuerda enteros:
    # quien filtra por entidad escribe «municipio» y quien busca un proceso teclea los últimos
    # dígitos. Los dos tipos comparan **exacto**, porque sus valores salen de un desplegable y una
    # igualdad parcial encontraría «Licitación» al pedir «Lic», que no es lo que se eligió.
    entidad: str | None = None
    tipo_proceso: str | None = None
    tipo_necesidad: str | None = None
    codigo: str | None = None
    desde: date | None = None
    hasta: date | None = None
    solo_nuevos: bool = False
    # Descarta lo que ya no admite proformas. Va en los filtros y no en el frontend porque el panel
    # está paginado: esconder en el navegador lo vencido de la página visible dejaría las siguientes
    # llenas de filas vencidas y los totales mentirían.
    solo_con_plazo: bool = False
    # Fuentes que quien consulta tiene permitido leer. **Forma parte de la clave de caché**, y no es
    # un detalle: sin ella, un usuario con dos vistas y otro con una compartirían entrada, y el
    # segundo recibiría la página completa que cacheó el primero. Sería una fuga silenciosa entre
    # niveles de permiso, que es peor que una entre negocios porque no la detecta el aislamiento.
    fuentes_permitidas: tuple[str, ...] = ()
    # Ancho de la ventana de «novedad», en minutos. Forma parte de los filtros y por tanto de la
    # clave de caché: si cambiara la configuración sin entrar en la clave, se servirían páginas
    # calculadas con la ventana anterior durante todo un TTL.
    ventana_nuevos_min: int = 60
    texto: str | None = None
    pagina: int = 1
    tamano: int = TAMANO_PREDETERMINADO
    orden: OrdenBusqueda = OrdenBusqueda.RECIENTES

    def validado(self) -> Filtros:
        """Comprueba los topes y devuelve los filtros listos para usar.

        Se **rechaza** en lugar de recortar en silencio: si el cliente pide 5 000 filas por página,
        devolver 100 sin avisar produce errores difíciles de rastrear en el frontend.
        """
        if self.pagina < 1:
            raise DatoInvalido("La página debe ser 1 o mayor.")
        if self.pagina > PAGINA_MAXIMA:
            raise DatoInvalido(
                f"La página supera el máximo permitido ({PAGINA_MAXIMA}). Acota los filtros."
            )
        if self.tamano < 1:
            raise DatoInvalido("El tamaño de página debe ser 1 o mayor.")
        if self.tamano > TAMANO_MAXIMO:
            raise DatoInvalido(f"El tamaño de página no puede superar {TAMANO_MAXIMO}.")
        if self.desde and self.hasta and self.desde > self.hasta:
            raise DatoInvalido("La fecha inicial no puede ser posterior a la final.")
        if self.categoria is not None and self.fuente:
            # Dos criterios que se contradicen. Se rechaza en lugar de devolver una tabla vacía: un
            # archivo sin ninguna fila parece un fallo del sistema, y quien lo mira no tiene forma
            # de saber que fue él quien pidió dos cosas incompatibles.
            admitidas = FUENTES_POR_CATEGORIA[self.categoria]
            if self.fuente.strip().upper() not in admitidas:
                raise DatoInvalido(
                    f"La categoría «{ETIQUETA_POR_CATEGORIA[self.categoria]}» no incluye la fuente "
                    f"{self.fuente!r}. Con esos dos criterios juntos no hay ningún resultado: "
                    f"quita uno de los dos."
                )
        return self

    @property
    def desplazamiento(self) -> int:
        """Filas a descartar antes de la primera de la página."""
        return (self.pagina - 1) * self.tamano

    @property
    def sin_terminos(self) -> bool:
        return not self.terminos

    @property
    def cacheable(self) -> bool:
        """¿Merece la pena guardar esta consulta en el caché?

        Dos criterios quedan fuera: `codigo` y `texto` libre. Los dos son lo que la persona escribe,
        así que su espacio de combinaciones es ilimitado y casi ninguna se repite. Guardarlas
        llenaría el almacén de entradas que nadie volvería a pedir, y cada una ocupa memoria
        mientras las demás siguen ocupando la suya: el caché dejaría de acelerar y pasaría a ser un
        residuo que crece con cada usuario.

        No es una regla de corrección —la respuesta sería igual de buena— sino de coste, y por eso
        vive aquí y no en el caso de uso: es una propiedad de los criterios, no del camino que los
        recorre.

        Los términos **sí** se cachean: son un catálogo compartido y normalizado, así que dos
        personas que vigilan lo mismo comparten entrada.

        Los términos de CPC se cachean igual, y conviene decir por qué: llegan normalizados
        —minúsculas, sin acentos, sin repetir y ordenados—, así que dos formas de escribirlos no
        crean dos entradas, y son un criterio pensado para repetirse: la lista de clasificaciones
        que un negocio vigila. Se parecen al catálogo de términos y no al texto libre. Si algún día
        se usaran como caja de búsqueda «mientras se escribe», esta decisión habría que revisarla:
        ese es exactamente el caso de `texto`, y llenaría el almacén de entradas que nadie repite.

        Se comparan los valores ya recortados porque un espacio suelto no es un filtro: si contara,
        escribir y borrar el mismo texto dejaría la caché desactivada sin que nadie lo notara.
        """
        return not ((self.codigo or "").strip() or (self.texto or "").strip())

    def canonico(self) -> dict[str, Any]:
        """Forma estable para calcular la huella.

        Las claves son cortas porque acaban dentro de la clave de caché.
        """
        return {
            "t": list(self.terminos),
            "m": str(self.modo),
            "cc": list(self.cpc),
            "f": self.fuente or "",
            # La categoría **tiene** que estar aquí. Faltando, una exportación de ínfimas y otra de
            # ofertas con los mismos filtros compartirían entrada de caché, y la segunda recibiría
            # la del primero: un archivo de ínfimas con las ofertas del compañero, o al revés. Es el
            # mismo fallo que ya se documentó con `solo_con_plazo` y no deja ningún rastro.
            "g": str(self.categoria) if self.categoria else "",
            "fp": list(self.fuentes_permitidas),
            # Las provincias van **ordenadas** y no en el orden en que se pulsaron. Sin ordenar, el
            # mapa guardaría una entrada de caché distinta según el orden de los clics —Pichincha
            # y luego Azuay frente a Azuay y luego Pichincha— para exactamente el mismo resultado.
            # El acierto de caché se perdería justo cuando más se usa el filtro.
            "p": sorted(normalizar(provincia) or "" for provincia in self.provincias),
            "e": normalizar(self.estado),
            # Los cuatro criterios del listado de ofertas van aquí por la misma razón que
            # `solo_con_plazo`: sin ellos, dos listados que solo se diferenciaran en la entidad o en
            # el código compartirían entrada de caché y el primero en llegar decidiría lo que ve el
            # otro durante todo un TTL. Es un fallo que no deja rastro —la respuesta es correcta,
            # pero para otra consulta— y solo se nota comparando dos pantallas a la vez.
            "en": normalizar(self.entidad),
            "tp": normalizar(self.tipo_proceso),
            "tn": normalizar(self.tipo_necesidad),
            "cd": (self.codigo or "").strip().lower(),
            "d": self.desde.isoformat() if self.desde else "",
            "h": self.hasta.isoformat() if self.hasta else "",
            "n": self.solo_nuevos,
            "v": self.ventana_nuevos_min,
            # `solo_con_plazo` **tiene** que estar aquí. Faltaba, y su ausencia era invisible: dos
            # peticiones que solo se diferenciaran en ese interruptor compartían entrada de caché,
            # así que la primera en llegar decidía lo que veía la otra durante todo un TTL. Daba
            # igual marcar «ocultar lo ya vencido»: si antes alguien había consultado sin marcarlo,
            # seguían apareciendo las vencidas, y al revés. Es el peor tipo de fallo de caché,
            # porque el resultado es correcto para *otra* consulta y no hay error que lo delate.
            "sp": self.solo_con_plazo,
            "x": normalizar(self.texto),
            "pg": self.pagina,
            "sz": self.tamano,
            "o": str(self.orden),
        }

    def canonico_agregados(self) -> dict[str, Any]:
        """Forma estable para los agregados, **sin paginación ni orden**.

        Las gráficas resumen todos los resultados que cumplen los filtros, no una página concreta.
        Si la huella incluyera la página, pasar de la 1 a la 2 dejaría sin efecto la caché de las
        gráficas aunque sus datos no hayan cambiado, y con veinte páginas se guardarían veinte
        copias idénticas del mismo agregado.

        El orden tampoco entra: reordenar la tabla no cambia un total.
        """
        completo = self.canonico()
        for clave in ("pg", "sz", "o"):
            completo.pop(clave, None)
        return completo

    def descripcion(self) -> str:
        """Texto legible para los avisos y los registros de auditoría."""
        partes = [f"modo={self.modo}"]
        if self.terminos:
            partes.append(f"terminos={','.join(self.terminos)}")
        if self.cpc:
            partes.append(f"cpc={','.join(self.cpc)}")
        if self.fuente:
            partes.append(f"fuente={self.fuente}")
        if self.categoria:
            partes.append(f"categoria={self.categoria}")
        if self.provincias:
            partes.append(f"provincias={','.join(self.provincias)}")
        if self.estado:
            partes.append(f"estado={self.estado}")
        if self.desde or self.hasta:
            partes.append(f"rango={self.desde or '-'}..{self.hasta or '-'}")
        if self.solo_nuevos:
            partes.append("solo_nuevos")
        if self.texto:
            partes.append("texto_libre")
        return " ".join(partes)


def huella_filtros(filtros: Filtros) -> str:
    """Huella estable de una combinación de criterios."""
    serializado = json.dumps(
        filtros.canonico(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()[:32]


def clave_generacion(fuente: str) -> str:
    """Clave del contador de generación de una fuente.

    La ingesta la incrementa al cerrar un ciclo con cambios; el lector la incorpora a su clave. Es
    lo que invalida una página entera sin borrar nada: las claves antiguas dejan de encontrarse y
    expiran solas por su tiempo de vida.
    """
    return f"{PREFIJO_GENERACION}:{fuente}"


def clave_resultados(filtros: Filtros, generacion: int) -> str:
    """Clave de caché de una página de resultados."""
    return f"{PREFIJO_RESULTADOS}:{generacion}:{huella_filtros(filtros)}"


def clave_catalogo(nombre: str, generacion: int = 0) -> str:
    """Clave de caché de un catálogo de filtros (provincias, estados, fuentes)."""
    return f"{PREFIJO_CATALOGO}:{generacion}:{normalizar(nombre)}"


def clave_estadisticas(filtros: Filtros, generacion: int = 0) -> str:
    """Clave de caché de las estadísticas agregadas.

    Depende de **los mismos criterios que la búsqueda**, porque los agregados se calculan sobre el
    resultado filtrado. Con una clave que solo mirara la fuente, dos usuarios con palabras clave
    distintas compartirían los totales y las gráficas mostrarían los del primero que preguntó.
    """
    serializado = json.dumps(
        filtros.canonico_agregados(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    huella = hashlib.sha256(serializado.encode("utf-8")).hexdigest()[:32]
    return f"{PREFIJO_ESTADISTICAS}:{generacion}:{huella}"


def clave_tablero_fuentes(generacion: int = 0) -> str:
    """Clave de caché del tablero de estado de las fuentes."""
    return f"{PREFIJO_TABLERO}:{generacion}"


@dataclass(frozen=True, slots=True)
class PaginaResultados:
    """Una página de resultados con lo necesario para pintarla y para saber de dónde salió."""

    elementos: tuple[Mapping[str, Any], ...]
    total: int
    pagina: int
    tamano: int
    generacion: int
    desde_cache: bool = False
    avisos: tuple[str, ...] = ()

    @property
    def paginas(self) -> int:
        """Número total de páginas. Cero cuando no hay resultados."""
        if self.tamano <= 0:
            return 0
        return (self.total + self.tamano - 1) // self.tamano

    @property
    def hay_anterior(self) -> bool:
        return self.pagina > 1

    @property
    def hay_siguiente(self) -> bool:
        return self.pagina < self.paginas

    def como_diccionario(self) -> dict[str, Any]:
        """Envoltura de respuesta. Nunca incluye `NaN` ni `Infinity` (RNF-13)."""
        return {
            "elementos": list(self.elementos),
            "total": self.total,
            "pagina": self.pagina,
            "tamano": self.tamano,
            "paginas": self.paginas,
            "hay_anterior": self.hay_anterior,
            "hay_siguiente": self.hay_siguiente,
            "generacion": self.generacion,
            "desde_cache": self.desde_cache,
            "avisos": list(self.avisos),
        }


def limitar_elementos(
    elementos: Iterable[Mapping[str, Any]], filtros: Filtros
) -> tuple[Mapping[str, Any], ...]:
    """Recorta en memoria y deja solo la página pedida.

    Se usa cuando el resultado viene de la caché ya completo o cuando una fuente local lo entrega
    entero; evita repetir la aritmética de la ventana en cada adaptador.
    """
    todos = list(elementos)
    inicio = filtros.desplazamiento
    return tuple(todos[inicio : inicio + filtros.tamano])


@dataclass(slots=True)
class ContadoresBusqueda:
    """Métricas de una consulta, para observabilidad (RNF-11)."""

    aciertos: int = 0
    fallos: int = 0
    milisegundos: float = 0.0
    avisos: list[str] = field(default_factory=list)

    def avisar(self, mensaje: str) -> None:
        if mensaje not in self.avisos:
            self.avisos.append(mensaje)

    @property
    def total(self) -> int:
        return self.aciertos + self.fallos

    @property
    def proporcion_aciertos(self) -> float:
        """Proporción de lecturas servidas desde caché. Cero si aún no hubo lecturas."""
        return 0.0 if self.total == 0 else self.aciertos / self.total
