# Fase 0 — Cimientos y seguridad del repositorio

| Campo | Valor |
|---|---|
| Estado | **En curso** |
| Casos de uso | — (habilitante) |
| Requisitos | RNF-09, RNF-10, RNF-12, R-05 (parcial) |

## 1. Objetivo

Dejar el repositorio listo para trabajar sin riesgo de filtrar secretos, con entorno local
reproducible, esqueleto hexagonal y puerta de calidad automatizada. **Sin lógica de negocio.**

## 2. Alcance

**Incluido:** `.gitignore` raíz · `.env.example` · esqueleto hexagonal · configuración con
validación fail-fast · app FastAPI mínima con `/salud` y `/listo` · `pyproject.toml` · CI
(`ruff`, `mypy`, `pytest`, `pip-audit`) · estructura de pruebas y documentación.

**Excluido:** cualquier tabla de negocio, migraciones de dominio, ingesta, caché, auth y frontend.

## 3. Entregables

| # | Entregable | Ruta |
|---|---|---|
| 1 | Ignorados de Git | `.gitignore` |
| 2 | Plantilla de entorno | `.env.example` |
| 3 | Proyecto del backend | `backend/pyproject.toml` |
| 4 | Configuración validada | `backend/src/contratacion/infraestructura/config/ajustes.py` |
| 5 | App y factoría | `backend/src/contratacion/infraestructura/app.py`, `asgi.py` |
| 6 | Salud y preparación | `.../adaptadores/entrada/http/routers/salud.py` |
| 7 | Conexiones | `.../adaptadores/salida/bd/sesion.py`, `.../cache/cliente.py` |
| 8 | CI | `.github/workflows/ci.yml` |
| 9 | Pruebas base | `backend/pruebas/` |

## 4. Criterios de aceptación

- [x] `.env.example` versionado y `.env` ignorado *(verificado por inspección; el repositorio aún no está inicializado en Git)*
- [x] Arrancar sin los secretos obligatorios **falla**: 5 errores de validación (`database_url`, `redis_url`, `jwt_secreto`, `clave_cifrado_datos`, `clave_pepper_hmac`)
- [x] `CORS_ORIGINS` con `*` es **rechazado** en la validación (corrección de V1)
- [x] `GET /salud` responde 200
- [x] `GET /listo` responde **503** nombrando la dependencia que falla
- [x] **Conexión a PostgreSQL gestionado verificada**: Supabase responde desde la aplicación, con TLS automático y controlador `asyncpg`
- [x] `GET /listo` responde **200** con PostgreSQL disponible: el caché es opcional y su ausencia no lo impide
- [x] `ruff check` sin hallazgos y `ruff format --check` limpio
- [x] `mypy` (estricto) sin errores en 31 archivos
- [x] `pytest` verde: 22 de unidad y 8 de integración
- [x] `pip-audit` sin vulnerabilidades conocidas
- [ ] CI verde en el primer push — **pendiente: inicializar Git y publicar**

## 5. Restricciones

- **R-05:** el rol de aplicación no puede ser superusuario (saltaría RLS) — se documenta aquí,
  se aplica en F1.
- Puerto del API v2: **8001** (el legado usa 8000 y debe seguir funcionando durante la migración).

## 6. Implementaciones realizadas

| # | Componente | Archivo / símbolo | Qué hace |
|---|---|---|---|
| 1 | Ignorados de Git | `.gitignore` | Excluye entornos, credenciales, artefactos y respaldos |
| 2 | Plantilla de entorno | `.env.example` | Declara todas las variables; marca las obligatorias sin valor por defecto |
| 3 | Proyecto | `backend/pyproject.toml` | Dependencias fijadas, extras de desarrollo, ruff, mypy y pytest |
| 4 | Configuración | `infraestructura/config/ajustes.py::Ajustes`, `obtener_ajustes` | Valida al arrancar; rechaza el comodín CORS; exige secretos largos en producción; deriva `ventana_solape_min` |
| 5 | Aplicación | `infraestructura/app.py::crear_app`, `_ciclo_vida` | Factoría con CORS desde configuración y verificación de dependencias al arrancar |
| 6 | Entrada ASGI | `asgi.py` | Punto de entrada del proceso `api` |
| 7 | Salud | `adaptadores/entrada/http/routers/salud.py` | `/salud` (vida) y `/listo` (dependencias, 503 si fallan) |
| 8 | PostgreSQL | `adaptadores/salida/bd/sesion.py` | Motor y sesiones asíncronas perezosas; `verificar_bd`; `cerrar_bd` |
| 9 | Redis | `adaptadores/salida/cache/cliente.py` | Cliente perezoso; `verificar_cache`; `cerrar_cache` |
| 10 | Integración continua | `.github/workflows/ci.yml` | ruff, formato, mypy, pytest y pip-audit |
| 11 | Pruebas | `pruebas/unidad/test_ajustes.py`, `test_salud.py`, `pruebas/integracion/test_dependencias.py` | 15 casos |

## 7. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Estilo | `ruff check .` | `All checks passed!` |
| Formato | `ruff format --check .` | `30 files already formatted` |
| Tipado estricto | `mypy` | `Success: no issues found in 27 source files` |
| Unidad y contrato | `pytest` | `22 passed, 1 skipped` |
| Integración contra Supabase | `pytest pruebas/integracion` con `PRUEBAS_INTEGRACION=1` | Postgres **pasa**; Redis falla (no está instalado) |
| Auditoría | `pip-audit -r deps-a-auditar.txt` | `No known vulnerabilities found` |
| Fallo rápido | `python -c "import contratacion.asgi"` sin variables | `5 validation errors for Ajustes` |

**Defectos encontrados y corregidos durante la verificación:**

1. `cors_origins` no aceptaba la forma `origen1,origen2` de `.env`: pydantic-settings intentaba interpretarla como JSON y fallaba. Se corrigió con `NoDecode`.
2. `mypy` sin argumentos no tenía objetivos: se añadió `files = ["src", "pruebas", "scripts"]`.
3. Dos pruebas tenían defectos propios: duplicación de palabra clave al combinar diccionarios y no eliminar la variable de entorno que define `conftest`.
4. Se habilitó la regla `BLE001` para exigir justificación de los `except Exception` amplios.
5. **La URI de un proveedor gestionado no era usable tal cual**: el panel entrega `postgresql://` y sin controlador asíncrono el error resultante es confuso. Se añadió `normalizar_url_bd` (controlador `asyncpg` + TLS en hosts remotos), con 8 pruebas.
6. **Las variables de entorno tapan el archivo `.env`**: `conftest` inyectaba destinos ficticios y hacía fallar las pruebas de integración sin motivo. Ahora solo los inyecta fuera del modo integración.
7. **El motor de base de datos global no sobrevive a distintos bucles de eventos**: la segunda prueba que tocaba la base fallaba con «Event loop is closed». Se añadió limpieza de recursos entre pruebas; el diseño definitivo (motor atado al ciclo de vida de la aplicación) queda para F1.
8. Se añadió `scripts/verificar_conexiones.py`, que diagnostica sin exponer credenciales: solo estado y causa clasificada.

## 8. Evidencia de aceptación

```
--- RUFF ---
All checks passed!  |  30 files already formatted
--- MYPY ---
Success: no issues found in 27 source files
--- PYTEST (unidad) ---
22 passed, 1 skipped
--- PIP-AUDIT ---
No known vulnerabilities found            EXIT=0
--- ARRANQUE SIN SECRETOS ---
ValidationError: 5 validation errors for Ajustes
  database_url / redis_url / jwt_secreto / clave_cifrado_datos / clave_pepper_hmac
--- CONEXION REAL (Supabase) ---
$ python scripts/verificar_conexiones.py
postgres   OK
redis      FALLO   ConnectionError        <- Redis no instalado, no es un fallo de configuracion
--- INTEGRACION ---
pruebas/integracion/test_dependencias.py::test_postgres_responde  PASSED
```

## 9. Deuda técnica y pendientes

- **El caché queda desactivado en desarrollo** por decisión explícita: sin `REDIS_URL`, el sistema funciona leyendo de la base de datos. Al desplegar se conectará el almacén gestionado. Ver el puerto `Cache` y sus dos implementaciones.
- **LangCache no sustituye a Redis.** LangCache es una caché *semántica* para respuestas de modelos de lenguaje, no un almacén clave-valor: devuelve resultados *parecidos*, no idénticos. El backend necesita Redis para la caché por combinación de filtros, las sesiones, la presencia y los bloqueos. Sus variables quedan reservadas en `.env.example`, sin uso.
- **Atar el motor de base de datos al ciclo de vida de la aplicación** en lugar de usar una variable global perezosa: hoy el motor queda ligado al bucle de eventos que lo creó.
- Generar el archivo de bloqueo de dependencias para builds reproducibles (RNF-08 / V8).
- Inicializar el repositorio Git y publicar para que el flujo de integración continua quede verde.
- Rotar la contraseña de la base de datos: la cadena de conexión se compartió en texto plano por chat.
- **No usar `SUPABASE_SECRET_KEY`**: es una clave de nivel servicio que **se salta Row Level Security** y anularía el aislamiento entre negocios (OE-7). El backend se conecta con usuario de base de datos, sujeto a RLS.
- Retirar `package.json`, `package-lock.json` y `node_modules` de la raíz: los creó una instalación npm que no aporta nada al backend Python.
