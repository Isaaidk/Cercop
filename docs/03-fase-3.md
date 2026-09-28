# Fase 3 — Redis-first: caché, filtros y búsqueda multi-palabra

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-09-27 |
| Depende de | F2 |
| Casos de uso | CU-03, CU-04 |
| Requisitos | RF-11, RF-12, RNF-01, RNF-02, RNF-04, RNF-13, OE-2, OE-4, OE-5 |

## 1. Objetivo

Que aplicar muchos filtros **no toque la base de datos ni la fuente oficial**, y que agregar una
palabra clave nueva dispare la consulta a la fuente sin exponer al usuario a la espera ni al
límite de tasa.

## 2. Alcance

**Incluido:** capa de caché como primera parada de toda lectura · invalidación lógica por
`generacion:{fuente}` · claves derivadas de `hash(filtros)` · caché de catálogo y estadísticas ·
búsqueda con N términos (seleccionados y agregados) con modo `todas`/`cualquiera` · cola de
ingesta bajo demanda con prioridad y deduplicación global · endpoint de estado de ingesta ·
degradación a base de datos cuando Redis no responde.

**Excluido:** RediSearch, búsqueda semántica, frontend.

## 3. Diseño

```
lectura  →  Redis (clave = hash(filtros) + generacion:fuente)  ──acierto──▶  respuesta
                                                                  │
                                                              fallo │
                                                                  ▼
                                                          PostgreSQL ─▶ guardar en caché ─▶ respuesta
```

| Regla | Definición |
|---|---|
| TTL | Un ciclo (15 min): máximo 1 consulta real a la base por combinación de filtros por ciclo |
| Invalidación | `INCR generacion:{fuente}` al cerrar cada ciclo; las claves antiguas quedan obsoletas y expiran solas |
| Qué se cachea | Páginas de resultados, catálogo de filtros y estadísticas. **Nunca** el conjunto completo |
| Término nuevo | El request responde de inmediato con resultados parciales y estado de ingesta; **jamás** llama a la fuente |
| Prioridad de cola | Nº de negocios suscritos, luego antigüedad sin ingesta |

## 4. Criterios de aceptación

- [ ] ≥80% de lecturas servidas desde caché en escenario de hora pico simulado
- [ ] p95 de consulta cacheada < 300 ms; consulta a base < 1,5 s
- [ ] Agregar un término nuevo responde en < 1 s con `estado_ingesta` y resultados parciales
- [ ] 10 negocios pidiendo el mismo término nuevo → **1** ingesta
- [ ] Tras un ciclo, la clave de caché cambia (invalidación efectiva)
- [ ] Con Redis apagado el sistema responde desde la base y devuelve `avisos`
- [ ] Ninguna respuesta contiene `NaN` ni `Infinity`

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-04 Redis caído | Fallback a base con avisos |
| RS-05 Hambruna de términos en cola | Prioridad + tope de antigüedad + alerta |
| Memoria de Redis por claves sin control | Tope de tamaño por entrada y política de expulsión |

## 6. Implementaciones realizadas

| Componente | Archivo | Qué resuelve |
|---|---|---|
| Filtros y huella | `dominio/busqueda.py` | `Filtros` inmutable, modos `todas`/`cualquiera`, huella estable, topes de paginación |
| Coincidencia y consulta | `dominio/busqueda.py` | `palabras_de`, `coincide`, `expresion_busqueda`, claves de caché |
| Serialización | `dominio/serializacion.py` | `sanear` convierte `NaN` e `Infinity` en nulo (RNF-13) |
| Generaciones | `aplicacion/generaciones.py` | `leer_generacion`, `subir_generacion` |
| Búsqueda con caché | `aplicacion/casos_uso/buscar_registros.py` | Caché por delante y degradación a base con avisos |
| Alta de términos | `aplicacion/casos_uso/encolar_termino.py` | Suscripción y encolado, **sin llamar a la fuente** |
| Lecturas | `salida/bd/consultas.py` | Texto completo con prefijos, catálogos, estadísticas, estado de fuentes |
| Términos | `salida/bd/terminos.py` | Catálogo global, suscripciones y cola priorizada |
| Contexto de negocio | `salida/bd/contexto.py` | `contexto_negocio` y `sin_contexto`, con transacción explícita |
| Endpoints | `routers/{busqueda,terminos,ingestas}.py` | `/v1/registros`, `/v1/catalogos`, `/v1/estadisticas`, `/v1/terminos`, `/v1/ingestas` |

### 6.1 Las decisiones que importan

- **Búsqueda por prefijo de palabra, no por subcadena.** Los índices GIN de `tsvector` **no aceleran
  `LIKE '%texto%'`**, así que la coincidencia se expresa con `@@` y `palabra:*`. La consecuencia
  buscada: «vial» encuentra «viales» y «oral» **no** encuentra «moral».
- **Las palabras se sanean antes de tocar el motor.** `&`, `|`, `!` y `*` significan algo en
  `tsquery`; filtrarlos convierte «obras|viales» en la conjunción que el usuario quiso escribir, en
  lugar de en otra consulta distinta.
- **Una sola función alimenta la comprobación en memoria y la consulta SQL.** Si divergieran, la
  misma búsqueda devolvería resultados distintos según tuviera el caché delante o no.
- **Dos generaciones, no una.** La de la fuente invalida lo suyo; la global invalida las búsquedas,
  porque una consulta puede abarcar varias fuentes a la vez.
- **Agregar un término no consulta la fuente.** Responde `202` con resultados parciales y encola; el
  panel refresca consultando el estado.

## 7. Pruebas ejecutadas y resultado real

| Conjunto | Cantidad | Resultado |
|---|---|---|
| `pruebas/unidad` | 162 | **162 pasan** |
| `pruebas/integracion` (con `PRUEBAS_INTEGRACION=1`) | 29 | **29 pasan** |

### 7.1 Defectos reales encontrados y corregidos

| # | Defecto | Cómo se encontró | Corrección |
|---|---|---|---|
| 1 | **Los números decimales se devolvían como texto** | `test_conserva_los_numeros_normales` | `float` faltaba en `TIPOS_ESCALARES`, así que caía en la conversión final a texto. Todos los montos habrían viajado entre comillas |
| 2 | **Una palabra clave con espacios se partía en varias** | `test_normaliza_acentos_mayusculas_y_espacios` | Se separa solo por comas, punto y coma y saltos de línea; los espacios se conservan dentro del término |
| 3 | **La migración no se podía aplicar: `unterminated dollar-quoted string`** | Al ejecutar `alembic upgrade head` | El cuerpo de la función lleva un `;` dentro; el separador de sentencias lo partía. Se envía como una única sentencia |
| 4 | **Una conexión reutilizada del grupo fallaba en lugar de denegar** | `test_sin_contexto_no_se_ve_ninguna_concesion` | Una vez fijada la variable de contexto, revertirla la deja **vacía**, no inexistente, y `''::uuid` es un error en lugar de `NULL`. Corregido con `NULLIF(..., '')` en la migración 0004 |

El cuarto es el más serio. De haberse desplegado, la segunda petición que llegara por una conexión ya
usada habría devuelto un error de servidor: el aislamiento no habría estado abierto, habría estado
roto, que se descubre mucho más tarde.

## 8. Evidencia de aceptación

```text
$ ruff check src pruebas scripts alembic
All checks passed!

$ ruff format --check src pruebas scripts alembic
83 files already formatted

$ mypy
Success: no issues found in 76 source files

$ pytest pruebas/unidad -q
162 passed

$ PRUEBAS_INTEGRACION=1 pytest pruebas/integracion -q
29 passed

$ pip-audit --skip-editable
No known vulnerabilities found

$ alembic current
0004 (head)

$ python scripts/estado_esquema.py
Tablas  : las 13 esperadas existen
Aislamiento: activo y forzado en las 12 tablas
  AVISO: este rol es superusuario=False y puede saltarse RLS=True.
```

### 8.1 Lo que la evidencia obliga a corregir antes de desplegar

El diagnóstico señala que el rol de la conexión **puede saltarse RLS** (`rolbypassrls=True`). Es el rol
`postgres` de Supabase, con el que la aplicación se conecta hoy. Las políticas están bien escritas y
las pruebas lo demuestran porque se conectan con un rol propio que no puede saltárselas, pero
**mientras `DATABASE_URL` apunte a `postgres`, en producción no se aplican**.

No es un defecto de esta fase: es la tarea pendiente R-05, y ahora está medida en lugar de supuesta.

## 9. Deuda técnica declarada

| Tema | Motivo | Fase |
|---|---|---|
| Sin inicio de sesión | El actor se construye desde cabeceras y solo con `PERMITIR_ACTOR_DE_DESARROLLO`; **en producción se rechaza siempre** | F4 |
| El `worker` no consume todavía la cola priorizada | La cola se llena cuando el panel permite agregar términos | F4 |
| Mantenimiento de particiones | Hay meses creados de sobra; toca automatizar la limpieza | Operación |
| Umbrales de búsqueda | Suficientes con el volumen actual; se revisarán con datos reales | Operación |

## 10. La lógica de la cola de palabras clave

Esta sección documenta la regla que decide si un cliente ve las contrataciones que le interesan, y
existe porque la primera versión **no las veía**.

### 10.1 El defecto

El planificador pedía los términos así:

```sql
ORDER BY prioridad DESC, ultima_ingesta_en NULLS FIRST, creado_en LIMIT 20
```

El orden parecía razonable y no lo era por dos motivos encadenados:

1. `ultima_ingesta_en` **no se actualizaba en ninguna parte**. El campo existía desde la fase 1 y nadie
   lo escribía.
2. Como todos los términos lo tenían nulo, el orden degeneraba en «los 20 primeros por fecha de
   creación».

La consecuencia: **todo término añadido después del vigésimo no se ingestaba jamás**. Nada fallaba, no
había errores en los registros y el panel mostraba el término «en cola» para siempre. Con 50 negocios
en el primer año y varias palabras clave por negocio, el catálogo supera las 20 con holgura: el sistema
habría ido perdiendo contrataciones en silencio desde el primer día.

### 10.2 La regla que lo sustituye

**Turno garantizado por rotación.** El orden pasa a ser:

```sql
ORDER BY ultima_ingesta_en NULLS FIRST,   -- nunca buscado, primero
         prioridad DESC,                  -- la urgencia de un administrador solo desempata
         conteo_suscriptores(id) DESC,    -- y a igualdad, lo que pide más gente
         creado_en
```

Y, después de cada ciclo correcto, los términos buscados se marcan con `marcar_terminos_ingestados`.
Esas dos piezas juntas garantizan que la cola **rote**: ningún término espera más de
`ceil(N / tope)` ciclos, donde `N` es el número de términos activos. Con 100 términos y un tope de 20,
el peor caso es de 75 minutos.

Conviene notar por qué la prioridad **no** va primero. Si mandara, un término urgente y otro tranquilo
competirían en proporción y el tranquilo acabaría sin buscarse nunca. Que un cliente se quede sin sus
datos porque otro pagó por ir primero no es un compromiso aceptable.

### 10.3 La ventana de recuperación

Un término nuevo se busca con una **ventana inicial amplia** (`VENTANA_INICIAL_DIAS`, 90 días por
defecto) en lugar de con el solape de dos ciclos. Es lo que recupera las contrataciones publicadas
**antes** de que el cliente se suscribiera: sin ello, agregar una palabra clave solo devolvería lo
publicado desde ese instante, y el histórico anterior sería irrecuperable para siempre.

La ventana del lote la fija el término más nuevo: basta con que uno nunca se haya buscado para leer
todo el lote desde la ventana amplia. Es deliberadamente conservador, y la asimetría lo justifica:
perder contrataciones es irreversible, releer datos ya vistos solo cuesta peticiones, y el presupuesto
del ciclo acota ese coste.

En OCDS el punto de partida no se traduce a un filtro de fechas —**la API busca por año**— sino a
cuántos años hay que revisar. Antes se ignoraba el parámetro y se revisaban todos los años
configurados en cada ciclo de 15 minutos; ahora el coste es proporcional a lo que de verdad hay que
recuperar.

### 10.4 Evidencia

`pruebas/integracion/test_cola_terminos.py` comprueba, contra la base real, que lo nunca buscado va
primero, que entre buscados gana el más olvidado, que la prioridad no puede dejar a nadie sin turno y
que **un término agregado después entra por delante**. Estas pruebas se limpian solas: crean términos en
el catálogo real con un prefijo reconocible y los borran al empezar y al terminar.

