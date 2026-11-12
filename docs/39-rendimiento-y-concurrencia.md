# Rendimiento, concurrencia y vistas ocultas (500 a 1.000 personas)

## 1. Objetivo

Más de 500 personas a la vez (idealmente 1.000) sin perder velocidad, sin perder datos y sin que se
mezclen los datos de dos empresas. Y comprobar que lo que el superadministrador oculta («vistas»)
sigue oculto por **todas** las puertas, incluidas las nuevas: propuestas, asistente, anexos, radar,
alertas y mercado.

Punto de partida: `docs/07`, `docs/16` y `docs/36` (pool, caché, cortacircuitos). Aquí se midió lo
que quedaba y se corrigió lo que no cuadraba.

## 2. Qué se midió

Base local (PostgreSQL 16, 5.642 registros, 21.205 requisitos, 882 avisos). Los tiempos absolutos
son pequeños porque la tabla lo es; lo que importa es **el plan** (recorrido completo o índice),
porque un recorrido completo crece con la tabla y uno por índice no.

| Consulta | Antes | Después |
|---|---|---|
| Ficha por código (`desde-codigo`, su sondeo cada 1,5–4 s, y `estado_desde_codigo`) | **Seq Scan** de `registro`, 9.775 bloques, 14,8 ms | Bitmap OR sobre dos índices btree, 9 bloques, **0,17 ms** |
| `ILIKE '%texto%'` de «Precios y competencia» (y `precio_referencia` / `competidores` del asistente) | Seq Scan de `registro` | Bitmap Index Scan en `ix_registro_texto_trgm_vigente` |
| Propuestas (`_INFIMAS_ABIERTAS`) | BitmapAnd plazo + vigentes + fuente, 4 ms | sin cambio (ya usa índices) |
| Candidatos de alertas | `ix_registro_nuevos`, 1,8 ms | sin cambio |
| Avisos de la persona | `ix_aviso_usuario`, 0,4 ms | sin cambio + filtro de fuente (join a `fuente`, memoizado) |
| «Mis ofertas» | Seq Scan + sort (20 filas) | `ix_proforma_negocio_creado` cuando crezca |
| Requisitos de una lectura | índice por empresa y filtro de 181 filas | `ix_requisito_proceso_lectura` |

Otras medidas:

- **Inicio del asistente**: lanzaba 7 lecturas a la vez, cada una con su conexión. Una persona
  abriendo el chat ocupaba 7 de las 20 conexiones del proceso: con tres a la vez, el resto esperaba
  turno. Además leía el perfil dos veces (cada lectura del perfil son 12 consultas).
- **Paquete del panel**: el JS principal pesaba 500 kB (168 kB gzip) porque Chart.js iba dentro.
  Ahora 319 kB (105 kB gzip); Chart.js (208 kB) se baja con la primera gráfica. jsPDF, pdf.js,
  html2canvas y Tesseract ya iban aparte.
- **Exportación a Excel**: armaba el libro (hasta 20.000 filas) dentro del bucle de eventos:
  segundos en los que el proceso no atendía a nadie.

## 3. Qué se cambió

### 3.1 Base de datos

- **Topes de PostgreSQL por conexión** (`BD_STATEMENT_TIMEOUT_MS=30000`,
  `BD_IDLE_TX_TIMEOUT_MS=60000`): viajan al abrir la conexión (`server_settings` de asyncpg), sin un
  viaje extra por petición. Una consulta colgada ya no retiene una ranura del pool para siempre. El
  **worker los pone a cero** (`tareas/worker.py`, con `os.environ.setdefault`), porque la ingesta y
  el mantenimiento tienen consultas largas y su bloqueo de ingesta vive en una conexión ociosa. Las
  conexiones se ven en `pg_stat_activity` como `cercoapp-api` y `cercoapp-worker`.
- **Una petición no ocupa varias conexiones**: el patrón de los repositorios ya era «una conexión
  por llamada, se suelta al terminar» (nada se retiene mientras se espera a la IA o al SRI). La
  excepción era el inicio del asistente: ahora va con `PARALELO_INICIO = 2`.
- **Perfil y CPC recordados durante la petición** del asistente (`aplicacion/asistente/recordados.py`):
  inicio y modelo leen el perfil una vez. Muere con la petición: nada compartido entre personas.
- **N+1 quitados**: requisitos (`guardar_requisitos`) en una sentencia con `unnest`; avisos de una
  revisión de alertas en una sentencia por empresa (`crear_avisos` con `jsonb_to_recordset`).
- **Ficha por código** compara `upper(...) = upper(:código)` en vez de `ILIKE :código` (que además
  trataba `_` y `%` del texto como comodines).
- **Migración `0040_rendimiento.py`** (aplicada en local; `CREATE INDEX CONCURRENTLY` en bloque de
  autocommit): `ix_registro_codigo_mayus`, `ix_registro_clave_natural_mayus`,
  `ix_registro_texto_trgm_vigente` (2 MB en local), `ix_requisito_proceso_lectura`,
  `ix_proforma_negocio_creado`, `ix_proforma_titulo`, `ix_lectura_documento_reciente`,
  `ux_aviso_alerta_registro` (único) y la columna `documento_tdr.tomado_en`.
  Ya existían y no se duplicaron: trigramas de `codigo`, `entidad` y `clave_natural`, parcial de
  `plazo_proformas_en`, `es_vigente` (en `ix_registro_nuevos`), `fuente_id`,
  `lectura_documento(negocio_id, registro_id, creado_en)` y los de `asistente_*`.

### 3.2 Bucle de eventos

- Exportación a Excel (`construir_libro`) y análisis de la plantilla (`analizar`) van a un hilo con
  `en_hilo` (tope de hilos por núcleo). Ya iban en hilo: lectura de PDF/Word/Excel/ZIP de anexos
  (`texto_anexos` vía `_leer_del_disco` y `_secciones_de_subida`), RUP (PDF y OCR), maquetado del
  PDF, Word y firma. No se encontró HTTP síncrono en el API (todo `httpx.AsyncClient`); el disco
  va por `asyncio.to_thread`.

### 3.3 Memorias en proceso

Todas revisadas. Ninguna guarda datos de una empresa: las que hay son de datos **públicos** y las
que dependen de las vistas llevan las fuentes en la llave.

| Memoria | Llave | Antes | Ahora |
|---|---|---|---|
| `_FICHAS` (`bd/documentos.py`) | (fuentes visibles, código) | dict, se vaciaba entera a 4.096 | `MemoLru(4096)` |
| `_RECORDADOS` (`salida/historial.py`) | RUC (OCDS público) | dict, vaciado a 512 | `MemoLru(512)` |
| `_RECORDADOS` (`fuentes/ocds_proceso.py`) | ocid | dict, vaciado a 1.024 | `MemoLru(1024)` |
| `_vistas_previas` (`revisar_alertas.py`) | criterios | dict, vaciado a 500, **sin fuentes** | `MemoLru(500)` con las fuentes en la llave |
| `_FUENTES` (`bd/tdr.py`, nueva) | registro → fuente | — | `MemoLru(20000)`, dato inmutable |
| `_LEIDOS` (`preparar_documentos.py`) | sha256 del archivo | `CacheLru(256)` | sin cambio (el resultado sale solo del contenido) |
| `_memo` de generaciones | nombre de fuente | TTL ≤ 60 s | sin cambio (la generación de permisos **no** se memoriza) |
| Propuestas | Redis, `negocio_id` + huella | — | sin cambio |

Con varias réplicas: los permisos de vistas viven en Redis (o no se cachean sin Redis), así que
ocultar una vista se nota en la petición siguiente en **todas** las réplicas. Las memorias de
arriba son públicas y con TTL corto: dos réplicas pueden diferir unos segundos, nunca en qué
empresa ve qué.

### 3.4 Integridad con concurrencia

| Caso | Riesgo | Ahora |
|---|---|---|
| Créditos de IA (solo lectura) | — | Ya correcto: `UPDATE … WHERE disponibles >= n RETURNING` es atómico; dos mensajes no gastan el mismo crédito. Riesgo menor: si el proceso muere entre cobrar y devolver, el crédito no se devuelve. |
| Título de proforma | Dos guardados a la vez pasaban la comprobación | `guardar_proforma` toma `pg_advisory_xact_lock` por empresa y vuelve a comprobar con la regla de `dominio.titulos` en la misma transacción. No es índice único porque la regla ignora tildes/guiones/espacios, y hay dos empresas locales con «proforma» ×9 y ×7 de antes de la regla, que no se tocan. Queda `ix_proforma_titulo` (no único) para la búsqueda. |
| Recorte de mensajes del asistente | — | Ya correcto: el `UPDATE` de la conversación bloquea su fila, así que inserción y recorte de una conversación van en fila. |
| Alertas | Dos réplicas del worker → avisos dobles | Bloqueo de asesoría «alertas» en el worker + índice único `(alerta_id, registro_id)` + `ON CONFLICT DO NOTHING`. La migración borra duplicados previos (en local no había con alerta). |
| Recordatorio de cierre | Dos réplicas → dos avisos | `UPDATE … WHERE recordado_en IS NULL RETURNING` primero; solo quien lo gana inserta. |
| Cola de TDR | Sin reserva: dos réplicas bajaban lo mismo | `UPDATE … FROM (SELECT … FOR UPDATE SKIP LOCKED)` + `tomado_en` (reserva de 10 min, por si muere el worker). El estado sigue siendo `pendiente`. |
| PATCH de «Mis ofertas» | Pérdida de actualización | Un solo `UPDATE` con solo los campos enviados: no hay lectura-modificación-escritura. Dos cambios al mismo campo: gana el último (aceptable para etapa/nota). |
| Worker | Cerraba el pool tras cada vigilancia mientras la cola de TDR lo usaba | En el bucle (`servir`) pool y caché viven lo que el proceso; los trabajos sueltos (`--una-vez`…) siguen cerrando. |

### 3.5 Vistas ocultas

Cómo funciona (sin cambios): el superadministrador concede o retira vistas por persona
(`/v1/accesos/usuarios/{id}/vistas`); `VistasDep` resuelve las vigentes (Redis, 60 s, con
generación que sube al retirar) y `fuentes_para_vistas` las traduce a fuentes: «Ínfimas cuantías» →
NCO, «Ofertas» → OCDS, «Mapa y resumen» → agregados. Una tupla vacía es «ninguna».

Verificación endpoint por endpoint:

| Ruta | Antes | Ahora |
|---|---|---|
| `/v1/registros`, exportación, `/v1/catalogos`, `/v1/estadisticas` | ✔ | ✔ |
| `/v1/propuestas`, `/v1/radar`, `/v1/mercado/*`, `/v1/procesos/{id}/anexos` | ✔ | ✔ |
| `/v1/documentos/desde-codigo` (+ estado, resumen, preguntar) | ✔ | ✔ |
| `/v1/alertas/vista-previa` | ✗ contaba y **enseñaba muestras** de NCO y OCDS a cualquiera | solo fuentes visibles |
| `/v1/avisos` | ✗ títulos de avisos de cualquier fuente | los de alertas, solo de fuentes visibles (los recordatorios de proformas propias, siempre) |
| `/v1/tdr/{registro_id}` (pedir, estado, archivo, relleno, borrador) | ✗ bastaba el id de una ínfima | exige la vista de la fuente del proceso |
| Asistente: `buscar_infimas`, `propuestas_para_ti` | ✔ | ✔ + no se ofrecen al modelo sin NCO |
| Asistente: `estado_proceso`, `preparar_proforma` | ✔ (busca solo en fuentes visibles) | ✔ |
| Asistente: `precio_referencia`, `competidores` | ✔ (caso de uso) | ✔ + no se ofrecen al modelo sin OCDS |
| Asistente: `historial_ruc` | ✗ procesos OCDS de cualquier RUC sin vista | exige «Ofertas» |
| Asistente: `crear_alerta` | ✗ la cuenta de coincidencias miraba las dos fuentes | solo fuentes visibles |
| Asistente: inicio | contador de propuestas fallaba (y se registraba) sin NCO | no se calcula; sugerencias filtradas |
| Asistente: sugerencias (inicio, camino rápido, modelo) | podían llevar a una vista oculta | filtradas con la regla de cada herramienta |
| `ejecutar` (cualquier herramienta que el modelo invente) | — | segunda barrera: `herramienta_permitida` antes de ejecutar |

Panel: las pestañas de una vista oculta **ya no salen en el menú** (antes salían con candado); el
radar y «Precios y competencia» se ocultan si no queda ninguna vista de datos; el asistente filtra
sus sugerencias fijas, las del servidor y los chips del resumen (`sugerenciasVisibles`), y no puede
navegar a una pestaña oculta. El servidor sigue siendo la barrera; el panel solo deja de ofrecerla.

### 3.6 Panel: sondeos y paquete

- `utils/sondeo.js`: espera creciente con tope, ±10 % de azar y pausa con la pestaña oculta.
- Bajada del TDR (`Documentos.vue`, `VisorTdr.vue`): no pregunta con la pestaña oculta; el rato
  oculto no cuenta para el tope de 2 min.
- Latido de presencia: con la pestaña oculta, al 80 % de la vigencia (48 s en vez de 30 s, sin
  pasar a rojo); tras fallos, se dobla hasta 5 min; con azar; al volver a la pestaña, late enseguida.
- Chart.js perezoso (ver 2). Revisado el montaje: vistas, catálogos, palabras y CPC se piden una vez
  y en paralelo; la revisión de vistas y de novedades ya se saltaba con la pestaña oculta.

### 3.7 Prueba de carga

`carga/panel.js` añade `asistente_inicio`, `asistente_mensaje` (camino rápido «mis alertas», sin IA),
`propuestas` y `mis_ofertas`, repartidos uno por vuelta, con sus umbrales. **Se niega a arrancar**
si `BASE_URL` no es local, salvo `-e PERMITIR_REMOTO=1` para un entorno de ensayo propio. No se
ejecutó contra producción.

## 4. Configuración recomendada en Railway

La cuenta que manda: `(réplicas × API_WORKERS) × (BD_POOL_SIZE + BD_MAX_OVERFLOW) + worker ≤
max_connections − margen` (deja ~10 para Alembic, consola y monitoreo).

| Servicio | Valor | Por qué |
|---|---|---|
| API | 2 réplicas × `API_WORKERS=2` | 4 procesos; las peticiones son de E/S, la base es el cuello |
| API | `BD_POOL_SIZE=8`, `BD_MAX_OVERFLOW=4`, `BD_POOL_TIMEOUT_SEG=5` | 4 × 12 = 48 conexiones |
| API | `BD_STATEMENT_TIMEOUT_MS=30000`, `BD_IDLE_TX_TIMEOUT_MS=60000` | por defecto ya |
| Worker | 1 réplica (puede ser 2: alertas, cierres y cola de TDR ya no duplican), `BD_POOL_SIZE=3`, `BD_MAX_OVERFLOW=2` | 5 conexiones; no comparte pool con el API, no puede dejarlo sin conexiones |
| Worker | **no** declarar `BD_STATEMENT_TIMEOUT_MS` | se pone a 0 solo |
| PostgreSQL | `max_connections` ≥ 100 (el de Railway por defecto) | 48 + 5 + margen |
| Redis | **obligatorio** con más de una réplica | sesiones vivas, generaciones, permisos de vistas, caché de propuestas y resultados |
| Más de ~100 conexiones | PgBouncer en modo transacción y `prepared_statement_cache_size=0` en la URL | ver docs/36 §5 |

Antes de desplegar: aplicar `alembic upgrade head` (incluye 0040; los índices concurrentes tardan
según el tamaño de `registro`, sin bloquear escrituras).

## 5. Riesgos que quedan

- **Cadena de migraciones**: 0040 cuelga de 0038 porque 0039 (seguridad) no existía. Si se crea
  0039 desde 0038, cambiar `down_revision` de 0040 a `"0039"` o habrá dos cabezas.
- Un `CREATE INDEX CONCURRENTLY` que falla deja un índice `INVALID`, y el `IF NOT EXISTS` no lo
  rehace: si pasa, `DROP INDEX` y volver a lanzar la migración.
- Los topes por persona (`LimitePorUsuario`) y por IP siguen en la memoria de cada proceso: con 4
  procesos el tope efectivo es ×4. Pasarlos a Redis si se quiere un tope exacto.
- `revisar_plantilla` (subida de la plantilla de Excel, solo administradores) aún abre el libro en
  el bucle; es infrecuente y con tamaño acotado.
- El perfil de la empresa se lee con 12 consultas en una conexión: barato en la red interna, caro
  si la base está lejos (95 ms × 12). Se mitigó en el asistente; juntarlas en una consulta cambiaría
  los tipos que devuelve y queda pendiente.
- Las pruebas de integración (`PRUEBAS_INTEGRACION=1`) no se ejecutaron aquí: escriben en la base
  configurada y en local es la de desarrollo. Ejecutarlas en CI con su base propia.
- Los archivos de TDR viven en el disco del worker (`TDR_DIR`): con API y worker en servicios
  distintos hace falta un volumen compartido; con dos réplicas del worker, el mismo volumen.
- Cobro de IA: si el proceso muere entre `consumir` y `devolver`, ese crédito no se devuelve.
