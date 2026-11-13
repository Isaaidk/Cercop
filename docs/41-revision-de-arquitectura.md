# Revisión de arquitectura: 500+ personas a la vez sin perder velocidad

## 1. Objetivo y reglas

Revisar la arquitectura y optimizar para 500+ usuarios concurrentes **sin quitar funciones y sin
debilitar el aislamiento entre empresas ni la seguridad**. Punto de partida: `docs/07`, `docs/16`,
`docs/36` (resiliencia) y `docs/39` (índices de 0040, topes de PostgreSQL, cachés acotadas, cola de
TDR con `SKIP LOCKED`, sondeos con espera creciente, Chart.js perezoso). No se repitió nada de eso:
aquí se midió lo que quedaba.

Reglas que se respetaron:

- Toda caché de datos de una empresa lleva `negocio_id` o el usuario en la llave. Lo único que se
  comparte entre peticiones es el **histórico público**, y solo con la llave del caché ya existente
  (generación + filtros + fuentes visibles).
- Las comprobaciones de seguridad por petición (sesión viva, empresa suspendida, contraseña
  temporal, políticas pendientes, vistas) se siguen haciendo **en cada petición**, sin caché nueva.
- Índices nuevos con `CREATE INDEX IF NOT EXISTS`, nunca `CONCURRENTLY`.

## 2. Arquitectura actual

```
                    navegador (Vue 3 + Vite, panel SPA)
                       │  HTTPS: JSON, sondeo de versión 60 s, latido 30 s, SSE de presencia
                       ▼
 ┌──────────────── Railway ─────────────────────────────────────────────────────────┐
 │  api  (uvicorn × API_WORKERS=2, FastAPI)                                          │
 │   ├─ entrada/http: routers → dependencias (actor, puerta, vistas, límites)        │
 │   │     freno por IP / por usuario: MEMORIA DE CADA PROCESO                       │
 │   ├─ aplicacion/casos_uso  (puertos Protocol)                                     │
 │   └─ salida: bd/ (SQLAlchemy async + asyncpg, pool 10+10 por proceso)            │
 │             cache/ (Redis: sesiones vivas, generaciones, permisos, resultados)    │
 │             SRI · OCDS · IA  (cortacircuitos + compartimentos, docs/36)           │
 │                    │                         │                                    │
 │                    ▼                         ▼                                    │
 │            PostgreSQL 16  ◄──────────  worker (1 proceso: ingesta, alertas,       │
 │            RLS por app.negocio_id        vigilancia, cola TDR; sin statement      │
 │            rol contratacion_app          timeout; pool propio)                    │
 │                    ▲                         │                                    │
 │                    └──────── Redis ◄─────────┘ (generación, petición de ciclo)    │
 └───────────────────────────────────────────────────────────────────────────────────┘
```

Cada lectura de datos de una empresa abre su propia transacción con
`contexto_negocio` (`BEGIN` → `set_config('app.negocio_id')` → consulta → `COMMIT`: **4 viajes** a
la base por cada conexión que toma del pool). Las del histórico usan `sin_contexto` (3 viajes).

## 3. Cómo se midió

- Banco **dentro del proceso** (FastAPI + httpx `ASGITransport`) contra la base local (PostgreSQL
  16, 6.609 registros, 21.214 requisitos, 1.253 lecturas), con un oyente de SQLAlchemy que cuenta
  **sentencias** y **conexiones tomadas del pool** por petición. 15 repeticiones por ruta tras una de
  calentamiento, y una ráfaga de **300 peticiones a la vez** mezclando 23 rutas (un solo proceso,
  pool 10+10, el mismo de producción por proceso). El freno por usuario se desactivó solo en el
  banco.
- Dos modos: sin Redis (como está el entorno local) y con un sustituto de Redis en memoria (como
  producción: sesión viva, vistas y resultados en caché).
- El «antes» se midió sobre un `git worktree` de `HEAD` y el «después» sobre el árbol con los
  cambios, uno detrás del otro y en la misma máquina. Los tiempos absolutos varían con la carga de
  la máquina (había otros procesos trabajando); lo que importa son **sentencias, conexiones, tamaño
  y la ráfaga**.
- `EXPLAIN (ANALYZE, BUFFERS)` y `cProfile` para las rutas que salieron caras.

## 4. Cuellos de botella encontrados (con números)

### 4.1 La puerta de cada petición: 3 conexiones antes de empezar a trabajar

Todas las rutas autenticadas leían, cada una con su conexión y su transacción:

| Lectura | Dónde |
|---|---|
| `negocio` (¿suspendida?) | `obtener_actor` |
| `usuario` (¿contraseña temporal?) | `consentimiento_del_actor` |
| `usuario` otra vez (`debe_aceptar_politica_version`) | `exigir_aceptado` |

3 conexiones y 12 viajes por petición, también en el latido de presencia (cada 30 s) y en la
comprobación de novedades (cada 60 s): con 500 paneles abiertos son ~25 peticiones/s de fondo, ~75
conexiones/s tomadas solo para decir «sí, puedes pasar».

### 4.2 CPU dentro del bucle de eventos en «Propuestas para ti», radar e inicio del asistente

`cProfile` de 10 peticiones a `/v1/propuestas`: **5,7 s**, el 70 % en `dominio/radar.plegar`
(quitar tildes carácter a carácter en Python): 7.525 llamadas y 550.000 caracteres por petición.
Sin perfilador, ~100 ms de CPU por petición **bloqueando el proceso entero**. El inicio del
asistente calcula lo mismo (contador de propuestas). Con 500 personas, es el techo del proceso.

### 4.3 `/v1/documentos/requisitos` sin tope: 6,8 MB por petición

Sin `lectura_id` devolvía **todos** los requisitos de **todas** las lecturas de la empresa,
intercalados por número (R1 de cada TDR, después R2…): 21.214 filas, **6,8 MB**, 240–535 ms. Y el
panel lo pedía en `onMounted` de «Preparar oferta», **cada vez que se abría la pestaña**, antes de
haber leído ningún TDR. El asistente («¿qué me falta?») también traía la lista entera para quedarse
con 12.

### 4.4 Catálogos de filtros: 15 descompresiones del `jsonb` por fila

`EXPLAIN (ANALYZE, BUFFERS)`: `unnest(campos) JOIN registro ON jsonb_exists(...)` con dos `->>` por
campo ⇒ el `datos` de cada fila (TOAST) se descomprimía 15 veces: **258.091 bloques** leídos para
6.609 filas, **172 ms** (240 ms con `EXPLAIN`). Crece lineal con el histórico: con las ~110.000
filas de producción son **segundos**, y se recalcula en cada cambio de generación.

### 4.5 Estampida tras subir la generación

La generación del caché sube con cada ciclo de ingesta con cambios. En ese instante **todas** las
claves dejan de encontrarse y los primeros N paneles piden a la vez exactamente lo mismo
(catálogos, gráficas sin filtros, primera página): N consultas idénticas compitiendo por 20
conexiones, justo cuando el caché no ayuda.

### 4.6 Otros

| Hallazgo | Medida |
|---|---|
| Saldo de IA: `INSERT … ON CONFLICT DO NOTHING` en **cada lectura** (inicio del asistente, créditos) | 1 escritura intentada + 1 viaje extra por lectura |
| `usuario` sin índice por `negocio_id` (lista de cuentas, recuentos del plan, accesos) | `Seq Scan on usuario` (todas las empresas) |
| `compra_ia` sin índice por `negocio_id` (últimas 10 compras en cada lectura del saldo) | `Seq Scan` + `Sort` |
| Subida de la plantilla de Excel: ZIP + `openpyxl` en el bucle de eventos | pendiente de docs/39 §5 |
| Perfil de la empresa: 11 consultas secuenciales en una conexión | 14–16 sentencias en `/v1/empresa/perfil`, propuestas, radar |
| Paquete del panel | `index` 334 kB (109 kB gzip); el resto ya es perezoso (Documentos 77 kB, pdf.js, jsPDF, Chart.js aparte) |
| Sondeos del panel | ya razonables (60 s novedades, 5 min vistas, latido 30 s/48 s oculto, pausa con pestaña oculta) |

## 5. Qué se cambió

| # | Cambio | Archivos |
|---|---|---|
| 1 | **Puerta de entrada en una consulta**: `negocio LEFT JOIN usuario` en el contexto RLS de la empresa del token, guardado en `request.state`; `consentimiento_del_actor` lo reutiliza (si es del mismo actor) y aplica **las mismas reglas en el mismo orden**: cuenta no visible ⇒ `NoEncontrado` (falla cerrada), contraseña temporal ⇒ 403, política pendiente ⇒ 403. Sin estado (atajo de desarrollo) se usa el camino de siempre. | `bd/entrada.py` (nuevo), `entrada/http/dependencias.py`, `casos_uso/consentimiento.py` (`exigir_sin_pendiente`), `bd/politicas.py` (`CUENTA_NO_VISIBLE`) |
| 2 | **`plegar` en C**: `str.translate` con una tabla que se rellena sola (`__missing__` pregunta a `unicodedata.combining`, la misma función de antes) + atajo ASCII + `lru_cache(8192)` solo para textos ≤ 200 caracteres. Función pura: el recuerdo no depende de quién pregunta. Probado igual al de antes en **todo Unicode**. | `dominio/texto.py` (nuevo), `dominio/radar.py` |
| 3 | **Requisitos con tope**: con `lectura_id`, igual que antes. Sin ella, las de las lecturas más recientes primero, agrupadas por lectura, máximo 500. Filtro `estado` y `limite` para el asistente (pide 12 pendientes a la base). El panel ya no los pide al montar si no hay lectura. | `bd/documentos.py`, `casos_uso/preparar_documentos.py`, `frontend/src/components/Documentos.vue` |
| 4 | **Catálogos con una descompresión por fila**: `jsonb_to_record(r.datos)` + `VALUES` lateral. Resultado comparado fila a fila con la consulta anterior: idéntico (541 filas). | `bd/consultas.py` |
| 5 | **Una consulta para peticiones idénticas a la vez** («single flight»): catálogos, estadísticas y búsqueda, **solo** cuando la consulta ya es `cacheable` y con la **misma llave del caché** (generación + filtros + fuentes visibles). El cálculo va en su propia tarea (si se va quien lo empezó, los demás no reciben su cancelación) y se olvida al terminar: no guarda nada. Cada llamador recibe su copia del diccionario. | `aplicacion/coalescer.py` (nuevo), `casos_uso/buscar_registros.py` |
| 6 | Saldo de IA: se lee primero y solo se abre si no existe (`ON CONFLICT` sigue garantizando un solo regalo). | `bd/creditos.py` |
| 7 | Revisión de la plantilla de Excel subida, en un hilo (`en_hilo`). | `casos_uso/gestionar_plantilla.py` |
| 8 | Migración **`0045_optimizacion.py`** (`down_revision = "0044"`): `ix_usuario_negocio (negocio_id)` y `ix_compra_ia_negocio_creado (negocio_id, creado_en DESC)`. Plan: `Seq Scan` ⇒ `Index Scan` / `Bitmap Index Scan` (comprobado en una transacción revertida y luego aplicada en local con `alembic upgrade head`). | `alembic/versions/0045_optimizacion.py` |
| 9 | Pruebas: equivalencia de `plegar` (todo Unicode + casos raros: `İ`, ligaduras, marcas sueltas), single flight (comparte, no mezcla claves, no recuerda, propaga errores, sobrevive a la cancelación del primero), y la puerta (deja pasar sin volver a la base, bloquea contraseña temporal y políticas, falla cerrada sin cuenta, ignora un estado de otro actor). | `pruebas/unidad/test_revision_rendimiento.py` (19) |

No se tocó: `app.py`, `proteccion.py`, `limites.py`, `routers/politicas.py`, migraciones previas,
`App.vue`, `main.js`, `api/endpoints.js` ni las pantallas públicas.

## 6. Antes / después

### 6.1 Por ruta (con Redis, como producción; mediana de 15)

| Ruta | Sentencias | Conexiones | Tamaño | Mediana |
|---|---|---|---|---|
| `/v1/registros` (página 1, en caché) | 6 → **2** | 3 → **1** | 83 kB | 24,7 → **14,6 ms** |
| `/v1/estadisticas` (en caché) | 6 → **2** | 3 → **1** | 3 kB | 21,2 → **13,6 ms** |
| `/v1/catalogos` (en caché) | 6 → **2** | 3 → **1** | 26 kB | 21,9 → **11,9 ms** |
| `/v1/ingestas/version` (sondeo de cada panel) | 6 → **2** | 3 → **1** | — | 18,2 → **11,8 ms** |
| `/v1/documentos/requisitos` (sin lectura) | 8 → 4 | 4 → 2 | **6.866 kB → 161 kB** | **535 → 62 ms** |
| `/v1/alertas`, `/v1/avisos`, `/v1/mis-ofertas` | 8 → 4 | 4 → 2 | = | 23–27 → **14–15 ms** |
| `/v1/propuestas` | 20 → 16 | 5 → 3 | 12 kB | 40,7 → 38,3 ms (en caché de Redis) |
| `/v1/radar` | 21 → 17 | 6 → 4 | — | 80,9 → **58,0 ms** |
| `/v1/asistente/inicio` | 32 → 27 | 10 → 8 | — | 61,1 → 63,5 ms (ruido) |
| `/v1/ia/creditos` | 6 → 5 | 2 → 2 | — | 15,4 → 14,3 ms |

### 6.2 Sin caché (peor caso: cambio de generación, o Redis caído)

| Ruta | Antes | Después |
|---|---|---|
| `/v1/catalogos` | 512 ms (11 sentencias, 6 conexiones) | **129 ms** (7, 4) |
| `/v1/propuestas` | 261 ms; CPU perfilada 5,7 s / 10 peticiones | **159 ms**; CPU perfilada **1,2 s / 10** (el resto es espera de E/S) |
| `/v1/asistente/inicio` | 251 ms (37 sentencias, 13 conexiones) | **146 ms** (32, 11) |
| `/v1/documentos/requisitos` | 525 ms, 6,8 MB | **62 ms, 161 kB** |
| `/v1/registros` (página 1) | 12 sentencias, 6 conexiones | 8, 4 |

### 6.3 Ráfaga de 300 peticiones a la vez (un proceso, pool 10+10)

| Modo | Antes | Después |
|---|---|---|
| Con Redis | 14,0 s · **21,5 pet/s** · p50 7,0 s · p95 12,1 s · **38 × 503** (pool agotado) · 1.042 conexiones del pool | **5,6 s · 53,9 pet/s · p50 3,3 s · p95 4,9 s · 0 errores** · 638 conexiones del pool |
| Sin Redis | 16,6 s · 18,0 pet/s · p95 14,8 s · **79 × 503** · 1.357 conexiones | 10,2 s · 29,3 pet/s · p95 9,3 s · 4 × 503 · 1.117 conexiones |

×2,5 de capacidad por proceso con Redis, sin errores. (La ráfaga es deliberadamente brutal: 300
peticiones en el mismo milisegundo contra **un** proceso; en producción hay 2 procesos por réplica
y las peticiones no llegan todas a la vez.)

## 7. Recomendaciones pendientes (por prioridad)

| # | Recomendación | Impacto | Esfuerzo |
|---|---|---|---|
| 1 | **Freno por IP/usuario en Redis** (`proteccion.py`, `limites.py`; no editados aquí por ser de otro trabajo). Hoy vive en la memoria de cada proceso: con 2 procesos × N réplicas el tope real es ×2N, y un reinicio lo pone a cero. Contador con `INCR` + `EXPIRE` por ventana (o ventana deslizante con un script Lua), con degradación a memoria si Redis no responde (como ya hace el resto del caché). | Alto (seguridad y raspado) | Medio (1 día) |
| 2 | **Escalar horizontalmente el API en Railway**: 2–3 réplicas × `API_WORKERS=2`. El código ya lo admite (sesiones, generaciones, permisos y presencia en Redis; tareas idempotentes en el worker). Redis es **obligatorio** con más de una réplica. Revisar la cuenta de conexiones (fila 3). | Alto | Bajo (configuración) |
| 3 | **PgBouncer en modo transacción** delante de PostgreSQL al pasar de ~100 conexiones: `(réplicas × procesos × (pool + overflow)) + worker` crece rápido (3 × 2 × 20 = 120). Con PgBouncer, pool por proceso 5+5 y `prepared_statement_cache_size=0` en la URL de asyncpg. `SET LOCAL`/`set_config(..., true)` es por transacción, así que **el RLS sigue funcionando en modo transacción**; el worker (bloqueo de asesoría de sesión, transacción larga) debe ir **directo** a PostgreSQL, no por PgBouncer. | Alto a partir de 2+ réplicas | Medio |
| 4 | **Separar el worker** en servicios por tarea: ingesta (larga, pesada), alertas/vigilancia (ligeras, frecuentes) y cola de TDR (red). Hoy una ingesta lenta retrasa las alertas. Los bloqueos de asesoría y `SKIP LOCKED` ya permiten varias réplicas. Recordar el volumen compartido de `TDR_DIR` o seguir con `archivo_tdr` en la base. | Medio | Medio |
| 5 | **CDN para el panel** (Cloudflare delante del servicio `frontend`, o el `dist/` en un bucket): los `assets/*-[hash].js` son inmutables (`Cache-Control: public, max-age=31536000, immutable`), `index.html` con `no-cache`. Quita del contenedor todo el tráfico estático (pdf.worker 1,4 MB, pdf.js 410 kB, jsPDF 358 kB). | Medio | Bajo |
| 6 | **Perfil de la empresa en un viaje**: hoy 11 consultas secuenciales (identidad + 10 colecciones) en propuestas, radar, perfil y asistente. Juntarlas (`json_agg` por colección o arrays de tipo compuesto) cambia los tipos que devuelve (fechas/decimales como texto) y hay que convertir; o recordarlo en Redis con llave `negocio_id` e invalidación al guardar el perfil. | Medio (≈10 viajes por petición en 4 rutas) | Medio |
| 7 | **Cachear el saldo y la lista de conversaciones del inicio del asistente** por `negocio_id`/`usuario_id` unos segundos, o bajar `PARALELO_INICIO` a conexiones compartidas: sigue siendo la ruta con más conexiones (8 con Redis). | Medio | Bajo |
| 8 | **`App.vue` perezoso** (lo edita otro trabajo): las pantallas públicas (`PantallaInicio`, `PantallaRegistro`, `PantallaContratacionPublica`) y `VistaPanel` van en el `index` (334 kB). Con `defineAsyncComponent`, quien entra al panel no baja la portada y al revés. | Bajo-medio (primer pintado) | Bajo |
| 9 | **`count(*)` exacto en cada página sin filtros**: con 110.000 filas se resuelve por índice y está en caché, pero tras cada cambio de generación lo paga la primera petición. Si crece a millones: estimación (`reltuples`) para la vista sin filtros, o el total en la caché del ciclo de ingesta. | Bajo hoy | Bajo |
| 10 | **Requisitos sin lectura**: el orden «lecturas más recientes primero» hace un top-N sobre todos los requisitos de la empresa (21.000 filas, ~10 ms). Si una empresa llega a cientos de miles, índice `(negocio_id, lectura_id)` + `lectura_documento (negocio_id, creado_en DESC)` (ya existe) con un `LATERAL` por lectura. | Bajo | Bajo |
| 11 | **Medir en producción**: activar `pg_stat_statements` en el PostgreSQL de Railway y revisar cada semana las 20 consultas de más tiempo total; vigilar `pg_stat_activity` por `application_name` (`cercoapp-api` / `cercoapp-worker`). | Alto para decidir lo siguiente | Bajo |
| 12 | **Prueba de carga real** con `carga/panel.js` (k6) contra un entorno de ensayo con Redis y 2 réplicas antes de cada salto de escala (no contra producción). | Alto | Bajo |

## 8. Riesgos y notas

- **0045 cuelga de 0044** (`politicas_lopdp`, de otro trabajo en curso). Si 0044 cambiara de
  número, ajustar `down_revision` o habrá dos cabezas. En local ya están aplicadas las dos.
- La puerta en una consulta solo reutiliza lo leído si el actor del estado coincide (usuario y
  empresa) y vive en `request.state`, que es de esa petición. Una suspensión, una contraseña
  temporal o una política nueva se notan en la **siguiente** petición, como antes.
- El single flight comparte solo resultados del **histórico público** con la **misma llave del
  caché** (que ya incluye las fuentes visibles de quien pregunta) y solo mientras la consulta está
  en curso; no se usa con datos de una empresa ni con búsquedas de texto libre (no `cacheable`).
- La tabla de `plegar` crece con cada carácter distinto visto (como mucho unos miles en la
  práctica; el dominio de Unicode completo serían ~1,1 M entradas si alguien enviara todo Unicode).
- El listado de requisitos sin lectura cambia de orden (antes intercalado por número, sin utilidad)
  y queda en 500 filas; con `lectura_id` no cambia nada.

## 8. Prueba de carga real (2026-11-13, entorno «PruebaUsuariosConsurrentes» en Railway)

Mismo código y misma configuración que producción, base con las 6.208 ínfimas públicas, usuario de
base restringido (`contratacion_app`). k6 desde Ecuador (`carga/panel.js`): escalera 50 → 200 →
500 → **1.000 usuarios simultáneos**, cada uno con su empresa y su cuenta.

| | 2 procesos (pool 10+10) | **4 procesos (pool 8+4)** |
|---|---|---|
| Lecturas atendidas | 103.325 | **150.279** |
| Comprobaciones fallidas | 0 | **0** |
| Tabla: mediana / p95 | 665 ms / 2,8 s | **287 ms / 0,56 s** |
| Gráficas: mediana / p95 | 625 ms / 2,7 s | **256 ms / 0,53 s** |
| Asistente (mensaje): mediana / p95 | 1.473 ms / 5,7 s | **413 ms / 1,0 s** |
| Propuestas: mediana / p95 | 938 ms / 4,0 s | **341 ms / 0,74 s** |
| CPU del API en el pico | ~2,5 núcleos (saturado) | ~4,8 núcleos de 8 |

Las medianas incluyen ~150–200 ms de ida y vuelta Ecuador ↔ Railway. Las 1.000 respuestas 401 que k6
cuenta como «fallos» son la caducidad del token de acceso, seguida de su renovación (como el panel).

**Conclusión**: con 2 procesos el cuello de botella era la CPU del API (Python usa un núcleo por
proceso), no la base (< 1 núcleo). Producción pasa a `API_WORKERS=4`, `BD_POOL_SIZE=8`,
`BD_MAX_OVERFLOW=4` (4 × 12 + worker 20 = 68 conexiones, por debajo de las 100 de PostgreSQL).
Para más de ~1.500 usuarios: réplicas del API + limitadores en Redis + PgBouncer (§7).
