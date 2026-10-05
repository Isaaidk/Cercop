"""Adaptador de la fuente OCDS (Datos Abiertos de contratación).

A diferencia de NCO, aquí **sí hay histórico**: el listado se consulta por año, así que al añadir un
término nuevo se puede recuperar lo publicado en años anteriores. Es lo que permite no perder
contrataciones cuando alguien agrega una palabra clave.

El coste es que cada término consume al menos una petición **por año y por página**, así que el
adaptador trabaja siempre contra el presupuesto del ciclo y se detiene cuando se agota.

Sobre el punto de partida (`desde`)
-----------------------------------
La API **no filtra por rango de fechas**: busca por año. Así que `desde` no se traduce a un filtro,
se traduce a **cuántos años hay que mirar**. Un término que se busca por primera vez llega con una
fecha antigua y por eso se revisan varios años; uno que se buscó hace un rato cae en el año en curso
y se revisa solo ese.

Ignorar `desde` —que era lo que hacía antes— funcionaba por accidente y a un precio alto: se
revisaban todos los años configurados en cada ciclo de 15 minutos, para todos los términos. Ahora el
coste es proporcional a lo que de verdad hay que recuperar.

Sobre qué páginas se leen
-------------------------
La API pagina **de lo más antiguo a lo más reciente**: las primeras páginas de un año traen los
procesos de enero y lo recién publicado está en las últimas. Comprobado contra la fuente el
2026-10-01: `year=2026&search=` (vacío) en la página 1 devuelve 2026-02-06 y 2026-01-05, mientras
que la página 534 de 535 de `search=mantenimiento` devuelve 2026-09-29 y 2026-09-30. Leer las tres
primeras páginas —lo que se hacía antes— era leer **lo más antiguo del año**, y por eso la tabla de
ofertas se quedaba meses atrás mientras el ciclo se registraba como correcto.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from math import ceil
from typing import Any

from contratacion.aplicacion.puertos.fuente import ResultadoExtraccion
from contratacion.dominio.ingesta import Presupuesto, clave_natural
from contratacion.infraestructura.adaptadores.salida.fuentes.limitador import LimitadorTasa

CODIGO = "OCDS"
API_URL = "https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api"
SEARCH_URL = f"{API_URL}/search_ocds"

# Páginas **del final** que se leen por término y año: son las que traen lo recién publicado, que
# es lo único que cambia entre dos ciclos. La primera página se pide **además**, no en su lugar: es
# la que dice cuántas páginas tiene la búsqueda —sin ese dato no se puede saltar al final— y de paso
# trae lo más antiguo del año, que es histórico que aún no está en la base.
PAGINAS_DEL_FINAL = 2

# Años que se revisan como mucho hacia atrás cuando el punto de partida es antiguo. Es el tope del
# rescate histórico: sin él, un término nuevo con una fecha muy lejana dispararía peticiones sin
# control. Con tres años se cubre de sobra la vida útil de una necesidad de contratación.
ANIOS_MAXIMOS_HACIA_ATRAS = 3

AVISO_PRESUPUESTO = (
    "El presupuesto de peticiones de este ciclo se agotó antes de completar todas las búsquedas. "
    "Los términos pendientes se ingestan en el siguiente ciclo."
)
AVISO_SIN_RESPUESTA = (
    "La fuente de procesos publicados no respondió para algunos términos. "
    "Los resultados pueden estar incompletos."
)


class _Estado(StrEnum):
    """Cómo terminó la lectura de una página. Es el control de flujo de `extraer`."""

    OK = "ok"
    FALLO = "fallo"
    AGOTADO = "agotado"


class FuenteOcds:
    """Procesos publicados, consultados por término y año."""

    codigo = CODIGO

    def __init__(
        self,
        terminos: Sequence[str],
        *,
        limitador: LimitadorTasa | None = None,
        paginas_del_final: int = PAGINAS_DEL_FINAL,
        anios: Sequence[int] | None = None,
    ) -> None:
        self._terminos = [termino.strip() for termino in terminos if termino.strip()]
        self._limitador = limitador or LimitadorTasa()
        self._paginas_del_final = max(1, paginas_del_final)
        # `None` significa «decide tú a partir del punto de partida». Una lista explícita manda.
        self._anios = list(anios) if anios is not None else None

    def _anios_para(self, desde: datetime) -> list[int]:
        """Años que hay que revisar, dado desde cuándo hay que buscar.

        Se acota por abajo con `ANIOS_MAXIMOS_HACIA_ATRAS` para que un punto de partida muy antiguo
        no dispare el número de peticiones, y por arriba con el año en curso.
        """
        if self._anios is not None:
            return list(self._anios)
        actual = datetime.now(UTC).year
        minimo = max(actual - ANIOS_MAXIMOS_HACIA_ATRAS, desde.year)
        return list(range(minimo, actual + 1))

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        resultado = ResultadoExtraccion()
        fallo = False
        completos: list[str] = []

        for termino in self._terminos:
            completo = True
            agotado = False
            for anio in self._anios_para(desde):
                estado = await self._leer_termino_anio(termino, anio, resultado, presupuesto)
                if estado is _Estado.AGOTADO:
                    agotado = True
                    break
                if estado is _Estado.FALLO:
                    completo = False
                    fallo = True
            # Un término solo se da por buscado si se leyeron **todas** sus páginas: si el
            # presupuesto se agotó a mitad, queda pendiente para la vuelta siguiente.
            if completo and not agotado:
                completos.append(termino)
            if agotado:
                break

        resultado.terminos_completos = tuple(completos)
        if resultado.agoto_presupuesto:
            resultado.avisos.append(AVISO_PRESUPUESTO)
        if fallo:
            resultado.avisos.append(AVISO_SIN_RESPUESTA)
            resultado.parcial = True

        return resultado

    async def _leer_termino_anio(
        self,
        termino: str,
        anio: int,
        resultado: ResultadoExtraccion,
        presupuesto: Presupuesto,
    ) -> _Estado:
        """Lee las páginas de un término y un año.

        Primero la primera página —dice cuántas hay y trae lo más antiguo del año— y después las
        últimas, que es donde está lo recién publicado.
        """
        estado, total, _ = await self._leer_pagina(termino, anio, 1, resultado, presupuesto)
        if estado is not _Estado.OK:
            return estado

        primera_del_final = max(1, total - self._paginas_del_final + 1)
        for pagina in range(primera_del_final, total + 1):
            if pagina == 1:
                continue  # Ya leída arriba.
            estado, _, _ = await self._leer_pagina(termino, anio, pagina, resultado, presupuesto)
            if estado is not _Estado.OK:
                return estado
        return _Estado.OK

    async def _leer_pagina(
        self,
        termino: str,
        anio: int,
        pagina: int,
        resultado: ResultadoExtraccion,
        presupuesto: Presupuesto,
    ) -> tuple[_Estado, int, list[str]]:
        """Pide una página, acumula sus registros y devuelve estado, total de páginas y fechas.

        Las fechas se devuelven porque el modo general las necesita para decidir si sigue caminando
        hacia atrás. Se calculan aquí, donde ya están las filas en la mano, para no volver a
        recorrerlas.
        """
        if not presupuesto.consumir():
            resultado.agoto_presupuesto = True
            return _Estado.AGOTADO, 0, []

        payload = await self._limitador.solicitar_json(
            SEARCH_URL,
            {"year": anio, "search": termino, "page": pagina},
            etiqueta=f"{termino or 'general'} · {anio} · pág. {pagina}",
        )
        resultado.peticiones += 1

        if payload is None:
            return _Estado.FALLO, 0, []

        fechas: list[str] = []
        registros = payload.get("data") or []
        if isinstance(registros, list):
            for registro in registros:
                if isinstance(registro, dict):
                    registro["_termino_buscado"] = termino
                    resultado.registros.append(registro)
                    fechas.append(str(registro.get("date") or ""))

        total = payload.get("pages")
        return _Estado.OK, total if isinstance(total, int) and total >= 1 else 1, fechas

    def clave_natural(self, crudo: Mapping[str, Any]) -> str | None:
        """El `ocid` es el identificador estándar y estable de un proceso."""
        ocid = str(crudo.get("ocid") or "").strip()
        if not ocid:
            return None
        return clave_natural(CODIGO, [ocid])

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """Término por el que entró el registro, útil para saber por qué está en la base."""
        encontrado = str(crudo.get("_termino_buscado") or "").strip()
        return [encontrado] if encontrado else []

    async def cerrar(self) -> None:
        await self._limitador.cerrar()


# --- Modo general: el listado del año, no la búsqueda por término ----------------------------- #
#
# MEDIDO CONTRA LA FUENTE (2026-10-01):
#
# - `search=` vacío devuelve el **listado general del año**, ordenado igual que la búsqueda: lo más
#   antiguo primero. La última página del 2026 traía el **2026-09-30**: el rabo es lo recién
#   publicado.
# - El año 2026 tiene **103.628 filas = 10.363 páginas**, y crece ~378 filas (37,8 páginas) al día.
# - Las filas del listado general traen **más** campos que las de una búsqueda por término: 15 con
#   dato, incluidos `budget` y `suppliers`, frente a 13 (esos dos llegan vacíos).
#
# POR QUÉ MERECE LA PENA: por término, veinte palabras cuestan ~45-60 peticiones por ciclo —unas
# 4.000 al día— contra una fuente que responde 429 con un `Retry-After` de 11-20 s cuando se le
# aprieta. Por el rabo del listado general, una vuelta cuesta **una petición para saber cuántas
# páginas hay más las que hayan crecido** desde la anterior: con 37,8 páginas al día son dos o tres,
# unas 135 al día. Treinta veces menos.
PAGINAS_POR_HORA = 1.6
# Margen sobre lo que crece el listado: una hora puede publicar el triple de la media, y releer de
# más no cuesta datos —el `upsert` por huella es idempotente—, mientras que quedarse corto pierde.
MARGEN_RABO = 3
PAGINAS_MINIMAS_DEL_RABO = 2
# Páginas del rabo como mucho en una vuelta. Es lo que acota la **primera**: no hay marca de agua de
# la que fiarse y la ventana es de noventa días, así que sin tope se traería el año entero de golpe.
PAGINAS_GENERALES_POR_CICLO = 40
# Presupuesto que no se gasta el rabo, para que un rescate pendiente no se quede sin cuota.
RESERVA_PARA_RESCATE = 30


class FuenteOcdsGeneral(FuenteOcds):
    """OCDS en modo general: se trae **lo que publica el año**, no lo que coincide con un término.

    Existe porque la búsqueda por palabra clave cuesta una petición por término, año y página, y eso
    con veinte términos son decenas de peticiones cada quince minutos contra una fuente que castiga
    las ráfagas con 429. El listado general es una sola secuencia ordenada por fecha: lo recién
    publicado está siempre al final, así que se leen las últimas páginas y se deja de leer.

    Los términos que se le pasan **no** son la forma normal de ingestar: son el **rescate** de una
    palabra clave que nunca se ha buscado (el caso de la que se acaba de añadir). El listado general
    da todo lo que se publique de aquí en adelante, pero no lo que se publicó antes de que esta
    fuente existiera; eso es lo que hace el rescate, y solo una vez por término.
    """

    codigo = CODIGO

    def __init__(
        self,
        terminos: Sequence[str] = (),
        *,
        paginas_por_ciclo: int = PAGINAS_GENERALES_POR_CICLO,
        desde_pagina: int | None = None,
        limitador: LimitadorTasa | None = None,
        paginas_del_final: int = PAGINAS_DEL_FINAL,
        anios: Sequence[int] | None = None,
    ) -> None:
        """`desde_pagina` es el **modo relleno**: empezar por esa página y caminar hacia atrás.

        Se usa para traer el histórico del año, que son miles de páginas y no cabe en una vuelta: el
        relleno lo ejecuta `scripts/rellenar_ofertas_ocds.py` por tandas, y cada tanda dice por
        dónde siguió. Con él se salta la lectura de la primera página —que solo hace falta para
        saber cuántas hay, y en este modo el número lo pone quien rellena—.
        """
        super().__init__(
            terminos, limitador=limitador, paginas_del_final=paginas_del_final, anios=anios
        )
        self._paginas_por_ciclo = max(1, paginas_por_ciclo)
        self._desde_pagina = desde_pagina

    def _paginas_a_leer(self, desde: datetime) -> int:
        """Cuántas páginas del rabo leer, estimadas por el **tiempo** transcurrido.

        No se decide por las fechas de las filas, y el motivo importa: muchas publican el día sin
        hora (`2026-09-30T00:00:00-05:00`), así que su fecha es anterior a una ventana de media hora
        aunque la fila acabe de aparecer. Comparar contra `desde` para saber cuándo parar cortaría
        antes de tiempo y se perderían publicaciones. El tiempo transcurrido, en cambio, se estima
        de sobra: se sabe cuánto crece el listado por hora y se multiplica por un margen.
        """
        horas = max(0.0, (datetime.now(UTC) - desde).total_seconds() / 3600)
        # El mínimo va aquí y no sumado a la estimación: `ceil` de cualquier número positivo ya vale
        # uno, así que sumarlo contaba dos veces el mínimo y leía una página de más en cada vuelta.
        estimadas = ceil(horas * PAGINAS_POR_HORA * MARGEN_RABO)
        return min(self._paginas_por_ciclo, max(PAGINAS_MINIMAS_DEL_RABO, estimadas))

    async def extraer(self, desde: datetime, presupuesto: Presupuesto) -> ResultadoExtraccion:
        """Trae el rabo del listado general y, si queda cuota, rescata los términos sin buscar."""
        resultado = await self._rabo_del_listado(desde, presupuesto)

        if self._terminos and presupuesto.restantes > 0:
            rescate = await super().extraer(desde, presupuesto)
            resultado.registros.extend(rescate.registros)
            resultado.avisos.extend(rescate.avisos)
            resultado.peticiones += rescate.peticiones
            # El `terminos_completos` del rescate es el que hay que respetar: son los términos cuyo
            # ciclo de búsqueda se cerró de verdad. El rabo no busca por término, así que no marca
            # ninguno.
            resultado.terminos_completos = rescate.terminos_completos
            resultado.parcial = resultado.parcial or rescate.parcial
            resultado.agoto_presupuesto = resultado.agoto_presupuesto or rescate.agoto_presupuesto

        return resultado

    async def _rabo_del_listado(
        self, desde: datetime, presupuesto: Presupuesto
    ) -> ResultadoExtraccion:
        """Lee el final del listado: lo que se ha publicado desde la vuelta anterior."""
        resultado = ResultadoExtraccion()
        leidas = 0
        fallo = False
        tope = self._paginas_a_leer(desde)
        reserva = RESERVA_PARA_RESCATE if self._terminos else 0

        for anio in self._anios_para(desde):
            if self._desde_pagina is not None:
                pagina = self._desde_pagina
            else:
                # Una petición para saber cuántas páginas hay: la primera las declara. Trae además
                # lo más antiguo del año, que es histórico que puede no estar todavía en la base.
                estado, total, _ = await self._leer_pagina("", anio, 1, resultado, presupuesto)
                leidas += 1
                if estado is _Estado.AGOTADO:
                    break
                if estado is _Estado.FALLO:
                    fallo = True
                    break
                pagina = total

            while pagina > 1 and leidas < tope and presupuesto.restantes > reserva:
                estado, _, _ = await self._leer_pagina("", anio, pagina, resultado, presupuesto)
                leidas += 1
                if estado is _Estado.AGOTADO:
                    break
                if estado is _Estado.FALLO:
                    fallo = True
                    break
                pagina -= 1

        if resultado.agoto_presupuesto:
            resultado.avisos.append(AVISO_PRESUPUESTO)
            # Se queda a medias de verdad: la marca de agua no debe avanzar, para que la siguiente
            # vuelta vuelva a cubrir lo que faltó.
            resultado.parcial = True
        if fallo:
            resultado.avisos.append(AVISO_SIN_RESPUESTA)
            resultado.parcial = True

        return resultado

    def terminos(self, crudo: Mapping[str, Any]) -> Sequence[str]:
        """Sin término: lo que entra por el rabo no lo trajo ninguna palabra clave."""
        return []
