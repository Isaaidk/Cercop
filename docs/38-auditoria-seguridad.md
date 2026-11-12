# 38 · Auditoría de seguridad (2026-11-12)

Revisión de autenticación, rutas, aislamiento entre empresas, entrada de datos, asistente, panel,
registros y configuración, pensando en 500–1.000 personas de muchas empresas a la vez. Se leyó el
código; donde se afirma algo de la base de datos, se comprobó contra la base local (`pg_class`,
`pg_policy`, `pg_proc`, `pg_roles`).

Regla seguida: **no se quitó ninguna función**. Cada arreglo es pequeño, tiene prueba de regresión
(`backend/pruebas/unidad/test_auditoria_seguridad.py`,
`backend/pruebas/integracion/test_seguridad_alertas_rls.py`) y, cuando cambia el despliegue, una
variable con valor por defecto seguro.

## 1. Hallazgos

Severidad: **Crítica** (expone datos de otras empresas o la cuenta), **Alta** (salta una defensa
principal), **Media** (debilita una defensa o abre un abuso acotado), **Baja** (endurecimiento),
**Info** (correcto, se deja constancia).

| # | Sev. | Qué | Dónde | Estado | Cómo |
|---|------|-----|-------|--------|------|
| S-01 | **Crítica** (despliegue) | La API se conecta a PostgreSQL con un rol **superusuario y con `BYPASSRLS`** (riesgo R-05). Con ese rol las políticas de RLS **no se aplican**: el aislamiento entre empresas depende solo de que cada consulta lleve su `WHERE negocio_id`. Comprobado en local (`scripts/estado_esquema.py`: `superusuario=True`, `BYPASSRLS=True`); en Railway, `DATABASE_URL` usa el usuario administrador del servicio `bd`. | Configuración | **Pendiente (acción del usuario)** | Crear un rol de aplicación `NOSUPERUSER NOBYPASSRLS` y usarlo en `DATABASE_URL`; migrar con el rol propietario. SQL en §3. El código ya está preparado: los procesos que leen de todas las empresas usan funciones `SECURITY DEFINER` y S-09 arregla el último que no. |
| S-02 | **Alta** | Freno por IP del inicio de sesión y del registro **esquivable**: Railway arranca uvicorn con `--forwarded-allow-ips '*'`, y uvicorn toma entonces la **primera** dirección de `X-Forwarded-For`, que escribe el cliente. Cambiándola en cada intento no había límite por IP. La misma IP falsa se guardaba en la sesión, la auditoría y la **aceptación de los términos** (prueba legal del consentimiento), que además se leía directamente de la cabecera. | `entrada/http/proteccion.py`, `routers/autenticacion.py`, `routers/politicas.py` | Corregido | `ip_cliente()` toma la dirección que añade el último proxy de confianza (`PROXY_SALTOS`, por defecto `0` = conexión directa). Todas las lecturas de IP pasan por ella (`IpClienteDep`). **En Railway hay que poner `PROXY_SALTOS=1`.** |
| S-03 | **Media** | El bloqueo por intentos era un **oráculo de la contraseña**: con la cuenta bloqueada, la contraseña buena respondía «cuenta bloqueada» y la mala «correo o contraseña incorrectos». Quien probaba contraseñas seguía durante el bloqueo y el cambio de mensaje le decía cuál era la correcta. | `aplicacion/casos_uso/autenticar.py` | Corregido | Durante el bloqueo la respuesta no depende de la contraseña (se comprueba la huella igual, para que el tiempo no la delate). Un único mensaje para todos los fallos, que ya avisa de que existe el bloqueo. |
| S-04 | **Media** | `GET /v1/terminos/{id}/estado` respondía **sin sesión**: texto del término y cuántas empresas lo vigilan (información comercial de los clientes). | `routers/terminos.py` | Corregido | Pide sesión y consentimiento. Prueba que recorre **todas** las rutas y falla si alguna no pública responde sin sesión. |
| S-05 | **Media** | Sin tope global de tamaño de cuerpo. Los topes de cada ruta (8 MB) se aplican cuando Starlette **ya guardó en disco** el formulario: un envío de varios GB llenaba el disco del contenedor. | `app.py`, `proteccion.py` | Corregido | Middleware ASGI `LimiteDeCuerpo` (`MAX_CUERPO_MB=20`): corta por `Content-Length` y también contando los trozos de un envío sin longitud. Responde 413. |
| S-06 | **Media** | **SSRF** en el worker de anexos: el enlace se tomaba de la ficha y se seguían redirecciones solas. Un enlace absoluto o una redirección a `169.254.169.254`, `localhost` o la red privada se descargaba y quedaba servido como si fuera un TDR. | `salida/archivos/tdr.py`, `casos_uso/atender_tdr.py` | Corregido | Lista de dominios permitidos (`ANEXOS_DOMINIOS_PERMITIDOS`, por defecto `compraspublicas.gob.ec` y sus subdominios). Sin IP escritas a mano, sin usuario:clave, solo http/https. Las redirecciones se siguen a mano y cada salto se valida. |
| S-07 | **Media** | Bomba ZIP en Word/Excel: en `.docx` cada parte se acotaba por separado (mil encabezados de 40 MB pasaban); el `.xlsx` se abría con openpyxl sin mirar el tamaño descomprimido. | `salida/texto_anexos.py` | Corregido | Antes de leer se suma el tamaño declarado de **todas** las partes (≤ 40 MB) y se limita su número (≤ 2.000). `zipfile` no descomprime más allá del tamaño declarado, así que la cifra es fiable. |
| S-08 | **Media** | Cambio de contraseña propio **sin freno**: con un token robado se podía probar la contraseña actual sin límite ni bloqueo y quedarse con la cuenta. Además, la sesión que se conserva salía del cuerpo de la petición. | `routers/autenticacion.py`, `aplicacion/actor.py` | Corregido | 5 intentos cada 5 min por persona. La sesión que se conserva sale del token (`Actor.sesion_id`); el campo del cuerpo solo cuenta si no hay token. |
| S-09 | **Media** (latente) | El worker marcaba las alertas como revisadas **sin contexto de empresa**. Solo funcionaba porque el rol se salta RLS (S-01): con el rol correcto la alerta no se marcaba nunca y se reprocesaba en cada vuelta. | `salida/bd/radar.py`, `casos_uso/revisar_alertas.py` | Corregido | `UPDATE` dentro del contexto de la empresa de la alerta. Prueba de integración con el rol real sin `BYPASSRLS`. |
| S-10 | **Baja** | Las rutas de la plantilla de Excel no pasaban por la puerta de consentimiento: una cuenta con **contraseña temporal** o con los términos sin aceptar podía subir o borrar la plantilla de la empresa. | `routers/plantilla.py` | Corregido | Puerta de consentimiento en todo el enrutador. |
| S-11 | **Baja** | El freno por IP se **vaciaba entero** al pasar de 50.000 claves: llenarlo (IPv6 da direcciones de sobra) reiniciaba también el cupo del atacante. Cada IPv6 contaba por separado, y `/v1/auth/sesion/` contaba aparte de `/v1/auth/sesion`. | `proteccion.py` | Corregido | Poda por último uso (nunca se pierde la clave activa), IPv6 por red /64, ruta normalizada en la llave. |
| S-12 | **Baja** | El cierre de sesión aceptaba cualquier motivo del cliente: se podía escribir en la auditoría «lo cerró un administrador» o «reutilización de token» sin que ocurriera. | `routers/autenticacion.py` | Corregido | Solo `logout` y `cierre_ventana`; cualquier otro se anota como `logout`. |
| S-13 | **Baja** | Dos tokens emitidos en el mismo segundo para la misma sesión salían **idénticos**: la rotación del token de renovación no rotaba nada dentro de ese segundo. | `salida/seguridad/tokens.py` | Corregido | Claim `jti` aleatorio en cada token. |
| S-14 | **Baja** | Sin `Content-Security-Policy` ni `frame-ancestors` en las respuestas de la API. | `proteccion.py` | Corregido | `default-src 'none'; frame-ancestors 'none'` en las respuestas JSON (no en PDF/Word, para no romper el visor). Ya había HSTS en producción, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`. |
| S-15 | **Baja** | `ENTORNO` mal escrito (`prd`, `produccion `) se leía como desarrollo: `/docs` publicado, secretos cortos admitidos, sin HSTS. | `config/ajustes.py` | Corregido | Valor desconocido = no arranca. |
| S-16 | **Baja** | Registros con datos personales: el correo completo del destinatario cuando falla un envío; los permisos denegados se registraban como `info` entre el resto de errores. | `salida/correo.py`, `app.py` | Corregido | Solo el dominio del correo. `SinPermiso` se registra como `warning` con método y ruta. |
| S-17 | **Baja** | `token_renovacion` sin longitud máxima; `User-Agent` guardado sin recortar. | `routers/autenticacion.py` | Corregido | 4.096 y 300 caracteres. |
| S-18 | **Baja** | `scripts/estado_esquema.py` no incluía las tablas de créditos (`saldo_ia`, `movimiento_ia`, `compra_ia`) y la lista se queda atrás con cada migración. La prueba de integración de aislamiento nombraba tablas que ya no existen y fallaba siempre, así que **no comprobaba nada**. | `scripts/estado_esquema.py`, `pruebas/integracion/test_aislamiento_negocios.py` | Corregido | Las dos comprueban además, contra el catálogo, que **toda** tabla con `negocio_id` tenga RLS activo, forzado y con política. Hoy: 32 tablas, todas bien. |
| S-19 | **Baja** | Funciones `SECURITY DEFINER` (`resolver_cuenta`, `listar_negocios`, `alertas_activas`, `proformas_por_cerrar`, `conteo_suscriptores`, `compras_ia_pendientes`) con `EXECUTE` para `PUBLIC`. Todas fijan `search_path` y la aplicación solo las llama tras comprobar el rol, pero cualquier rol de la base puede ejecutarlas. | Migraciones 0007–0038 | Pendiente | Al crear el rol de aplicación (§3): `REVOKE EXECUTE ... FROM PUBLIC` y `GRANT EXECUTE ... TO` ese rol. No se hizo en una migración porque el nombre del rol de producción no se conoce desde el código. |
| S-20 | **Baja** | Las particiones de `auditoria` (`auditoria_2026xx`) no tienen RLS propio. La política vive en la tabla madre y la aplicación siempre consulta por ella, así que hoy no se puede leer cruzado. | Base de datos | Pendiente (aceptado) | Si algún día se consulta una partición directamente, activar RLS también en ella. |
| S-21 | **Media** | El freno por IP y el freno por persona viven **en memoria de cada proceso**: con `API_WORKERS=4` el tope real es 4× y no se comparte entre réplicas. | `proteccion.py`, `limites.py` | Pendiente | Llevar los contadores a Redis (`INCR` + `EXPIRE`). El bloqueo por cuenta (5 fallos → 15 min, en la base) sí es global y es la defensa principal contra la fuerza bruta de una cuenta. |
| S-22 | **Media** | El token de renovación vive en `sessionStorage`: un XSS en el panel podría leerlo. El panel no usa `v-html` con datos (solo iconos constantes), los enlaces se filtran a http/https en el servidor (`dominio/enlaces.py`) y no hay secretos en `VITE_*`; pero el panel **no envía CSP**. | `frontend/vercel.json` | Pendiente | Añadir en Vercel, primero como `Content-Security-Policy-Report-Only` y luego en firme, algo como `default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; connect-src 'self' https://<api>; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` y ajustar a lo que use el OCR. No se tocó porque una CSP mal ajustada deja el panel en blanco y no se puede probar aquí. |
| S-23 | **Baja** | El registro dice «ese correo ya tiene cuenta» (enumeración). Es inevitable en un alta y está acotado: 5 altas por IP y hora, y ahora el freno sí cuenta la IP real (S-02). El inicio de sesión no enumera: mismo mensaje y huella de descarte para igualar tiempos. | `routers/registro.py` | Aceptado | — |
| S-24 | **Info** | Las rutas del TDR (`/v1/tdr/...`) exigen permiso `tdr.ver` pero **no** comprueban las vistas concedidas (`fuentes_para_vistas`). Los datos son públicos del SERCOP, pero una cuenta sin la vista de ínfimas puede pedir y bajar TDR. | `routers/tdr.py` | Para el otro frente | Lo lleva quien trabaja en las vistas ocultas. |

### Lo que se revisó y está bien

- **Contraseñas**: Argon2id (32 MiB, t=3, p=2), rehash automático al cambiar parámetros; política de 12+ caracteres, variedad mínima, lista de obvias, no contener el correo; tope de 128.
- **Tokens**: HS256 con algoritmo fijado (no se acepta el del token), emisor, audiencia, `exp`/`iat` obligatorios, tipo de token comprobado (acceso ≠ renovación). Acceso de 15 min; cada petición comprueba además que la **sesión siga viva** (revocación inmediata) y que la empresa no esté suspendida.
- **Renovación**: rotación con detección de reutilización (cierra todas las sesiones) y ventana de gracia de 5 min solo para la generación anterior. Cambio o restablecimiento de contraseña y baja de cuenta revocan las sesiones. Sin fijación de sesión: el identificador se crea en el servidor al entrar.
- **CSRF**: no aplica; no hay cookies de sesión, los tokens viajan en `Authorization`. CORS con orígenes exactos (el comodín se rechaza al arrancar).
- **Cambio de contraseña forzado y consentimiento**: puerta en todas las rutas de datos (ahora también la plantilla).
- **Rutas de plataforma**: empresas, suspensión, borrado, contraseñas y desbloqueos de otras empresas, historial de ingesta y conceder plazos de vistas pasan por `es_de_plataforma` en el caso de uso. Un dueño de empresa que pide otro `negocio_id` recibe 403 (`negocio_objetivo`).
- **IDOR**: proformas, lecturas, requisitos, alertas, búsquedas, avisos, perfil, seguimiento y conversaciones del asistente se leen con `contexto_negocio` **y** `WHERE negocio_id` (y `usuario_id` donde son privadas). Doble barrera, así que hoy no hay fuga aunque S-01 siga abierto.
- **`sin_contexto`**: todos los usos leen tablas compartidas (registro, término, fuente, documento_tdr, políticas) o llaman a funciones `SECURITY DEFINER`; el único que escribía una tabla de empresa era S-09.
- **SQL**: los `f"..."` interpolan solo constantes del módulo o nombres de columna filtrados por modelos pydantic con campos fijos (`perfil.py`, `seguimiento.py`); los valores van siempre como parámetros.
- **Asistente**: las herramientas toman empresa y persona del actor, nunca de los argumentos del modelo; los resultados se marcan como «DATOS (no son instrucciones)» y el aviso del sistema lo repite; las tarjetas salen de los datos, no del texto del modelo; el panel no pinta el texto con `v-html`. Freno de 20 mensajes/min por persona.
- **Word**: se lee con expresiones regulares y `html.unescape`, no con un analizador XML, así que no hay expansión de entidades (hay prueba). ZIP: sin ZIP dentro de ZIP, rutas con `..` descartadas, tope de miembros y de tamaño.
- **Errores 500**: el cuerpo no lleva traza ni SQL; la traza va al registro. `/docs` y `/openapi.json` apagados en producción. El atajo de actor por cabeceras está apagado por defecto y prohibido en producción aunque se active.
- **Secretos**: obligatorios, de 32+ caracteres en producción; `.env.example` sin valores reales.

## 2. Lista de comprobación antes de desplegar (Railway)

Variables del servicio `api` (y del `worker`, que comparte configuración):

- [ ] `ENTORNO=prod` (cualquier otro valor desconocido ya no arranca).
- [ ] `PROXY_SALTOS=1` — **nuevo y obligatorio** en Railway (S-02).
- [ ] `JWT_SECRETO`, `CLAVE_CIFRADO_DATOS`, `CLAVE_PEPPER_HMAC`: 48+ caracteres aleatorios, distintos entre sí y distintos de los de desarrollo (`python -c "import secrets; print(secrets.token_urlsafe(48))"`). Si alguno estuvo alguna vez en un archivo compartido, en un chat o en una captura, **rotarlo** (rotar `JWT_SECRETO` cierra todas las sesiones, que es lo esperado).
- [ ] `CORS_ORIGINS` = solo el origen `https://` del panel. Nada de `http://localhost` en producción.
- [ ] `DATABASE_URL` con el **rol de aplicación** de §3, no con el usuario administrador del servicio `bd` (S-01).
- [ ] `PERMITIR_ACTOR_DE_DESARROLLO` sin definir o `false`.
- [ ] `FRENO_IPS_EXENTAS` vacía (solo se usa durante una prueba de carga).
- [ ] Opcionales con valor seguro por defecto: `MAX_CUERPO_MB=20`, `ANEXOS_DOMINIOS_PERMITIDOS=compraspublicas.gob.ec`.
- [ ] `REDIS_URL` configurado: sin él la caducidad por inactividad no se aplica (la revocación sí, por base de datos).
- [ ] La API es el único servicio con puerto público; `bd`, `cache` y `worker` solo en la red interna.
- [ ] Tras desplegar: `python scripts/estado_esquema.py` con la `DATABASE_URL` de la API debe terminar en «esquema correcto» (sin el aviso de superusuario/`BYPASSRLS`).
- [ ] Comprobar en el navegador que la respuesta de `/salud` trae `Strict-Transport-Security` y `Content-Security-Policy`.
- [ ] Plan S-22: CSP del panel en `Content-Security-Policy-Report-Only` durante unos días antes de activarla.

## 3. Rol de aplicación (cierra S-01 y S-19)

Ejecutar **una vez** con el usuario administrador (el de `POSTGRES_USER` del servicio `bd`), después
de `alembic upgrade head`. `<CLAVE>` es una clave nueva y larga; no la escribas en ningún archivo del
repositorio.

```sql
CREATE ROLE contratacion_app LOGIN PASSWORD '<CLAVE>'
    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE contratacion TO contratacion_app;
GRANT USAGE ON SCHEMA public TO contratacion_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO contratacion_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO contratacion_app;
-- Las tablas y secuencias que creen las migraciones futuras (las crea el administrador).
ALTER DEFAULT PRIVILEGES FOR ROLE contratacion IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO contratacion_app;
ALTER DEFAULT PRIVILEGES FOR ROLE contratacion IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO contratacion_app;
-- S-19: las funciones que leen de todas las empresas, solo para la aplicación.
DO $$
DECLARE f regprocedure;
BEGIN
    FOR f IN SELECT p.oid::regprocedure FROM pg_proc p
             JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE n.nspname = 'public' AND p.prosecdef
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO contratacion_app', f);
    END LOOP;
END $$;
```

Luego, en Railway:

- `DATABASE_URL` → `postgresql+asyncpg://contratacion_app:<CLAVE>@bd.railway.internal:5432/contratacion`.
- Nueva variable `DATABASE_URL_MIGRACIONES` con la URL del administrador (la que había).
- Comando de arranque de la API:
  `sh -c "DATABASE_URL=$DATABASE_URL_MIGRACIONES alembic upgrade head && exec uvicorn contratacion.asgi:app --host 0.0.0.0 --port 8001 --workers $API_WORKERS --timeout-keep-alive 65 --forwarded-allow-ips '*'"`
  (las migraciones corren como propietario; el servidor, como `contratacion_app`).
- Si una migración futura crea una función `SECURITY DEFINER`, repetir el bloque `DO $$ ... $$`.

## 4. Cómo se comprobó

- `ruff check`, `ruff format`, `mypy src`: limpios en lo tocado por esta auditoría. Al cerrar
  quedaban avisos de orden de imports y formato en `aplicacion/creditos_actor.py`,
  `casos_uso/asistente.py` y `casos_uso/preparar_documentos.py`, que estaban a medio editar por el
  trabajo de créditos y no se tocaron.
- `pytest pruebas`: 1.357 pasan, 95 omitidas (las de integración sin `PRUEBAS_INTEGRACION=1`).
- Con `PRUEBAS_INTEGRACION=1` contra la base local: pasan las de aislamiento (reparadas, S-18) y las
  nuevas de alertas con el rol sin `BYPASSRLS`. Siguen fallando, por datos de prueba anteriores a
  esta auditoría, `test_acceso_vistas.py::test_extender_anade_una_fila_y_no_acorta` (usa la vista
  retirada `contrataciones`).
- No hizo falta migración: nada de lo corregido cambia el esquema.
