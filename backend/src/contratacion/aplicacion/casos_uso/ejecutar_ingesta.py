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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from contratacion.aplicacion.generaciones import subir_generacion
from contratacion.aplicacion.mapeo import MapeoCampo, aplicar
from contratacion.aplicacion.puertos.cache import Cache
from contratacion.aplicacion.puertos.fuente import FuenteExterna
from contratacion.dominio.ingesta import (
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
) -> ResultadoCiclo:
    """Ejecuta un ciclo para una fuente y devuelve su resumen."""
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

    try:
        extraccion = await definicion.adaptador.extraer(desde, presupuesto)
        peticiones = extraccion.peticiones or presupuesto.usadas
        for aviso in extraccion.avisos:
            contadores.avisar(aviso)

        mapeos = await repositorio.obtener_mapeos(fuente_id)
        preparados = _mapear_todo(definicion, mapeos, extraccion.registros, contadores)

        huellas = await repositorio.huellas_existentes(
            fuente_id, [clave for clave, *_ in preparados]
        )
        for clave, datos, crudo_limpio, texto, huella in preparados:
            clasificacion = clasificar(huellas.get(clave), huella)
            if clasificacion is Clasificacion.IGUAL:
                contadores.iguales += 1
                continue

            registro_id = await repositorio.guardar_registro(
                fuente_id,
                clave=clave,
                datos=datos,
                crudo=crudo_limpio,
                texto_busqueda=texto,
                hash_contenido=huella,
                fecha_publicacion=_fecha_utc(datos.get("fecha_publicacion")),
            )
            if clasificacion is Clasificacion.NUEVO:
                contadores.nuevos += 1
            else:
                contadores.actualizados += 1
                await repositorio.agregar_historial(registro_id, datos=datos, hash_contenido=huella)

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

    # Los términos solo se dan por buscados si el ciclo terminó bien. Si fue parcial o falló, se
    # dejan pendientes a propósito: así el siguiente ciclo los vuelve a pedir desde la ventana
    # amplia y no queda un hueco en lo que se perdió.
    if definicion.terminos_buscados and estado == ESTADO_OK:
        marcados = await repositorio.marcar_terminos_ingestados(
            definicion.terminos_buscados, momento
        )
        registro.info("%s: %s términos marcados como buscados", definicion.codigo, marcados)

    if contadores.nuevos or contadores.actualizados:
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
    )


def _mapear_todo(
    definicion: DefinicionFuente,
    mapeos: Sequence[MapeoCampo],
    crudos: Sequence[Mapping[str, Any]],
    contadores: ContadoresCiclo,
) -> list[tuple[str, dict[str, Any], dict[str, Any], str, str]]:
    """Convierte cada payload crudo en lo que hay que guardar.

    Se separa de la escritura para poder calcular las huellas en lote y no consultar la base una vez
    por registro.
    """
    preparados: list[tuple[str, dict[str, Any], dict[str, Any], str, str]] = []
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
            (clave, datos, crudo_limpio, _texto_busqueda(datos), hash_contenido(datos))
        )

    return preparados


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
