# documentacion.md
# Plataforma SERCOP Multi-Tenant — Documentación del Proyecto

| Campo | Valor |
|---|---|
| Proyecto | Plataforma de inteligencia de contratación pública (SERCOP) multi-tenant |
| Versión del documento | 0.1 (borrador) |
| Estado | En planificación — F0 no iniciada |
| Responsable de mantenimiento | Ingeniero QA |
| Última actualización | 2026-09-27 |

> **Documento vivo.** Cada fase cierra completando su sección en el capítulo 10. Una fase sin
> documentación no está terminada.

---

## 1. Resumen ejecutivo

Herramienta SaaS que convierte los datos públicos de contratación del SERCOP (Ecuador) en
información oportuna para consultorías: acumula histórico propio, permite consultas multi-palabra
de respuesta rápida, exporta a Excel sin límite y conserva evidencia de cumplimiento legal.
La arquitectura es un monolito modular con capas hexagonales, dos procesos (`api` y `worker`),
PostgreSQL con aislamiento por negocio (RLS) y Redis como capa más cercana al cliente.

**Restricción que gobierna todo el diseño:** el SERCOP limita la tasa de peticiones (HTTP 429).
Ninguna acción de un usuario puede originar una petición a la fuente; solo el `worker` la consume,
con presupuesto acotado por ciclo.

---

## 2. Objetivos

### 2.1 Objetivo general
Disponer de una plataforma comercializable, segura y auditable que entregue inteligencia de
contratación pública con datos acumulados propios, soportando 50+ negocios sin degradar el
servicio ni saturar las fuentes oficiales.

### 2.2 Objetivos específicos

| # | Objetivo | Indicador | Meta | Fase |
|---|---|---|---|---|
| OE-1 | Acumular histórico propio de contrataciones | Ciclos exitosos por día | ≥1, con 0 pérdidas sin registro | F2 |
| OE-2 | Consulta rápida para el consultor | p95 de consulta cacheada | < 300 ms | F3 |
| OE-3 | Ingesta incremental correcta | Duplicados por clave natural | 0 | F2 |
| OE-4 | Desacoplar la BD del tráfico de usuarios | Aciertos de caché en hora pico | ≥ 80% | F3 |
| OE-5 | No bloquear el SERCOP | Peticiones originadas por usuarios | 0 | F2, F3 |
| OE-6 | Cumplir la LOPDP y demostrarlo | Usuarios con consentimiento versionado | 100% | F5 |
| OE-7 | Multiusuario seguro y aislado | Fugas entre negocios detectadas | 0 | F1, F4 |
| OE-8 | Visibilidad operativa en tiempo real | Latencia del cambio de presencia | < 2 s (proactivo) / ≤ 60 s (piso) | F4 |
| OE-9 | Calidad verificable | Cobertura en dominio y aplicación | ≥ 80% | Transversal |

---

## 3. Alcance

### 3.1 Incluido
Arquitectura multi-tenant con RLS · ingesta automática cada 15 min con deduplicación global ·
mapeo automático de filas y columnas · búsqueda multi-palabra (seleccionar y agregar) · capa
Redis-first · autenticación con roles y sesiones limitadas · panel de super administrador con
presencia en tiempo real · exportación a Excel sin tope (por criterios o por selección) ·
cumplimiento LOPDP · documentación y trazabilidad por fase.

### 3.2 Excluido
Escritura hacia el SERCOP (el sistema es de solo lectura) · microservicios · aplicación móvil ·
facturación y pasarela de pago · RediSearch · despliegue dedicado por cliente · eliminación del
módulo administrativo (queda para v2).

### 3.3 Alcance por fase

| Fase | Alcance |
|---|---|
| F0 | Repositorio seguro, entorno local, esqueleto hexagonal, CI |
| F1 | Modelo relacional multi-tenant, RLS, migraciones |
| F2 | Ingesta 15 min, mapeo automático, historial |
| F3 | Caché Redis-first, multi-palabra, ingesta bajo demanda |
| F4 | Auth, sesiones, evicción, presencia, super admin |
| F5 | Cumplimiento LOPDP: consentimiento, ARCO, retención, cifrado |
| F6 | Exportación sin tope, frontend, retiro del legado |

---

## 4. Actores y partes interesadas

| Actor | Tipo | Interés |
|---|---|---|
| Consultor | Usuario | Encontrar oportunidades a tiempo y exportarlas |
| Administrador del negocio | Usuario | Gestionar su equipo y sus términos |
| Super Administrador | Usuario | Operar la plataforma, resolver mapeos, auditar |
| Planificador | Sistema | Ingesta periódica confiable |
| Titular de datos | Externo | Ejercer derechos sobre sus datos personales |
| Cliente (consultoría) | Parte interesada | Responsable del tratamiento; exige cumplimiento |
| SPDP | Regulador | Exige evidencia de cumplimiento LOPDP |

---

## 5. Requisitos

### 5.1 Funcionales

| ID | Requisito | Fase |
|---|---|---|
| RF-01 | Alta de negocios y usuarios (1 negocio : N usuarios; 1 usuario : 1 negocio) | F1 |
| RF-02 | Autenticación con access + refresh token y rotación | F4 |
| RF-03 | Máximo 2 sesiones simultáneas; el 3.º login revoca la más antigua | F4 |
| RF-04 | Estados de usuario y de sesión, con auditoría de cada cambio | F4 |
| RF-05 | Gate de primer login: lectura completa y aceptación de términos | F5 |
| RF-06 | Registro de consentimiento con versión, hash, IP y user-agent | F5 |
| RF-07 | Ingesta automática cada 15 min con ventana de solape de 2 ciclos | F2 |
| RF-08 | Alta incremental: insertar nuevos, actualizar cambiados, historial append-only | F2 |
| RF-09 | Detección automática de campos nuevos sin pérdida del payload original | F2 |
| RF-10 | Resolución de mapeos pendientes desde el panel administrativo | F2, F6 |
| RF-11 | Búsqueda con N palabras clave seleccionadas y/o agregadas, modo AND/OR | F3 |
| RF-12 | Ingesta bajo demanda al agregar una palabra clave nueva, con ventana de recuperación histórica y turno garantizado en la cola | F3 |
| RF-13 | Exportación a Excel de todos los procesos filtrados o seleccionados, sin tope | F6 |
| RF-14 | Panel de presencia: conectados/desconectados en tiempo real, verde/rojo, con motivo | F4 |
| RF-15 | Auditoría inmutable de acciones sensibles | F4, F5 |
| RF-16 | Canal de solicitudes ARCO con plazo calculado a 15 días hábiles | F5 |
| RF-17 | Exportación del Registro de Actividades de Tratamiento (RAT) | F5 |
| RF-18 | Cifrado del contacto de funcionarios y retención automática | F5 |
| RF-19 | El administrador solo ve los usuarios **registrados** en su propio negocio y su estado de conexión (verde/rojo); nunca usuarios ni datos de otro negocio | F4 |
| RF-20 | El administrador concede o retira el acceso a cada vista del panel por plazos cerrados (7 días, 30 días, 3 meses, 6 meses, 1 año) | F3.5 |
| RF-21 | El vencimiento lo calcula el backend como instante absoluto; el cliente nunca envía fechas ni plazos fuera del catálogo | F3.5 |
| RF-22 | El acceso se comprueba al leer y la retirada es inmediata, incluso con el permiso en caché | F3.5 |

### 5.2 No funcionales

| ID | Categoría | Requisito | Meta |
|---|---|---|---|
| RNF-01 | Desempeño | Consulta cacheada | p95 < 300 ms |
| RNF-02 | Desempeño | Consulta en BD | < 1,5 s |
| RNF-03 | Escalabilidad | Negocios soportados | 50+ en el primer año |
| RNF-04 | Disponibilidad | Operación si Redis cae | Degradación a BD con avisos |
| RNF-05 | Seguridad | Aislamiento entre negocios | 0 fugas; RLS forzado |
| RNF-06 | Seguridad | Almacenamiento de credenciales | Argon2id |
| RNF-07 | Seguridad | Cifrado de datos personales | AES-256-GCM en columna |
| RNF-08 | Cumplimiento | LOPDP | Consentimiento demostrable, ARCO, retención |
| RNF-09 | Mantenibilidad | Tipado y estilo | mypy estricto + ruff en CI |
| RNF-10 | Testabilidad | Cobertura dominio/aplicación | ≥ 80% |
| RNF-11 | Observabilidad | Trazabilidad de ingesta y errores | Logs estructurados + métricas por ciclo |
| RNF-12 | Portabilidad | Cambio de BD local a remota | Solo cambiar `DATABASE_URL` |
| RNF-13 | Integridad | Respuestas JSON sin `NaN`/`Infinity` | 0 ocurrencias |
| RNF-14 | Usabilidad | Claridad ante fallos parciales | Mensajes vía `avisos`, nunca error crudo |

### 5.3 Restricciones
- **R-01** Ninguna petición de usuario puede originar tráfico hacia el SERCOP.
- **R-02** Presupuesto de peticiones acotado por ciclo (configurable).
- **R-03** Un solo ciclo de ingesta concurrente (advisory lock).
- **R-04** `negocio_id` se toma siempre del JWT, nunca del cliente.
- **R-05** El rol de aplicación no puede ser superusuario (saltaría RLS).
- **R-06** NCO no expone histórico: solo se acumula desde la primera ingesta.

---

## 6. Casos de uso

### 6.1 Tabla resumen

| ID | Caso de uso | Actor | Precondición | Resultado esperado | Criterio de aceptación |
|---|---|---|---|---|---|
| CU-01 | Iniciar sesión | Todos | Usuario activo | Sesión con tokens | 3.º login expulsa la más antigua en <2 s |
| CU-02 | Aceptar términos en primer login | Todos | Primer acceso o versión nueva | Consentimiento registrado | Sin aceptar no hay acceso; se guarda versión+hash+IP+UA |
| CU-03 | Consultar con múltiples palabras clave | Consultor | Sesión activa | Resultado paginado | p95 < 300 ms; 0 llamadas a SERCOP |
| CU-04 | Agregar palabra clave nueva | Consultor | Sesión activa | Término en cola + resultados parciales | Respuesta inmediata con estado de ingesta |
| CU-05 | Ver procesos nuevos del ciclo | Consultor | Ingesta previa | Lista de nuevos | Visibles < 15 min tras publicarse |
| CU-06 | Ver historial de un proceso | Consultor | Proceso en BD | Cambios con fecha | Cada cambio tiene fecha de detección |
| CU-07 | Exportar todos los procesos filtrados | Consultor | Resultado no vacío | Archivo Excel | Sin tope; enlace válido 24 h |
| CU-08 | Ver usuarios conectados/desconectados | Admin del negocio | Rol autorizado | Panel con semáforo | Actualización asíncrona sin recargar; **solo usuarios registrados en su negocio** |
| CU-09 | Resolver mapeo de columnas pendiente | Super Admin | Existe pendiente | Campo canónico asignado | El ciclo siguiente puebla la columna |
| CU-10 | Auditar acciones | Super Admin | — | Registro consultable | Toda acción sensible registrada |
| CU-11 | Ejercer derechos ARCO | Titular | — | Solicitud registrada | Vencimiento a 15 días hábiles calculado |
| CU-12 | Sincronizar fuentes cada 15 min | Planificador | Ciclo vencido | Nuevos/actualizados + caché invalidada | 1 solo ciclo concurrente |
| CU-13 | Registrar consentimiento | Sistema | Aceptación previa | Evidencia almacenada | Versión, hash, IP y UA presentes |
| CU-14 | Gestionar usuarios del negocio | Admin del negocio | Rol autorizado | Usuario creado/editado | No puede ver datos de otro negocio |
| CU-15 | Conceder acceso a una vista por un plazo | Admin del negocio | Rol autorizado | Concesión con vencimiento | El vencimiento es ahora + el plazo, calculado en el servidor |
| CU-16 | Retirar el acceso a una vista | Admin del negocio | Existía concesión | Sin acceso y con historial | Deja de conceder en la petición siguiente |

### 6.2 Ficha CU-04 — Agregar palabra clave nueva *(caso crítico)*

| Elemento | Detalle |
|---|---|
| Actor | Consultor |
| Precondición | Sesión activa; términos permitidos por el negocio |
| Disparador | El usuario escribe y agrega un término que no está en el catálogo |
| Flujo principal | 1. El API normaliza el término y lo crea/recupera en el catálogo global. 2. Crea la suscripción del negocio. 3. Responde de inmediato con resultados parciales y `estado_ingesta`. 4. Encola el término. 5. El `worker` lo ingesta respetando el presupuesto. 6. El frontend consulta el estado y refresca. |
| Flujos alternos | 4a. El término ya tiene ingesta reciente → no se encola. 4b. El mismo término lo pidieron otros negocios → se reutiliza la ingesta (deduplicación global). |
| Excepciones | 5a. HTTP 429 → estado `parcial`, watermark **no avanza**, se avisa. 5b. Presupuesto agotado → queda `en_cola` para el ciclo siguiente. |
| Postcondición | Resultados completos cuando la ingesta termina |
| Reglas | **Nunca** se llama al SERCOP dentro del request. Backfill por año solo en OCDS; en NCO no existe histórico. |

### 6.3 Ficha CU-08 — Ver usuarios conectados/desconectados

| Elemento | Detalle |
|---|---|
| Actor | Administrador del negocio |
| Precondición | Sesión con rol autorizado |
| **Alcance de visibilidad** | **Solo usuarios registrados y pertenecientes a su propio negocio**, en cualquiera de sus estados. No puede ver usuarios de otros negocios ni cuentas de plataforma. Esto no depende del código de la consulta: el aislamiento lo impone RLS (`app.negocio_id` sale del token, nunca del cliente). |
| Flujo principal | 1. El frontend abre un canal SSE. 2. El API se suscribe a Redis Pub/Sub del negocio. 3. Emite el estado inicial. 4. Cada heartbeat o cierre publica un evento. 5. El panel repinta el color sin recargar. |
| Estados y colores | Verde `#22c55e` = conectado (presencia viva + token activo). Rojo `#ef4444` = desconectado. |
| Motivos mostrados | `logout` · `cierre_ventana` · `heartbeat_vencido` · `expirado` · `eviccion` · `admin` |
| Excepciones | Cierre abrupto del navegador → no llega el beacon → el rojo se refleja al vencer el TTL (≤60 s) |
| Postcondición | El panel refleja el estado real de **los usuarios del negocio** |

### 6.4 Diagrama de casos de uso

```mermaid
flowchart LR
  CO(["Consultor"]) --> CU03["CU-03 Consultar multi-palabra"]
  CO --> CU04["CU-04 Agregar palabra clave"]
  CO --> CU05["CU-05 Ver nuevos del ciclo"]
  CO --> CU06["CU-06 Ver historial"]
  CO --> CU07["CU-07 Exportar sin tope"]
  CO --> CU01["CU-01 Iniciar sesión"]
  AD(["Admin del negocio"]) --> CU01
  AD --> CU14["CU-14 Gestionar usuarios"]
  SA(["Super Admin"]) --> CU08["CU-08 Ver conectados verde/rojo"]
  SA --> CU09["CU-09 Resolver mapeos"]
  SA --> CU10["CU-10 Auditar"]
  TI(["Titular"]) --> CU11["CU-11 Derechos ARCO"]
  PL(["Planificador"]) --> CU12["CU-12 Sincronizar 15 min"]
  CU01 -.->|include| CU02["CU-02 Aceptar términos"]
  CU02 -.->|include| CU13["CU-13 Registrar consentimiento"]
  CU04 -.->|include| CU12
  CU12 -.->|include| CU05
```

### 6.5 Diagrama de secuencia — ingesta y caché

```mermaid
sequenceDiagram
  participant W as Worker
  participant L as Advisory Lock
  participant F as SERCOP
  participant DB as PostgreSQL
  participant R as Redis
  W->>L: intentar lock por fuente
  alt sin lock
    W-->>W: otra réplica ya ingiere (salir)
  end
  W->>F: NCO (1 petición) + OCDS (términos con presupuesto)
  F-->>W: crudo (o 429 → parcial, watermark no avanza)
  W->>W: normalizar + mapear + hash
  W->>DB: upsert nuevos y cambiados
  W->>DB: historial append (solo cambios)
  W->>R: INCR generacion:fuente
  W->>R: nuevos en lista con TTL
  W->>L: liberar lock
```

---

## 7. Arquitectura

```mermaid
flowchart TB
  FE["frontend/ (Vue 3)"] -->|HTTP| API["api (FastAPI)"]
  API --> R[("Redis")]
  API --> DB[("PostgreSQL")]
  WK["worker"] --> F["SERCOP"]
  WK --> DB
  WK --> R
  API -.->|nunca| F
```

- **Estilo:** monolito modular con puertos y adaptadores. La infraestructura implementa puertos; el dominio no depende de nada.
- **Dos procesos:** `api` (tráfico de usuarios) y `worker` (ingesta, exportaciones, retención).
- **Redis-first (lectura):** `clave = hash(filtros) + generacion:fuente`; TTL = un ciclo.
- **Decisiones registradas:** ADR-000 (fundamentos, lenguaje, arquitectura, BD, Redis, planificador, migración incremental) y ADR-001 (multi-tenant, palabras clave, modelo de datos, exportación, admin desmontable).

---

## 8. Modelo de datos

```mermaid
erDiagram
  NEGOCIO ||--o{ USUARIO : tiene
  NEGOCIO ||--o{ SUSCRIPCION_TERMINO : sigue
  NEGOCIO ||--o{ EXPORTACION : genera
  USUARIO ||--o{ SESION : abre
  USUARIO ||--o{ CONSENTIMIENTO : otorga
  USUARIO ||--o{ CONJUNTO_TERMINOS : crea
  CONJUNTO_TERMINOS ||--o{ CONJUNTO_TERMINO : contiene
  TERMINO ||--o{ CONJUNTO_TERMINO : usado
  TERMINO ||--o{ SUSCRIPCION_TERMINO : seguido
  FUENTE ||--o{ REGISTRO : produce
  REGISTRO ||--o{ REGISTRO_HISTORIAL : evoluciona
  REGISTRO ||--|| PUNTO_CONTACTO_ENTIDAD : protege
  FUENTE ||--o{ CAMPO_MAPEO : define
```

**Plano compartido** (sin `negocio_id`): `fuente`, `campo_mapeo`, `campo_pendiente`, `termino`,
`registro`, `registro_historial`, `sincronizacion`.
**Plano de negocio** (`negocio_id` + RLS forzado): `negocio`, `usuario`, `sesion`,
`suscripcion_termino`, `conjunto_terminos`, `conjunto_termino`, `filtro_guardado`, `exportacion`,
`consentimiento`, `solicitud_arco`, `auditoria`, `politica_version`.
**Tablas particionadas por mes:** `registro_historial`, `auditoria`.
**Extensiones:** `pg_trgm`, `unaccent`, `pgcrypto`, `citext`.

---

## 9. Fases de desarrollo y documentación

| Fase | Objetivo | Estado | Documento | Casos de uso |
|---|---|---|---|---|
| F0 | Cimientos y seguridad del repositorio | **Completada** — 2026-09-27 | [`docs/00-fase-0.md`](docs/00-fase-0.md) | — |
| F1 | Modelo multi-tenant + RLS | **Completada** — 2026-09-27 | [`docs/01-fase-1.md`](docs/01-fase-1.md) | RF-01, CU-14 |
| F2 | Ingesta + mapeo automático | **Completada** — 2026-09-27 | [`docs/02-fase-2.md`](docs/02-fase-2.md) | CU-05, CU-06, CU-12 |
| F3 | Redis-first + multi-palabra | **Completada** — 2026-09-27 | [`docs/03-fase-3.md`](docs/03-fase-3.md) | CU-03, CU-04 |
| F3.5 | Acceso a vistas por suscripción | **Completada** — 2026-09-27 | [`docs/03b-fase-3b-acceso-vistas.md`](docs/03b-fase-3b-acceso-vistas.md) | CU-15, CU-16 |
| F4 | Auth completo, sesiones, presencia, super administrador, familias de contratación y plantilla de Excel | **Completada** — 2026-09-29 | [`docs/04-fase-4.md`](docs/04-fase-4.md) | CU-01, CU-08, CU-10, CU-14 |
| F4.1 | Exportación fiel a los filtros, columnas elegidas por empresa, informe de la plantilla y panel plegable | **Completada** — 2026-09-29 | [`docs/08-fase-4b-exportacion-columnas-panel.md`](docs/08-fase-4b-exportacion-columnas-panel.md) | CU-07, CU-09 |
| F5 | Cumplimiento LOPDP | Pendiente | `docs/05-fase-5.md` | CU-02, CU-11, CU-13 |
| F6 | Export sin tope + frontend | Pendiente | `docs/06-fase-6.md` | CU-07, CU-09 |

### 9.1 Registro de implementaciones

> Esta tabla se completa al cerrar cada fase. Una fase sin fila aquí **no está terminada**.

| Fase | Fecha cierre | Implementado | Archivos/símbolos clave | Pruebas | Evidencia | Deuda |
|---|---|---|---|---|---|---|
| F0 | 2026-09-27 (parcial) | Repositorio seguro, esqueleto hexagonal, configuración con fallo rápido, app con `/salud` y `/listo`, diagnóstico de conexiones, adaptación a proveedor gestionado, CI | `.gitignore`, `.env.example`, `backend/pyproject.toml`, `ajustes.py`, `app.py`, `asgi.py`, `routers/salud.py`, `bd/sesion.py`, `cache/cliente.py`, `scripts/preparar_entorno.py`, `scripts/verificar_conexiones.py`, `.github/workflows/ci.yml` | 22 pasan · 1 omitida · integración Postgres pasa, Redis pendiente | `ruff: All checks passed` · `ruff format: 30 files` · `mypy: no issues found in 27 source files` · `pytest: 22 passed, 1 skipped` · `pip-audit: No known vulnerabilities found` · Supabase: `postgres OK` | Instalar Redis · motor atado al ciclo de vida · `uv.lock` · inicializar Git · rotar la contraseña compartida por chat |
| F1 | 2026-09-27 | Esquema completo (19 tablas), RLS forzado con políticas por negocio, particionado mensual, migraciones reversibles, caché opcional | `alembic/env.py`, `alembic/versions/0001_esquema_inicial.py`, `0002_aislamiento_rls.py`, `aplicacion/puertos/cache.py`, `cache/{cliente,nula,redis}.py`, `routers/salud.py` | 22 de unidad · 8 de integración | `ruff` y `mypy` limpios · `alembic downgrade base` → `upgrade head` sin errores · `test_un_negocio_no_ve_los_datos_de_otro` **PASSED** · `/listo` → 200 | Crear el rol de aplicación real · job de particiones futuras (F2) · verificar email único por negocio |
| F2 | 2026-09-27 | Ingesta cada 15 min con solape, mapeo dirigido por datos, detección de campos nuevos, historial *append-only*, límite de tasa y exclusión mutua, worker ejecutable | `dominio/ingesta.py`, `dominio/palabras.py`, `aplicacion/mapeo.py`, `aplicacion/casos_uso/ejecutar_ingesta.py`, `aplicacion/puertos/fuente.py`, `infraestructura/salida/bd/{ingesta,bloqueo}.py`, `infraestructura/salida/fuentes/{limitador,nco,ocds,nco_mapeos,ocds_mapeos}.py`, `tareas/{planificador,worker}.py` | 68 de unidad · 14 de integración | `ruff: All checks passed` · `ruff format: 56 files` · `mypy: no issues found in 50 source files` · idempotencia, historial, pendientes, marca de agua y caché verificados sobre PostgreSQL real · `alembic current` → `0002 (head)` **sin cambios de esquema** | `registro.terminos_ids` en F3 · mantenimiento de particiones en F3 · el worker necesita proceso persistente (no sirve un entorno sin servidor) · 48 h continuas se validan en operación |
| F3 | 2026-09-27 | Caché por delante en toda lectura con invalidación por generación, búsqueda multi-palabra con modos `todas`/`cualquiera` sobre texto completo, catálogos y estadísticas cacheadas, alta de palabras clave sin llamar a la fuente, estado de ingesta | `dominio/busqueda.py`, `dominio/serializacion.py`, `aplicacion/generaciones.py`, `aplicacion/casos_uso/{buscar_registros,encolar_termino}.py`, `salida/bd/{consultas,terminos,contexto}.py`, `routers/{busqueda,terminos,ingestas}.py` | 162 de unidad · 29 de integración | `ruff` y `mypy` limpios · 4 defectos reales corregidos, entre ellos decimales devueltos como texto y una conexión reutilizada que fallaba en lugar de denegar | El `worker` no consume aún la cola priorizada · umbrales de búsqueda por revisar con datos reales |
| F3.5 | 2026-09-27 | Concesión de acceso a vistas por plazos cerrados con vencimiento absoluto, comprobado al leer; retirada inmediata con caché; tablero de las cuatro vistas en verde y rojo; aislamiento por RLS en tabla propia | `dominio/acceso.py`, `aplicacion/{actor.py,casos_uso/gestionar_acceso.py}`, `aplicacion/puertos/accesos.py`, `salida/bd/accesos.py`, `alembic/versions/{0003_acceso_vistas,0004_politicas_contexto_vacio}.py`, `routers/accesos.py`, `scripts/estado_esquema.py` | 38 de unidad · 15 de integración | Sobre la base real con un rol sin privilegios: aislamiento forzado, contexto vacío deniega, `CHECK` rechaza plazos inventados · `estado_esquema.py` destapa que el rol actual se salta RLS | Las vistas aún no se exigen en los endpoints de lectura · presencia y aviso de vencimiento en F4 |
| F4 | 2026-09-29 | Sesiones con vida en el almacén (cierre por inactividad sin consultar la base), ventana de gracia en la rotación del token de renovación, evicción por máximo de sesiones, presencia en vivo con canal por negocio y cuadro guardado unos segundos, super administrador de plataforma, familias de contratación (ínfimas / ofertas) con hoja propia en la exportación, **pestañas separadas por familia** con el mapa eligiendo entre ínfimas, ofertas o las dos, plantilla de Excel por empresa con rechazo de macros, filtro por **varias** provincias, mensajes de sesión sin jerga técnica, **descarga fiel a la vista y a la plantilla del cliente** (cabecera buscada en las primeras filas, títulos sinónimos, filas anteriores sustituidas y una pestaña por familia) | `dominio/sesiones_vivas.py`, `dominio/presencia.py`, `aplicacion/sesiones_vivas.py`, `aplicacion/casos_uso/{presencia,autenticar}.py`, `aplicacion/plantillas.py`, `salida/archivos/local.py`, `salida/bd/{plantillas,terminos}.py`, `routers/{presencia,plantilla,busqueda}.py`, `alembic/versions/{0009_plantilla_excel,0010_gracia_rotacion}.py`, `frontend/src/components/{CampoContrasena,PlantillaExcel,MapaEcuador,VistaPanel}.vue` | 568 de unidad · 54 de integración | `ruff` y `mypy` limpios (179 y 165 archivos) · `pytest: 568 passed` · migración `0010` aplicada | Tres cierres por `reuso_detectado` en un día → ventana de gracia de 30 s (`refresh_gracia_seg`), con la fila de la sesión guardando la huella anterior · mensaje al usuario que hablaba de tokens → reemplazado en la API y en el cliente · listado de palabras clave que pedía los suscriptores término por término → una sola consulta en lote, medido de **16,7 s a 3,0 s** · **pestañas reordenadas** —Ínfimas cuantías, Ofertas, Mapa, Plantilla, Resumen, Usuarios, Empresas— con la familia fijada por la pestaña y selector de família en el mapa, verificado en el navegador: 2.210 ínfimas · 53 ofertas · 2.263 ambas · **exportación probada contra las dos plantillas realmente subidas**: una tenía los encabezados en la fila 4 y las dos usan títulos distintos a los propios («Entidad Contratante», «Descripción del Objeto de compra»), así que la cabecera se busca en las primeras diez filas y se admiten sinónimos; la descarga sustituye las filas anteriores (1.404 en la plantilla real) en lugar de arrastrarlas y manda cada familia a su pestaña · mapa que marca y desmarca con un solo clic, sin el rectángulo negro del contorno de foco | Rol de aplicación sin `BYPASSRLS` (F5) · exportación aún síncrona · prueba de carga con k6 sin ejecutar · rotar la contraseña de Redis compartida por chat |
| F4.1 | 2026-09-29 | Exportación que respeta los filtros de la pantalla (llevaba el histórico entero), **columnas elegidas por empresa** guardadas en el servidor y aplicadas al archivo, **informe de la plantilla** que dice a qué hoja va cada familia y qué títulos se reconocen, panel de filtros plegable con la preferencia recordada y **contador por familia** en las pestañas | `aplicacion/casos_uso/{exportar_registros,analizar_plantilla,gestionar_columnas,buscar_registros}.py`, `aplicacion/puertos/exportacion.py`, `salida/bd/{columnas,consultas}.py`, `routers/{plantilla,busqueda}.py`, `alembic/versions/0011_columnas_exportacion.py`, `frontend/src/components/{ColumnasExcel,AnalisisPlantilla,VistaPanel,BarraSuperior}.vue`, `frontend/src/composables/useEsMovil.js`, `frontend/src/api/endpoints.js` | 573 de unidad · 6 de integración nuevas · `verificar_exportacion.py` completo | `ruff` y `mypy` limpios (186 y 172 archivos) · esquema en `0011 (head)` · navegador: 2.210/53 que no cambian al abrir Ofertas, 519/11 al filtrar por Pichincha, panel que se pliega y recuerda, casillas que guardan 15 de 16 y el Excel sale sin «Objeto de compra» | El contador de Ofertas puede no coincidir con la tabla de esa pestaña (sus filtros son propios) · con selección activa no se añaden campos nuevos de la fuente |
| F4.2 | 2026-09-29 | **Búsqueda por palabras clave de CPC**: el listado de necesidades no publica la clasificación, así que se lee la ficha de cada necesidad (`NCORegistroDetalle.cpe`, HTML) y se guardan sus ítems —código, nombre estándar, descripción, unidad y cantidad—. Criterio de filtro `cpc` nuevo y propio, sumable al de palabras clave, con su índice de texto completo; relleno **reanudable por tandas** con cuota propia; columna **CPC** en la exportación y desglose de ítems en el detalle del panel | `dominio/cpc.py`, `salida/fuentes/{nco_detalle,nco}.py`, `salida/fuentes/limitador.py`, `aplicacion/puertos/items.py`, `aplicacion/casos_uso/recoger_items.py`, `tareas/planificador.py`, `dominio/busqueda.py`, `salida/bd/{consultas,ingesta}.py`, `casos_uso/exportar_registros.py`, `routers/busqueda.py`, `alembic/versions/0012_items_cpc.py`, `frontend/src/stores/filtros.js`, `frontend/src/utils/cpc.js`, `frontend/src/components/{PanelFiltros,TablaRegistros}.vue` | 628 de unidad · 17 nuevas de CPC y 8 del relleno · `scripts/verificar_filtros.py` con su apartado 8 | `ruff: All checks passed` · `ruff format: 196 archivos` · `mypy: no issues found in 180 source files` · `pytest: 628 passed` · esquema en `0012 (head)` · contra el portal y la base reales: la necesidad del cliente (NIC-0860001560001-2026-00083) da **17 ítems** con CPC `871410032 LAVADO Y ENGRASADO DE AUTOMOTORES` y el filtro `cpc=lavado` la encuentra, mientras que el mismo término por texto libre sigue devolviendo lo que solo lo menciona | Al desplegar quedan **2.262 fichas por leer** (~8 ciclos a 300/vuelta, ~20 min de peticiones) y hasta entonces `cpc` no filtra: se ve el desglose pero la columna del panel sale vacía · OCDS no publica CPC, así que el criterio solo tiene datos en las ínfimas · la ficha se relee al cambiar la necesidad, no cuando la entidad edita solo el detalle |
| F4.3 | 2026-10-01 | **Recuperación de la ingesta, vigilancia del listado y arreglos de operación**: cinco llamadas del caso de uso apuntaban a código inexistente, así que **cada ciclo NCO moría con cero filas** y nada lo anunciaba —proceso vivo, sincronizaciones escritas y la tabla congelada—. Ahora el campo `terminos_completos` está declarado y las cuatro escrituras por lotes existen. El worker pasa a tener **dos cadencias**: el listado de NCO cada 150 s —sin cola de términos, sin fichas y sin invalidar la caché, que a esa cadencia dejaría inservible el catálogo de desplegables— y el ciclo completo cada 15 min. La vigencia se reconcilia en las **dos** direcciones (cierra lo que desaparece y reabre lo que vuelve) y NCO se declara `listado_completo`. El filtro de CPC se aplica al guardar la lista —se guardaba, el chip aparecía y la tabla no cambiaba— con aviso del modo «Todas», que con clasificaciones alternativas devuelve cero | `aplicacion/puertos/fuente.py`, `salida/bd/ingesta.py`, `tareas/{planificador,worker}.py`, `infraestructura/config/ajustes.py`, `pruebas/unidad/test_fuente_nco.py`, `pruebas/integracion/test_ingesta_ciclo.py`, `scripts/verificar_cpc_lista.py`, `frontend/src/{stores/filtros.js,components/GestorPalabrasCpc.vue,api/cliente.js}`, `.github/agents/revisor-{ingesta,despliegue}.agent.md`, `docs/10-fase-4d-vigilancia-y-operacion.md` | 669 de unidad (7 recuperadas de la vigilancia) · prueba nueva de reapertura de vigencia · 6 del adaptador de NCO | `ruff: All checks passed` · `mypy: no issues found in 194 source files` · `pytest: 669 passed` · ciclo NCO real `ok · 143 nuevos, 0 actualizados, 1562 iguales` (1.705 filas escritas en **6 s**) · worker: `Ítems CPC: 32 fichas leídas (32 con ítems), 0 fallidas, 0 pendientes` · con la lista real de 31 términos: 3.729 ínfimas sin CPC → **294** con «cualquiera» → **0** con «todas» | La prueba de carga (k6, 900 paneles con el flujo de eventos abierto) sigue pendiente y es lo que convierte la estimación de capacidad en un hecho · **nueve de los 31 términos de CPC del cliente no existen en la nomenclatura oficial** (`atl`, `btl`, `cinemometro`…): hay que decidir si se quitan de la lista, y eso es de negocio · la cola de términos avanza a veinte palabras por ciclo, limitada por el presupuesto de la fuente |
| F4.4 | 2026-10-01 | **La pantalla se actualiza sola cuando la ingesta termina.** Hasta aquí lo único que refrescaba la tabla era tocar un filtro —el canal en vivo solo transporta presencia—, así que la ingesta podía cerrar dos ciclos con las contrataciones guardadas y su CPC leído y la pantalla seguía enseñando lo de antes. Se cierra también la mitad que se escapaba: el CPC se escribe **después** de que cada fuente invalide lo suyo, así que las páginas cacheadas salían sin columna CPC durante un cuarto de hora. Ahora el worker sube la generación al escribir CPC y el API publica `GET /v1/ingestas/version` —una lectura de caché, sin tocar la base— que el panel pregunta cada minuto (y al volver a una pestaña de fondo) para recargar con los filtros ya aplicados | `tareas/planificador.py`, `routers/ingestas.py`, `entrada/http/dependencias.py`, `scripts/estado_version.py`, `pruebas/unidad/test_vigilancia_listado.py`, `frontend/src/{api/endpoints.js,stores/datos.js,components/VistaPanel.vue}` | 672 de unidad (3 nuevas) | `ruff` y `mypy` limpios (195 archivos) · `pytest: 672 passed` · contador leído y movido: `21 → 23` observando 90 s con un ciclo en marcha · `/v1/ingestas/version` registrada **antes** de `/{codigo}` en el esquema y 401 sin sesión (no 404) | El refresco **no** se ha podido observar desde un navegador: hace falta una sesión abierta en el panel · la vuelta corta sigue sin invalidar la caché a propósito, así que lo que entra por ella aparece en pantalla con el ciclo completo |
| F4.5 | 2026-10-01 (en curso) | **La ingesta de ofertas pasa a ser general.** Medido contra la fuente: veinte palabras clave costaban ~45-60 peticiones por ciclo —unas 5.760 al día— contra un origen que responde 429 con `Retry-After` de 11-29 s; el rabo del listado general del año se sigue con **~133 peticiones al día**. Hasta aquí OCDS solo traía lo que coincidía con las palabras clave del cliente —**800 filas de las 103.628** que tiene el año—, así que los filtros del panel buscaban sobre casi nada. Ahora el worker lee el **final del listado general** (la API pagina de lo más antiguo a lo más reciente, así que lo recién publicado está al final) y las palabras clave quedan como **rescate de una sola vez**, limitado a los términos que **nunca** se han buscado: re-buscar uno ya buscado serían ~4.300 peticiones al día por datos que el rabo ya trae. El tope de páginas del rabo se estima por **tiempo** y no por las fechas de las filas —muchas publican el día sin hora y comparar contra la ventana cortaría antes de tiempo—, y el rabo **no** declara `listado_completo`, porque es una parte del listado y declararlo cerraría casi todo lo que hay en la base. Se añade el **modo relleno** del adaptador y `scripts/rellenar_ofertas_ocds.py`: reanudable, en tandas del tamaño del ciclo, que **cede el bloqueo al worker entre tandas** (con 90 s de pausa) para que el rabo siga entrando cada cuarto de hora mientras se rellena el pasado, y que se declara **parcial** para no mover la marca de agua | `salida/fuentes/ocds.py` (`FuenteOcdsGeneral`, `_paginas_a_leer`, `desde_pagina`), `tareas/planificador.py`, `infraestructura/config/ajustes.py`, `pruebas/unidad/{test_fuente_ocds,test_vigilancia_listado}.py`, `scripts/{rellenar_ofertas_ocds,verificar_relleno}.py`, `docs/12-fase-4e-ingesta-general-ocds.md` | 678 de unidad (4 nuevas del modo general y 2 del filtro del rescate) · 10 del adaptador de OCDS · 10 de integración | `ruff: All checks passed` · `ruff format: 216 archivos sin cambios` · `mypy: no issues found in 199 source files` · `pytest: 678 passed` · plan del relleno medido contra la fuente: **10.363 páginas · 103.630 filas · 1.031 MB** · tandas reales de 40 páginas: **238 y 262 filas nuevas**, sin errores · `verificar_relleno.py`: la sincronización del relleno queda `parcial` con la marca **anterior** (16:21:09) y las filas entran vigentes · el worker reiniciado registra el modo nuevo: `OCDS: sin términos por rescatar; se lee el rabo del listado general` | **El año no está relleno**: de 800 filas de OCDS se ha pasado a las que el relleno va dejando (~1.350 al escribir esto), de las 103.630, y tarda ~34 h al ritmo real medido de ~12 s por página (no los 0,6 s del intervalo mínimo) · la cola de términos ya solo significa el rescate, conviene revisar el texto de la pantalla · `ix_registro_datos` (GIN, 20,3 MB, tres cuartas partes de los índices) puede sobrar: solo lo usa la consulta de catálogos, pero retirarlo pide un `EXPLAIN` medido · el relleno no está automatizado a propósito |
| F4.6 | 2026-10-01 | **El año entero de procesos publicados, en minutos.** La vía paginada devuelve diez filas por petición y no acepta tamaño de página (se probaron ocho parámetros: los ignora), así que el año 2026 eran **10.363 peticiones** contra un origen que responde 429 cada cinco o seis: medido, ~9 s por página y **~26 horas**; subir el intervalo entre peticiones lo **empeora** (2,5 s dieron 21 s por página). El portal publica los mismos procedimientos **por meses en un ZIP** —endpoint descubierto en el script de su propia web—, así que el año son **doce peticiones**: septiembre se importó en **13 segundos** (4.634 filas, 1 petición) y los nueve meses publicados de 2026 dieron **103.135 procedimientos**, el **94 % con objeto de compra** y el **91 % con proveedor adjudicado**, campos que el listado deja a cero. El fichero es un **delta de publicaciones** (2.340 de las 4.634 de septiembre no traen `tender`), así que las filas se **combinan por `ocid`** antes de escribir: sin eso, la publicación de la adjudicación dejaría el título en blanco y la del anuncio borraría el proveedor. La tubería no se toca: el adaptador entrega la **misma fila plana** que el listado, con la equivalencia de cada campo medida contra los ficheros reales. No adelanta la marca de agua (se declara parcial: una foto con horas de retraso no cubre el final del listado) y los **ítems con CPC** que el fichero trae quedan para después, por decisión expresa | `salida/fuentes/ocds_masiva.py` (`traducir_publicacion`, `combinar`, `FuenteOcdsMasiva`), `scripts/{importar_ocds_masivo,sondear_ocds_masivo,comparar_ocds_listado_masiva}.py`, `pruebas/unidad/test_ocds_masiva.py`, `docs/13-fase-4f-descarga-masiva.md` | 710 de unidad (32 nuevas) · contraste campo a campo contra el listado · sonda del fichero contra `get-totals` | `ruff` y `mypy` limpios (204 archivos) · `pytest: 710 passed` · septiembre: 4.634 filas en **13 s** con **1 petición** (3.973 nuevas, 661 actualizadas) · año: 103.135 publicaciones → 103.135 procedimientos en 15 s de lectura, 97.057 con objeto de compra y 94.043 con proveedor · `get-totals` del año (103.628) cuadra con el listado | **Los ítems con CPC del fichero no se guardan** (4.294 solo en septiembre, con cantidad y precios): es la mejora pendiente más grande, y no haría falta volver a descargar · el `crudo` guardado es la fila plana, no el estándar completo · la importación del mes en curso no está automatizada: el fichero tiene horas de retraso y a esa frescura la da el rabo paginado · el total del fichero de un mes abierto va 3,4 % por detrás del listado (lo publicado después de generarse), que es justo lo que cubre el ciclo de quince minutos |
| F4.7 | 2026-10-01 | **El panel de plataforma enseña el trabajo de la ingesta y puede pedir un ciclo.** Hasta aquí la ingesta era una caja negra desde el panel: se veía el **último** ciclo de cada fuente y nada más —ni la serie, ni si llevaba dos horas callada, ni una racha de fallos— y no había forma de forzar una vuelta. Se añade `GET /v1/plataforma/ingesta/historial` (la serie de 24 ciclos **por fuente**, un `JOIN LATERAL` con tope por fuente porque la que más escribe se quedaría con toda la ventana si el tope fuera global) y `POST /v1/plataforma/ingesta/solicitud`. La petición **no la ejecuta el API**: se deja en la caché con `TTL` de 900 s y **se borra al recogerla** —si no, el worker la ejecutaría en cada vuelta, un ciclo cada cinco segundos—, y el worker la consume en su bucle, que ahora duerme en tramos de 5 s en vez de hasta la hora que toque: es lo que hace que el botón tenga un retardo de segundos y no de quince minutos. Un ciclo pedido a mano **es** un ciclo (se da por servida la hora y se reprograma la vigilancia). Todo ello respetando R-01/CU-07: ninguna petición de usuario origina tráfico hacia el SERCOP. En la misma tanda se arreglan las gráficas, que mentían: el reparto por provincia llegaba **recortado a doce filas** (`LIMITE_PROVINCIAS`) y se calculaba **con el filtro de provincia aplicado**, de modo que doce provincias parecían vacías y elegir una ponía las demás a cero; ahora se calcula sin ese filtro y se agrupa por la clave normalizada (sin tildes), porque agrupar por el texto crudo partía «SANTO DOMINGO DE LOS TSÁCHILAS» en dos. Y se arregla la gráfica que **nacía en blanco**: con la pestaña oculta al montarse, Chart.js no recibe aviso de que el contenedor aparece (el lienzo mide 300×150 antes y después) y la gráfica no se pintaba hasta que algo la refrescaba | `aplicacion/casos_uso/operar_ingesta.py`, `aplicacion/puertos/consultas.py`, `salida/bd/consultas.py`, `routers/plataforma.py`, `tareas/worker.py`, `pruebas/unidad/{test_operar_ingesta,test_vigilancia_listado}.py`, `frontend/src/components/{TrabajoWorkers,PanelEmpresas}.vue`, `frontend/src/composables/useGrafica.js`, `frontend/src/utils/familias.js`, `frontend/src/{api/endpoints.js,utils/formato.js}`, `scripts/{verificar_plataforma,verificar_graficas}.py`, `docs/14-fase-4g-panel-plataforma.md` | 721 de unidad (11 nuevas) · dos pruebas del bucle del worker reescritas para medir la cadencia por **tiempo acumulado** y no por número de sueños · § 10 nuevo en `verificar_plataforma.py` | `ruff: All checks passed` · `mypy: no issues found in 207 source files` · `pytest: 721 passed` · **verificado contra la API y el worker reales**: historial 200 con `['NCO','OCDS']` y 24 ciclos de cada uno · un administrador de empresa recibe **403 `sin_permiso`** en los dos endpoints · `POST` → **201** y **el worker la recogió en 3,2 s** con la fila del ciclo escrita 8 s después · `worker.err.log`: `Ciclo completo pedido desde el panel por …; se adelanta.` · en el navegador: la gráfica pinta (65.588 píxeles), el botón encola, el ciclo aparece **en marcha** y luego **terminado · 14 nuevos**, y el panel se pone al día solo (contador 335 → 345) · gráficas del mapa y del resumen: 25 provincias en el reparto, Zamora 889 = su tabla, Galápagos 375, Santa Elena 111, Santo Domingo 69 En el panel se añade además que cada gráfica del Resumen diga **qué familia está enseñando** —la fija la pestaña, así que desde la gráfica no se puede adivinar— y que se pueda **elegir cuáles se ven**, con la preferencia recordada en el navegador; la serie deja de decir «doce meses» cuando lo que dibuja son veinticuatro | Las gráficas nuevas (por entidad, tipo de procedimiento, estado o rango de monto) quedan **pendientes**: cada una exige un agregado nuevo en el servidor y hay que decidir cuáles se piden · el botón no distingue «en marcha» de «en cola» · no hay tope de peticiones por persona · la gráfica mezcla en la misma escala los ciclos del worker y las cargas masivas del año |
| F4.8 | 2026-10-02 | **Buscar una ínfima cuantía por su NIC.** El panel acotaba por palabras clave, CPC, provincia, estado y fechas, pero no por el código que la ficha publica y que todo el mundo cita: el NIC («NIC-1768120280001-2022-00003»). Se añade un campo **NIC de la ínfima cuantía** al panel lateral, que **reutiliza el criterio `codigo`** que ya existía en la API —el NIC *es* el código de la necesidad NCO, por el mapeo `codigo_contratacion` → `codigo`— y por tanto ya llegaba a la tabla, a las gráficas y a la exportación. La comparación es por fragmento (`ILIKE`), como el resto de búsquedas por código, y la consulta **no** se guarda en el caché, que ya era la regla para `codigo` | `frontend/src/stores/filtros.js`, `frontend/src/components/PanelFiltros.vue`, `backend/pruebas/unidad/test_criterios_cpc.py`, `backend/scripts/verificar_filtros.py` (§ 9), `docs/15-fase-4h-filtro-nic.md` | 723 de unidad (2 nuevas) | `ruff: All checks passed` · `mypy: no issues found in 207 source files` · `vite build: 86 módulos en 2,13 s` · contra la base real: `NIC-0360016310001-2026-00053` → **1** fila, su fragmento `26-00053` → 39, un código inventado → **0**, y `cacheable = False` | El NIC solo existe en NCO, así que con el mapa en familia «todas» el criterio compara contra el código de cualquier fuente (en la práctica no devuelve ofertas, porque sus códigos no empiezan por `NIC-`) · el guion de verificación completo es lento contra la base remota y conviene pasarlo con el API y el worker parados |
| F6 | — | — | — | — | — | — |

### 9.2 Plantilla obligatoria por fase (`docs/0N-fase-N.md`)

    # Fase N — <nombre>
    ## 1. Objetivo
    ## 2. Alcance (incluido / excluido)
    ## 3. Implementaciones realizadas   (qué se construyó, archivo/símbolo)
    ## 4. Decisiones tomadas y justificación
    ## 5. Casos de uso cubiertos (CU-xx) y requisitos (RF-xx / RNF-xx)
    ## 6. Pruebas ejecutadas y resultado real
    ## 7. Evidencia de aceptación (comandos y salidas)
    ## 8. Deuda técnica y pendientes
    ## 9. Riesgos abiertos y mitigaciones
    ## 10. Aprobación (QA + Revisor)

---

## 10. Plan de pruebas

| Nivel | Alcance | Herramienta | Criterio de salida |
|---|---|---|---|
| Unidad | Dominio y aplicación | pytest | Cobertura ≥80%; 0 fallos |
| Integración | Postgres y Redis reales | pytest + contenedores | Aislamiento cross-tenant = 0 filas |
| Contrato | Parseo SERCOP con fixtures | pytest | Salida idéntica a los fixtures |
| Restricciones | Rate limit, caché, idempotencia | pytest + dobles | 0 peticiones originadas por usuarios |
| Carga | p95 y aciertos de caché | herramienta de carga | p95 <300 ms; aciertos ≥80% |
| E2E | Flujo completo de usuario | navegador automatizado | Flujo sin errores de consola |
| Seguridad | Dependencias y configuración | pip-audit + revisión | 0 altas/críticas |

**Regla:** cada criterio de aceptación debe mapearse a al menos una prueba. Un criterio sin prueba es un criterio no cumplido.

---

## 11. Seguridad y cumplimiento (LOPDP)

| Control | Implementación | Fase |
|---|---|---|
| Aislamiento por negocio | RLS forzado + `negocio_id` desde el JWT | F1 |
| Credenciales | Argon2id | F4 |
| Sesiones | Máx. 2, rotación de refresh, detección de reuso | F4 |
| Datos personales | AES-256-GCM en columna + clave gestionada aparte | F5 |
| Retención | `vigente_hasta` + job automático | F5 |
| Consentimiento | Gate de primer login + registro versionado con evidencia | F5 |
| Derechos del titular | Canal ARCO con vencimiento a 15 días hábiles | F5 |
| Accountability | RAT exportable + auditoría inmutable | F5 |
| Cookies | Solo cookie de refresh `HttpOnly; Secure` (estrictamente necesaria → sin banner) | F4 |
| Brechas | Procedimiento documentado de notificación | F5 |

**Roles legales:** para los datos consultados, el **cliente es Responsable** y la plataforma
**Encargado** (Acuerdo de Encargado conforme a la normativa). Para las cuentas de usuario, la
plataforma es Responsable.
**Límite honesto:** ninguna arquitectura otorga inmunidad legal; reduce el riesgo y permite
demostrar diligencia.

---

## 12. Riesgos

| ID | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| RS-01 | Fuga de datos entre negocios | Media | Crítico | RLS forzado + prueba automatizada en CI |
| RS-02 | 429 sostenido detiene la ingesta | Alta | Alto | Presupuesto, cooldown, watermark que no avanza |
| RS-03 | Pérdida irreversible de histórico NCO | Alta | Alto | Arrancar F2 cuanto antes; historial append-only |
| RS-04 | Redis caído degrada el servicio | Media | Medio | Fallback a BD con avisos |
| RS-05 | Hambruna de términos en cola | Media | Medio | Prioridad + tope de antigüedad |
| RS-06 | Exportación masiva tumba el worker | Media | Medio | Proceso separado, streaming, umbral |
| RS-07 | Evicción usada como ataque | Media | Medio | Auditoría, notificación, rate limit de login |
| RS-08 | Secretos filtrados al repositorio | Media | Crítico | `.gitignore` en F0 + escaneo en CI |

---

## 13. Matriz de trazabilidad

| Objetivo | Requisitos | Casos de uso | Fase | Verificación |
|---|---|---|---|---|
| OE-1 | RF-07, RF-08 | CU-05, CU-12 | F2 | 48 h sin ciclos perdidos |
| OE-2 | RNF-01 | CU-03 | F3 | Prueba de carga p95 |
| OE-3 | RF-08 | CU-06, CU-12 | F2 | 0 duplicados |
| OE-4 | RNF-04 | CU-03 | F3 | Métrica de aciertos |
| OE-5 | R-01, R-02 | CU-04, CU-12 | F2, F3 | Auditoría de tráfico saliente |
| OE-6 | RF-05, RF-06, RF-16, RF-17 | CU-02, CU-11, CU-13 | F5 | Registro de consentimientos |
| OE-7 | RF-03, RF-04, RNF-05 | CU-01, CU-14 | F1, F4 | Prueba cross-tenant |
| OE-8 | RF-14 | CU-08 | F4 | Beacons y TTL medidos |
| OE-9 | RNF-10 | — | Transversal | Reporte de cobertura |

---

## 14. Glosario

| Término | Significado |
|---|---|
| NCO | Necesidades de Contratación (fuente del portal SERCOP) |
| OCDS | Open Contracting Data Standard (datos abiertos del SERCOP) |
| Negocio | Cliente de la plataforma (tenant); tiene N usuarios |
| RLS | Row Level Security de PostgreSQL; garantiza el aislamiento por negocio |
| Redis-first | La lectura se resuelve en Redis; la BD solo en caso de fallo de caché |
| Generación | Contador que invalida lógicamente toda la caché al cerrar un ciclo |
| Watermark | Marca de agua temporal que indica hasta dónde se ingirió |
| Ventana de solape | Margen (2 ciclos) que evita perder registros entre ejecuciones |
| Campo pendiente | Columna detectada en la fuente sin mapeo canónico definido |
| ARCO | Acceso, Rectificación, Cancelación y Oposición (derechos del titular) |
| RAT | Registro de Actividades de Tratamiento |
| LOPDP | Ley Orgánica de Protección de Datos Personales (Ecuador) |
| SPDP | Superintendencia de Protección de Datos Personales |

---

## 15. Control de cambios del documento

| Versión | Fecha | Cambio | Responsable |
|---|---|---|---|
| 0.1 | 2026-09-27 | Versión inicial: objetivos, alcance, requisitos, casos de uso, arquitectura, fases y plan de pruebas | Ingeniero QA |
| 0.2 | 2026-09-27 | Fase 0 en curso: se registran implementaciones, pruebas y evidencia real; capítulo 9.1 completado para F0 | Ingeniero QA |
| 0.3 | 2026-09-27 | Conexión a PostgreSQL gestionado (Supabase) verificada; adaptación de la URI y diagnóstico de conexiones; 5 defectos corregidos | Ingeniero QA |
| 0.4 | 2026-09-27 | Fase 1 completada: esquema de 19 tablas, aislamiento por RLS verificado con prueba automatizada, caché opcional y documentación por fase | Ingeniero QA |
| 0.5 | 2026-09-27 | Fase 2 completada sin cambios de base de datos: ingesta cada 15 min, mapeo automático de columnas, conservación del crudo y historial. Se documenta la decisión de la marca de agua en ciclos parciales. Nuevo **RF-19** y precisión del alcance del administrador en CU-08 (solo usuarios registrados y conectados de su propio negocio). Seis defectos reales encontrados por las pruebas y corregidos | Ingeniero QA |
| 0.6 | 2026-09-27 | Fases 3 y 3.5 completadas. F3: caché por delante con invalidación por generación, búsqueda multi-palabra sobre texto completo y alta de palabras clave sin llamar a la fuente. F3.5: acceso a vistas por plazos cerrados, con el vencimiento calculado en el servidor y comprobado al leer. Nuevos RF-20 a RF-22 y CU-15, CU-16. Cuatro defectos reales corregidos, entre ellos decimales devueltos como texto y, sobre todo, que una conexión reutilizada del grupo fallaba en lugar de denegar el acceso. Se añade `scripts/estado_esquema.py`, que destapa que el rol de conexión actual se salta RLS | Ingeniero QA |
| 0.7 | 2026-09-29 | Fase 4.1: la exportación deja de descargar el histórico entero —los filtros no llegaban al servidor por un desajuste de firma en el cliente—, se añaden las **columnas elegidas por empresa** (tabla `exportacion_columnas`, migración `0011`, RLS forzado y validación contra el catálogo), el **informe de la plantilla** que responde «¿dónde entran mis datos?», el **panel de filtros plegable** con preferencia recordada y los **totales por familia** en las pestañas (que ya no se contaminan al navegar). Verificado en el navegador con una empresa temporal | Ingeniero QA |
| 0.8 | 2026-09-29 | Fase 4.2: **búsqueda por CPC**, la clasificación normalizada del Estado. Hasta ahora el filtro de palabras clave solo miraba el objeto de compra —texto libre de la entidad— y por eso traía cualquier contratación que mencionara la palabra; ahora el CPC se lee de la ficha de cada necesidad (migración `0012`, cuatro columnas e índices), se rellena por tandas con cuota propia y se filtra con un criterio independiente que se puede sumar al de palabras clave. La exportación lleva una columna CPC y el detalle del panel muestra el desglose de ítems con su código y su cantidad. | Ingeniero QA |
| 0.9 | 2026-10-01 | Fase 4.3: **la ingesta estaba caída y parecía sana**. Cinco llamadas del caso de uso apuntaban a código que no existía —`terminos_completos` sin declarar y cuatro escrituras por lotes sin implementar—, y como el ciclo captura sus excepciones y las registra como «fallo inesperado», el síntoma no era un error visible sino **cero filas por ciclo**. Se recupera la ingesta y con ella se activa la **vigilancia del listado**: solo NCO cada 150 s, además del ciclo completo cada 15 min, para estrechar el hueco de una fuente que no publica histórico. La vigencia se reconcilia en las dos direcciones, NCO se declara `listado_completo` y el filtro de CPC pasa a aplicarse al guardar la lista, que es lo que se percibía como «no me deja agregar». Se añaden dos agentes revisores —**Ingesta** (¿trabajan los workers y escriben datos?) y **Despliegue** (¿se puede desplegar hoy y cuánta gente cabe, según qué evidencia?)— y `scripts/verificar_cpc_lista.py`, que dice cuánto aporta cada término de una lista de CPC | Ingeniero QA |
| 1.0 | 2026-10-01 | Fase 4.4: **el panel se pone al día solo**. Lo único que refrescaba la tabla era tocar un filtro, y el canal en vivo solo mueve presencia: la ingesta podía cerrar dos ciclos y la pantalla seguía igual. Se añade `GET /v1/ingestas/version` —la generación, una lectura de caché— que el panel pregunta cada minuto cuando la pestaña está visible, y se sube la generación al escribir los **CPC**, que entraban después de la invalidación de cada fuente y por eso aparecían sin clasificación. Se documenta además el flujo completo del sistema en `docs/11-flujo-del-sistema.md` | Ingeniero QA |
| 1.1 | 2026-10-01 | Fase 4.5: **la ingesta de ofertas pasa a ser general**. Medido contra la fuente, veinte palabras clave costaban ~5.760 peticiones al día; el listado general del año se sigue con ~133. Hasta aquí OCDS solo traía lo que coincidía con las palabras clave del cliente —800 filas de las 103.628 del año—, así que los filtros del panel buscaban sobre casi nada. Ahora el worker lee el **rabo del listado general** (lo recién publicado está al final) y las palabras clave quedan como **rescate** de una sola vez, limitado a los términos que **nunca** se han buscado —re-buscar uno ya buscado serían ~4.300 peticiones al día por datos que el rabo ya trae—. Se añade `scripts/rellenar_ofertas_ocds.py`, reanudable, para traer el año entero por tandas —10.363 páginas, ~1 GB, y ~34 h al ritmo real medido de ~12 s por página, con 429 y esperas de 20-30 s dentro—, que cede el bloqueo al worker entre tandas y **no mueve la marca de agua**, porque no cubre el final del listado. Nueva fase en `docs/12-fase-4e-ingesta-general-ocds.md` | Ingeniero QA |
| 1.2 | 2026-10-01 | Fase 4.6: **el año de procesos publicados entra en minutos, no en días.** La vía paginada del portal devuelve diez filas por petición y no acepta tamaño de página, así que completar 2026 costaba 10.363 peticiones con 429 cada cinco o seis —medido, ~26 horas—; el portal publica además los mismos procedimientos por meses en un ZIP, y son **doce peticiones**. Septiembre entró en 13 segundos y los nueve meses publicados dieron **103.135 procedimientos con el 94 % de objetos de compra y el 91 % de proveedores adjudicados**, campos que el listado dejaba a cero. El fichero es un delta de publicaciones, así que las filas se combinan por `ocid` antes de escribir. Se añaden tres guiones de medida y contraste, y queda **pendiente** lo más valioso: los ítems con **CPC** que el fichero ya trae —darían clasificación a las ofertas sin una petición por necesidad— | Ingeniero QA |
| 1.3 | 2026-10-01 | Fase 4.7: **se ve lo que trabajan los workers, y se les puede pedir un ciclo.** La pantalla de plataforma gana una tarjeta con la serie de sincronizaciones por fuente —leída de la tabla que los ciclos ya escriben, sin instrumentar nada nuevo— y un botón **Ejecutar ahora** que **no ingesta**: deja una petición en la caché con caducidad de quince minutos y el worker la consume en su bucle, que ahora duerme en tramos de cinco segundos para notarla. Un ciclo pedido a mano es un ciclo: se da por servida la hora y se reprograma la vigilancia. Verificado de extremo a extremo contra la API y el worker reales: el historial responde con las dos fuentes y 24 ciclos de cada una, un administrador de empresa recibe 403 en los dos endpoints, la petición se encola y **el worker la recogió en 3,2 s** arrancando el ciclo. Se arreglan además las gráficas, que mentían por dos motivos —el reparto por provincia llegaba **recortado a doce filas** y se calculaba con el filtro de provincia aplicado, así que doce provincias parecían vacías y elegir una ponía las demás a cero— y la gráfica que **nacía en blanco** cuando su pestaña estaba oculta al montarse: Chart.js no recibe aviso de que el contenedor aparece, y la gráfica se quedaba sin pintar hasta que algo la refrescaba, que es lo que se percibía como «las gráficas se bugean». Los tres defectos del camino —la lista de avisos que se pintaba como `[]`, el `IntersectionObserver` que tumbaba el panel entero y la carrera al comprobar el ciclo nuevo— están en `docs/14-fase-4g-panel-plataforma.md`. Queda **pendiente** que las gráficas respondan a las preguntas que se les piden | Ingeniero QA |
| 1.4 | 2026-10-02 | Fase 4.8: **buscar una ínfima cuantía por su NIC**. El panel ya acotaba por palabras clave, CPC, provincia, estado y fechas, pero no por el código que la ficha publica —el NIC—, así que quien tenía un `NIC-…` delante no podía pedir esa necesidad. Se añade el campo al panel lateral **sin tocar la API**: el NIC es el `codigo` de la necesidad NCO —el mapeo de la fuente lo traduce— y ese criterio ya existía, ya llegaba al `WHERE` y ya viajaba a la tabla, las gráficas y la exportación. La búsqueda es por fragmento y no se guarda en el caché, que es la regla que `Filtros.cacheable` ya aplicaba al código. Verificado contra la base real con un NIC de verdad: encuentra su fila, un fragmento encuentra la suya y sus vecinas, y un código inventado devuelve cero | Ingeniero QA |
