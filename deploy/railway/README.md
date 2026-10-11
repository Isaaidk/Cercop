# Desplegar en Railway: todo en contenedores, sin Supabase

> **¿Primera vez con Railway?** Empieza por [`PASO-A-PASO.md`](PASO-A-PASO.md): el mismo despliegue
> explicado clic a clic, con lo que tienes que ver en pantalla tras cada paso y una lista de
> problemas frecuentes. Este documento es la referencia técnica: qué variables hay, por qué cada
> comando y qué cuesta.

Esta es la variante de la guía de despliegue (`docs/29-despliegue-paso-a-paso.md`) para **Railway**.
Cambia una cosa de fondo: aquí no hay `docker-compose` ni Caddy. Cada pieza es un **servicio** y el
TLS, el dominio y la red privada los pone la plataforma.

Lo que **no** cambia: los procesos son los mismos, el `Dockerfile` del backend es el mismo y la
aritmética de conexiones es la misma. Si algo de aquí no cuadra, la referencia sigue siendo `docs/29`.

## Por qué esto resuelve el problema de Supabase

No es «estar en un contenedor». Es que **el PostgreSQL pasa a ser tuyo**:

| | Supabase (agrupador) | PostgreSQL en Railway |
|---|---|---|
| Conexiones | **15** clientes en modo sesión | `max_connections=200`, y lo fijas tú |
| Latencia desde el API | ~280 ms (otra red) | **~1 ms** (misma red privada) |
| Tamaño | límite del plan gratuito | el disco que pagues |
| Quién corta | el proveedor | nadie |

Las 15 ranuras del agrupador son las que tumbaron el panel el 2026-10-06: con tres workers
acumulados, el API se quedó **sin ninguna conexión** y respondió 500 a todo durante media hora
(`EMAXCONNSESSION`). Eso desaparece.

## Los cinco servicios

| Servicio | Origen | Puerto | Volumen | Comando |
|---|---|---|---|---|
| `bd` | Imagen `postgres:17-alpine` | privado `5432` | `/var/lib/postgresql/data` | `postgres -c max_connections=200 -c shared_buffers=256MB …` |
| `cache` | Imagen `redis:7-alpine` | privado `6379` | `/data` | `redis-server --appendonly yes --maxmemory 128mb --maxmemory-policy allkeys-lru` |
| `api` | Repo, `backend/Dockerfile` | **público** `8001` | `/app/plantillas` | `sh -c "alembic upgrade head && exec uvicorn …"` |
| `worker` | Repo, **el mismo** `backend/Dockerfile` | ninguno | — | `python -m contratacion.tareas.worker` |
| `panel` | Repo, `frontend/Dockerfile` | público `80` | — | el del Dockerfile |

Dos servicios salen del mismo `Dockerfile` a propósito: separarlos solo garantizaría que un día
llevaran versiones distintas del mismo paquete (`docs/29`).

**Nombra los servicios exactamente así** (`bd`, `cache`, `api`, `worker`, `panel`): la red privada de
Railway se resuelve por nombre, `<servicio>.railway.internal`, y las variables de abajo lo usan.

---

## Desde cero: de la cuenta al panel funcionando

Esta es la secuencia de pantallas, en orden. Lo que no esté aquí (variables, comandos, volcados)
está detallado en los apartados siguientes, y la versión **clic a clic** —con lo que hay que ver en
pantalla y los problemas frecuentes— es [`PASO-A-PASO.md`](PASO-A-PASO.md).

### 0 · Cuenta y plan

1. Entra en **`railway.app`** y pulsa **Login** → *Login with GitHub*. Con la cuenta de GitHub donde
   vive el repositorio: así el permiso sobre el código se concede una sola vez.
2. Los **volúmenes** (y sin volumen la base y Redis pierden los datos en cada despliegue) no están
   disponibles en el plan de prueba: hace falta el plan **Hobby** (~5 $/mes, que se consumen del
   propio gasto del proyecto). Si intentas crear un volumen y no te deja, es esto.

### 1 · Proyecto

**New Project → Empty Project.** Nómbralo `contratacion`.

*Vacío y no «deploy from GitHub repo»*: ese camino crea un servicio con el repositorio entero y lo
intenta construir con la detección automática, que aquí no sabe qué hacer —hay dos `Dockerfile` y
cinco procesos—. Un fallo de construcción en el primer minuto no enseña nada.

### 2 · Servicio `bd`

1. **+ Create → Docker Image** y escribe `postgres:17-alpine`.
2. Pulsa el nombre del servicio y renómbralo a **`bd`** (los nombres son el DNS privado).
3. Pestaña **Variables → Raw Editor** y pega:

   ```
   POSTGRES_DB=contratacion
   POSTGRES_USER=contratacion
   POSTGRES_PASSWORD=<clave larga, sin @ : / >
   ```

4. Menú del servicio → **Volumes → Add Volume**, *mount path* **`/var/lib/postgresql/data`**.
5. **Settings → Deploy → Custom Start Command** y pega el `postgres -c …` del apartado [Paso 1](#paso-1--bd).
6. **Deploy**. Espera a que quede en verde y mira los registros: tiene que decir
   `database system is ready to accept connections`.

### 3 · Servicio `cache`

Igual, con la imagen `redis:7-alpine`, renombrado a **`cache`**, volumen en **`/data`** y el comando
de arranque del [Paso 2](#paso-2--cache). Sin la variable `POSTGRES_*`, aquí no hay variables.

### 4 · Servicio `api`

1. **+ Create → GitHub Repo** y elige este repositorio. Railway pedirá instalar su **GitHub App**: dale
   acceso **a este repositorio** (o a todos) y vuelve.
2. Renómbralo a **`api`**.
3. **Settings → Build → Root Directory**: `/backend`.
4. **Settings → Deploy → Custom Start Command**: el `sh -c "alembic upgrade head && exec uvicorn …"`
   del [Paso 3](#paso-3--api).
5. **Settings → Deploy → Healthcheck Path**: `/salud`.
6. **Volumes → Add Volume**, *mount path* **`/app/plantillas`**.
7. **Variables → Raw Editor** y pega el bloque de `api` (apartado [Las variables](#las-variables-servicio-por-servicio)).
   `CORS_ORIGINS` déjalo de momento con el dominio que *crees* que tendrá el panel; lo corriges en el
   paso 7 con el real.
8. **Settings → Networking → Generate Domain.** Si pregunta el puerto, **8001**.
9. **Deploy** y mira los registros del *build*: la primera construcción de esta imagen es la primera
   vez que se construye en algún sitio, así que es donde puede aparecer un fallo de verdad.

### 5 · Servicio `worker`

**+ Create → GitHub Repo** (el mismo), renómbralo a **`worker`**, Root Directory `/backend`, comando
`python -m contratacion.tareas.worker` y **las mismas variables que el `api` menos `CORS_ORIGINS`**
(pega el bloque y borra esa línea). **Sin** dominio y **sin** volumen.

Los registros tienen que mostrar, a los pocos segundos:
`Worker iniciado. Ciclo completo: 15 min. Vigilancia del listado: 150 s.`

### 6 · Servicio `panel`

**+ Create → GitHub Repo**, renómbralo a **`panel`**, Root Directory **`/frontend`**, variable
`VITE_API_BASE=https://<el-dominio-del-api>`, y **Generate Domain** con puerto **80**.

### 7 · Cerrar el círculo: CORS

Vuelve al servicio **`api`** y corrige `CORS_ORIGINS` con el dominio **real** del panel. Al guardar la
variable, Railway vuelve a desplegar solo. Sin esto el panel carga y se queda sin datos: es el fallo
número uno de un despliegue nuevo.

### 8 · Comprobar

```bash
curl -s https://<api>.up.railway.app/salud
curl -s https://<api>.up.railway.app/listo
```

Y en el navegador, el panel: entrar, ver datos y descargar un Excel (eso ejercita CORS, las cabeceras
y el flujo de presencia de una vez).

### 9 · Traer los datos

Ver [Paso 6](#paso-6--traer-los-datos-de-supabase): **TCP Proxy** en `bd` y `pg_dump`/`pg_restore`, o
reimportar el año de ofertas y migrar solo las tablas de negocio.

### 10 · Copias de seguridad: aquí sí hay que decidir

`deploy/copias.sh` está atado al `compose` (`docker compose exec bd pg_dump`), así que **en Railway no
funciona tal cual**. Dos caminos:

- **Usar el PostgreSQL gestionado de Railway** en lugar del contenedor: trae copias y
  restauraciones del proveedor, y se acabó el problema. Cuesta más al mes que el contenedor y deja de
  ser «todo en Docker», pero es la opción con menos trabajo.
- **Mantener el contenedor** y sacar el volcado por el **proxy TCP** desde tu máquina, con el cliente
  de PostgreSQL instalado (`pg_dump`, `age` y `rclone` como en el `compose`).

lo que **no** vale es dejarlo sin copias: las empresas, las cuentas, los consentimientos y las
palabras clave de los clientes solo están ahí, y no se pueden volver a pedir a SERCOP.

---

## Detalle de cada servicio

## Paso 1 · `bd`

- **New → Docker Image → `postgres:17-alpine`.**
- **Volume** montado en `/var/lib/postgresql/data`. Sin él, cada despliegue empieza con la base vacía.
- **Variables:** `POSTGRES_DB=contratacion`, `POSTGRES_USER=contratacion`,
  `POSTGRES_PASSWORD=<clave larga>` y **`PGDATA=/var/lib/postgresql/data/pgdata`**.
  Esta última no es un adorno: el volumen de Railway es un sistema de ficheros montado y trae un
  `lost+found`, y PostgreSQL se niega a inicializar la base en un directorio que no esté vacío
  («directory "/var/lib/postgresql/data" exists but is not empty»). Con la base en un subdirectorio,
  el `lost+found` deja de importar. Es la solución que documenta la propia imagen.
  ⚠️ Si la clave lleva `@`, `:` o `/`, hay que **codificarla** al construir la URL (`%40`, `%3A`,
  `%2F`); es la trampa que ya está documentada en `.env.example`.
- **Start command** (los ajustes son los del `compose`, con la memoria recortada al tamaño de un
  contenedor de Railway). El `docker-entrypoint.sh` del principio es **imprescindible**: al poner un
  comando propio se sustituye el arranque de la imagen, y es ese script el que cambia de usuario —
  PostgreSQL se niega a correr como `root`, que es como arrancan los contenedores en esta
  plataforma—:

```
docker-entrypoint.sh postgres -c max_connections=200 -c shared_buffers=256MB -c effective_cache_size=1GB -c work_mem=8MB -c maintenance_work_mem=128MB -c random_page_cost=1.1 -c checkpoint_timeout=15min -c max_wal_size=1GB -c log_min_duration_statement=1000
```

`work_mem` a 8 MB y no a 16: en Railway pagas la memoria del contenedor, y `work_mem` **se multiplica
por conexión**. Si algún día aparece el asesino por memoria, el primer número que se baja es este.

## Paso 2 · `cache`

- **New → Docker Image → `redis:7-alpine`.**
- **Volume** en `/data`.
- **Custom Start Command:**

```
sh -c "chown -R redis:redis /data 2>/dev/null; exec redis-server --appendonly yes --appendfsync everysec --maxmemory 128mb --maxmemory-policy allkeys-lru --lazyfree-lazy-eviction yes --lazyfree-lazy-expire yes"
```

El `chown` está ahí por un motivo concreto: **en Redis viven las sesiones abiertas**. La ausencia de
la clave significa «sesión cerrada», así que sin AOF cada reinicio del contenedor expulsa a todo el
mundo. Si el volumen llega con otro dueño, el AOF no se puede escribir y el síntoma es un
«MISCONF Redis is configured to save RDB snapshots» o cada sesión perdida tras un despliegue.

**Redis va aquí y no en un plan gratuito de fuera.** El de Redis Cloud tenía un tope de **30
conexiones** (medido) y cobra por comando; en el mismo proyecto no hay tope medido y no se paga por
comando.

## Paso 3 · `api`

- **New → GitHub Repo →** este repositorio. **Root Directory: `/backend`.**
  Si Railway no encuentra el `Dockerfile`, define `RAILWAY_DOCKERFILE_PATH=Dockerfile`.
- **Volume** montado en `/app/plantillas`. Es donde vive la plantilla de Excel que sube cada empresa,
  y **no está en la base**: sin volumen, cada despliegue borra las de los clientes sin ningún error.
- **Public Networking:** genera dominio y pon el **target port en `8001`**.
- **Variables** (las de la tabla de abajo).
- **Custom Start Command** — aquí van también las migraciones:

```
sh -c "alembic upgrade head && exec uvicorn contratacion.asgi:app --host 0.0.0.0 --port 8001 --workers $API_WORKERS --timeout-keep-alive 65 --forwarded-allow-ips '*'"
```

Tres decisiones metidas en esa línea:

- **`alembic upgrade head` antes de arrancar.** Con `&&`, si la migración falla el API **no arranca**,
  que es lo correcto: un API con el esquema viejo es peor que un API caído. Si prefieres separarlo,
  Railway tiene *Pre-Deploy Command*; no lo uses con **más de una réplica**, porque dos migraciones a
  la vez sí pueden pelearse.
- **`--workers $API_WORKERS`** desde variable, no escrito a mano: es el número que entra en la
  aritmética de conexiones y hay que poder ajustarlo sin tocar código.
- **`--forwarded-allow-ips '*'`** para que la aceptación de términos guarde la **IP del cliente** y no
  la del borde de Railway. Es seguro porque el contenedor no es alcanzable más que por el borde y por
  la red privada.
- **No** pongas `--reload` (vigila todo el árbol, reinicia con cada escritura y deja conexiones
  abiertas al apagarse).

**Healthcheck:** `/salud`. **No** `/listo`: ese devuelve **503** cuando una dependencia no responde, y
un healthcheck que falla hace que Railway reinicie el servicio — justo lo contrario de lo que quieres
cuando tarda la base.

## Paso 4 · `worker`

- **New → GitHub Repo →** el mismo repositorio, **Root Directory `/backend`**.
- **Sin** dominio público y **sin** volumen.
- **Custom Start Command:** `python -m contratacion.tareas.worker`.
- **Variables:** las mismas `DATABASE_URL`, `REDIS_URL` y secretos que el API. Lo único que **no**
  lleva es `CORS_ORIGINS` (no atiende navegadores).

**Un solo worker.** El ciclo se protege con un bloqueo de asesoría de PostgreSQL, así que un segundo
proceso no duplicaría el trabajo: solo esperaría ocupando conexiones.

## Paso 5 · `panel`

- **New → GitHub Repo →** el repositorio, **Root Directory `/frontend`.**
- **Public Networking** con el target port en `80`.
- **Variable de compilación** `VITE_API_BASE=https://<tu-api>.up.railway.app`.
  El `Dockerfile` del panel ya la declara como `ARG`, que es lo que Railway necesita para pasarla al
  *build*.

⚠️ **`VITE_API_BASE` se incrusta al compilar, no se lee al arrancar.** Si la cambias, hay que volver a
desplegar el panel. Y **tiene que llamarse así**: con otro nombre Vite incrusta un valor vacío, el
panel llama a su propio origen y cada petición da 404 sin decir por qué.

**La alternativa es Vercel** (Root Directory `frontend` + la misma variable). Funciona igual de bien y
está documentada en `docs/29`. La diferencia es solo de dónde se sirve el HTML.

Después de desplegar, en el servicio **`api`**: `CORS_ORIGINS=https://<tu-panel>.up.railway.app`.
**Exacto, sin `*`** — el comodín se rechaza al arrancar. Si el panel va en Vercel, se añaden los dos
orígenes separados por coma.

---

## Las variables, servicio por servicio

**`api` y `worker`** (las mismas en los dos, salvo `CORS_ORIGINS`):

| Variable | Valor | Por qué |
|---|---|---|
| `ENTORNO` | `prod` | Activa las validaciones de producción |
| `DATABASE_URL` | `postgresql+asyncpg://contratacion:${{bd.POSTGRES_PASSWORD}}@bd.railway.internal:5432/contratacion` | Red privada, misma región |
| `REDIS_URL` | `redis://cache.railway.internal:6379/0` | Sin TLS: es red privada |
| `JWT_SECRETO` · `CLAVE_CIFRADO_DATOS` · `CLAVE_PEPPER_HMAC` | 48+ caracteres aleatorios | El arranque **falla** si miden menos de 32 en producción |
| `CORS_ORIGINS` | `https://<panel>.up.railway.app` | Solo el API. Orígenes exactos |
| `BD_POOL_SIZE` / `BD_MAX_OVERFLOW` | `10` / `10` | Los del servidor, **no** los del portátil (4/2) |
| `API_WORKERS` | `2` (sube si subes CPU) | Entra en la aritmética de conexiones |
| `PLANTILLAS_DIR` | `/app/plantillas` | Debe coincidir con el volumen montado |
| `LOG_NIVEL` | `INFO` | `DEBUG` llena el disco |
| `PURGA_PLAZO_DIAS` / `PURGA_MAX_FILAS_POR_VUELTA` | `7` / `500` | Retención de ínfimas vencidas (`0` la desactiva) |
| `NCO_PROXY_URL` | *(vacío)* | **Solo en el `worker`.** Salida de la fuente NCO por un proxy. El servidor de necesidades descarta en silencio las conexiones que llegan de centros de datos (`ConnectTimeout` tras dos minutos, sin llegar a ver la petición), mientras los datos abiertos del mismo portal —OCDS— responden con normalidad: por eso solo NCO lo usa. Tiene que salir por una IP **ecuatoriana o residencial**; un proxy en otro centro de datos estará bloqueado igual |

Generar un secreto: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

**La aritmética que hay que respetar al subir `API_WORKERS`:**

```
(API_WORKERS + 1) × (BD_POOL_SIZE + BD_MAX_OVERFLOW) ≤ max_connections
(2 + 1) × (10 + 10) = 60 ≤ 200      ← el worker también abre su pool
```

---

## Paso 6 · Traer los datos de Supabase

El procedimiento es el de `deploy/MIGRACION.md`; aquí cambia **cómo se llega a la base**:

1. En el servicio `bd`, activa **TCP Proxy** y copia el `host:puerto` que te da.
2. Con eso a mano, desde tu máquina:
   - `pg_dump` de Supabase (la cadena del agrupador, la del `.env`),
   - `pg_restore` contra el proxy de Railway.
3. Compara recuentos tabla por tabla — el script de `MIGRACION.md` los imprime.
4. Deja el proyecto de Supabase **intacto** una temporada, como red de seguridad.

Si la copia es grande, mídelo antes con `scripts/estado_datos.py`. La `registro` del año son cientos de
megas y el proxy de Railway no es rápido: para un volumen así, es más rápido **reimportar el año** con
`scripts/importar_ocds_masivo.py` (medido: 23 min 58 s y 10 peticiones al portal) y migrar solo las
tablas de negocio —empresas, cuentas, consentimientos, palabras clave—, que son miles de filas.

## Paso 7 · Comprobaciones

```bash
curl -s https://<api>.up.railway.app/salud     # {"servicio":"contratacion-api","estado":"ok"}
curl -s https://<api>.up.railway.app/listo     # {"listo":true,…} con postgres y cache en ok
```

En los registros del `worker`, a los pocos segundos: `Worker iniciado. Ciclo completo: 15 min.` y
`OCDS: sin términos por rescatar; se lee el rabo del listado general`.

**`backend/scripts/verificar_despliegue.py` aquí no sirve**: lee `deploy/docker-compose.yml`, que en
Railway no existe. Las tres comprobaciones equivalentes, a mano:

1. Conexiones: en la consola de `bd`, `select count(*) from pg_stat_activity;` con el panel abierto —
   tiene que quedarse muy por debajo de `max_connections`.
2. Memoria: el panel de métricas de Railway, servicio por servicio.
3. Descriptores: no aplica; el sistema operativo del contenedor no es tu problema.

Y el panel, en el navegador: entrar, ver datos y comprobar que las descargas en Excel llegan con
nombre de archivo (eso ejercita CORS y las cabeceras expuestas).

---

## Lo que hay que saber antes de decidir

**Railway cobra por uso, no por máquina.** Un despliegue siempre encendido —PostgreSQL, Redis, API y
worker— ronda los **20-40 dólares al mes** según el plan y los recursos, muy por encima de los 4-6 €
de un VPS equivalente. A cambio no administras nada y **no necesitas Docker en tu máquina**: Railway
construye las imágenes en la nube (en este portátil no hay Docker instalado, así que este es el camino
que puedes recorrer hoy).

Para bajarlo sin romper nada: `shared_buffers` y `maxmemory` como arriba, `API_WORKERS=2` y **límites
de recursos por servicio** en el panel de Railway. Lo que **no** se debe recortar es la memoria de
PostgreSQL por debajo de lo que necesita el `work_mem` de sus conexiones.

**Lo que sigue pendiente y hay que probar en el primer despliegue** (es lo mismo que dice `docs/29`):

- Las imágenes **nunca se han construido en la máquina de desarrollo** (no hay Docker): el primer
  *build* de Railway es su primera vez de verdad.
- Si la subida de una plantilla de Excel falla con un error de permisos, es el volumen: el
  `Dockerfile` crea `/app/plantillas` con el dueño correcto, pero un volumen montado puede llegar con
  otro. Se arregla una vez desde la shell del servicio (`railway ssh`).
- `BD_RANDOM_PAGE_COST=1.1` cambia los planes de consulta: compruébalos con
  `scripts/medir_consultas.py` (esa sí se puede correr desde aquí, apuntando al proxy de `bd`).
- Un servidor (o un proyecto de Railway) **es un punto único de fallo**. Antes de replicar el API,
  **Redis tiene que ser compartido**: con el bus de presencia en memoria de cada proceso, dos réplicas
  mostrarían estados distintos y el panel mentiría sobre quién está conectado.
