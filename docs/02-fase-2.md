# Fase 2 — Ingesta automática y mapeo automático de columnas

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-09-27 |
| Depende de | F1 |
| Casos de uso | CU-05, CU-06, CU-12 |
| Requisitos | RF-07, RF-08, RF-09, RF-10, OE-1, OE-3, OE-5, R-01, R-02, R-03, R-06 |

> **Sin cambios de base de datos.** El esquema de F1 ya cubría todo lo necesario
> (`fuente`, `campo_mapeo`, `campo_pendiente`, `termino`, `registro`, `registro_historial`,
> `sincronizacion`). La revisión de Alembic sigue en `0002 (head)`.

## 1. Objetivo

Acumular histórico propio de forma confiable cada 15 minutos, sin bloquear nunca la fuente
oficial y sin perder ningún campo que la fuente publique.

> **Este es el hito que arranca el activo comercial:** el SERCOP no expone histórico de NCO, por
> lo que cada día sin ingesta es información irrecuperable.

## 2. Alcance

**Incluido:** proceso `worker` con planificador de 15 min · lock de exclusión mutua
(advisory lock) · limitador de tasa compartido (semáforo, intervalo mínimo, cooldown, reintentos
con `Retry-After`) · presupuesto de peticiones por ciclo · adaptadores de fuente (NCO y OCDS) ·
motor de mapeo dirigido por datos (`campo_mapeo`) · detección de campos nuevos
(`campo_pendiente`) con conservación del payload íntegro en JSONB · upsert por clave natural y
`hash_contenido` · historial *append-only* · registro de cada ciclo en `sincronizacion`.

**Excluido:** caché de lectura, endpoints de consulta, autenticación.

## 3. Reglas de negocio de la ingesta

| Regla | Definición |
|---|---|
| Ventana de solape | `2 × intervalo` (30 min) desde el watermark, para no perder registros entre ciclos |
| Nuevo | Clave natural ausente en la base → insertar, `es_nuevo = true` |
| Cambiado | Clave natural presente con `hash_contenido` distinto → actualizar + historial |
| Igual | Clave natural presente con el mismo hash → no tocar |
| Marca temporal | No existe "hora de creación" en las fuentes: se usa `fecha_publicacion` como proxy y `primera_vez_visto` como autoridad |
| Fallo parcial | 429/5xx → ciclo `parcial`, **el watermark no avanza**, se registran `avisos` |
| Deduplicación | Un término se ingesta **una sola vez** para todos los negocios |

## 4. Criterios de aceptación

- [ ] 48 h continuas sin perder un ciclo, con registro de cada ejecución → **diferido a operación**; requiere el `worker` en un proceso persistente (ver deuda)
- [x] Ejecutar el mismo ciclo dos veces → 0 nuevos, 0 duplicados, 0 filas nuevas de historial
- [x] Un payload con una clave desconocida crea `campo_pendiente` y **conserva el crudo íntegro**
- [x] Al resolver un pendiente, el ciclo siguiente puebla el campo canónico
- [x] Un ciclo nunca supera `presupuesto_peticiones_ciclo` (`Presupuesto.agotado`)
- [x] 429 simulado → ciclo `parcial` y watermark sin avanzar
- [x] **0 peticiones originadas por usuarios** (solo el worker habla con la fuente)
- [x] Detección de cambios: 1 campo distinto → 1 fila de historial y 1 actualización
- [x] La caché solo se invalida cuando hay cambios reales (generación de la clave)

### 4.1 Decisión sobre el watermark en ciclos parciales

En un ciclo `parcial` (429/5xx) **no se deja el watermark en `NULL`**: se persiste el **mismo valor
anterior**. Dejarlo en `NULL` haría que `ultima_sincronizacion_ok()` cayera en el último ciclo
registrado y el siguiente intento reabriera una ventana enorme. Conservar el valor anterior logra
las dos cosas a la vez:

- la marca **no avanza**, así que lo que falló se vuelve a pedir en el próximo ciclo (cero huecos);
- la ventana se mantiene acotada (`2 × intervalo`), así que no se dispara el presupuesto.

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-02 429 sostenido | Presupuesto + cooldown + watermark que no avanza |
| RS-03 Pérdida de histórico NCO | Arrancar cuanto antes; historial append-only |
| Cambio silencioso de contrato de la fuente | `esquema_version` + alerta al cambiar el conjunto de claves |

## 6. Implementaciones realizadas

| Componente | Archivo | Qué resuelve |
|---|---|---|
| Reglas de ingesta | `dominio/ingesta.py` | `clasificar()`, `hash_contenido()`, `ventana_desde()`, `Presupuesto`, `ContadoresCiclo` |
| Normalización de términos | `dominio/palabras.py` | Sin acentos, minúsculas, mínimo 3 caracteres, deduplicación por forma normalizada |
| Conversión de tipos | `aplicacion/mapeo.py` | `html_a_texto`, fechas, entero, moneda y número **con separadores locales**, booleano, `separar_por`, `regex` con reserva del valor original |
| Orquestación del ciclo | `aplicacion/casos_uso/ejecutar_ingesta.py` | Clave natural, upsert, historial, pendientes, watermark, invalidación de caché |
| Persistencia | `infraestructura/salida/bd/ingesta.py` | 11 métodos; `SET`/contexto por transacción |
| Exclusión mutua | `infraestructura/salida/bd/bloqueo.py` | `pg_try_advisory_lock` con clave `sha256` → `int64` |
| Límite de tasa | `infraestructura/salida/fuentes/limitador.py` | Semáforo 2, intervalo mínimo 0,6 s, enfriamiento global ante 429, `Retry-After`, retroceso exponencial |
| Fuente NCO | `infraestructura/salida/fuentes/nco.py` | Una petición de ~1,8 MB, 120 s, cabeceras del portal |
| Fuente OCDS | `infraestructura/salida/fuentes/ocds.py` | Consulta por término, 3 páginas por término, marcador `_termino_buscado`, filtro por año |
| Mapeos por defecto | `nco_mapeos.py`, `ocds_mapeos.py` | Prefijos de las claves reales + `regex` para provincia y `href` |
| Planificador | `tareas/planificador.py` | `fuentes_por_defecto()`, `ejecutar_todos()`, `LIMITE_TERMINOS_POR_CICLO = 20` |
| Proceso | `tareas/worker.py` | `bucle()`, `ejecutar_un_ciclo()`, bandera `--una-vez` |
| Caché opcional | `salida/cache/{cliente,nula,redis}.py` | Sin `REDIS_URL` el sistema funciona leyendo de la base |

### 6.1 Reglas de calidad aplicadas

- **Inversión de dependencias:** el caso de uso solo conoce los puertos `FuenteExterna` y `Cache`;
  ninguna librería HTTP o de base de datos entra en `dominio/` ni en `aplicacion/`.
- **Datos personales fuera del índice:** `CAMPOS_BUSCABLES` excluye explícitamente `funcionario`,
  `email`, `telefono` y `contacto`, para no construir un buscador de personas (LOPDP).
- **Sin pérdida de información:** el payload crudo se guarda **completo** en JSONB antes de mapear;
  un campo desconocido se registra en `campo_pendiente` en lugar de descartarse.
- **Idempotencia:** la clave natural y el `hash_contenido` hacen que repetir un ciclo sea inofensivo.

## 7. Pruebas ejecutadas y resultado real

| Conjunto | Cantidad | Resultado |
|---|---|---|
| `pruebas/unidad` | 68 | **68 pasan** |
| `pruebas/integracion` (con `PRUEBAS_INTEGRACION=1`) | 14 | **14 pasan** |

Casos de integración que cubren los criterios de aceptación:

| Prueba | Qué demuestra |
|---|---|
| `test_el_ciclo_es_idempotente` | Repetir el ciclo no duplica ni ensucia el historial |
| `test_detecta_cambios_y_guarda_historial` | Un cambio real produce 1 historial y 0 duplicados |
| `test_un_campo_nuevo_queda_pendiente_sin_perder_el_crudo` | El crudo íntegro sobrevive al campo desconocido |
| `test_resolver_un_pendiente_puebla_el_campo_en_el_siguiente_ciclo` | El mapeo resuelto se aplica en el ciclo siguiente |
| `test_la_generacion_de_cache_solo_sube_cuando_hay_cambios` | La caché no se invalida en ciclos sin novedades |
| `test_si_el_ciclo_es_parcial_la_marca_de_agua_no_avanza` | Un 429 no abre hueco ni dispara el presupuesto |

### 7.1 Defectos reales encontrados y corregidos

| # | Defecto | Causa | Corrección |
|---|---|---|---|
| 1 | `"1.234,56"` se leía como `1.234` | Conversión ingenua con `float` | `_a_decimal()` con detección de separador decimal y de miles |
| 2 | `asyncpg` rechazaba la fecha como texto | Parámetro `timestamptz` enviado como `str` | `fecha_a_utc()` en el dominio + objetos `datetime` reales |
| 3 | Las pruebas de integración no veían la base real | `conftest` inyectaba URLs falsas **por encima** del `.env` | Inyección solo fuera del modo integración |
| 4 | `Event loop is closed` entre pruebas | Motor global compartido entre bucles de eventos | Fixture autouse que cierra motor y caché |
| 5 | Migración fallida en Supabase | `asyncpg` rechaza SQL con varias sentencias | `_ejecutar()` divide por `;` |
| 6 | Faltaban zonas horarias en Windows | No hay base de datos horaria del sistema | Dependencia `tzdata` |

## 8. Evidencia de aceptación

```text
$ ruff check .
All checks passed!

$ ruff format --check .
56 files already formatted

$ mypy
Success: no issues found in 50 source files

$ pytest pruebas/unidad -q
68 passed

$ PRUEBAS_INTEGRACION=1 pytest pruebas/integracion -q
14 passed

$ alembic current
0002 (head)          # sin cambios de esquema en la fase

$ python scripts/verificar_conexiones.py
postgres   OK
redis      OK   deshabilitada (sin REDIS_URL): el sistema funciona sin caché
```

## 9. Deuda técnica declarada

| Tema | Motivo | Fase |
|---|---|---|
| `registro.terminos_ids` queda vacío | El catálogo de términos y la suscripción se activan en F3 | F3 |
| El planificador pide todo desde el conteo más conservador | Sin catálogo de suscripciones todavía no hay nada que filtrar | F3 |
| Sin `periodista` de particiones futuras | Las particiones hasta 2027 ya existen; toca automatizar el mantenimiento | F3 |
| El `worker` necesita un proceso persistente | En un entorno sin servidor (Vercel) no sobrevive entre ejecuciones | Operación |
| 48 h continuas sin perder ciclos | Requiere el entorno real de operación | Operación |

