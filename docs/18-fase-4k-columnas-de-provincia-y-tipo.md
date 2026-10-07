# Fase 4.11 — Provincia y tipo de proceso como columnas propias

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

## 1. Objetivo

**Que las estadísticas del panel dejen de tardar medio minuto.** La fase 4.9 midió de dónde venía la
lentitud y arregló el camino de la tabla —el orden de la página, la búsqueda del NIC y el clic del
mapa—, pero dejó dos cosas sin resolver porque exigían cambiar el esquema: el **reparto por provincia**
(21,4 s) y el **reparto por tipo de proceso** (15,1 s). Con ellos, `estadisticas` tardaba entre 37 y
47 s.

La causa está medida y no admite discusión: para contar hay que leer todas las filas, así que lo único
que los hacía lentos era **qué** leían. La expresión que se agrupa cuelga de `datos`, un `jsonb` de
unos 2 KB por fila que vive comprimido en `TOAST`: recorrer el histórico es descomprimir 180 MB, fila
a fila. Y no hay índice que lo arregle —la fase 4.9 lo intentó con un índice sobre la expresión y el
planificador lo usó visitando el montón fila a fila, once segundos **peor**—.

La salida es la que ya se había tomado antes con `texto_busqueda`, `cpc_busqueda`, `items` y
`fecha_publicacion`: **sacar el valor a una columna en el momento de escribir**.

## 2. Alcance

**Incluido**

- Dos columnas nuevas en `registro` (`provincia` y `tipo_proceso`) con la clave ya normalizada, y el
  relleno de las 110.743 filas del histórico.
- Las dos funciones que calculan esas claves, en un solo sitio (`bd/claves.py`), usadas **por la
  ingesta al escribir y por las consultas al filtrar**. Es la garantía de que las dos coincidan.
- El filtro por provincia y por tipo de proceso pasa a ser una igualdad contra una columna.
- Los dos repartos pasan a agrupar por la columna.
- Dos índices cubridores y la retirada de los dos índices de expresión que quedaban sin uso.
- El relleno de las filas nuevas en los dos caminos de escritura de la ingesta.

**Excluido (deliberadamente)**

- Sacar a columna `estado`, `tipo_necesidad` y `entidad`, que es lo que sigue haciendo lento el
  catálogo de los desplegables (8,9 s). Cada columna nueva cuesta un relleno que reescribe la tabla.
- Compactar la tabla. Hace falta y está pedido, pero **no cabía**: ver § 8.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| Las claves, la normalización y su porqué, en un solo sitio | `salida/bd/claves.py` (`clave_provincia`, `clave_tipo_proceso`) |
| Columnas, relleno por tandas, `NOT NULL`, índices y `ANALYZE` | `alembic/versions/0017_provincia_y_tipo_proceso.py` |
| Índices reconstruidos para que **cubran** lo que la consulta necesita | `alembic/versions/0018_indices_cubridores.py` |
| Retirada del GIN del `jsonb` completo, que nadie usaba | `alembic/versions/0019_retirar_gin_datos.py` |
| Las claves se escriben al guardar, en los dos caminos | `salida/bd/ingesta.py` (`guardar_registro`, `guardar_registros`) |
| El filtro y los dos repartos leen la columna | `salida/bd/consultas.py` (`_condiciones`, `estadisticas`) |
| Nueve pruebas: claves, relleno e invarianza entre escribir y comparar | `pruebas/unidad/test_consultas_bd.py` |

## 4. Decisiones tomadas y justificación

### 4.1 Una sola función para las dos mitades

La clave se escribe al guardar (ingesta) y se compara al buscar (consulta). Si cada mitad tuviera su
regla —una que quita tildes y otra que se olvida, una que recorta el cantón y otra que no— el síntoma
sería el peor posible: unas filas se encuentran y otras no, sin ningún error y sin ninguna fila de
más. Por eso las dos llaman a la **misma función**, y hay una prueba que comprueba que el resultado
que pide el filtro es el que escribe la ingesta.

Lo que se guarda:

- **`provincia`**: la provincia sin el cantón, en minúsculas y sin tildes (`CAÑAR` → `canar`). El
  cantón se descarta porque es lo que se elige en el panel y agrupar por «provincia - cantón»
  partiría Pichincha en decenas de barras.
- **`tipo_proceso`**: el texto publicado, sin espacios de sobra. Aquí **no** se normalizan tildes ni
  mayúsculas, a propósito: la clave viaja de vuelta —el reparto devuelve «Subasta Inversa
  Electrónica» y al pulsar esa barra ese texto se envía como filtro— y tres normalizaciones distintas
  acabarían en barras que no encuentran nada.

### 4.2 Las columnas son `NOT NULL` con valor por defecto

Cuando la fuente no publica el dato, la clave es «sin provincia» o «sin clasificar», nunca nulo. No es
un adorno: garantiza que **ninguna fila queda fuera de un filtro** porque alguien olvidara escribir la
columna. Una fila sin clave no aparece en ninguna búsqueda por provincia y nadie la echa de menos: es
el fallo más caro de detectar.

De paso, arregla una barra que mentía: el reparto contaba las filas «sin clasificar» —12.743 hoy— pero
el filtro comparaba contra el texto crudo de `datos`, que en ellas está vacío. Pulsar esa barra
devolvía **cero**. Ahora devuelve exactamente las 12.743.

### 4.3 El relleno se hace **antes** de poner el valor por defecto

Las columnas se añaden sin `DEFAULT` y se rellenan por tandas; el `DEFAULT` y el `NOT NULL` van al
final. El orden no es arbitrario: en PostgreSQL 11+ un `ADD COLUMN … DEFAULT` no reescribe la tabla
—el valor se resuelve al leer—, así que las filas existentes **parecerían** rellenas, el `UPDATE` no
encontraría nada y la migración terminaría en segundos sin haber rellenado nada.

Todo el relleno va dentro de la transacción de la migración: o quedan las 110.743 filas con su clave,
o no queda ninguna.

### 4.4 Un índice tiene que **cubrir** todo lo que la consulta necesita

Aquí está el error que hubo que corregir, y merece quedar escrito porque se repite solo. La 0017 creó
los índices como `(clave, fecha_publicacion DESC NULLS LAST, id)`. Con eso, el reparto **sin tocar
`fuente`** funciona: medido, `Index Only Scan` y **686 ms**. Pero las consultas reales no lo usaban:

| Consulta | Plan | Tiempo |
|---|---|---|
| `SELECT provincia, count(*) FROM registro GROUP BY 1` | `Index Only Scan` | **686 ms** |
| la misma, con `WHERE fuente_id = ANY(…)` | `Parallel Seq Scan` | 12,8 s |
| la real, uniendo con `fuente` para el permiso | `Index Scan using ix_registro_fecha` | 19,4 s |

La diferencia es **una columna**: `fuente_id`. Un escaneo «solo índice» exige que **todas** las
columnas que la consulta necesita estén en el índice, y estas consultas siempre lo necesitan porque el
permiso de lectura por fuente se aplica uniendo con `fuente`. Sin él, el planificador vuelve a leer
—y descomprimir— el `jsonb` de cada fila, que es justo lo que se venía a evitar.

Y había un efecto peor que no se ve en el tiempo del reparto: **el índice nuevo empeoraba el clic del
mapa**. El `count(*)` de una provincia pasó de ~400 ms a **9,5 s**, porque el planificador lo resolvía
con un `Bitmap Heap Scan` —29.707 visitas al montón, cada una descomprimiendo un `jsonb`— que antes no
podía elegir. Un índice que no cubre todo lo necesario no es neutro: es una trampa. La 0018 los
reconstruye con `fuente_id` **al final**, para no cambiar las columnas que van delante: `provincia`
primero acota el rango, `fecha_publicacion`/`id` detrás son el orden en que el panel pide la página, y
`fuente_id` solo hace falta para **descartar**, así que al final no rompe ni el rango ni el orden.

### 4.5 Se retira el GIN del `jsonb` completo

`ix_registro_datos` es un GIN sobre **todo** `datos`: 113 MB, casi la mitad de lo que suman los demás
índices. La 0014 ya lo señaló como candidato a retirarlo y lo dejó pendiente de medir. Medido:
**la consulta de catálogos, su única usuaria declarada, no lo usa** —hace un recorrido completo, y el
`jsonb_exists` se resuelve como condición—, y ninguna otra consulta del sistema usa `datos @>` ni
`jsonb_exists` (los filtros leen campos sueltos con `->>`, que no puede usar el GIN). Se retira y el
`downgrade` lo vuelve a crear igual: recuperarlo es una orden si algún día se quiere consultar el
`jsonb` por contenido.

## 5. Casos de uso y requisitos cubiertos

- CU-02 (ver las gráficas): el reparto por provincia y el de tipo de proceso.
- CU-01 (consultar el histórico con filtros): el clic del mapa y el filtro por tipo de proceso.
- CU-05 (localización de una contratación): el `count(*)` de una provincia, de 9,5 s a 14 ms.
- RF-05 (rendimiento de las consultas), OE-5.

## 6. Pruebas ejecutadas y resultado real

### 6.1 Que no se pierda nada: la comparación de antes y después

Antes de tocar el esquema se guardó el resultado de **22 filtros** —por provincia completa, por
provincia suelta, con tilde, inventada, por tipo de proceso, por estado, por palabra clave, por CPC,
por código de NIC, por familia, por fuente, combinados— y, para cuatro de ellos, los **cuatro repartos
completos** (por provincia, por tipo de proceso, por fuente y la serie mensual). Con la escritura
congelada (API y worker parados) para que la comparación fuera exacta.

Después del cambio, con las mismas consultas:

- **21 de los 22 casos dan un resultado idéntico**, incluidos los cuatro repartos completos, fila por
  fila.
- **1 caso cambia: `tipo_proceso = «sin clasificar»`, de 0 a 12.743 filas.** No es una pérdida, es el
  arreglo del § 4.2: el reparto ya contaba esas 12.743 filas en su barra y el filtro no encontraba
  ninguna. El número coincide exactamente con la barra.

Y la comprobación directa del relleno, fila a fila: **0 filas con las columnas nulas** y **0 filas
donde la clave guardada no coincida con la que calcula la regla**, recalculada desde `datos` para las
110.743 filas.

### 6.2 Medición, con los servicios parados

| Caso | Antes de la fase 4.9 | Tras la 4.9 | **Ahora** |
|---|---|---|---|
| Página sin filtros | 1.818 ms | 414 ms | 452 ms |
| Página con el orden por defecto | 1.967 ms | 406 ms | **373 ms** |
| Página filtrada por provincia (el clic del mapa) | 940 ms | 412 ms | **352 ms** |
| Código por fragmento (el NIC) | 24.376 ms | 365 ms | 361 ms |
| CPC por código | 598 ms | 364 ms | 363 ms |
| Palabra clave | 488 ms | 483 ms | 412 ms |
| Rango de fechas | 340 ms | 352 ms | 334 ms |
| **`estadisticas` (las gráficas)** | **36.217 ms** | 46.978 ms | **3.619 ms** |
| Reparto por provincia (dentro de la anterior) | 18,9–21,4 s | 21,4 s | **103 ms** |
| Reparto por tipo de proceso | 17,9 s | 15,1 s | ~1 s |
| `count(*)` del clic del mapa | — | 9,5 s | **14 ms** |
| Catálogos (los desplegables) | 12.903 ms | 6.446 ms | 8.888 ms (**peor**, § 8) |

El reparto por provincia pasa de 21,4 s a **103 ms**: doscientas veces menos. `estadisticas` entera,
que era el techo del panel, pasa de 47 s a 3,6 s.

### 6.3 Comprobaciones automáticas

- `ruff check` → `All checks passed` · `ruff format --check` → 232 archivos
- `mypy` → `Success: no issues found in 210 source files`
- `pytest pruebas/unidad` → **745 pasan** (9 nuevas)

Las nueve pruebas nuevas no comprueban un resultado, comprueban **acuerdos entre textos**: que la
condición sea una igualdad contra la columna y no toque `datos`, que la clave que pide el filtro sea
la que escribe la ingesta, que «PICHINCHA - QUITO» y «Pichincha» den la misma clave, que «sin
clasificar» encuentre sus filas, que el relleno de la migración diga lo mismo que la función de
Python, y que un valor ausente tenga clave en lugar de dejar la columna vacía.

### 6.4 Verificación de extremo a extremo

Con el sistema en marcha, el worker cerró un ciclo real: **`Vigilancia NCO: ok · 20 nuevos, 0
actualizados, 1786 iguales, 1 cerrados`** y `Ítems CPC: 59 fichas leídas, 0 pendientes`. Las 20 filas
nuevas —escritas por el `INSERT` de la ingesta, el camino que no cubre ninguna prueba de unidad—
llevan sus claves: `CAÑAR` → `canar`, `MORONA SANTIAGO` → `morona santiago`, y `sin clasificar`
donde la fuente no publica el tipo.

## 7. Evidencia de aceptación

- Los planes lo dicen: `Parallel Index Only Scan using ix_registro_provincia` en el reparto real y
  `Index Only Scan using ix_registro_provincia` en el `count(*)` del mapa, los dos con
  `Heap Fetches: 233`.
- `alembic current` → `0019 (head)`.
- 110.743 filas, 0 con clave nula, 0 donde la clave no coincida con la regla.
- Los 22 filtros comparados dos veces, con la escritura congelada entre las dos.

## 8. Deuda técnica y pendientes

1. **La tabla tiene ~230 MB de espacio muerto y hay que compactarla.** El relleno reescribió las
   110.743 filas y dejó una versión muerta de cada una: `registro` pasó de 230 MB a **415 MB** y la
   base de 410 MB a **704 MB**. `VACUUM` marca ese espacio como reutilizable —las filas nuevas de la
   ingesta ya ocupan ese hueco, así que la tabla no crecerá— pero **el archivo no encoge**, y por eso
   un recorrido completo de los catálogos lee 415 MB en lugar de 230: de ahí que tarden 8,9 s en vez
   de 6,4 s.
   `VACUUM FULL` **falló con «No space left on device»**: reescribir la tabla necesita sitio libre
   para la copia nueva mientras la original sigue ahí —unos 370 MB entre la copia y el WAL— y la
   instancia estaba al límite. Se liberaron 113 MB retirando el GIN que nadie usaba (0019), con lo
   que la base quedó en **590 MB**, pero **no es suficiente para compactar**. Hay que subir el disco
   de la instancia (o mover los datos a una con más espacio) y entonces ejecutar `VACUUM FULL
   registro`. Es una operación de minutos con la escritura parada.
2. **`catálogos` (los desplegables) sigue tardando 8,9 s**, y en parte por lo anterior. Es un
   `DISTINCT` sobre cinco campos de `datos` en una sola consulta. Con las columnas nuevas podrían
   resolverse `provincia` y `tipo_proceso` sin tocar `datos`, y los otros tres exigirían sus propias
   columnas —tres rellenos más, y con el disco como está no es el momento—. Está cacheado.
3. **El filtro por entidad** sigue comparando con una expresión sobre `datos` (medido: ~20 s en el
   sondeo de equivalencia). Es el último filtro que lee el `jsonb` en cada fila.
4. Las pruebas de carga con k6 siguen pendientes.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Una fila escrita por un camino que no rellene las claves | Las columnas son `NOT NULL` con `DEFAULT`: la fila no puede quedar sin clave, y un escritor que la omita recibe el valor de defecto en lugar de una fila invisible |
| La regla de la ingesta y la del relleno se separan | Una prueba compara el SQL de la migración con la función de Python; otra compara lo que pide el filtro con lo que escribe la ingesta |
| El disco vuelve a llenarse | Está al límite y hace falta ampliarlo (§ 8.1). Ninguna operación nueva escribe ~230 MB hasta entonces |
| El índice deja de usarse porque le falte una columna | Es lo que pasó en la 0017 y está documentado con la tabla de los tres planes; `scripts/medir_consultas.py` imprime el plan, no solo el tiempo |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | `0017` → `0018` → `0019 (head)` |
| Comprobaciones | ruff, ruff format, mypy, 745 pruebas unitarias y la comparación de los 22 filtros |
| Pendiente del usuario | ampliar el disco de la instancia para poder compactar la tabla (§ 8.1) |
