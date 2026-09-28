# Fase 1 — Modelo de datos multi-tenant y aislamiento

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-09-27 |
| Depende de | F0 |
| Casos de uso | CU-14 |
| Requisitos | RF-01, RNF-05, R-04, R-05 |

## 1. Objetivo

Implementar el modelo relacional completo (plano compartido + plano de negocio) con aislamiento
por negocio garantizado **por la base de datos**, no por el código.

## 2. Alcance

**Incluido:** extensiones `pg_trgm`, `unaccent`, `pgcrypto`, `citext` · tablas del plano
compartido (`fuente`, `campo_mapeo`, `campo_pendiente`, `termino`, `registro`,
`registro_historial`, `sincronizacion`) · tablas del plano de negocio (`negocio`, `usuario`,
`sesion`, `suscripcion_termino`, `conjunto_terminos`, `conjunto_termino`, `filtro_guardado`,
`exportacion`, `consentimiento`, `solicitud_arco`, `auditoria`, `politica_version`) · RLS
forzado · particionado mensual de `registro_historial` y `auditoria` · migraciones Alembic.

**Excluido:** lógica de ingesta, caché, autenticación y endpoints de negocio.

## 3. Modelo de relaciones clave

```
negocio 1 ─── N usuario          (un usuario pertenece a un solo negocio)
negocio 1 ─── N suscripcion_termino
negocio 1 ─── N exportacion
usuario 1 ─── N sesion
usuario 1 ─── N consentimiento
fuente  1 ─── N registro
registro 1 ── N registro_historial
registro 1 ── 1 punto_contacto_entidad
```

## 4. Criterios de aceptación

- [x] `alembic upgrade head` corre contra una base vacía y deja el esquema completo
- [x] `alembic downgrade base` revierte sin errores y `upgrade head` vuelve a aplicarlo
- [x] Todas las tablas del plano de negocio tienen `ENABLE` **y** `FORCE ROW LEVEL SECURITY` (comprobado contra `pg_class`)
- [x] El rol de la aplicación **no** es superusuario ni tiene `BYPASSRLS` (comprobado contra `pg_roles`)
- [x] **Prueba de aislamiento: consultando sin `WHERE`, cada negocio solo ve sus filas y sin contexto no se ve ninguna**
- [x] El `WITH CHECK` impide insertar datos a nombre de otro negocio
- [x] Las tablas particionadas tienen partición del mes en curso y partición predeterminada
- [ ] `UNIQUE (negocio_id, lower(email))` permite el mismo email en dos negocios distintos — **no verificado explícitamente** (ver deuda)

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-01 Fuga entre negocios | RLS forzado + prueba automatizada contra la base real |
| Migraciones no portables local→remoto | Solo cambiar `DATABASE_URL`; sin SQL específico de un motor |

## 6. Implementaciones realizadas

| # | Componente | Archivo / símbolo | Qué hace |
|---|---|---|---|
| 1 | Entorno de migraciones | `backend/alembic.ini`, `backend/alembic/env.py` | Resuelve la URL desde la configuración de la aplicación; migraciones escritas a mano |
| 2 | Esquema inicial | `alembic/versions/0001_esquema_inicial.py` | 19 tablas: 7 del plano compartido + 11 del plano de negocio + `politica_version`, con índices y particionado |
| 3 | Aislamiento | `alembic/versions/0002_aislamiento_rls.py` | RLS `ENABLE` + `FORCE` y políticas por negocio, incluida la tabla sin `negocio_id` |
| 4 | Caché opcional | `aplicacion/puertos/cache.py`, `cache/{cliente,nula,redis}.py` | El sistema funciona sin Redis; al desplegar se conecta por `REDIS_URL` |
| 5 | Informe de preparación | `routers/salud.py` | `/listo` distingue `ok`, `deshabilitada` y `error`; solo PostgreSQL es imprescindible |
| 6 | Prueba de aislamiento | `pruebas/integracion/test_aislamiento_negocios.py` | 5 casos, incluida la creación de un rol de aplicación real |

### Decisiones tomadas

1. **Sin extensiones de PostgreSQL.** `gen_random_uuid()` es nativo desde la versión 13 y el índice único usa `lower(email)` en vez de `citext`. Esto evita depender de en qué esquema instale las extensiones un proveedor gestionado.
2. **Dos planos de datos.** El plano compartido no lleva `negocio_id` porque los datos del SERCOP son públicos e idénticos para todos los clientes: se ingestan una vez y se sirven a todos. Con 50 clientes siguiendo el mismo término, eso es **1 petición** al SERCOP en lugar de 50.
3. **Partición predeterminada** en las dos tablas particionadas, para que una inserción nunca falle por falta de partición mensual.
4. **El rol de pruebas no se elimina**: `DROP ROLE` falla mientras conserve privilegios y revocarlos exige permisos que el administrador de un proveedor gestionado no tiene. Se crea o se le refresca la clave, que es idempotente.

## 7. Pruebas ejecutadas y resultado real

| Prueba | Resultado |
|---|---|
| `ruff check` + `ruff format --check` | `All checks passed!` · `37 files already formatted` |
| `mypy` (estricto) | `Success: no issues found in 31 source files` |
| Unidad | `22 passed` |
| Integración contra Supabase | `8 passed` |
| Reversibilidad | `downgrade base` → `upgrade head` → `0002 (head)` sin errores |

**Defectos encontrados y corregidos:**

1. **`asyncpg` no admite varias sentencias en una consulta preparada**: la migración inicial fallaba con «cannot insert multiple commands into a prepared statement». Se añadió un ejecutor que parte el SQL sentencia a sentencia.
2. **`CREATE ROLE` y `ALTER ROLE` no admiten parámetros** y, además, cambiar atributos privilegiados de un rol exige superusuario: el segundo caso se resolvió refrescando solo la clave.
3. **`DROP ROLE` fallaba por privilegios concedidos** y el administrador del proyecto no puede hacer `DROP OWNED BY`.
4. **La limpieza de datos necesita contexto de negocio**: las políticas también se aplican al borrar, así que la prueba fija el contexto antes de insertar y de eliminar.

## 8. Evidencia de aceptación

```
$ alembic upgrade head
Running upgrade  -> 0001, Esquema inicial: plano compartido, plano de negocio y tablas particionadas.
Running upgrade 0001 -> 0002, Aislamiento entre negocios mediante Row Level Security.

$ alembic current
0002 (head)

$ alembic downgrade base
Running downgrade 0002 -> 0001 / 0001 -> 
$ alembic upgrade head   # se vuelve a aplicar sin errores

$ pytest pruebas/integracion -v     (PRUEBAS_INTEGRACION=1)
test_postgres_responde                        PASSED
test_cache_esta_operativa_o_deshabilitada     PASSED
test_listo_devuelve_200                       PASSED
test_las_tablas_tienen_rls_activado_y_forzado PASSED
test_un_negocio_no_ve_los_datos_de_otro       PASSED
test_sin_contexto_no_se_ve_nada               PASSED
test_no_se_puede_insertar_en_otro_negocio     PASSED
test_el_rol_de_aplicacion_no_es_superusuario  PASSED

8 passed
```

## 9. Deuda técnica y pendientes

- **Verificar explícitamente** que el mismo email puede existir en dos negocios distintos.
- **Crear el rol de aplicación en el entorno real** y cambiar `DATABASE_URL` para que la aplicación no use el usuario administrador: es lo que garantiza que RLS proteja de verdad (R-05).
- **Particiones futuras**: hoy se crean las del mes en curso y dos más. Hace falta un job que las genere antes de que llegue el mes (F2).
- Mover las filas que caigan en la partición predeterminada a su partición mensual.
- `SET LOCAL app.negocio_id` por transacción en el repositorio (F3), con el valor tomado del token y nunca de la petición.
