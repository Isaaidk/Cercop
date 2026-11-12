# Arquitectura hexagonal y resiliencia: que un servicio caído no tumbe el monolito

## 1. Objetivo

El pedido: «principios SOLID, modularidad y arquitectura hexagonal, para 500 a 1.000 usuarios
concurrentes, y que si un servicio se cae no caiga todo el monolito».

El backend ya era un monolito modular con capas (`dominio`, `aplicacion`, `infraestructura`,
`tareas`). Esta fase hace tres cosas:

1. **Aísla cada dependencia externa** con tiempos límite, cortacircuitos y compartimentos, y
   corrige dos sitios donde una dependencia *opcional* podía apagar el API entero.
2. **Invierte dependencias** en los casos de uso más nuevos (puertos `Protocol`) y añade una prueba
   de arquitectura que impide que la deuda crezca.
3. **Revisa la capacidad** y deja recomendaciones concretas.

## 2. Mapa de módulos y puertos

```
dominio/            reglas puras. No importa nada de fuera (lo comprueba test_arquitectura).
aplicacion/
  casos_uso/        orquestan reglas. Dependen de puertos, no de adaptadores.
  puertos/          contratos (typing.Protocol) que la infraestructura implementa.
infraestructura/
  adaptadores/entrada/http/   FastAPI: enrutadores, dependencias, límites, protección.
  adaptadores/salida/         PostgreSQL (bd/), Redis (cache/, presencia/), SRI, OCDS, NCO, IA, PDF…
  adaptadores/salida/resiliencia.py   cortacircuitos y compartimentos (nuevo).
  config/ajustes.py           toda la configuración, validada.
tareas/             worker: ingesta, vigilancia, alertas, TDR. Proceso aparte del API.
```

Puertos nuevos en esta fase:

| Puerto | Archivo | Lo implementa | Lo usa |
|---|---|---|---|
| `RepositorioPerfil` | `puertos/perfil.py` | `bd/perfil.py` | `gestionar_perfil`, `ver_radar` |
| `ConsultaRuc` | `puertos/perfil.py` | `salida/sri.py` | `gestionar_perfil` |
| `HistorialContratos` | `puertos/perfil.py` | `salida/historial.py` | `gestionar_perfil` |
| `ExtractorTextoPdf` | `puertos/perfil.py` | `salida/pdf.texto_de_pdf` | `gestionar_perfil.leer_rup_pdf` |
| `CandidatosRadar` | `puertos/radar.py` | `bd/radar.py` | `ver_radar`, vista previa de alertas |
| `RepositorioAlertas` | `puertos/radar.py` | `bd/radar.py` | `revisar_alertas` (worker) |
| `RepositorioSeguimiento` | `puertos/seguimiento.py` | `bd/seguimiento.py` | `seguimiento_ofertas` |
| `RepositorioMercado` | `puertos/mercado.py` | `bd/mercado.py` | `ver_mercado` |

Los puertos son estrechos a propósito (segregación de interfaces): `CandidatosRadar` tiene un solo
método porque es lo único que necesitan el radar y la vista previa; `RepositorioAlertas` lo amplía
con lo que necesita el worker. Los adaptadores existentes los cumplen sin heredar de nada, así que
no cambió ningún contrato HTTP ni ninguna firma de adaptador. El único cambio de firma es
`leer_rup_pdf(..., extraer_texto=...)`, que ahora recibe el extractor desde el enrutador.

## 3. Cómo se aísla cada dependencia

### 3.1 La pieza común: `infraestructura/adaptadores/salida/resiliencia.py`

- **Cortacircuitos por servicio**, en la memoria de cada proceso. Estados `cerrado` → `abierto`
  (tras `umbral_fallos` fallos seguidos) → `semiabierto` (pasado `enfriamiento_seg`, deja pasar
  **una** llamada de prueba; si sale bien se cierra, si falla se vuelve a abrir).
- **Compartimento** (*bulkhead*): un semáforo por servicio (`max_concurrencia`). Quien llega con el
  compartimento lleno espera `espera_turno_seg` y, si no hay sitio, recibe «demasiadas consultas en
  curso» en vez de hacer cola sin fin.
- **Tope total** opcional (`limite_seg`) sobre la operación entera, que acota los reintentos.
- **Qué es un fallo**: errores de red, tiempos agotados, respuestas 5xx o 429, buscando también en
  la cadena de causas (`raise … from error`). Un `NoEncontrado`, un 404 o un JSON raro **no** son
  fallos: el servicio respondió. Así diez RUC mal escritos no cortan el SRI a todos.
- Abierto o lleno, se lanza `ServicioNoDisponible`, un error de dominio nuevo que **hereda de
  `EstadoInvalido`** (todo el código que ya lo atrapaba sigue igual) y que el API traduce a **503**
  con `codigo: "servicio_no_disponible"` y un mensaje que dice qué pasa y que basta con reintentar.
- El estado de todos los circuitos se publica en `GET /listo` (`circuitos`), con contadores de
  aperturas y rechazos.

### 3.2 Configuración por servicio

| Servicio | Circuito | Umbral | Enfriamiento | Compartimento | Tope total | Tiempo por llamada |
|---|---|---|---|---|---|---|
| SRI (consulta de RUC) | `sri` | 5 | 60 s | 8 a la vez, espera 3 s | 20 s | 12 s (conexión 6 s) |
| Datos abiertos OCDS (historial del perfil) | `ocds_historial` | 3 | 120 s | 6 recorridos, espera 2 s | 60 s | 25 s (conexión 8 s) |
| IA (proveedor OpenAI-compatible) | `ia` | 4 | 45 s | 4 × `IA_CONCURRENCIA`, espera 5 s | — | `IA_TIEMPO_SEG` (45 s) × 3 intentos |
| Redis (caché, sesiones vivas, presencia) | `redis` | 3 | 15 s | — (lo limita el pool de Redis) | — | `CACHE_TIMEOUT_SEG` (2 s) |

La IA conserva además su semáforo de llamadas en vuelo (`IA_CONCURRENCIA`); el compartimento del
circuito limita cuántas pueden *esperar* turno.

## 4. Qué pasa cuando cae cada dependencia

| Dependencia | Antes | Ahora (respuesta del sistema) |
|---|---|---|
| **SRI** | Cada registro/consulta de RUC esperaba hasta 12 s y respondía 409. Con muchas a la vez, corrutinas retenidas sin tope. | Tras 5 fallos, durante 60 s: **503 inmediato** «El SRI no responde ahora…; llena los datos a mano». Como mucho 8 consultas colgadas por proceso. El resto del API intacto. |
| **Datos abiertos (OCDS) desde el perfil** | Hasta 25 s × varios años por petición; sin tope de recorridos simultáneos. | Tras 3 fallos, 503 inmediato 2 min. Máximo 6 recorridos por proceso. |
| **IA** | 3 intentos × 45 s + esperas: más de 2 minutos por petición antes de fallar; cola sin tope en el semáforo. | Tras 4 fallos (red, 5xx, 429), 503 inmediato 45 s. Cola acotada a 4 × concurrencia. Un 4xx (clave o modelo mal configurados) no abre el circuito. |
| **Redis** | Sin tiempo límite en el cliente: con el servidor inalcanzable, cada comando esperaba lo que tardara el SO (20 s–2 min) **en casi todas las peticiones**. Y `/listo` daba 503 → el balanceador sacaba **todas** las réplicas → API caído entero. | Tope de 2 s y circuito: tras 3 fallos, durante 15 s ni se intenta. Las lecturas degradan a la base (ya estaba programado: generación = 0, permisos recalculados, sesión viva = «sin respuesta» → se comprueba en PostgreSQL). `/listo` sigue en **200** con `"degradado": true`. Ver 4.1 para lo que sí deja de funcionar. |
| **PostgreSQL saturado** | (ya resuelto antes) | `bd/saturacion.py` + manejador: **503** `bd_saturada` en vez de 500; el pool espera como mucho `BD_POOL_TIMEOUT_SEG` (5 s). Sin cambios en esta fase. |
| **PostgreSQL caído/inalcanzable** | Abrir conexión esperaba los 60 s por defecto de asyncpg en cada petición. | `BD_CONEXION_TIMEOUT_SEG` (10 s). `/listo` da 503 con el motivo: es la única dependencia imprescindible. |
| **Portal SERCOP (NCO/TDR)** | Solo lo usa el **worker**: no afecta al API. Ya tenía limitador de tasa, enfriamiento tras 429 y salidas con enfriamiento de 2 min tras 3 fallos (`fuentes/salidas.py`). | Sin cambios: ya es un cortacircuitos por salida. |
| **Correo (SMTP)** | `salida/correo.py` no tiene llamadores hoy. | Sin cambios. Si se usa desde el API, hay que llevarlo a un hilo (`en_hilo`) o al worker: `smtplib` es síncrono y bloquearía el bucle de eventos hasta 20 s. |
| **Una tarea del worker** | Cada etapa del bucle está envuelta en `try/except` con registro. | Verificado: un ciclo, una vigilancia, un TDR o una alerta que fallan no matan el bucle. El worker es otro proceso: si cae, el API sigue. |

### 4.1 Lo que deja de funcionar con Redis caído (decisión pendiente)

- **Iniciar sesión** falla con 503 «El almacén de sesiones no responde…». Es deliberado y está
  documentado en `aplicacion/sesiones_vivas.py::abrir`: si la sesión se abriera sin anotarla, al
  volver Redis la clave ausente significaría «cerrada» y la persona recibiría un 401 nada más
  entrar. Las sesiones **ya abiertas** siguen funcionando (se comprueban en PostgreSQL).
  Alternativa a evaluar: abrir sin clave cuando el circuito `redis` está abierto y, al volver
  Redis, tratar la ausencia como «sin respuesta» durante un margen igual al de inactividad.
- **Cerrar sesión / revocar** también propaga el fallo (para no decir «cerrada» sin cerrarla).
- **Presencia** (latido, panel de conectados): responde 503 rápido en lugar de colgarse.
- **Pedir un ciclo de ingesta a mano** desde el panel: se rechaza (el worker lo lee de Redis).

## 5. Capacidad para 500–1.000 concurrentes

La aritmética ya estaba resuelta y verificada por `backend/scripts/verificar_despliegue.py`
(ver `docs/07-capacidad-y-concurrencia.md`):

    (API_WORKERS + 1) × (BD_POOL_SIZE + BD_MAX_OVERFLOW) ≤ max_connections
    (4 + 1) × (10 + 10) = 100 ≤ 200

No se encontró un error claro en los valores por defecto, así que no se cambiaron. Lo que sí se
añadió son los dos topes que faltaban (`BD_CONEXION_TIMEOUT_SEG`, `CACHE_TIMEOUT_SEG`).

Recomendaciones, en orden de impacto:

1. **No retener conexiones de la base mientras se espera a un servicio externo.** Es el riesgo real
   a 1.000 usuarios: una petición que lee la base y después llama al SRI o a la IA retiene la
   conexión todo ese tiempo. Los compartimentos ya limitan cuántas pueden hacerlo a la vez (8 SRI,
   6 OCDS, 16 IA por proceso con los valores por defecto), lo que deja margen en un pool de 20.
   Si se sube `IA_CONCURRENCIA`, subir el pool en proporción o hacer el commit antes de llamar.
2. **Réplicas del API**: con varias réplicas, cada una suma su pool. Con PostgreSQL gestionado y
   tope bajo de conexiones, poner **PgBouncer en modo transacción** delante y bajar el pool por
   proceso (p. ej. 5 + 5). En modo transacción, asyncpg necesita
   `prepared_statement_cache_size=0` (o `statement_cache_size=0`) en la URL; **no se ha aplicado**
   porque el despliegue actual va directo a PostgreSQL.
3. **Redis es necesario para escalar horizontalmente** (sesiones vivas, presencia compartida,
   generación del caché): sin él, cada lectura cara va a la base. Vigilar `"degradado"` en `/listo`.
4. **Uvicorn**: un proceso por núcleo (`API_WORKERS`), como ya indica `.env.example`. Las peticiones
   son de E/S; más procesos no dan más capacidad si la base es el cuello.
5. **Límites por usuario**: ya existen `LimitePorUsuario` en las rutas caras y freno por IP en
   inicio de sesión y registro (`proteccion.py`). Mantenerlos en toda ruta nueva que llame a un
   servicio externo.
6. **Tiempo máximo de consulta en PostgreSQL** (`statement_timeout`): no se aplicó porque el worker
   ejecuta consultas largas legítimas (ingesta, mantenimiento). Si se quiere, ponerlo por rol
   (`ALTER ROLE api SET statement_timeout = '15s'`) con un rol distinto para el worker.

## 6. Verificación

- `pruebas/unidad/test_resiliencia.py` (21 pruebas): apertura tras el umbral sin llamar al servicio,
  errores de negocio que no cuentan, semiabierto con una sola llamada de prueba, reapertura,
  compartimento lleno, tope total, clasificación de fallos y cadena de causas, el SRI real con un
  transporte caído, la traducción a 503, Redis caído (generación = 0, sesión «sin respuesta»,
  circuito abierto con fallo inmediato) y `/listo` en 200 con caché caída y 503 sin base.
- `pruebas/unidad/test_arquitectura.py` (6 pruebas): el dominio no importa aplicación,
  infraestructura ni bibliotecas de E/S; ningún caso de uso fuera de la lista de deuda importa la
  infraestructura; la lista de deuda no conserva módulos ya corregidos; los cinco módulos pasados
  a puertos no retroceden.
- `conftest.py` reinicia los circuitos después de cada prueba.

## 7. Pendiente

Casos de uso que todavía importan adaptadores (están en `DEUDA_CONOCIDA` de la prueba de
arquitectura, que impide añadir más):

| Módulo | Importa | Puerto propuesto |
|---|---|---|
| `generar_oferta.py` | `RepositorioCreditos`, `RepositorioDocumentos`, `RepositorioPerfil`, `ModeloIa` | `ModeloLenguaje` (`completar`, `completar_json`, `disponible`), `RepositorioCreditos`, `LecturasDocumento`; perfil ya existe |
| `preparar_documentos.py` | 6 repositorios, `ModeloIa`, `texto_de_pdf` | los mismos + `ExtractorTextoPdf` (ya existe). Se dejó para no chocar con el trabajo en curso sobre `dominio/documentos.py` |
| `atender_tdr.py` | `descargar_a`, `TopeExcedido`, `RepositorioTdr`, `PoolSalidas`, `httpx` | `DescargadorTdr` y `RepositorioTdr`; la construcción del pool pasa a `tareas/worker.py` |
| `ejecutar_ingesta.py` | `bd.ingesta` | `RepositorioIngesta` (los métodos que usa) |

Otros pendientes:

- Decidir el comportamiento del inicio de sesión con Redis caído (4.1).
- El estado de los circuitos es por proceso; si se quisiera una vista agregada, sumar los `/listo`
  de cada réplica desde el monitor, no compartir estado (sería otra dependencia que puede caer).
- Llevar `correo.py` a un hilo o al worker antes de usarlo desde el API.
