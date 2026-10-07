# Fase 4.9 — Que las consultas del panel no recorran el histórico entero

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

## 1. Objetivo

**Dejar de pagar medio minuto por abrir el panel.** La queja era «va lento», y una queja sin números
no se puede arreglar: no distingue una consulta mal escrita de un índice que falta, de un caché que
no acierta o de un viaje de red de más. Así que esta fase empieza midiendo y solo después toca algo.

El histórico tiene **110.678 filas** y ocupa **410 MB** —230 MB de tabla y 180 MB de `TOAST`—. La
mayor parte de ese peso está en `datos`, el `jsonb` con el payload canónico, de unos **2 KB por
fila**: leerlo obliga a descomprimir fila a fila. Esa es la causa de casi todo lo que sigue, y no se
veía en ningún sitio porque ninguna consulta fallaba: solo tardaba.

## 2. Alcance

**Incluido**

- `scripts/medir_consultas.py`: un guion de solo lectura que cronometra los siete casos que hace el
  panel y, además, imprime el **primer paso del plan** de las consultas que dependen de un índice.
  Se llama a la capa de consulta directamente, sin credenciales, y conviene ejecutarlo con el API y
  el worker parados, porque compiten por las conexiones del agrupador.
- La migración `0015`: el índice del orden por defecto, y `pg_trgm` con un índice de trigramas para
  la búsqueda por fragmento del código.
- La migración `0016`: **retira** los dos índices de reparto que la 0015 había añadido con un
  razonamiento equivocado. La historia completa está en el § 4.3.
- El orden «más antiguos» con el desempate invertido, para que los dos órdenes por fecha quepan en
  un solo índice.
- Las expresiones de los dos repartos, extraídas a constantes (`PROVINCIA_AGRUPADA` y
  `TIPO_PROCESO_AGRUPADO`) para que la consulta y el índice no puedan separarse en silencio.
- La tabla y las gráficas del panel se piden **en paralelo**: eran dos viajes en serie sin ninguna
  razón (`frontend/src/stores/datos.js`).

**Excluido (deliberadamente)**

- **Los dos repartos de las estadísticas.** Siguen tardando entre 7 y 21 segundos, y la causa está
  identificada y medida, pero el arreglo es un cambio de esquema con un relleno de 110.678 filas en
  caliente: se decide aparte, con estas cifras delante (§ 8).
- Las pruebas de carga con k6 (~1.000 usuarios concurrentes). Son otro trabajo y necesitan su
  entorno.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| Guion de medida de las consultas del panel | `backend/scripts/medir_consultas.py` |
| Índice del orden por defecto, reconstruido con `NULLS LAST` | `alembic/versions/0015_indices_agregados.py` |
| `pg_trgm` + índice GIN de trigramas sobre `COALESCE(datos ->> 'codigo','')` | `alembic/versions/0015_indices_agregados.py` |
| Retirada de los dos índices de reparto | `alembic/versions/0016_retirar_indices_reparto.py` |
| Orden «más antiguos» como marcha atrás del de recientes | `bd/consultas.py` (`ORDENES`) |
| Expresiones de reparto como constantes | `bd/consultas.py` |
| Tabla y gráficas en paralelo | `frontend/src/stores/datos.js` |
| Cuatro pruebas del acuerdo entre el SQL y los índices | `pruebas/unidad/test_consultas_bd.py` |

## 4. Decisiones tomadas y justificación

### 4.1 El índice del orden tiene que declarar los nulos igual que la consulta

La 0014 creó `ix_registro_fecha_id` como `(fecha_publicacion DESC, id)` razonando que el orden por
defecto era «`fecha_publicacion DESC` y desempatar por `id`». El orden real de la consulta es
`fecha_publicacion DESC NULLS LAST, id`. **En PostgreSQL `DESC` implica `NULLS FIRST`**, así que las
dos definiciones no son la misma y el planificador hace lo correcto: ignorar el índice y ordenar.
Medido, `Gather Merge → Sort → Parallel Seq Scan`: **10.451 ms por página**. Reconstruido el índice
con `NULLS LAST`, la misma consulta hace `Index Scan using ix_registro_fecha_id`: **7,9 ms**.

Conviene subrayar por qué nadie lo había notado: **hoy no hay ni una fila sin fecha de publicación**
(comprobado: 0 de 110.678). El desajuste no estaba en los datos, estaba en la definición, y el
planificador compara definiciones.

### 4.2 El orden «más antiguos» se ajusta para compartir el índice

Un índice de varias columnas se lee en los dos sentidos, pero el sentido inverso no es «lo mismo con
el signo cambiado»: al invertir el recorrido se invierten **todas** las columnas. La marcha atrás de
`(fecha_publicacion DESC NULLS LAST, id)` es «`ASC NULLS FIRST` y desempate al revés», así que el
orden «más antiguos» pasa a desempatar por `id DESC`. Cuál de los dos desempates se use es
indiferente —son filas publicadas el mismo día—; lo que no es indiferente es que haya **un solo
índice** para los dos órdenes en lugar de dos índices casi iguales, o de volver a ordenar en cada
página. Hay una prueba que comprueba que una cláusula es exactamente la inversa de la otra, y que
falla si alguien «arregla» el desempate.

### 4.3 Los índices de reparto, y por qué hubo que retirarlos

El razonamiento era: los repartos tardan 20 s porque hay que leer `datos` de todas las filas; si la
expresión que se agrupa está en un índice, el recuento se resolverá con un `Index Only Scan` y no se
descomprimirá nada. La primera mitad es cierta. **La segunda, no.**

Medido con los dos índices creados y las estadísticas al día: el reparto por provincia pasó de 18,9 s
a **29,8 s** —once segundos peor— porque el planificador los usa como `Index Scan` con una visita al
montón por fila, que es exactamente el trabajo que se quería evitar. Y no es un problema de coste:
forzando `enable_seqscan = off` y `enable_bitmapscan = off` el plan sigue siendo `Index Scan`, nunca
`Index Only Scan`; y con `enable_indexscan = off` —que lo penaliza con 10¹⁰— el planificador **lo
sigue eligiendo**, lo que significa que el otro camino no existe.

La comprobación que lo cierra es el control: agrupando por una columna normal,
`registro_fuente_id_clave_natural_key` da `Index Only Scan` con un coste estimado de 3.238 frente a
los 30.000 del recorrido. Es decir: **el escaneo «solo índice» funciona perfectamente en esta tabla;
lo que no funciona es sobre una expresión que cuelga de `datos`.** Los dos índices se retiran en la
0016, y con ellos se van unos 16 MB de peso y el coste de mantenerlos en cada escritura. El detalle
completo, con los planes, está en la cabecera de `0016_retirar_indices_reparto.py`.

### 4.4 Un `VACUUM ANALYZE` cambia el plan, y conviene saberlo

El mapa de visibilidad de `registro` estaba al **94,8 %** y el planificador elegía, para los
repartos, un `Nested Loop` sobre `ix_registro_fecha` que costaba 18,9 s. Después de
`VACUUM (ANALYZE) registro` —visibilidad al 100 % y, sobre todo, estadísticas al día— prefería un
`Parallel Seq Scan` que cuesta **7,4 s**. La mitad del problema de los repartos se arregla sin tocar
el esquema, manteniendo la tabla analizada después de una ingesta grande.

Queda anotado como operación, y hay que ser honesto sobre su fragilidad: **el planificador salta de
un plan de 7 s a otro de 21 s para la misma consulta** según detalles finos de las estadísticas. Eso
no es un plan bueno; es un plan que hoy sale bien.

### 4.5 El código por fragmento sí necesitaba una extensión

El NIC se busca por fragmento («26-00053»), y un `ILIKE '%…%'` no lo resuelve ningún btree: la 0014
lo dejó pendiente con la nota de que la salida sería `pg_trgm` «y eso conviene medirlo antes». Se
midió: 3.385 ms de recorrido completo, y la extensión estaba **disponible pero sin instalar**. Con
`ix_registro_codigo_trgm`, 116 ms. Se instala la extensión desde la migración (`CREATE EXTENSION IF
NOT EXISTS`) pero **no se retira en el `downgrade`**: es una operación del servidor y otras consultas
podrían estar usándola; el índice que la necesita sí se borra.

### 4.6 El clic del mapa no necesitó ningún índice nuevo

El filtro por provincia tardaba 8,7 s en frío, y lo natural era pensar en un índice que cubriera la
provincia junto con el orden. No hizo falta: **arreglado el orden, el planificador resuelve el clic
recorriendo el índice por fecha y descartando** las filas que no son de esa provincia. Como Pichincha
es una de cada cuatro filas, encuentra las 25 que pide en unas pocas decenas de lecturas. Medido:
`Index Scan using ix_registro_fecha_id`, **412 ms**, de los cuales ~230 son el `count(*)` del total.
La lección es la de siempre: se mide antes de añadir un índice.

## 5. Casos de uso y requisitos cubiertos

- CU-01 (consultar el histórico con filtros) y CU-02 (ver las gráficas): el panel responde en el
  camino de la tabla.
- CU-05 (buscar una necesidad concreta) por su código: el NIC pasa de 3,4 s a 0,12 s.
- RF-05 (rendimiento de las consultas), OE-5, R-01 (la caché por generación no cambia).

## 6. Pruebas ejecutadas y resultado real

### 6.1 Medición antes y después

Mediana de cinco repeticiones, con el API y el worker parados, desde `scripts/medir_consultas.py`:

| Caso | Antes | Después |
|---|---|---|
| Página sin filtros | 1.818 ms | **414 ms** |
| Página con el orden por defecto | 1.967 ms | **406 ms** |
| Página filtrada por provincia (el clic del mapa) | 940 ms (8.677 ms en frío) | **412 ms** |
| Código por fragmento (el NIC) | 24.376 ms | **365 ms** |
| CPC por código | 598 ms | 364 ms |
| Palabra clave | 488 ms | 483 ms |
| Rango de fechas | 340 ms | 352 ms |

Los ~350 ms que comparten casi todos los casos son el `count(*)` del total, que se ejecuta con el
mismo `WHERE` que la página: es el suelo de esta pantalla, no el coste de cada filtro.

Desglose de las estadísticas, que **no se mejoran en esta fase** (medido por separado, en frío):

| Consulta | Antes | Después | Por qué |
|---|---|---|---|
| Reparto por provincia | 18,9 s | 7,4–21,4 s | lee `datos` de las 110.678 filas |
| Reparto por tipo de proceso | 17,9 s | 7,8–15,1 s | ídem |
| Serie mensual | 191 ms | 158 ms | escaneo solo-índice |
| Conteo por fuente | 426 ms | 423 ms | escaneo solo-índice |
| Catálogos (los desplegables) | 12,9 s | 6,4 s | cinco `DISTINCT` sobre `datos` |

El rango de los repartos es el del § 4.4: el mismo SQL tarda 7,4 s o 21,4 s según el plan que elija
el motor. Se deja escrito así, y no como una cifra única, porque **la variación es el problema**.

### 6.2 Comprobaciones automáticas

- `ruff check` → `All checks passed`
- `ruff format --check` → 229 archivos ya formateados
- `mypy` → `Success: no issues found in 209 source files`
- `pytest pruebas/unidad` → **742 pasan** (4 nuevas)

Las cuatro pruebas nuevas no comprueban un resultado, comprueban que **dos textos siguen
coincidiendo**: el orden por defecto con la definición del índice, que «más antiguos» es la inversa
exacta de «más recientes», y que las claves de los repartos son las que el filtro acepta al
pulsarlas. Cuando dejan de coincidir no hay error, ni aviso, ni fila de más: solo una consulta que
vuelve a tardar veinte segundos.

### 6.3 Estado de la base

`alembic current` → `0016 (head)`. La 0015 tardó 65 s en aplicarse (reconstruir el índice del orden
sobre 410 MB no es instantáneo) y conviene aplicarla con el worker parado: los `CREATE INDEX` no son
concurrentes y bloquean la escritura mientras se construyen.

## 7. Evidencia de aceptación

- El plan de la página con el orden por defecto es `Index Scan using ix_registro_fecha_id`, no un
  `Sort` sobre la tabla. La prueba `test_el_orden_por_defecto_declara_los_nulos_como_el_indice`
  falla si la migración y el orden se separan.
- El plan de la búsqueda por fragmento es `Bitmap Index Scan on ix_registro_codigo_trgm`.
- El plan del clic del mapa es `Index Scan using ix_registro_fecha_id` con el filtro de provincia
  aplicado encima: 412 ms.
- `estado_datos.py` y la tabla del panel siguen devolviendo lo mismo: los cambios son de plan, no de
  resultado. Las 742 pruebas unitarias, incluidas las del filtro por provincia y las del código por
  fragmento, pasan sin cambios en su semántica.

## 8. Deuda técnica y pendientes

1. **Los dos repartos de las estadísticas y los catálogos** siguen leyendo `datos` de todas las filas
   al terminar esta fase. **Resuelto en parte en la fase 4.11** (`docs/18-fase-4k-columnas-de-provincia-y-tipo.md`):
   `provincia` y `tipo_proceso` pasaron a ser columnas propias y los dos repartos bajaron de 21,4 s y
   15,1 s a 103 ms y ~1 s. Los catálogos siguen igual porque les quedan tres campos (`estado`,
   `tipo_necesidad`, `entidad`) que también viven en el `jsonb`.
2. **El `count(*)` del total** (~230 ms) se ejecuta con el mismo `WHERE` que la página y es el suelo
   de los 350 ms de todos los casos. Candidato a caché por generación, que ya existe para las
   estadísticas.
3. **`ix_registro_fecha` es sospechoso.** Es un `(fuente_id, fecha_publicacion DESC)` que hoy sirve
   el `count(*)` y la serie mensual como escaneo solo-índice —pero los dos podrían usar
   `ix_registro_fecha_id`— y que en cambio provoca el `Nested Loop` de 21 s en los repartos, porque
   empieza por la columna de la fuente. Retirarlo hay que medirlo contra las consultas del worker
   antes de decidirlo.
4. Las pruebas de carga con k6 siguen pendientes.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El planificador vuelve a elegir el `Nested Loop` de 21 s para los repartos | Está documentado con las dos cifras; el arreglo estructural es el § 8.1 |
| El plan del panel cambia sin que nadie toque nada (estadísticas, versión del motor) | `scripts/medir_consultas.py` imprime el plan, no solo el tiempo: repetirlo después de una ingesta grande avisa antes que el usuario |
| `pg_trgm` no está en un servidor nuevo | La migración lo instala; si el rol no pudiera, la migración falla en el `upgrade` y se ve, en lugar de degradarse en silencio |
| Los índices de expresión se separan de la consulta en un arreglo futuro | Cuatro pruebas comparan los textos; el porqué está en la cabecera de la migración |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | `0015 (head)` → `0016 (head)` |
| Comprobaciones | ruff, ruff format, mypy y 742 pruebas unitarias en verde |
| Revisión | pendiente de la decisión del § 8.1 para los repartos |
