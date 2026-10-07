"""Repositorio de ingesta: acceso a las tablas del plano compartido.

Se implementa como clase —y no como funciones sueltas— porque necesita mantener el motor y recibir
dependencias inyectadas, lo que permite probar el ciclo completo contra una base real sin tocar la
red.

Las tablas del plano compartido **no tienen RLS** a propósito: los datos del SERCOP son públicos e
idénticos para todos los negocios, así que se ingestan una sola vez. El aislamiento se aplica al
plano de negocio.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from contratacion.aplicacion.mapeo import MapeoCampo
from contratacion.dominio.cpc import codigos_de, items_desde_crudos, texto_de_cpc
from contratacion.dominio.plazos import instante_de_limite
from contratacion.infraestructura.adaptadores.salida.bd.claves import (
    clave_provincia,
    clave_tipo_proceso,
)

ESTADO_OK = "ok"
ESTADO_PARCIAL = "parcial"
ESTADO_ERROR = "error"

# Filas por sentencia en las escrituras de tanda. El tope real lo pone PostgreSQL —65.535
# parámetros por sentencia—, y con seis parámetros por fila 500 deja un margen de sobra: se elige
# por debajo para que el número no haya que recalcularlo cada vez que una fila gane una columna.
FILAS_POR_LOTE = 500


class RepositorioIngesta:
    """Operaciones de escritura y lectura de la ingesta."""

    def __init__(self, motor: AsyncEngine) -> None:
        self._motor = motor

    # ------------------------------------------------------------------ #
    # Configuración de fuentes y mapeos
    # ------------------------------------------------------------------ #
    async def asegurar_fuente(
        self,
        codigo: str,
        nombre: str,
        endpoint_base: str,
        *,
        intervalo_min: int,
        ventana_solape_ciclos: int,
        presupuesto_peticiones_ciclo: int,
    ) -> UUID:
        """Crea la fuente si no existe y devuelve su identificador."""
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    INSERT INTO fuente (
                        codigo, nombre, endpoint_base, intervalo_min,
                        ventana_solape_ciclos, presupuesto_peticiones_ciclo
                    )
                    VALUES (:codigo, :nombre, :endpoint, :intervalo, :solape, :presupuesto)
                    ON CONFLICT (codigo) DO UPDATE
                        SET nombre = EXCLUDED.nombre,
                            endpoint_base = EXCLUDED.endpoint_base,
                            actualizado_en = now()
                    RETURNING id
                    """
                ),
                {
                    "codigo": codigo,
                    "nombre": nombre,
                    "endpoint": endpoint_base,
                    "intervalo": intervalo_min,
                    "solape": ventana_solape_ciclos,
                    "presupuesto": presupuesto_peticiones_ciclo,
                },
            )
            return fila.scalar_one()

    async def obtener_mapeos(self, fuente_id: UUID) -> list[MapeoCampo]:
        """Reglas de mapeo activas, ordenadas para que el resultado sea reproducible."""
        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                text(
                    """
                    SELECT clave_cruda, campo_canonico, tipo_dato, transformacion, requerido
                    FROM campo_mapeo
                    WHERE fuente_id = :fuente AND activo
                    ORDER BY orden, clave_cruda
                    """
                ),
                {"fuente": str(fuente_id)},
            )
            return [
                MapeoCampo(
                    clave_cruda=fila.clave_cruda,
                    campo_canonico=fila.campo_canonico,
                    tipo_dato=fila.tipo_dato,
                    transformacion=fila.transformacion or {},
                    requerido=fila.requerido,
                )
                for fila in filas
            ]

    async def registrar_pendientes(
        self, fuente_id: UUID, claves: Sequence[str], ejemplos: dict[str, str]
    ) -> None:
        """Anota las claves sin mapeo, acumulando cuántas veces se han visto.

        No se crea una fila por registro: se acumula por clave, porque lo que interesa es saber que
        la fuente publicó algo nuevo, no cuántas veces.
        """
        if not claves:
            return
        async with self._motor.begin() as conexion:
            for clave in claves:
                await conexion.execute(
                    text(
                        """
                        INSERT INTO campo_pendiente (fuente_id, clave_cruda, valor_ejemplo)
                        VALUES (:fuente, :clave, :ejemplo)
                        ON CONFLICT (fuente_id, clave_cruda) DO UPDATE
                            SET veces_visto = campo_pendiente.veces_visto + 1,
                                ultimo_detectado_en = now(),
                                valor_ejemplo = COALESCE(
                                    campo_pendiente.valor_ejemplo, EXCLUDED.valor_ejemplo
                                )
                        """
                    ),
                    {
                        "fuente": str(fuente_id),
                        "clave": clave,
                        "ejemplo": ejemplos.get(clave, "")[:500],
                    },
                )

    async def asegurar_mapeos(self, fuente_id: UUID, mapeos: Sequence[Mapping[str, Any]]) -> int:
        """Siembra las reglas de mapeo por defecto la primera vez.

        No sobrescribe nada: `DO NOTHING` deja intacto lo que un administrador haya ajustado. El
        catálogo por defecto es un punto de partida, no la verdad: a partir de ahí manda la tabla.
        """
        if not mapeos:
            return 0
        insertados = 0
        async with self._motor.begin() as conexion:
            for mapeo in mapeos:
                resultado = await conexion.execute(
                    text(
                        """
                        INSERT INTO campo_mapeo (
                            fuente_id, clave_cruda, campo_canonico, etiqueta,
                            tipo_dato, transformacion, requerido, orden, ancho_excel
                        )
                        VALUES (
                            :fuente, :clave, :canonico, :etiqueta,
                            :tipo, CAST(:transformacion AS jsonb), :requerido, :orden, :ancho
                        )
                        ON CONFLICT (fuente_id, clave_cruda) DO NOTHING
                        """
                    ),
                    {
                        "fuente": str(fuente_id),
                        "clave": mapeo["clave_cruda"],
                        "canonico": mapeo["campo_canonico"],
                        "etiqueta": mapeo["etiqueta"],
                        "tipo": mapeo["tipo_dato"],
                        "transformacion": json.dumps(
                            mapeo.get("transformacion", {}), ensure_ascii=False
                        ),
                        "requerido": bool(mapeo.get("requerido", False)),
                        "orden": int(mapeo.get("orden", 0)),
                        "ancho": mapeo.get("ancho_excel"),
                    },
                )
                insertados += resultado.rowcount or 0

            # Un campo que ya tiene mapeo deja de estar pendiente, aunque su fila se creara antes de
            # que el mapeo existiera. Sin esto, `campo_pendiente` acumula avisos que ya no
            # significan nada: quedaron seis claves marcadas como «sin mapear» que llevaban ciclos
            # enteros guardándose bien, porque nadie cerraba la fila al añadir su regla. Y el aviso
            # de la tabla es justo el mecanismo que dice «la fuente ha cambiado»: si grita cuando no
            # ha pasado nada, el día que pase de verdad nadie lo mirará.
            await conexion.execute(
                text(
                    """
                    UPDATE campo_pendiente p
                       SET resuelto_en = now(),
                           mapeo_id = m.id
                      FROM campo_mapeo m
                     WHERE m.fuente_id = p.fuente_id
                       AND m.clave_cruda = p.clave_cruda
                       AND p.resuelto_en IS NULL
                    """
                )
            )
        return insertados

    async def obtener_pendientes_de_ingesta(self, limite: int) -> list[dict[str, Any]]:
        """Términos que toca buscar en este ciclo, en orden de urgencia.

        El orden es la pieza que evita que un término se quede sin ingestar para siempre:

        1. primero los que **nunca** se han buscado (`ultima_ingesta_en` nulo);
        2. después los que llevan más tiempo sin buscarse;
        3. la prioridad que fije un administrador solo desempata.

        Poner la prioridad por delante del tiempo sería un error: un término urgente y otro
        tranquilo acabarían compitiendo, y el segundo no se ingestaría nunca. El orden anterior
        tenía ese defecto y además otro peor: `ultima_ingesta_en` no se actualizaba en ninguna
        parte, así que todos los términos lo tenían nulo y el `LIMIT` elegía siempre los mismos por
        fecha de creación. **Todo término añadido después del vigésimo no se ingestaba jamás.**

        El primer desempate es el número de negocios suscritos, para que un término que pide mucha
        gente no quede detrás de uno que solo interesa a un cliente.
        """
        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                text(
                    """
                    SELECT id, texto, texto_normalizado, prioridad, ultima_ingesta_en,
                           conteo_suscriptores(id) AS suscriptores
                    FROM termino
                    WHERE activo
                    ORDER BY ultima_ingesta_en NULLS FIRST,
                             prioridad DESC,
                             conteo_suscriptores(id) DESC,
                             creado_en
                    LIMIT :limite
                    """
                ),
                {"limite": limite},
            )
            return [
                {
                    "termino_id": fila.id,
                    "texto": fila.texto,
                    "texto_normalizado": fila.texto_normalizado,
                    "prioridad": fila.prioridad,
                    "ultima_ingesta_en": fila.ultima_ingesta_en,
                    "suscriptores": fila.suscriptores,
                }
                for fila in filas
            ]

    async def marcar_terminos_ingestados(self, terminos: Sequence[UUID], momento: datetime) -> int:
        """Deja constancia de que estos términos se acaban de buscar.

        Sin esta marca, `ultima_ingesta_en` se queda nulo para siempre, la cola degenera en «los
        primeros por fecha de creación» y la ventana de búsqueda se mantiene ancha indefinidamente.
        Es la pieza que hace que el orden de la cola rote de verdad.
        """
        if not terminos:
            return 0
        async with self._motor.begin() as conexion:
            resultado = await conexion.execute(
                text("UPDATE termino SET ultima_ingesta_en = :momento WHERE id = ANY(:terminos)"),
                {"momento": momento, "terminos": list(terminos)},
            )
        return int(resultado.rowcount or 0)

    # ------------------------------------------------------------------ #
    # Sincronizaciones
    # ------------------------------------------------------------------ #
    async def ultima_sincronizacion_ok(self, fuente_id: UUID) -> datetime | None:
        """Marca de agua: hasta dónde llegó el último ciclo completo.

        Solo cuentan los ciclos `ok` o `parcial`: si un ciclo falló, la ventana no avanza, para que
        la siguiente ejecución vuelva a cubrir el hueco.
        """
        async with self._motor.connect() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    SELECT watermark_fecha
                    FROM sincronizacion
                    WHERE fuente_id = :fuente AND estado IN ('ok', 'parcial')
                    ORDER BY iniciada_en DESC
                    LIMIT 1
                    """
                ),
                {"fuente": str(fuente_id)},
            )
            return fila.scalar_one_or_none()

    async def iniciar_sincronizacion(self, fuente_id: UUID) -> UUID:
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text("INSERT INTO sincronizacion (fuente_id) VALUES (:fuente) RETURNING id"),
                {"fuente": str(fuente_id)},
            )
            return fila.scalar_one()

    async def cerrar_sincronizacion(
        self,
        sincronizacion_id: UUID,
        *,
        estado: str,
        peticiones: int,
        nuevos: int,
        actualizados: int,
        errores: int,
        avisos: Sequence[str],
        watermark: datetime | None,
    ) -> None:
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE sincronizacion
                       SET terminada_en = now(),
                           estado = :estado,
                           peticiones = :peticiones,
                           nuevos = :nuevos,
                           actualizados = :actualizados,
                           errores = :errores,
                           avisos = CAST(:avisos AS jsonb),
                           watermark_fecha = :watermark
                     WHERE id = :id
                    """
                ),
                {
                    "id": str(sincronizacion_id),
                    "estado": estado,
                    "peticiones": peticiones,
                    "nuevos": nuevos,
                    "actualizados": actualizados,
                    "errores": errores,
                    "avisos": json.dumps(list(avisos), ensure_ascii=False),
                    "watermark": watermark,
                },
            )

    # ------------------------------------------------------------------ #
    # Registros
    # ------------------------------------------------------------------ #
    async def huellas_existentes(self, fuente_id: UUID, claves: Sequence[str]) -> dict[str, str]:
        """Huella de contenido de los registros ya conocidos, por clave natural."""
        if not claves:
            return {}
        consulta = text(
            "SELECT clave_natural, hash_contenido FROM registro "
            "WHERE fuente_id = :fuente AND clave_natural IN :claves"
        ).bindparams(bindparam("claves", expanding=True))

        async with self._motor.connect() as conexion:
            filas = await conexion.execute(
                consulta, {"fuente": str(fuente_id), "claves": list(claves)}
            )
            return {fila.clave_natural: fila.hash_contenido for fila in filas}

    # ------------------------------------------------------------------ #
    # Ítems con CPC (detalle de la necesidad)
    # ------------------------------------------------------------------ #
    async def registros_sin_items(
        self, fuentes: Sequence[str], limite: int
    ) -> list[dict[str, Any]]:
        """Registros cuya ficha todavía no se ha leído, de las fuentes que publican detalle.

        Se filtra por código de fuente y no se recorre todo: solo algunas fuentes tienen ficha, y
        las demás llenarían la tanda con registros que nunca se podrán completar —petición perdida
        por ciclo—. El orden es del más reciente al más antiguo porque es el orden en el que el
        panel los muestra: lo que alguien acaba de publicar es lo que más se consulta.

        Los que ya se intentaron y **no tienen ítems** no aparecen: `items_recogidos_en` queda
        marcado aunque la tabla venga vacía, que es un caso real.
        """
        if not fuentes or limite <= 0:
            return []
        async with self._motor.connect() as conexion:
            filas = (
                (
                    await conexion.execute(
                        text(
                            """
                            SELECT r.id, r.clave_natural, f.codigo AS fuente,
                                   r.datos ->> 'enlace' AS enlace
                            FROM registro r
                            JOIN fuente f ON f.id = r.fuente_id
                            WHERE f.codigo = ANY(:fuentes)
                              AND r.items_recogidos_en IS NULL
                            ORDER BY r.primera_vez_visto DESC, r.id
                            LIMIT :limite
                            """
                        ),
                        {"fuentes": list(fuentes), "limite": limite},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(fila) for fila in filas]

    async def contar_sin_items(self, fuentes: Sequence[str]) -> int:
        """Registros de estas fuentes a los que todavía no se les ha leído la ficha.

        Se apoya en el índice parcial de pendientes: sin él, contar sería recorrer la tabla entera
        en cada tanda para encontrar un puñado de filas.
        """
        if not fuentes:
            return 0
        async with self._motor.connect() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    SELECT count(*)
                    FROM registro r
                    JOIN fuente f ON f.id = r.fuente_id
                    WHERE f.codigo = ANY(:fuentes)
                      AND r.items_recogidos_en IS NULL
                    """
                ),
                {"fuentes": list(fuentes)},
            )
            return int(fila.scalar_one())

    async def guardar_items(
        self,
        registro_id: UUID,
        *,
        items: Sequence[Mapping[str, Any]],
        cpc_busqueda: str,
        cpc_codigos: Sequence[str],
    ) -> None:
        """Guarda los ítems de un registro y lo marca como leído.

        El texto de búsqueda y los códigos se calculan en el dominio y llegan ya hechos: aquí solo
        se escriben. Dejarlos a la base —derivarlos del `jsonb` con una expresión SQL— ataría la
        forma del texto a PostgreSQL y no se podría probar sin base.

        `items_recogidos_en` se marca **siempre**, aunque la lista venga vacía. Es lo que distingue
        «esta necesidad no publica detalle» de «todavía no se ha pedido», y equivocarse dejaría a
        las necesidades sin detalle reintentándose en cada tanda para siempre.
        """
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text(
                    """
                    UPDATE registro
                       SET items = CAST(:items AS jsonb),
                           cpc_busqueda = :texto,
                           cpc_codigos = :codigos,
                           items_recogidos_en = now()
                     WHERE id = :id
                    """
                ),
                {
                    "id": str(registro_id),
                    "items": json.dumps(list(items), ensure_ascii=False, default=str),
                    "texto": cpc_busqueda,
                    "codigos": list(cpc_codigos),
                },
            )

    async def guardar_registro(
        self,
        fuente_id: UUID,
        *,
        clave: str,
        datos: dict[str, Any],
        crudo: dict[str, Any],
        texto_busqueda: str,
        hash_contenido: str,
        fecha_publicacion: datetime | None,
    ) -> UUID:
        """Inserta o actualiza el registro y devuelve su identificador.

        El conflicto se resuelve por clave natural: es lo que hace la ingesta idempotente. Se guarda
        el payload íntegro en `crudo` para no perder ningún campo que no sepamos mapear todavía.

        `ultima_vez_visto` solo se actualiza cuando el contenido cambia. Es deliberado: marcar las
        ~1.700 filas de NCO en cada ciclo, 96 veces al día, sería un desperdicio de escrituras sin
        aportar nada.

        **El detalle ya leído no se toca.** Ni se invalida ni se vuelve a pedir: la ficha se lee una
        vez, cuando el registro entra, y a partir de ahí solo se actualizan los campos del listado.
        El motivo es la cuota: cada ficha es una petición a un origen que limita la tasa, y volver a
        leer las de todo lo que cambia cada ciclo gastaría el presupuesto en fichas ya conocidas.
        Lo que se paga a cambio es que el CPC de una necesidad que cambió de estado se queda como
        estaba; quien necesite refrescarlo tiene `scripts/rellenar_items_cpc.py` para forzarlo a
        mano. Se decidió así a petición explícita: el histórico se completa, no se repasa.
        """
        async with self._motor.begin() as conexion:
            fila = await conexion.execute(
                text(
                    """
                    INSERT INTO registro (
                        fuente_id, clave_natural, datos, crudo, texto_busqueda, hash_contenido,
                        fecha_publicacion, provincia, tipo_proceso, plazo_proformas_en
                    )
                    VALUES (
                        :fuente, :clave, CAST(:datos AS jsonb), CAST(:crudo AS jsonb),
                        :texto, :hash, CAST(:fecha AS timestamptz), :provincia, :tipo_proceso,
                        CAST(:plazo AS timestamptz)
                    )
                    ON CONFLICT (fuente_id, clave_natural) DO UPDATE
                        SET datos = EXCLUDED.datos,
                            crudo = EXCLUDED.crudo,
                            texto_busqueda = EXCLUDED.texto_busqueda,
                            hash_contenido = EXCLUDED.hash_contenido,
                            fecha_publicacion = EXCLUDED.fecha_publicacion,
                            provincia = EXCLUDED.provincia,
                            tipo_proceso = EXCLUDED.tipo_proceso,
                            plazo_proformas_en = EXCLUDED.plazo_proformas_en,
                            ultima_vez_visto = now()
                    RETURNING id
                    """
                ),
                {
                    "fuente": str(fuente_id),
                    "clave": clave,
                    "datos": json.dumps(datos, ensure_ascii=False, default=str),
                    "crudo": json.dumps(crudo, ensure_ascii=False, default=str),
                    "texto": texto_busqueda,
                    "hash": hash_contenido,
                    "fecha": fecha_publicacion,
                    # Las claves de filtro se calculan aquí, al escribir, y no al consultar: son las
                    # mismas que usa el filtro al leer la petición, porque salen de las mismas dos
                    # funciones. El porqué, en `bd/claves.py`.
                    "provincia": clave_provincia(datos.get("provincia")),
                    "tipo_proceso": clave_tipo_proceso(datos.get("tipo_proceso")),
                    # El plazo sale a columna por la misma razón que las claves de arriba: la purga
                    # y el filtro «solo con plazo» necesitan un rango sobre un índice, no un `CAST`
                    # del texto del JSON fila a fila.
                    "plazo": instante_de_limite(datos.get("fecha_limite_proformas")),
                },
            )
            return fila.scalar_one()

    async def agregar_historial(
        self, registro_id: UUID, *, datos: dict[str, Any], hash_contenido: str
    ) -> None:
        """Añade una versión al histórico. Solo se llama cuando el contenido cambió.

        Esta tabla es el activo comercial del producto: la fuente no publica histórico de
        necesidades, así que lo que no se guarde aquí, se pierde.
        """
        async with self._motor.begin() as conexion:
            await conexion.execute(
                text(
                    """
                    INSERT INTO registro_historial (registro_id, datos, hash_contenido)
                    VALUES (:registro, CAST(:datos AS jsonb), :hash)
                    """
                ),
                {
                    "registro": str(registro_id),
                    "datos": json.dumps(datos, ensure_ascii=False, default=str),
                    "hash": hash_contenido,
                },
            )

    # ------------------------------------------------------------------ #
    # Registros — escritura por lotes
    # ------------------------------------------------------------------ #
    # El ciclo escribe ~1.700 filas por vuelta. Hacerlo fila a fila son tres viajes de ida y vuelta
    # a la base por registro; con una base a 86 ms, eso son casi nueve minutos por ciclo, que es con
    # diferencia lo más caro del proceso y lo que lo empujaba a pisar el intervalo siguiente. Las
    # cuatro operaciones de abajo resuelven su tanda en **una sola sentencia** cada una. No es una
    # comodidad de estilo: es lo que hace que el ciclo quepa entre dos vueltas.
    async def guardar_registros(
        self, fuente_id: UUID, filas: Sequence[Mapping[str, Any]]
    ) -> dict[str, UUID]:
        """Inserta o actualiza una tanda entera y devuelve `clave natural → id`.

        El conflicto se resuelve por clave natural, igual que en `guardar_registro`: es lo que hace
        la ingesta idempotente y lo que permite volver a pasar el mismo listado sin duplicar nada.
        Los identificadores devueltos hacen falta para el histórico, que se escribe por separado.

        Reescribir una fila la devuelve a «vigente», y esa es la otra mitad de
        `marcar_fuera_de_listado`: aquella cierra lo que dejó de aparecer, esta reabre lo que vuelve
        a aparecer. Sin esta mitad, un cierre equivocado —una lectura del listado truncada por la
        fuente, que llegue sin error y sin marca de parcial— sería definitivo, y la necesidad
        quedaría cerrada para siempre: un dato de negocio falso y sin remedio.

        La tanda se trocea en bloques, dentro de la **misma** transacción. No es por rendimiento
        —una sola sentencia de 1.700 filas va bien— sino porque PostgreSQL admite como mucho 65.535
        parámetros por sentencia: con once por fila, una fuente que devolviera veinte mil registros
        reventaría con un error que no dice nada de la causa. El troceo deja el techo fuera de
        alcance sin cambiar el resultado, que sigue siendo todo o nada.

        Los **ítems del producto** se escriben aquí, en la misma sentencia, cuando la fila los trae.
        Van con una guarda que no es un detalle: una lista vacía **no borra** lo que ya hubiera. El
        listado paginado de OCDS y la vigilancia del listado escriben las mismas filas sin desglose
        —no lo publican—, y sin la guarda cada vuelta de esas borraría los ítems que la importación
        mensual sí había guardado. Lo mismo con `cpc_busqueda`, `cpc_codigos` y la marca de leído.
        """
        if not filas:
            return {}
        ids: dict[str, UUID] = {}
        async with self._motor.begin() as conexion:
            for inicio in range(0, len(filas), FILAS_POR_LOTE):
                tanda = filas[inicio : inicio + FILAS_POR_LOTE]
                parametros: dict[str, Any] = {"fuente": str(fuente_id)}
                for indice, fila in enumerate(tanda):
                    parametros[f"clave_{indice}"] = fila["clave"]
                    parametros[f"datos_{indice}"] = json.dumps(
                        fila["datos"], ensure_ascii=False, default=str
                    )
                    parametros[f"crudo_{indice}"] = json.dumps(
                        fila["crudo"], ensure_ascii=False, default=str
                    )
                    parametros[f"texto_{indice}"] = fila["texto"]
                    parametros[f"hash_{indice}"] = fila["hash"]
                    parametros[f"fecha_{indice}"] = fila["fecha"]
                    # Las claves de filtro se calculan aquí, al escribir, y no al consultar. Son las
                    # mismas que usa el filtro al leer la petición porque salen de las mismas dos
                    # funciones (`bd/claves.py`), y eso es lo que permite que la consulta sea una
                    # igualdad contra una columna en lugar de una expresión sobre el `jsonb`.
                    parametros[f"provincia_{indice}"] = clave_provincia(
                        fila["datos"].get("provincia")
                    )
                    parametros[f"tipo_{indice}"] = clave_tipo_proceso(
                        fila["datos"].get("tipo_proceso")
                    )
                    parametros[f"plazo_{indice}"] = instante_de_limite(
                        fila["datos"].get("fecha_limite_proformas")
                    )
                    parametros[f"items_{indice}"] = json.dumps(
                        list(fila.get("items") or []), ensure_ascii=False, default=str
                    )
                    # El texto de búsqueda del CPC y sus códigos salen de los **mismos** ítems que
                    # se guardan, y se calculan con las funciones del dominio que ya usa la lectura
                    # de fichas: es lo que hace que el buscador por clasificación encuentre una
                    # oferta exactamente igual que encuentra una ínfima.
                    items = items_desde_crudos(fila.get("items") or ())
                    parametros[f"cpc_{indice}"] = texto_de_cpc(items)
                    parametros[f"codigos_{indice}"] = list(codigos_de(items))
                # Los parámetros se nombran por posición (`:clave_0`, `:clave_1`…) porque cuántas
                # filas trae una tanda lo decide la fuente en cada ciclo, y `text()` no admite un
                # número variable de parámetros.
                valores = ", ".join(
                    f"(:fuente, :clave_{i}, CAST(:datos_{i} AS jsonb), CAST(:crudo_{i} AS jsonb), "
                    f":texto_{i}, :hash_{i}, CAST(:fecha_{i} AS timestamptz), "
                    f":provincia_{i}, :tipo_{i}, CAST(:plazo_{i} AS timestamptz), "
                    f"CAST(:items_{i} AS jsonb), :cpc_{i}, CAST(:codigos_{i} AS text[]), "
                    f"CASE WHEN jsonb_array_length(CAST(:items_{i} AS jsonb)) > 0 THEN now() END)"
                    for i in range(len(tanda))
                )
                filas_escritas = await conexion.execute(
                    text(
                        f"""
                        INSERT INTO registro (
                            fuente_id, clave_natural, datos, crudo, texto_busqueda,
                            hash_contenido, fecha_publicacion, provincia, tipo_proceso,
                            plazo_proformas_en, items, cpc_busqueda, cpc_codigos,
                            items_recogidos_en
                        )
                        VALUES {valores}
                        ON CONFLICT (fuente_id, clave_natural) DO UPDATE
                            SET datos = EXCLUDED.datos,
                                crudo = EXCLUDED.crudo,
                                texto_busqueda = EXCLUDED.texto_busqueda,
                                hash_contenido = EXCLUDED.hash_contenido,
                                fecha_publicacion = EXCLUDED.fecha_publicacion,
                                provincia = EXCLUDED.provincia,
                                tipo_proceso = EXCLUDED.tipo_proceso,
                                plazo_proformas_en = EXCLUDED.plazo_proformas_en,
                                items = CASE
                                    WHEN jsonb_array_length(EXCLUDED.items) > 0
                                    THEN EXCLUDED.items
                                    ELSE registro.items
                                END,
                                cpc_busqueda = CASE
                                    WHEN EXCLUDED.cpc_busqueda <> '' THEN EXCLUDED.cpc_busqueda
                                    ELSE registro.cpc_busqueda
                                END,
                                cpc_codigos = CASE
                                    WHEN coalesce(array_length(EXCLUDED.cpc_codigos, 1), 0) > 0
                                    THEN EXCLUDED.cpc_codigos
                                    ELSE registro.cpc_codigos
                                END,
                                items_recogidos_en = coalesce(
                                    EXCLUDED.items_recogidos_en, registro.items_recogidos_en
                                ),
                                es_vigente = true,
                                ultima_vez_visto = now()
                        RETURNING clave_natural, id
                        """
                    ),
                    parametros,
                )
                ids.update({fila.clave_natural: fila.id for fila in filas_escritas})
        return ids

    async def refrescar_volatiles(
        self, fuente_id: UUID, refrescos: Sequence[Mapping[str, Any]]
    ) -> int:
        """Actualiza en bloque los campos que la fuente reescribe sola, sin tocar la huella.

        Es el caso del token del enlace de la ficha, que se regenera en **cada** listado: eso deja
        la mayoría de las filas «iguales» en contenido y, aun así, con un enlace que envejece hasta
        dejar de abrir la ficha. Se escribe solo ese campo y solo en las filas que lo cambiaron, en
        lugar de reescribir el registro entero —lo que además metería en el histórico versiones que
        no lo son—.

        Se hace con una fusión de JSON (`datos || volatiles`) y no campo a campo: los volátiles son
        campos canónicos que viven dentro de `datos`, y enumerarlos aquí volvería a haber dos listas
        de campos que mantener en sincronía.
        """
        if not refrescos:
            return 0
        pares = [{"clave": fila["clave"], "volatiles": fila["volatiles"]} for fila in refrescos]
        async with self._motor.begin() as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE registro AS r
                       SET datos = r.datos || v.volatiles
                      FROM jsonb_to_recordset(CAST(:pares AS jsonb))
                           AS v(clave text, volatiles jsonb)
                     WHERE r.fuente_id = :fuente
                       AND r.clave_natural = v.clave
                    """
                ),
                {
                    "fuente": str(fuente_id),
                    "pares": json.dumps(pares, ensure_ascii=False, default=str),
                },
            )
        return int(resultado.rowcount or 0)

    async def agregar_historial_en_lote(self, filas: Sequence[Mapping[str, Any]]) -> int:
        """Añade varias versiones al histórico de una vez.

        Solo se llama con los registros cuyo contenido **cambió**. Esta tabla es el activo comercial
        del producto —la fuente no publica histórico de necesidades, así que lo que no se guarde
        aquí se pierde—, y meter en ella los que siguen iguales la convertiría en un registro de
        visitas: dejaría de ser «las versiones que tuvo» para ser «las veces que se miró».
        """
        if not filas:
            return 0
        registradas = 0
        async with self._motor.begin() as conexion:
            for inicio in range(0, len(filas), FILAS_POR_LOTE):
                tanda = filas[inicio : inicio + FILAS_POR_LOTE]
                parametros: dict[str, Any] = {}
                for indice, fila in enumerate(tanda):
                    parametros[f"registro_{indice}"] = str(fila["registro_id"])
                    parametros[f"datos_{indice}"] = json.dumps(
                        fila["datos"], ensure_ascii=False, default=str
                    )
                    parametros[f"hash_{indice}"] = fila["hash"]
                valores = ", ".join(
                    f"(:registro_{i}, CAST(:datos_{i} AS jsonb), :hash_{i})"
                    for i in range(len(tanda))
                )
                resultado = await conexion.execute(
                    text(
                        f"""
                        INSERT INTO registro_historial (registro_id, datos, hash_contenido)
                        VALUES {valores}
                        """
                    ),
                    parametros,
                )
                registradas += int(resultado.rowcount or 0)
        return registradas

    async def marcar_fuera_de_listado(self, fuente_id: UUID, claves: Sequence[str]) -> int:
        """Deja la vigencia **igual al listado**: cierra lo que se fue y reabre lo que vuelve.

        La fuente solo publica lo vigente y no guarda histórico, así que «ya no aparece» es la única
        señal de que una necesidad se cerró, y es información de negocio: distingue la que todavía
        admite proformas de la que ya no. Por eso solo se llama con listados **completos**:
        aplicarlo a una fuente que se consulta por partes daría por cerrado lo que simplemente no se
        llegó a mirar.

        Las dos direcciones van en la **misma sentencia**, y no es una optimización: es lo que evita
        que un cierre equivocado sea definitivo. La vuelta de una necesidad no se puede detectar al
        escribirla —si vuelve con el mismo contenido, la clasificación la da por «igual» y no se
        escribe—, así que reabrir tiene que ser parte de la reconciliación y no de la escritura. Y
        con `IS DISTINCT FROM` solo se tocan las filas cuyo estado cambia de verdad: las ~1.700 que
        siguen iguales no se reescriben en cada vuelta.

        Devuelve cuántas se **cerraron**, que es el dato de negocio; las reabiertas no se cuentan
        porque no son novedad, son una corrección.

        Con la lista vacía no se cierra nada, y es una decisión, no un descuido: una lista vacía
        significa «no vi ningún registro», y de ahí no se sigue que no quede ninguno vivo. Cerrar el
        catálogo entero por no haber leído nada sería justo lo contrario de lo que se sabe.
        """
        if not claves:
            return 0
        async with self._motor.begin() as conexion:
            resultado = await conexion.execute(
                text(
                    """
                    UPDATE registro
                       SET es_vigente = (clave_natural = ANY(:claves))
                     WHERE fuente_id = :fuente
                       AND es_vigente IS DISTINCT FROM (clave_natural = ANY(:claves))
                    RETURNING es_vigente
                    """
                ),
                {"fuente": str(fuente_id), "claves": list(claves)},
            )
            return sum(1 for fila in resultado if not fila.es_vigente)
