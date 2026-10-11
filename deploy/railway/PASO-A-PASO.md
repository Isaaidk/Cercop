# Railway, explicado desde el principio

Este documento está escrito para alguien que **nunca ha usado Railway** y quiere llegar al final sin
adivinar nada. Cada paso dice: dónde pulsar, qué escribir y **qué tienes que ver** cuando ha salido
bien. Si algo no aparece en tu pantalla, al final hay una lista de problemas frecuentes con su causa.

Si solo quieres la referencia técnica de cada valor (para qué sirve cada variable, por qué ese
comando), está en [`README.md`](README.md). Aquí está el camino.

---

## Antes de empezar: qué es cada cosa

Railway es una web que ejecuta **contenedores** por ti. No instalas nada en tu ordenador: subes el
código a GitHub y Railway construye y ejecuta. Nuestro sistema son cinco piezas, y cada una es un
**servicio** (una especie de ordenador pequeño, con su memoria y su disco):

| Nombre del servicio | Qué es | Se comunica con |
|---|---|---|
| `bd` | La base de datos PostgreSQL | `api` y `worker` |
| `cache` | Redis: caché, sesiones abiertas y presencia | `api` y `worker` |
| `api` | El servidor que atiende al panel | `bd`, `cache` |
| `worker` | El que descarga datos de SERCOP cada 15 min | `bd`, `cache` |
| `panel` | La página web que abres en el navegador | `api` |

Los cinco viven **dentro del mismo proyecto**, y dentro de un proyecto se ven entre ellos por su
nombre: `bd.railway.internal` es como el número de puerta de la base dentro del edificio. Por eso los
nombres importan y por eso **no** hay que inventarse otros.

Palabras que vas a ver y conviene reconocer:

- **Proyecto**: el edificio. Dentro están los servicios.
- **Servicio**: una pieza del sistema. Tiene pestañas: *Variables*, *Settings*, *Deployments*, *Logs*, *Metrics*.
- **Deploy**: construir y arrancar. Al guardar una variable, Railway **vuelve a desplegar solo**.
- **Volumen**: el disco que sobrevive a los despliegues. Sin él, cada despliegue deja la base vacía.
- **Raw Editor**: el botón que convierte la lista de variables en un cuadro de texto donde se pega todo de golpe.

### Ten a mano

1. La cuenta de **GitHub** donde está este repositorio (es con la que entrarás a Railway).
2. Una **tarjeta** o forma de pago: los volúmenes necesitan el plan **Hobby** (~5 $/mes).
3. Los **tres secretos** generados (paso 3). Se generan en tu ordenador, no se inventan.
4. Unos **20 minutos**.

---

## Paso 1 · Entrar en Railway

1. Abre el navegador en **`railway.app`**.
2. Arriba a la derecha, **Login** → **Login with GitHub**.
3. Te llevará a GitHub para autorizar. Pulsa **Authorize Railway**.
4. Vuelves a Railway con tu nombre arriba a la derecha. **No** crees ningún proyecto de ejemplo.

**Qué tienes que ver:** la pantalla con el botón **New Project** en el centro o arriba a la izquierda.

> Si te ofrece elegir plan, elige **Hobby** (gratis no deja poner volúmenes, y sin volúmenes pierdes
> la base de datos en cada despliegue). El plan da 5 $ de consumo al mes y luego se paga lo que se use.

---

## Paso 2 · Crear el proyecto

1. Pulsa **New Project**.
2. Elige **Empty Project** (el recuadro en blanco; **no** «Deploy from GitHub repo»).
3. Arriba, donde pone *Untitled project*, pulsa y escribe **`contratacion`**.

**Qué tienes que ver:** un lienzo vacío con un botón **+ Create** en el centro (o una tarjeta que dice
«Create a service»).

> **¿Por qué vacío?** Porque el camino «Deploy from GitHub repo» crea un servicio con el repositorio
> entero y lo intenta construir solo. En este repositorio hay **dos** `Dockerfile` y cinco procesos,
> así que no acierta y falla en el primer minuto. Ese fallo no significa que algo esté mal.

---

## Paso 3 · Generar los secretos (en tu ordenador, una vez)

Abre PowerShell en la carpeta del proyecto y ejecuta esto cinco veces. Cada ejecución imprime una
línea de 48 caracteres; **cópialas** (a un bloc de notas, no en el código):

```powershell
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 48 | ForEach-Object {[char]$_})
```

Necesitas:

| Para qué | Cuántas | Longitud |
|---|---|---|
| `JWT_SECRETO`, `CLAVE_CIFRADO_DATOS`, `CLAVE_PEPPER_HMAC` | 3 | 48 |
| La clave de PostgreSQL (`POSTGRES_PASSWORD`) | 1 | 32, y **sin `@` `:` `/`** |
| Nada más | — | — |

> ⚠️ `CLAVE_CIFRADO_DATOS` cifra datos personales en la base. **Si la cambias después, lo ya cifrado
> deja de poder leerse.** Guárdala con las copias de seguridad.

`POSTGRES_PASSWORD` sin símbolos raros es a propósito: la contraseña va dentro de una dirección
(`postgresql://usuario:CLAVE@…`) y los caracteres `@`, `:` y `/` rompen esa dirección de una forma que
parece un error de contraseña y no lo es.

---

## Paso 4 · Servicio `bd` (la base de datos)

### 4.1 · Crear el servicio

1. Pulsa **+ Create**.
2. Elige **Docker Image** (no *GitHub Repo*).
3. Escribe `postgres:17-alpine` y confirma con **Create**.

**Qué tienes que ver:** aparece una tarjeta nueva en el lienzo y empieza a construir. Espera a que
ponga `Deployed` (tarda uno o dos minutos).

### 4.2 · Ponerle nombre

1. Pulsa sobre la tarjeta del servicio para abrirlo.
2. Arriba, pulsa el nombre (algo como `postgres-17-alpine`) y **renómbralo a `bd`**. Enter.

**Qué tienes que ver:** la tarjeta del lienzo ahora se llama `bd`. Este nombre es literalmente la
dirección interna, así que tiene que ser exactamente `bd`.

### 4.3 · Las variables

1. Dentro del servicio, pestaña **Variables**.
2. Pulsa **Raw Editor** (esquina superior derecha del panel: cambia de lista a cuadro de texto).
3. Borra lo que haya y pega esto, cambiando `<CLAVE>` por la clave que generaste en el paso 3:

```
POSTGRES_DB=contratacion
POSTGRES_USER=contratacion
POSTGRES_PASSWORD=<CLAVE>
PGDATA=/var/lib/postgresql/data/pgdata
```

**`PGDATA` apunta a un subdirectorio a propósito, y es el cuarto tropiezo de este despliegue.** El
volumen de Railway es un sistema de ficheros montado, y trae un directorio `lost+found`; PostgreSQL se
niega a inicializar la base en un directorio que **no esté vacío** —«directory "/var/lib/postgresql/data"
exists but is not empty»— y el arranque se queda en bucle. Con `PGDATA` en un subdirectorio, la base se
crea dentro de él y el `lost+found` deja de importar. Es la solución que documenta la propia imagen de
PostgreSQL para volúmenes que no están vacíos.

4. Pulsa **Deploy** o **Update variables**.

**Qué tienes que ver:** el servicio se vuelve a desplegar y termina en `Deployed`.

### 4.4 · El disco (volumen)

1. En la tarjeta del servicio (o en su menú de tres puntos), busca **Volumes** → **Add Volume** /
   **New Volume**.
2. En *Mount path* escribe exactamente: `/var/lib/postgresql/data`
3. Confirma.

**Qué tienes que ver:** el volumen aparece listado con esa ruta.

> Si no te deja crear el volumen, es el plan: hace falta **Hobby**.
> Si te equivocas de ruta, PostgreSQL arranca con la base vacía cada vez.

### 4.5 · Los ajustes de PostgreSQL

1. Ve a **Settings** → sección **Deploy** → **Start command** (lo que yo llamo *Custom Start Command*).
2. Pega esto entero (**en una sola línea**, tal cual, sin saltos de línea):

```
docker-entrypoint.sh postgres -c max_connections=200 -c shared_buffers=256MB -c effective_cache_size=1GB -c work_mem=8MB -c maintenance_work_mem=128MB -c random_page_cost=1.1 -c checkpoint_timeout=15min -c max_wal_size=1GB -c log_min_duration_statement=1000
```

**`docker-entrypoint.sh` delante no es opcional, y es la trampa de este paso.** La imagen de
PostgreSQL trae un script de arranque que prepara el directorio de datos y, sobre todo, **cambia de
usuario**: PostgreSQL se niega a correr como `root` —«`root` execution of the PostgreSQL server is
not permitted»— y las plataformas ejecutan el contenedor como root por defecto. Al escribir un Start
Command propio se sustituye el arranque de la imagen y ese script no corre; llamarlo a mano es lo que
lo devuelve. En el `docker-compose` de `deploy/` esto **no** hace falta: allí `command:` solo cambia
el comando y Docker sigue ejecutando el punto de entrada de la imagen.

3. **Deploy** y abre la pestaña **Logs** (o *Deployments* → el último → *View logs*).

**Qué tienes que ver** en los registros: `database system is ready to accept connections`. Esa línea
significa que la base está viva y con los 200 huecos de conexión que necesita el resto del sistema.

---

## Paso 5 · Servicio `cache` (Redis)

Son los mismos cinco sub-pasos, con tres valores distintos:

1. **+ Create → Docker Image** → `redis:7-alpine`.
2. Renombra el servicio a **`cache`**.
3. **Volumes → Add Volume**, *mount path*: `/data`
4. **Settings → Deploy → Custom Start Command**:

```
sh -c "chown -R redis:redis /data 2>/dev/null; exec redis-server --appendonly yes --appendfsync everysec --maxmemory 128mb --maxmemory-policy allkeys-lru --lazyfree-lazy-eviction yes --lazyfree-lazy-expire yes"
```

5. **Deploy**.

**Qué tienes que ver** en los registros: `Ready to accept connections`.

> **No** hace falta ninguna variable en este servicio.
> El `chown` del principio parece un detalle y no lo es: **en Redis viven las sesiones abiertas**, y
> si no puede escribir su fichero de persistencia, cada despliegue expulsa a todos los usuarios.

---

## Paso 6 · Servicio `api` (el servidor)

Este es el servicio importante. Vamos por partes.

### 6.1 · Crear el servicio desde el repositorio

1. **+ Create → GitHub Repo**.
2. La primera vez Railway pide instalar su aplicación en GitHub: pulsa **Configure GitHub App**,
   elige **Only select repositories** → este repositorio, y **Install**.
3. Vuelve a Railway y elige este repositorio en la lista.
4. Renombra el servicio a **`api`**.

**Qué tienes que ver:** empieza a construir. **Puede fallar aquí y es normal**: todavía no le hemos
dicho dónde está el `Dockerfile` ni cómo arrancar. Seguimos.

### 6.2 · Decirle dónde está el código

1. **Settings → Build → Root Directory**: escribe `/backend` y confirma.

> El repositorio tiene la parte de servidor en `backend/` y la web en `frontend/`. Cada servicio mira
> solo su carpeta; por eso cada uno tiene su propio *Root Directory*.

### 6.3 · Cómo arranca (y las migraciones)

1. **Settings → Deploy → Custom Start Command**.
2. Pega esto entero, en una línea:

```
sh -c "alembic upgrade head && exec uvicorn contratacion.asgi:app --host 0.0.0.0 --port 8001 --workers $API_WORKERS --timeout-keep-alive 65 --forwarded-allow-ips '*'"
```

Qué hace, en castellano: primero pone al día las tablas de la base (`alembic upgrade head`) y **si eso
falla, no arranca** —un servidor con las tablas viejas es peor que un servidor caído—; después levanta
el servidor en el puerto 8001 con el número de procesos que diga la variable `API_WORKERS`.

### 6.4 · El chequeo de salud

1. **Settings → Deploy → Healthcheck Path** (puede estar como *Healthcheck*): escribe `/salud`.

> `/salud` responde siempre que el servidor esté en pie. El otro endpoint, `/listo`, devuelve 503
> cuando la base tarda, y un healthcheck que falla hace que Railway reinicie el servicio justo cuando
> menos falta hace.

### 6.5 · El disco de las plantillas de Excel

1. **Volumes → Add Volume**, *mount path*: `/app/plantillas`

Cada empresa puede subir su plantilla de Excel, y ese archivo **no está en la base**: vive aquí. Sin
volumen, cada despliegue borra las de los clientes sin ningún error ni aviso.

### 6.6 · Las variables (el bloque largo)

1. Pestaña **Variables → Raw Editor**.
2. Pega el bloque de abajo y **sustituye las cuatro partes en mayúsculas y entre `<>`**:

```
ENTORNO=prod
DATABASE_URL=postgresql+asyncpg://contratacion:${{bd.POSTGRES_PASSWORD}}@bd.railway.internal:5432/contratacion
REDIS_URL=redis://cache.railway.internal:6379/0
JWT_SECRETO=<SECRETO-1>
CLAVE_CIFRADO_DATOS=<SECRETO-2>
CLAVE_PEPPER_HMAC=<SECRETO-3>
CORS_ORIGINS=https://pendiente
BD_POOL_SIZE=10
BD_MAX_OVERFLOW=10
API_WORKERS=2
PLANTILLAS_DIR=/app/plantillas
LOG_NIVEL=INFO
PURGA_PLAZO_DIAS=7
PURGA_MAX_FILAS_POR_VUELTA=500
```

Tres cosas que **no** hay que tocar de ese bloque:

- `${{bd.POSTGRES_PASSWORD}}` no es un error de escritura: es una **referencia**. Railway la cambia por
  la clave que pusiste en el servicio `bd`, así que la contraseña se escribe **una sola vez**.
- `bd.railway.internal` y `cache.railway.internal` son las direcciones internas. Como los servicios se
  llaman así, funcionan solas.
- `CORS_ORIGINS=https://pendiente` es provisional a propósito: todavía no existe el panel, y su
  dirección se escribe en el paso 9.

3. Guarda. El servicio se vuelve a desplegar.

**Qué tienes que ver** en los registros: `Application startup complete.` y ninguna línea en rojo. Si
aparece `EMAXCONNSESSION`, `ECHECKOUTTIMEOUT` o `could not connect`, la base no está bien
configurada: revisa los pasos 4.3, 4.4 y 4.5.

### 6.7 · La dirección pública

1. **Settings → Networking** → **Generate Domain**.
2. Si te pregunta el puerto (a veces lo detecta solo), escribe **8001**.
3. Copia la dirección que te da, algo como `contratacion-api.up.railway.app`. **Guárdala**: la
   necesitas en los pasos 8 y 9.

**Qué tienes que ver:** si abres `https://<esa-direccion>/salud` en el navegador, esto:

```json
{"servicio":"contratacion-api","estado":"ok"}
```

Si eso sale, **la mitad del trabajo está hecho**: ya hay servidor, con base de datos propia y sin
Supabase.

---

## Paso 7 · Servicio `worker` (el que trae los datos)

1. **+ Create → GitHub Repo** → el mismo repositorio. Renómbralo a **`worker`**.
2. **Settings → Build → Root Directory**: `/backend`
3. **Settings → Deploy → Custom Start Command**:

```
python -m contratacion.tareas.worker
```

4. **Variables → Raw Editor**: pega **el mismo bloque del paso 6.6** y **borra la línea
   `CORS_ORIGINS`** (el worker no atiende navegadores, no la necesita).
5. **No** le pongas dominio y **no** le pongas volumen.

**Qué tienes que ver** en los registros, a los pocos segundos:

```
Worker iniciado. Ciclo completo: 15 min. Vigilancia del listado: 150 s.
OCDS: sin términos por rescatar; se lee el rabo del listado general
```

Esas dos líneas son la prueba de que el sistema **está trayendo datos**. A partir de aquí, solo, cada
15 minutos.

---

## Paso 8 · Servicio `panel` (la web)

1. **+ Create → GitHub Repo** → el mismo repositorio. Renómbralo a **`panel`**.
2. **Settings → Build → Root Directory**: `/frontend`
3. **Variables → Raw Editor**, una sola línea (sustituye la dirección por la del paso 6.7):

```
VITE_API_BASE=https://contratacion-api.up.railway.app
```

4. **Settings → Networking → Generate Domain**, puerto **80**.
5. Copia esa dirección: es la del panel (`contratacion-panel.up.railway.app` o similar).

**Qué tienes que ver:** al abrir la dirección, la pantalla de acceso del panel.

> ⚠️ Esa variable se **hornea dentro del JavaScript** al construir. Si la cambias, hay que volver a
> desplegar el panel. Y tiene que llamarse exactamente `VITE_API_BASE`.
>
> Si abres el panel y no carga nada, mira en el navegador (F12 → *Network*) si las llamadas van a
> `localhost` en vez de a tu API: eso significa que la variable no llegó al *build*.

---

## Paso 9 · Cerrar el círculo (CORS): el paso que casi todos olvidan

1. Vuelve al servicio **`api`**.
2. **Variables → Raw Editor** y cambia la línea `CORS_ORIGINS` por la dirección **real** del panel,
   sin barra al final:

```
CORS_ORIGINS=https://contratacion-panel.up.railway.app
```

3. Guarda. Railway vuelve a desplegar el `api` solo.

**Por qué:** el navegador no deja que una página (`…panel…`) hable con otro dominio (`…api…`) si el
servidor no lo autoriza expresamente. Sin este paso el panel carga y se queda cargando datos para
siempre. Es el fallo número uno de un despliegue nuevo.

**Qué tienes que ver:** recarga el panel, entra con tu cuenta y aparecen datos. Descarga un Excel de
prueba: si llega con nombre de archivo, CORS está bien puesto **y** las cabeceras también.

---

## Paso 10 · Traer los datos que ya tienes

La base nueva está **vacía**: el esquema (las tablas) sí está, porque lo creó `alembic` al arrancar el
`api`, pero dentro no hay nada. Tienes dos caminos, y se puede mezclar:

**A) Copiar todo lo de Supabase** (lo más completo). Procedimiento en `../MIGRACION.md`, y en Railway
hace falta abrir la puerta:

1. Servicio `bd` → **Settings → Networking → TCP Proxy** → activarlo.
2. Railway te da algo como `roundhouse.proxy.rlwy.net:34567`. Eso es la dirección de tu base desde
   fuera.
3. Desde tu ordenador: `pg_dump` contra Supabase y `pg_restore` contra esa dirección.
4. Compara los recuentos de filas tabla por tabla: el script de `MIGRACION.md` los imprime.

**B) Reimportar solo las ofertas del año.** Medido: 23 minutos y 10 peticiones al portal.

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\importar_ocds_masivo.py --dir tmp\ocds_2026
```

Las **ínfimas cuánticas** no se pueden reimportar: la fuente solo publica las que están **abiertas**,
así que un despliegue nuevo recibe todas las abiertas en su primer ciclo, pero las que se cerraron
esta semana solo llegan por el camino A.

---

## Paso 11 · Copias de seguridad: lo único que hay que decidir

`deploy/copias.sh` está atado al `docker-compose`, así que **en Railway no funciona tal cual**. Dos
salidas:

- **Usar el PostgreSQL de Railway** (el «gestionado», no el contenedor): trae copias del proveedor
  hechas por él. Es lo más cómodo y lo más caro.
- **Mantener el contenedor** y hacer el volcado por el **proxy TCP** del paso 10 desde tu ordenador,
  con `pg_dump`.

Lo que **no** vale es dejarlo sin copias. Las empresas, las cuentas, los consentimientos y las
palabras clave de los clientes solo están ahí, y eso no se puede volver a pedir a SERCOP.

---

## Problemas frecuentes: qué significa cada uno

| Lo que ves | Qué está pasando | Qué hacer |
|---|---|---|
| El `api` no arranca y en los registros dice `could not connect` | No encuentra la base | Revisa que el servicio `bd` se llame **`bd`** y que `DATABASE_URL` tenga `bd.railway.internal` |
| `EMAXCONNSESSION` o `ECHECKOUTTIMEOUT` | Estás apuntando a Supabase, no a Railway | Mira que `DATABASE_URL` no tenga `supabase.co` ni `pooler` |
| El `api` en **Build failed** y habla de `requirements.txt` o `nixpacks` | Está construyendo con la detección automática | *Root Directory* tiene que ser `/backend` y el `Dockerfile` estar ahí |
| El `worker` arranca y se para solo | El comando está mal escrito | Tiene que ser exactamente `python -m contratacion.tareas.worker` |
| El panel carga y no salen datos | CORS | Paso 9: `CORS_ORIGINS` con la dirección real del panel |
| El panel llama a `localhost` | `VITE_API_BASE` no llegó al *build* | Corrige la variable y vuelve a desplegar el panel |
| Tras un despliegue, todo el mundo fuera de la sesión | Redis sin persistencia | El volumen en `/data` y el `--appendonly yes` del paso 5 |
| Tras un despliegue, la base está vacía | Falta el volumen | Paso 4.4, ruta `/var/lib/postgresql/data` |
| «Falta `POSTGRES_PASSWORD`» | La clave no llegó al contenedor | Paso 4.3 |
| Subir la plantilla de Excel da error de permisos | El volumen llegó con otro dueño | Se arregla una vez desde la consola del servicio (`railway ssh`) con `chown -R app:app /app/plantillas` |

---

## Lo que no hay que hacer

- **No** cambiar los nombres de los servicios: son las direcciones internas.
- **No** poner `--reload` en el comando del `api`.
- **No** tocar `BD_POOL_SIZE` y `BD_MAX_OVERFLOW` sin hacer la cuenta otra vez:
  `(API_WORKERS + 1) × (BD_POOL_SIZE + BD_MAX_OVERFLOW) ≤ max_connections` — con los valores de esta
  guía: `(2 + 1) × (10 + 10) = 60 ≤ 200`.
- **No** crear un segundo servicio `worker`: el trabajo se repite sin ganar nada.
- **No** desplegar el panel sin haber puesto antes su dirección en `CORS_ORIGINS` del `api`.
