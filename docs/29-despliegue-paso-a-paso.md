# Despliegue, paso a paso

Esta es la guía del operador: qué se despliega, dónde, con qué variables y en qué orden. La razón de
que exista es que el despliegue de este sistema **no es un `git push`**: son cinco procesos, una base
de datos y un proxy, y las tres decisiones que más cuestan (dónde vive la base, cuántas conexiones se
abren y dónde se sirve el panel) se toman antes de escribir la primera línea.

Lo que hay detrás de cada paso —la aritmética de capacidad, el porqué de cada parámetro— está en
[`deploy/README.md`](../deploy/README.md) y en [`07-capacidad-y-concurrencia.md`](07-capacidad-y-concurrencia.md).
Aquí está el camino, en orden, con los comandos tal como se escriben.

---

## 1. Qué se va a desplegar

| Pieza | Dónde vive al final | Cómo se despliega |
|---|---|---|
| **PostgreSQL 17** | El servidor, en un contenedor y **sin puerto publicado** | `deploy/docker-compose.yml` |
| **Redis 7** | El mismo servidor, con persistencia activa | `deploy/docker-compose.yml` |
| **API** (FastAPI, uvicorn) | El mismo servidor, 4 procesos, escuchando solo en `127.0.0.1` | `deploy/docker-compose.yml` |
| **Worker de ingesta** | El mismo servidor, un solo proceso | `deploy/docker-compose.yml` |
| **Migraciones** (`alembic upgrade head`) | Un contenedor que corre una vez y termina | `deploy/docker-compose.yml` |
| **Caddy** (TLS automático y flujo de presencia) | El mismo servidor, único que escucha en 80 y 443 | `deploy/docker-compose.yml` |
| **Panel** (Vue compilado) | Una CDN — Vercel por defecto | `frontend/vercel.json` |

Todo menos el panel sale de **un solo comando**. Eso es deliberado: lo que hace lento a este sistema
son los ~280 ms que cuesta cada bloque de consulta cuando la base está al otro lado de la red, y con
la base en el mismo host ese coste baja a ~1 ms. Separar las piezas en servicios gestionados es
justo lo que hay que evitar aquí.

---

## 2. Dónde hacerlo

### La recomendación: un servidor propio con Docker

**Un VPS de 2 vCPU y 4 GB** cubre el arranque con holgura: el reparto de memoria medido por
`verificar_despliegue.py` es **2.836 MB de 4.096 (69 %)**, con sitio para picos. Para miles de
usuarios concurrentes, 4 vCPU y 8 GB.

Opciones que sirven, de más barata a más cómoda:

| Proveedor | Máquina | Orden de precio | Notas |
|---|---|---|---|
| **Hetzner Cloud** | CX22 o CPX21 (2 vCPU / 4 GB / 40 GB) | ~4-6 €/mes | La mejor relación precio-red para Europa; centro de datos en EE. UU. disponible. Es la que yo elegiría |
| **Oracle Cloud Always Free** | 4 núcleos ARM / 24 GB | **gratis** | Potente y gratis, pero conseguir la instancia puede llevar días y la red es menos previsible. Todas las imágenes del `compose` tienen versión ARM |
| **DigitalOcean / Vultr / Lightsail** | 2 vCPU / 4 GB | 12-24 $/mes | Más caras, panel y facturación muy cómodos |
| **Contabo** | 4 vCPU / 8 GB | ~6 €/mes | Mucha máquina por poco dinero; el rendimiento por núcleo y la red son peores |

**Región:** costa este de Estados Unidos o Miami. Los usuarios están en Ecuador y la fuente oficial
también, y es donde está hoy la base de Supabase que se va a migrar: así la copia inicial es rápida.
La base **final** no tiene que estar en la misma región que Supabase; eso solo afecta a lo que tarde
la migración.

**Sistema operativo:** Ubuntu 24.04 LTS. Es lo que asumen los comandos de abajo.

### Lo que no hay que hacer

- **No desplegar solo con Supabase y Vercel.** Es lo que hay hoy en desarrollo y tiene dos techos
  medidos: el agrupador de Supabase en modo sesión **admite quince clientes** —con veinte usuarios
  concurrentes aparecieron un 10,78 % de fallos y `EMAXCONNSESSION` en el registro— y la base
  gratuita tiene un límite de tamaño que el histórico ya roza (575 MB medidos el 06/10/2026). Vercel
  sí vale para el panel; para la base, no.
- **No poner el panel en el mismo servidor** mientras haya Vercel. Es una pieza menos que mantener
  por fuera, y el panel es lo único del sistema que no depende de la base de datos.
- **No usar un PaaS (Railway, Render, Fly.io) para el API y el worker.** Se puede, pero: el worker
  necesita un proceso vivo (no vale *serverless*), la base gestionada cuesta más que el servidor
  entero, y se pierde la ventaja que justifica todo el diseño —la base al lado del API—. Si aun así
  se elige, el worker va como *worker* del PaaS y hay que comprobar que no lo duerme.

---

## 3. Preparar el servidor

### 3.1. DNS, antes de nada

Dos registros, y en este orden:

```
api.tu-dominio.com    A       IP_DEL_SERVIDOR
panel.tu-dominio.com  CNAME   cname.vercel-dns.com        # el panel, si va en Vercel
```

**El DNS tiene que resolver antes de levantar el despliegue.** Caddy pide el certificado TLS al
arrancar y, si el nombre todavía no apunta al servidor, falla; después hay que reiniciarlo a mano.

### 3.2. La máquina

```bash
# Paquetes al día
sudo apt update && sudo apt upgrade -y

# Docker y el plugin compose (el script oficial, no el de la distribución: el de Ubuntu va viejo)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"      # y volver a entrar en la sesión

# Cortafuegos: SSH, 80 y 443. Nada más.
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable

# Solo si la máquina tiene 4 GB o menos: un fichero de intercambio evita que el asesino por memoria
# mate a PostgreSQL en el pico de una migración.
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**PostgreSQL y Redis no se publican.** En el `compose` no hay un `- "5432:5432"` y eso es
deliberado: exponerlos convierte un descuido de configuración en una brecha. Se entra por
`docker compose exec bd psql ...` cuando hace falta.

**Zona horaria:** el servidor puede quedarse en UTC. La zona del negocio la aplica el código, y
confundirlas fue una fuente de fallos ya resuelta.

---

## 4. Traer el código y escribir el `.env`

```bash
sudo mkdir -p /opt/contratacion && sudo chown "$USER" /opt/contratacion
git clone git@github.com:TU-USUARIO/TU-REPO.git /opt/contratacion
cd /opt/contratacion

cp .env.example .env
```

### 4.1. Los secretos

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # repetir tres veces
```

Van en `JWT_SECRETO`, `CLAVE_CIFRADO_DATOS` y `CLAVE_PEPPER_HMAC`. En producción el arranque
**falla** si alguno mide menos de 32 caracteres, así que es mejor descubrirlo aquí.

`CLAVE_CIFRADO_DATOS` cifra datos personales en la base: **si se cambia, lo ya cifrado deja de poder
leerse**. Se genera una vez y se guarda con las copias de seguridad.

### 4.2. Las variables, una por una

El `.env` completo se arma con esta tabla. «Quién la lee» importa: las del `compose` las usa Docker
para construir los contenedores, y las de la aplicación llegan al API y al worker.

**Obligatorias — sin ellas no arranca**

| Variable | Valor en el servidor | Quién la lee |
|---|---|---|
| `ENTORNO` | `prod` | Aplicación. Activa las validaciones de producción |
| `JWT_SECRETO` | 48+ caracteres aleatorios | Aplicación |
| `CLAVE_CIFRADO_DATOS` | 48+ caracteres aleatorios | Aplicación |
| `CLAVE_PEPPER_HMAC` | 48+ caracteres aleatorios | Aplicación |
| `CORS_ORIGINS` | `https://panel.tu-dominio.com` | Aplicación. **Orígenes exactos**, separados por comas. El comodín `*` se rechaza al arrancar |
| `BD_CLAVE` | contraseña larga, sin `@` `:` `/` | `compose` (PostgreSQL) |
| `DOMINIO` | `api.tu-dominio.com` — **sin** `https://` | `compose` (Caddy) |
| `CORREO_TLS` | tu correo | `compose` (Caddy, aviso de caducidad) |

`DATABASE_URL` y `REDIS_URL` **no se escriben**: el `compose` las construye (`bd:5432`, `cache:6379`).
Si se dejan puestas en el `.env`, el despliegue hablaría con la base de desarrollo sin avisar.

**Dimensiones — las tres que deciden si aguanta**

| Variable | 4 GB / 2 vCPU | 8 GB / 4 vCPU | Por qué |
|---|---|---|---|
| `API_WORKERS` | `4` | `4` (o `8`) | Un proceso por núcleo; son de entrada y salida, no de cálculo |
| `BD_POOL_SIZE` + `BD_MAX_OVERFLOW` | `10` + `10` | `10` + `10` | ⚠️ **Los de `.env.example`, no los de tu portátil.** Ver el aviso de abajo |
| `BD_MAX_CONNECTIONS` | `200` | `200` | Tiene que caber `(API_WORKERS + 1) × (pool + overflow)` = 100 |
| `BD_SHARED_BUFFERS` | `1GB` | `2GB` | ~25 % de la RAM |
| `BD_EFFECTIVE_CACHE_SIZE` | `3GB` | `6GB` | ~75 % de la RAM; es una pista, no memoria reservada |
| `BD_WORK_MEM` | `16MB` | `16MB` | Por operación **y por conexión**: 100 conexiones son 1,6 GB en el peor caso |
| `BD_RANDOM_PAGE_COST` | `1.1` | `1.1` | Correcto para SSD. **Hay que comprobar los planes en el servidor** (§ 10) |
| `CACHE_MAXMEMORY` | `512mb` | `512mb` | Red de seguridad de Redis, no régimen de funcionamiento |

> **⚠️ El error que ya ha pasado una vez.** Tu `.env` de desarrollo tiene `BD_POOL_SIZE=4` y
> `BD_MAX_OVERFLOW=2` **a propósito**: allí la base es el agrupador de Supabase, que en modo sesión
> admite quince clientes. Copiar ese archivo al servidor «para no empezar de cero» deja el despliegue
> con menos de la mitad de la concurrencia para la que está dimensionado todo lo demás, y no falla:
> va lento. En el servidor, `10 + 10`. `verificar_despliegue.py` avisa si detecta el perfil pequeño.

**Copias de seguridad**

| Variable | Valor | Para qué |
|---|---|---|
| `CLAVE_PUBLICA_AGE` | `age1…` | **Obligatoria**: sin ella el script se niega a guardar una copia sin cifrar |
| `COPIA_DIR` | `deploy/copias` (por defecto) | Dónde deja los volcados |
| `COPIA_DIAS` | `14` (por defecto) | Cuántos días se conservan en el servidor |
| `COPIA_REMOTO` | `b2:cubeta/contratacion` | Opcional pero muy recomendable: una copia que solo vive en la máquina que se copia no protege de que esa máquina desaparezca |

**Negocio y operación — tienen valor por defecto, se cambian por decisión**

| Variable | Por defecto | Qué decide |
|---|---|---|
| `RETENCION_DIAS_DATOS_PERSONALES` | `365` | LOPDP: cuánto se conservan los datos personales |
| `PURGA_PLAZO_DIAS` | `7` | Días que se conserva una ínfima después de vencer su plazo |
| `PURGA_MAX_FILAS_POR_VUELTA` | `500` | **`0` desactiva la retención** (se informa y no se borra) |
| `INTERVALO_INGESTA_MIN` | `15` | Ciclo completo de ingesta |
| `INTERVALO_VIGILANCIA_SEG` | `150` | Vigilancia del listado de NCO |
| `PRESUPUESTO_PETICIONES_CICLO` | `90` | Peticiones por ciclo contra la fuente oficial |
| `EXPORT_ASYNC_UMBRAL_FILAS` / `EXPORT_TTL_HORAS` | `20000` / `24` | Cuándo la exportación pasa a segundo plano |
| `MODULO_ADMIN_HABILITADO` | `true` | El módulo administrativo (v1) |
| `LOG_NIVEL` | `INFO` | `DEBUG` llena el disco; dejarlo en `INFO` |
| `PLANTILLAS_DIR` | `/app/plantillas` | El `compose` ya lo fija al volumen |

`PERMITIR_ACTOR_DE_DESARROLLO` no hace falta ponerlo: su valor por defecto es `false` **y** el código
lo ignora en producción aunque alguien lo ponga a `true`.

**El panel** (no va en el `.env` de la raíz: es una variable de compilación, § 8):

```
VITE_API_BASE = https://api.tu-dominio.com
```

### 4.3. Cuántas conexiones se abren, y por qué eso deja de ser el problema

Es la pregunta que decide si el sistema aguanta, y la respuesta cambia por completo al mover la base
al mismo servidor:

| | Base gestionada (agrupador, lo que hay en desarrollo) | Base en Docker, en el servidor |
|---|---|---|
| Techo de conexiones | **15** clientes en modo sesión | `max_connections` = **200** |
| Lo que abre el sistema | 2 procesos × 20 = 40 posibles | (4 API + 1 worker) × (10 + 10) = **100** |
| Latencia de una consulta | ~280 ms | ~1 ms |
| Consultas por segundo y conexión | ~3,5 | ~1.000 |
| Quién pone el límite | el proveedor | la CPU de la máquina |

**La fórmula, que es lo único que hay que recordar:**

```
(API_WORKERS + 1) × (BD_POOL_SIZE + BD_MAX_OVERFLOW) ≤ BD_MAX_CONNECTIONS
```

El `+1` es el worker de ingesta, que abre su propio conjunto. Con los valores del `.env.example`:
`(4 + 1) × (10 + 10) = 100 ≤ 200`, y sobran cien conexiones para la migración y para mirar la base a
mano.

**Lo que hace que sobre tanto:** una conexión se ocupa **mientras dura la consulta** y se devuelve al
conjunto. Mil usuarios con el panel abierto no son mil conexiones: son mil sesiones y, en un instante
cualquiera, unas pocas decenas de consultas en vuelo. Con la base a 1 ms, cada conexión despacha
centenares de consultas por segundo en lugar de tres, así que el techo deja de ser el número de
conexiones y pasa a ser el trabajo que la máquina puede hacer.

**Y lo que no son conexiones de base, aunque se cuente junto:** cada panel abierto mantiene **una
conexión HTTP** con el flujo de presencia. Mil paneles son mil descriptores de fichero —por eso
`nofile: 65536` en el API y en Caddy—, unos 150 MB por proceso de uvicorn, y **cero conexiones a
PostgreSQL** durante los quince segundos entre instantáneas.

Si algún día hiciera falta más: subir `API_WORKERS` (más procesos, más CPU) y `BD_MAX_CONNECTIONS` a
la vez. **No** hace falta un PgBouncer: con la base al lado, solo añadiría un salto más donde
diagnosticar.

---

## 5. Levantar

```bash
cd /opt/contratacion
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

Lo que pasa, en orden, y por eso el orden importa:

1. Arrancan PostgreSQL y Redis y **esperan a estar sanos** (`healthcheck`).
2. Corre `migraciones` una vez: `alembic upgrade head`. Si falla, se ve en los registros y **no
   reintenta en silencio**.
3. El API espera a que las migraciones **terminen bien**. Si el esquema no está al día, el API no
   arranca: es lo correcto.
4. Arranca el worker de ingesta.
5. Caddy pide el certificado TLS para `DOMINIO`.

Comprobar el estado del conjunto:

```bash
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs migraciones
docker compose -f deploy/docker-compose.yml logs proxy | grep -i cert
```

---

## 6. Comprobar que responde

```bash
curl -s http://127.0.0.1:8001/salud        # {"servicio":"contratacion-api","estado":"ok"}
curl -s https://api.tu-dominio.com/listo   # {"listo":true,...} con postgres y cache en ok
```

Si `/listo` devuelve `503`, el cuerpo dice **qué** dependencia falla. Los dos casos que se ven:

- `cache: deshabilitada` → `REDIS_URL` no llegó al contenedor. Con el `compose`, no debería pasar.
- `postgres: error` → la base no responde; mirar `docker compose logs bd`.

Desde el navegador, con el panel ya desplegado (§ 8), la prueba que cierra el círculo es **entrar
con una cuenta y ver datos**. Mientras no haya datos (base recién creada), el panel arranca vacío:
es el momento de la migración.

---

## 7. Traer los datos que ya existen

Un despliegue nuevo arranca con el esquema **vacío**: el histórico de contratación se puede volver a
pedir a SERCOP, pero las empresas, las cuentas, los consentimientos y las palabras clave que
configuró cada cliente solo están en la base actual.

El procedimiento completo —volcado, restauración y, sobre todo, **cómo comprobar que no falta
nada**— está en [`deploy/MIGRACION.md`](../deploy/MIGRACION.md). Se hace **una vez**, con una ventana
de corte de minutos, y se puede volver atrás en un minuto porque el proyecto de Supabase se queda
intacto.

Resumen del orden:

```bash
cd backend
.venv/Scripts/python.exe scripts/estado_datos.py       # cuánto se va a mover (en Windows)
```

1. Levantar el `compose` **con el API y el worker parados** (`docker compose stop api worker`).
2. Volcar desde Supabase y restaurar en el PostgreSQL del servidor.
3. Comparar recuentos tabla por tabla — el script de `MIGRACION.md` los imprime.
4. Volver a arrancar (`docker compose start api worker`) y dejar que el worker haga su primer ciclo.

**Mientras el historial no esté migrado, las estadísticas del panel saldrán vacías o parciales**, y
eso no es un fallo: es que la base aún no tiene el año.

---

## 8. El panel

**Vercel (por defecto).** Se importa el repositorio y se definen dos cosas:

| Ajuste en Vercel | Valor |
|---|---|
| *Root Directory* | `frontend` |
| Variable de entorno | `VITE_API_BASE` = `https://api.tu-dominio.com` |

`frontend/vercel.json` ya lleva lo que no se deduce solo: un año de caché para los `assets` (llevan
el hash del contenido en el nombre), las cabeceras de seguridad y un `rewrites` que **excluye `/v1`**.

> **`VITE_API_BASE` se incrusta al compilar, no se lee al arrancar.** Cambiarla obliga a volver a
> compilar. Equivocarse —o usar otro nombre de variable— compila un panel que llama a su propio
> origen: en Vercel eso es un 404 en cada petición y el error no dice por qué.

Después, en el `.env` del servidor, `CORS_ORIGINS` tiene que contener exactamente el origen del
panel (`https://panel.tu-dominio.com`). Si el panel se sirve desde un dominio de Vercel, se añade
también (`https://tu-proyecto.vercel.app`), separado por comas. Sin esto, el navegador bloquea las
peticiones y el panel se queda cargando para siempre: es el fallo número uno de un despliegue nuevo.

**Servir el panel desde el mismo servidor** es la otra opción y está preparada en
`frontend/Dockerfile`, pero **no está montada en el `compose`**: exige que Caddy reenvíe también
`/v1` y `/salud` manteniendo el `flush_interval -1` del flujo de presencia. Está documentado como
pendiente en `deploy/README.md` y hay que probarlo antes de usarlo en producción.

---

## 9. Copias de seguridad

Es la parte que se olvida y la única que no se puede recuperar de otra forma.

```bash
# Una vez: crear la pareja de claves
age-keygen -o clave-copias.txt     # la pública va en CLAVE_PUBLICA_AGE del .env

# Comprobar que el script funciona, antes de programarlo
deploy/copias.sh
```

Y en el cron del servidor, una vez al día:

```
0 3 * * *  /opt/contratacion/deploy/copias.sh >> /var/log/copias-contratacion.log 2>&1
0 4 * * 0  /opt/contratacion/deploy/restaurar-prueba.sh >> /var/log/restauracion.log 2>&1
```

**La clave privada (`clave-copias.txt`) se guarda fuera del servidor.** Si vive en la misma máquina
que las copias, quien entre ahí tiene las dos cosas. Y si se pierde, las copias dejan de poder
abrirse: es la única pieza de este sistema que, perdida, no tiene vuelta atrás.

Las copias son **dos archivos**: la base y el volumen de plantillas de Excel (que no está en la
base).

---

## 10. Las tres medidas que hay que correr en el servidor

Estas no se pueden correr desde el portátil: miden esta máquina.

**a) La aritmética.** Comprueba que los pools caben en `max_connections`, que el reparto de memoria
cabe en la RAM, que hay topes de registro y que el API confía en las cabeceras del proxy solo porque
escucha en `127.0.0.1`:

```bash
cd backend
.venv/Scripts/python.exe scripts/verificar_despliegue.py --ram-gb 4
```

Tiene que terminar en `Todas las comprobaciones pasaron`. Si avisa de que el pool por proceso es
pequeño, es que el `.env` viene del portátil (§ 4.2).

**b) Los planes de consulta.** `BD_RANDOM_PAGE_COST=1.1` es lo correcto para disco de estado sólido,
pero **cambia los planes**, y los de este proyecto se eligieron midiendo:

```bash
.venv/Scripts/python.exe scripts/medir_consultas.py
```

Si algún plan empeora, se pone `BD_RANDOM_PAGE_COST=4`, se reinicia el `compose` y se vuelve a medir.
Es una variable del `.env`, no un cambio de código.

**c) La escalera de carga.** Es la única prueba que dice **cuánta gente cabe de verdad**:

```bash
k6 run -e BASE_URL=https://api.tu-dominio.com -e VUS=100 -e DURACION=5m  carga/panel.js
# y después la escalera: 250, 500, 1.000
```

Antes de la primera vuelta hay que crear las cuentas de prueba:

```bash
.venv/Scripts/python.exe scripts/preparar_carga.py
```

Los números de `docs/07-capacidad-y-concurrencia.md` son **aritmética de diseño hasta que esto se
corre**. Medido en desarrollo, el agrupador de Supabase se queda en quince clientes; aquí la base es
propia y el techo lo pone la aritmética que acaba de comprobar el paso (a).

---

## 11. Actualizar el despliegue

```bash
cd /opt/contratacion
git pull
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

El servicio `migraciones` vuelve a correr, aplica lo que falte y el API se recrea detrás. Los
volúmenes —base, caché, plantillas, certificados— no se tocan.

Si el cambio incluye el panel, hay que **volver a compilarlo** (Vercel lo hace con el `push`), porque
`VITE_API_BASE` queda dentro del JavaScript.

**No** poner `--reload` en producción, y **no** añadir `- "5432:5432"` al `compose` «un momento para
mirar algo».

---

## 12. Lista de comprobación final

- [ ] El DNS de `api.tu-dominio.com` resuelve a la IP del servidor **antes** de levantar.
- [ ] Solo 80, 443 y SSH abiertos. PostgreSQL y Redis sin puerto publicado.
- [ ] `.env` en el servidor con `ENTORNO=prod` y los tres secretos de 48+ caracteres.
- [ ] `BD_POOL_SIZE=10` y `BD_MAX_OVERFLOW=10` (**no** los del portátil).
- [ ] `CORS_ORIGINS` con el origen exacto del panel.
- [ ] `docker compose ps` con `bd` y `cache` en `healthy`.
- [ ] `migraciones` terminó con código 0.
- [ ] `https://api.tu-dominio.com/listo` responde `{"listo": true}`.
- [ ] El certificado TLS emitido (`logs proxy`).
- [ ] Datos migrados y recuentos comparados (`deploy/MIGRACION.md`).
- [ ] El panel entra, muestra datos y la presencia funciona (un punto verde por sesión).
- [ ] `verificar_despliegue.py`: todas las comprobaciones pasaron.
- [ ] `medir_consultas.py`: los planes siguen siendo los buenos (o `BD_RANDOM_PAGE_COST=4`).
- [ ] `deploy/copias.sh` ejecutado a mano **una vez** y programado en el cron.
- [ ] `clave-copias.txt` guardada **fuera** del servidor.
- [ ] `restaurar-prueba.sh` en el cron del domingo.
- [ ] La escalera de k6 corrida y el número anotado en `docs/07`.

---

## 13. Lo que no se ha podido comprobar desde aquí

Honestidad por delante, porque de esto depende dónde poner la atención los primeros días:

- **Las imágenes de Docker nunca se han construido en esta máquina**: aquí no hay Docker instalado.
  El `compose` se ha revisado como texto y con `verificar_despliegue.py`, no ejecutándolo. El primer
  `up --build` en el servidor es, de verdad, la primera vez que esas imágenes se construyen. Si algo
  falla, será ahí.
- **La aritmética de capacidad es de diseño, no una medición.** Los costes por operación están
  medidos; el modelo de carga, deducido del código. La escalera de k6 (§ 10c) es lo que lo convierte
  en un hecho.
- **`BD_RANDOM_PAGE_COST=1.1` está sin comprobar contra el disco del servidor.** Hay que correr
  `medir_consultas.py` allí.
- **El panel servido desde el propio Caddy está pendiente a propósito** (§ 8).
- **Poner el panel y el API bajo el mismo dominio** exige montar las rutas y probar el flujo de
  presencia; hoy no está hecho.
