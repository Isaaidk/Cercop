"""Caso de uso: ejecutar un ciclo de ingesta completo.

Orquesta la cadena entera sin saber de HTTP ni de SQL concretos: pide a la fuente a través del
puerto, mapea con las reglas de la base, clasifica por huella, guarda e invalida la caché.

Reglas que aplica este caso de uso:

- La ventana de lectura se solapa con el ciclo anterior: un registro publicado entre dos
  ejecuciones no debe perderse nunca.
- El `upsert` es idempotente por clave natural y huella: repetir un ciclo no duplica ni crea
  historial falso.
- El historial solo crece cuando el contenido cambia: llenarlo de ruido lo inutiliza.
- Los campos sin mapear se registran, no se descartan: la fuente puede añadir columnas sin avisar.
- La marca de agua **no avanza** si el ciclo fue parcial: un fallo no debe dejar un hueco.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.generaciones import subir_generacion
from contratacion.aplicacion.mapeo import MapeoCampo, aplicar
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.fuente import FuenteExterna
from contratacion.dominio.cpc import items_desde_crudos
from contratacion.dominio.ingesta import (
    CAMPOS_VOLATILES,
    DIAS_VENTANA_INICIAL,
    Clasificacion,
    ContadoresCiclo,
    Presupuesto,
    clasificar,
    fecha_a_utc,
    hash_contenido,
    ventana_desde,
)
from contratacion.dominio.palabras import normalizar
from contratacion.infraestructura.adaptadores.salida.bd.ingesta import (
    ESTADO_ERROR,
    ESTADO_OK,
    ESTADO_PARCIAL,
    RepositorioIngesta,
)

registro = logging.getLogger(__name__)

# Campos que alimentan el texto de búsqueda. Deliberadamente **fuera**: funcionario, email, teléfono
# y contacto. Son datos personales y no deben acabar indexados en un campo de búsqueda libre.
CAMPOS_BUSCABLES = (
    "codigo",
    "objeto_compra",
    "entidad",
    "provincia",
    "canton",
    "tipo_necesidad",
    "tipo_proceso",
    "estado",
    "proveedor",
)


@dataclass(frozen=True)
class DefinicionFuente:
    """Una fuente con todo lo que el ciclo necesita para registrarla."""

    codigo: str
    nombre: str
    endpoint_base: str
    adaptador: FuenteExterna
    mapeos_por_defecto: Sequence[Mapping[str, Any]] = ()
    # Desde cuándo leer. El planificador ya ha deducido la ventana a partir de los términos de este
    # ciclo y la pasa aquí; si se deja en `None`, se deduce de la marca de agua de la fuente.
    desde: datetime | None = None
    # Términos cuyo ciclo de búsqueda hay que cerrar al terminar, para que la cola avance.
    terminos_buscados: Sequence[UUID] = ()
    # Texto de cada término → su identificador. Es lo que permite marcar **solo** los términos que
    # esta vuelta leyó enteros cuando el ciclo queda parcial.
    terminos_por_texto: Mapping[str, UUID] = field(default_factory=dict)
    # La fuente publica **todo lo vigente** en cada extracción, no una parte. Solo con eso se puede
    # deducir que un registro que ya no aparece se cerró: a una fuente que se consulte por partes
    # —OCDS, por término y página— aplicarle esa deducción daría por cerrado lo que solo no se miró.
    listado_completo: bool = False


@dataclass(frozen=True)
class ResultadoCiclo:
    """Resumen de un ciclo, para registrarlo y para poder auditarlo."""

    fuente: str
    estado: str
    nuevos: int
    actualizados: int
    iguales: int
    sin_mapear: int
    peticiones: int
    avisos: tuple[str, ...]
    # Registros que esta vuelta dejó de ver en el listado y por tanto se cerraron. Es información de
    # negocio, no un detalle técnico: es lo que distingue una necesidad que sigue admitiendo
    # proformas de una que ya se cerró.
    cerrados: int = 0

    @property
    def hubo_cambios(self) -> bool:
        return self.nuevos > 0 or self.actualizados > 0


def _texto_busqueda(datos: Mapping[str, Any]) -> str:
    partes = [str(datos[campo]) for campo in CAMPOS_BUSCABLES if datos.get(campo) not in (None, "")]
    return normalizar(" ".join(partes))


async def ejecutar_ciclo(
    definicion: DefinicionFuente,
    repositorio: RepositorioIngesta,
    cache: Cache,
    *,
    intervalo_min: int,
    ventana_solape_ciclos: int,
    presupuesto_peticiones: int,
    dias_ventana_inicial: int = DIAS_VENTANA_INICIAL,
    ahora: datetime | None = None,
    invalidar_cache: bool = True,
) -> ResultadoCiclo:
    """Ejecuta un ciclo para una fuente y devuelve su resumen.

    `invalidar_cache` existe para la vigilancia del listado (ver
    `planificador.ejecutar_vigilancia`), que escribe cada dos minutos y medio. Subir la generación
    cada vez deja inservible todo lo cacheado a esa cadencia —y el catálogo de desplegables, que
    recorre el histórico entero, es la consulta más cara del sistema—, así que la vigilancia guarda
    los datos **sin** tocar la caché y es el ciclo pesado el que la invalida, una vez cada cuarto de
    hora. Lo que ve el panel no cambia: una página de resultados ya vive 900 s de todos modos.
    """
    momento = ahora or datetime.now(UTC)
    contadores = ContadoresCiclo()

    fuente_id = await repositorio.asegurar_fuente(
        definicion.codigo,
        definicion.nombre,
        definicion.endpoint_base,
        intervalo_min=intervalo_min,
        ventana_solape_ciclos=ventana_solape_ciclos,
        presupuesto_peticiones_ciclo=presupuesto_peticiones,
    )
    if definicion.mapeos_por_defecto:
        await repositorio.asegurar_mapeos(fuente_id, definicion.mapeos_por_defecto)

    ultima = await repositorio.ultima_sincronizacion_ok(fuente_id)
    # La ventana la decide quien conoce los términos de este ciclo. Solo si no la trae se deduce de
    # la marca de agua de la fuente, que es el criterio general y no sabe nada de suscripciones.
    desde = definicion.desde or ventana_desde(
        ultima, intervalo_min, ventana_solape_ciclos, momento, dias_ventana_inicial
    )
    sincronizacion_id = await repositorio.iniciar_sincronizacion(fuente_id)
    presupuesto = Presupuesto(limite=presupuesto_peticiones)
    peticiones = 0
    estado = ESTADO_OK
    # Lo rellena la fuente dentro del `try`; si el ciclo revienta antes, se queda vacío y ningún
    # término se da por buscado.
    terminos_completos: tuple[str, ...] = ()
    # Registros que dejaron de estar en el listado (se cerraron). Se cuentan dentro del `try`.
    cerrados = 0

    try:
        extraccion = await definicion.adaptador.extraer(desde, presupuesto)
        peticiones = extraccion.peticiones or presupuesto.usadas
        terminos_completos = extraccion.terminos_completos
        for aviso in extraccion.avisos:
            contadores.avisar(aviso)

        mapeos = await repositorio.obtener_mapeos(fuente_id)
        preparados = _mapear_todo(definicion, mapeos, extraccion.registros, contadores)

        huellas = await repositorio.huellas_existentes(
            fuente_id, [clave for clave, *_ in preparados]
        )
        # Las filas que hay que escribir se juntan primero y se escriben **de una vez**, en una sola
        # transacción y por lotes. Escribirlas una a una —lo que se hacía— son tres viajes de ida y
        # vuelta a la base por fila: con el listado de 1.715 necesidades y una base a 86 ms eso son
        # casi nueve minutos, que era, con diferencia, lo más caro del ciclo.
        a_guardar: list[dict[str, Any]] = []
        con_historial: list[dict[str, Any]] = []
        a_refrescar: list[dict[str, Any]] = []
        for clave, datos, crudo_limpio, texto, huella, items in preparados:
            clasificacion = clasificar(huellas.get(clave), huella)
            if clasificacion is Clasificacion.IGUAL:
                contadores.iguales += 1
                # La fila no cambió, pero sus campos volátiles sí pueden haber cambiado: el token
                # del enlace de la ficha se regenera en cada listado. Se refresca solo eso, sin
                # reescribir el registro ni añadir historial, y así el enlace guardado no envejece.
                volatiles = {
                    campo: valor for campo, valor in datos.items() if campo in CAMPOS_VOLATILES
                }
                if volatiles:
                    a_refrescar.append({"clave": clave, "volatiles": volatiles})
                if not items:
                    continue
                # Con ítems no se puede saltar la escritura aunque el contenido sea el mismo: el
                # desglose del producto **no entra en la huella** (`hash_contenido` mira `datos`),
                # así que una fila que se importó antes de que supiéramos leerlo se ve igual que
                # una que ya lo tiene. Sin esta excepción, el relleno de los ítems de un año
                # importado no escribiría ni uno solo: se contaría todo como «igual».
                #
                # No cuenta como actualización ni deja historial: el contenido de `datos` no ha
                # cambiado, y meterlo en el histórico convertiría esa tabla en un registro de
                # visitas.
            else:
                if clasificacion is Clasificacion.NUEVO:
                    contadores.nuevos += 1
                else:
                    contadores.actualizados += 1
                    con_historial.append({"datos": datos, "hash": huella, "clave": clave})

            a_guardar.append(
                {
                    "clave": clave,
                    "datos": datos,
                    "crudo": crudo_limpio,
                    "texto": texto,
                    "hash": huella,
                    "fecha": _fecha_utc(datos.get("fecha_publicacion")),
                    "items": list(items),
                }
            )

        ids = await repositorio.guardar_registros(fuente_id, a_guardar)
        if a_refrescar:
            await repositorio.refrescar_volatiles(fuente_id, a_refrescar)
        if con_historial:
            await repositorio.agregar_historial_en_lote(
                [
                    {
                        "registro_id": ids[fila["clave"]],
                        "datos": fila["datos"],
                        "hash": fila["hash"],
                    }
                    for fila in con_historial
                ]
            )

        # La vigencia se marca **después** de escribir, y solo si la extracción trajo la foto
        # completa: lo que acaba de entrar está en el listado y no puede quedarse fuera por una
        # carrera con esta misma marca. Un ciclo parcial o vacío no cierra nada — dar por cerrado lo
        # que solo no se pudo leer es peor que no actualizar el estado.
        if definicion.listado_completo and not extraccion.parcial and extraccion.registros:
            cerrados = await repositorio.marcar_fuera_de_listado(
                fuente_id, [clave for clave, *_ in preparados]
            )
        await repositorio.registrar_pendientes(
            fuente_id, list(_pendientes(mapeos, extraccion.registros)), {}
        )
        contadores.sin_mapear = len(_pendientes(mapeos, extraccion.registros))

        if extraccion.parcial:
            estado = ESTADO_PARCIAL
        elif not extraccion.registros and avisos_de_fallo(extraccion.avisos):
            estado = ESTADO_ERROR

    except Exception as exc:  # noqa: BLE001 - un ciclo fallido no debe tumbar el worker
        registro.exception("Fallo inesperado en el ciclo de %s", definicion.codigo)
        contadores.errores += 1
        contadores.avisar(f"Fallo inesperado durante la ingesta: {type(exc).__name__}")
        estado = ESTADO_ERROR

    # La marca de agua solo avanza si el ciclo se completó: si fue parcial, se conserva la anterior
    # para que el siguiente ciclo vuelva a cubrir lo que quedó pendiente.
    watermark = momento if estado == ESTADO_OK else ultima

    await repositorio.cerrar_sincronizacion(
        sincronizacion_id,
        estado=estado,
        peticiones=peticiones,
        nuevos=contadores.nuevos,
        actualizados=contadores.actualizados,
        errores=contadores.errores,
        avisos=contadores.avisos,
        watermark=watermark,
    )

    # Los términos se dan por buscados cuando su búsqueda se **completó**.
    #
    # Antes se marcaban solo si el ciclo entero terminaba bien, y con una fuente que responde 429 a
    # menudo eso condenaba a la cola: los ciclos parciales eran lo normal, los términos —siempre los
    # mismos veinte— no llegaban a marcarse nunca y los añadidos después no se buscaban jamás. El
    # síntoma era una tabla de ofertas congelada meses atrás mientras el ciclo se registraba una y
    # otra vez.
    #
    # Los términos que fallaron a medias siguen pendientes: es lo que evita dejar un hueco en lo que
    # no se llegó a leer.
    a_marcar: list[UUID] = []
    if definicion.terminos_buscados:
        if estado == ESTADO_OK:
            a_marcar = list(definicion.terminos_buscados)
        else:
            a_marcar = [
                definicion.terminos_por_texto[texto]
                for texto in terminos_completos
                if texto in definicion.terminos_por_texto
            ]
    if a_marcar:
        marcados = await repositorio.marcar_terminos_ingestados(a_marcar, momento)
        registro.info("%s: %s términos marcados como buscados", definicion.codigo, marcados)

    if invalidar_cache and (contadores.nuevos or contadores.actualizados):
        await _invalidar_cache(cache, definicion.codigo)

    return ResultadoCiclo(
        fuente=definicion.codigo,
        estado=estado,
        nuevos=contadores.nuevos,
        actualizados=contadores.actualizados,
        iguales=contadores.iguales,
        sin_mapear=contadores.sin_mapear,
        peticiones=peticiones,
        avisos=tuple(contadores.avisos),
        cerrados=cerrados,
    )


def _mapear_todo(
    definicion: DefinicionFuente,
    mapeos: Sequence[MapeoCampo],
    crudos: Sequence[Mapping[str, Any]],
    contadores: ContadoresCiclo,
) -> list[tuple[str, dict[str, Any], dict[str, Any], str, str, tuple[Any, ...]]]:
    """Convierte cada payload crudo en lo que hay que guardar.

    Se separa de la escritura para poder calcular las huellas en lote y no consultar la base una vez
    por registro.

    El último elemento son los **ítems del producto**, cuando la fuente los publica con el propio
    listado. Viajan aparte de `datos` porque no son un campo canónico: no hay columna en el `jsonb`
    que los reciba. Una fuente que no los traiga —el listado paginado de OCDS, por ejemplo— devuelve
    la lista vacía, y para esas filas todo el camino de abajo se comporta como antes.
    """
    preparados: list[tuple[str, dict[str, Any], dict[str, Any], str, str, tuple[Any, ...]]] = []
    vistos: set[str] = set()

    for crudo in crudos:
        clave = definicion.adaptador.clave_natural(crudo)
        if not clave:
            contadores.errores += 1
            contadores.avisar("Se descartó un registro sin identificador utilizable.")
            continue
        if clave in vistos:
            continue  # La misma clave puede llegar por dos términos distintos.
        vistos.add(clave)

        datos, _ = aplicar(mapeos, crudo)
        # El payload se guarda sin las marcas internas del adaptador, para que sea fiel a la fuente.
        crudo_limpio = {
            clave_cruda: valor
            for clave_cruda, valor in crudo.items()
            if not clave_cruda.startswith("_")
        }
        preparados.append(
            (
                clave,
                datos,
                crudo_limpio,
                _texto_busqueda(datos),
                hash_contenido(datos),
                _items(crudo),
            )
        )

    return preparados


def _items(crudo: Mapping[str, Any]) -> tuple[Any, ...]:
    """Los ítems del producto que trae el crudo, ya reducidos a la forma que se guarda.

    Se pasan por `items_desde_crudos` —la misma función con la que se leen de la base— en vez de
    guardarlos tal cual: así lo que se escribe es exactamente lo que después se puede leer, y un
    ítem al que le falte el código se cae aquí y no en cada consulta del panel.
    """
    crudos = crudo.get("_items")
    if not isinstance(crudos, (list, tuple)):
        return ()
    return tuple(item.como_diccionario() for item in items_desde_crudos(crudos))


def _pendientes(mapeos: Sequence[MapeoCampo], crudos: Sequence[Mapping[str, Any]]) -> set[str]:
    """Claves que la fuente publica y el catálogo todavía no sabe interpretar."""
    pendientes: set[str] = set()
    for crudo in crudos:
        _, sin_mapear = aplicar(mapeos, crudo)
        pendientes.update(sin_mapear)
    return pendientes


def avisos_de_fallo(avisos: Sequence[str]) -> bool:
    """¿Los avisos indican que la fuente no respondió?"""
    return any("no respondió" in aviso.lower() for aviso in avisos)


def _fecha_utc(valor: Any) -> datetime | None:
    """Convierte a UTC la fecha canónica, que el mapeo deja como texto ISO local."""
    if valor is None or valor == "":
        return None
    return fecha_a_utc(str(valor))


async def _invalidar_cache(cache: Cache, codigo: str) -> None:
    """Sube las generaciones que dependen de esta fuente.

    Se suben dos contadores por motivos distintos:

    - el **propio de la fuente**, que invalida lo que solo depende de ella (su tablero de estado);
    - el **global**, que invalida las búsquedas, porque una consulta puede abarcar varias fuentes a
      la vez y no se puede saber cuáles toca cada página cacheada.

    No se borran claves: al incrementar la generación, todas las claves calculadas con la anterior
    dejan de encontrarse y expiran solas por su tiempo de vida.
    """
    await subir_generacion(cache, codigo)
    await subir_generacion(cache)
