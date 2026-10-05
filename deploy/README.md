# Despliegue de un solo servidor

Levanta el sistema completo —PostgreSQL, Redis, API, worker de ingesta y Caddy— en una sola máquina.
Es la opción barata y, en este proyecto, también la rápida: lo que limita al sistema no es la
capacidad de la base de datos, sino los ~280 ms que cuesta cada consulta cuando la base está al otro
lado de la red. Aquí la base está al lado.

| Componente | Dónde vive | Coste |
|---|---|---|
| Frontend (Vue estático) | CDN, apuntando `VITE_API_BASE` a este host | ~0 |
| API + worker + PostgreSQL + Redis + Caddy | Este servidor | ~5-16 €/mes |
| Copias de seguridad | Almacenamiento de objetos (Backblaze B2, Cloudflare R2) | ~1 €/mes |

## Antes de empezar

**Tamaño de la máquina.** Para cientos de usuarios, 4 GB y 2 vCPU. Para miles, 8 GB y 4 vCPU.
El sistema es de entrada y salida, así que la memoria manda más que los núcleos.

**DNS.** El dominio del API tiene que apuntar al servidor **antes** de levantar el despliegue:
Caddy pide el certificado al arrancar y, si el DNS todavía no resuelve, falla y hay que reiniciarlo.

**Puertos abiertos.** 80 y 443. Nada más. PostgreSQL y Redis no se publican a propósito.

## Puesta en marcha

1. Copiar `.env.example` a `.env` en la raíz del repositorio y completar los **obligatorios**
   (`DATABASE_URL` no hace falta: la construye el `compose`), los secretos `JWT_SECRETO`,
   `CLAVE_CIFRADO_DATOS` y `CLAVE_PEPPER_HMAC`, y las variables de despliegue `BD_CLAVE`,
   `DOMINIO` y `CORREO_TLS`.

   Para generar los secretos:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`

2. Levantar todo:

   ```
   docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
   ```

   El servicio `migraciones` corre una vez, aplica el esquema y termina. El API espera a que
   termine: si el esquema no está al día, el API no arranca, que es lo correcto.

3. Comprobar:

   ```
   curl -s http://127.0.0.1:8001/salud
   curl -s https://TU-DOMINIO/listo
   ```

   `/listo` tiene que responder `{"listo": true}` con `postgres` y `cache` en `ok`. Si el caché sale
   como `deshabilitada`, es que `REDIS_URL` no llegó al contenedor.

## Traer los datos que ya tienes

Un despliegue recién levantado arranca con el esquema vacío. Si el sistema ya lleva tiempo en
Supabase, los datos se traen una sola vez y el proyecto de Supabase se queda como red de seguridad
hasta que pase un tiempo de uso real. El procedimiento —copia, restauración y, sobre todo, **cómo
comprobar que no falta nada**— está en [`MIGRACION.md`](MIGRACION.md).

## Copias de seguridad

Esto es la parte que se olvida y la única que no se puede recuperar de otra forma: los datos de
contratación se pueden volver a pedir a SERCOP, pero las empresas, las cuentas, los consentimientos
y las palabras clave que configuró cada cliente **solo están aquí**.

```
deploy/copias.sh            # volcado → verificado → comprimido → cifrado → rotado
```

No hay que escribir ese comando a mano: así es como se programa en el cron del servidor, una vez al
día a las tres de la madrugada.

```
0 3 * * *  /ruta/al/repositorio/deploy/copias.sh >> /var/log/copias-contratacion.log 2>&1
```

Las variables que lee del `.env` (no del entorno: un cron no hereda el de la sesión):

| Variable | Para qué |
|---|---|
| `CLAVE_PUBLICA_AGE` | Clave pública de `age`. **Obligatoria**: sin ella el script se niega a guardar una copia sin cifrar. |
| `COPIA_DIR` | Dónde dejar las copias. Por defecto `deploy/copias`. |
| `COPIA_DIAS` | Cuántos días conservar en el servidor. Por defecto 14. |
| `COPIA_REMOTO` | Destino de `rclone` (`b2:cubeta/contratacion`). Opcional, pero ver el aviso de abajo. |

Para crear la pareja de claves, una sola vez:

```
age-keygen -o clave-copias.txt     # la privada
# la «Public key: age1…» que imprime es la que va en CLAVE_PUBLICA_AGE
```

**La clave privada se guarda fuera del servidor.** Si vive en la misma máquina que las copias, quien
entre ahí tiene las dos cosas y el cifrado no ha servido para nada. Y si se pierde, las copias dejan
de poder abrirse: es la única pieza de este sistema que, perdida, no tiene vuelta atrás.

Dos detalles del script que no son cosméticos:

- **Verifica antes de guardar.** Abre el volcado con `pg_restore --list` y cuenta las tablas con
  datos. Un volcado truncado —disco lleno, contenedor reiniciado a media escritura— se comprime y se
  cifra sin protestar, y solo se descubre el día que hace falta. Comprobarlo cuesta un segundo.
- **Avisa si la copia no sale del servidor.** Una copia que solo vive en la máquina que se está
  copiando no protege del caso más probable, que es que esa máquina desaparezca.

### Y las plantillas de Excel, aparte

Cada empresa puede subir su plantilla, y **ese archivo no está en la base**: vive en el volumen
`datos-plantillas` y la tabla solo guarda su referencia. Por eso la copia son **dos archivos**, uno
con la base y otro con las plantillas, y el script los hace los dos.

Si algún día hay que restaurarlas a mano:

```
docker run --rm -i -v contratacion_datos-plantillas:/datos alpine \
  tar -xzf - -C /datos < plantillas-FECHA.tar.gz.age | age -d -i clave-copias.txt
```

(El nombre real del volumen lleva el prefijo del proyecto del `compose`: `contratacion_`. Se
comprueba con `docker volume ls`.)

### Y la restauración, probada

```
deploy/restaurar-prueba.sh
```

Levanta un PostgreSQL desechable, restaura ahí la copia más reciente y compara los recuentos con la
base viva. Una copia que nunca se ha restaurado no es una copia: es un archivo del que se *supone*
algo. Y el modo de fallo es silencioso —el cifrado funciona, el tamaño parece razonable, el nombre
lleva la fecha— hasta el día en que hace falta de verdad.

No exige que los recuentos coincidan, y es a propósito: `registro` recibe contrataciones cada quince
minutos, así que la copia de esta madrugada **nunca** cuadrará con la base de ahora. Exigir igualdad
daría un fallo permanente y el script se acabaría ignorando. Lo que exige es que ninguna tabla que
tenga datos en la base esté **vacía** en la copia, que es lo que delata un volcado incompleto.

Ponlo en el cron del domingo, no a diario: la prueba levanta un contenedor y tarda un rato.

## El panel

El panel es un sitio estático. Hay dos formas de servirlo y las dos están preparadas.

**Vercel (por defecto).** Se importa el repositorio, se indica que el directorio raíz es `frontend`
y se define una variable de entorno:

```
VITE_API_BASE = https://api.tu-dominio.com
```

`frontend/vercel.json` ya lleva lo que no se deduce solo: el `Cache-Control` de un año para los
`assets` —que llevan el hash del contenido en el nombre, así que un cambio de contenido cambia el
nombre—, las cabeceras de seguridad y un `rewrites` que **excluye `/v1`**, para que el día que el
panel tenga rutas propias no se trague una llamada a la API.

Ojo con `VITE_API_BASE`: Vite **incrusta** las variables en el momento de compilar, así que el valor
queda escrito dentro del JavaScript. No es una variable de ejecución. Cambiarla obliga a volver a
compilar, y equivocarse compila un panel que llama a `localhost` sin que nada avise.

**Desde este mismo servidor, sin Vercel.** `frontend/Dockerfile` compila el panel y lo sirve con
Caddy. Se elige por tres razones concretas: una cosa menos que puede fallar por fuera, la latencia
deja de depender de un CDN en otro país, y el panel puede caerse Vercel sin que se caiga el panel.

```
docker build -t panel:local --build-arg VITE_API_BASE= frontend/
docker run -d --name panel -p 127.0.0.1:8080:80 panel:local
```

Con `VITE_API_BASE` vacío el panel llama a su propio origen, lo que solo funciona si Caddy le pasa
también las rutas de la API. Eso hoy **no** está montado y hay que hacerlo con cuidado: el
`flush_interval -1` de `deploy/Caddyfile` es lo que mantiene viva la presencia, y una ruta mal puesta
lo rompería de una forma difícil de diagnosticar. Queda pendiente y hay que probarlo antes de
cambiarlo en producción.

## Redis: va dentro, y no se paga

El `docker-compose.yml` levanta su propio `redis:7-alpine`. **No hace falta ninguna suscripción**: ni
Upstash, ni Redis Cloud, ni nada. El servicio `cache` de este despliegue es el Redis del sistema y
vive en el mismo servidor que el API, la base y el worker.

Eso importa más de lo que parece. Redis Cloud se usó durante el desarrollo, en su plan gratuito, y
tuvo dos problemas que aquí desaparecen: un tope de **30 conexiones** —que la presencia agotaba con
menos de treinta paneles abiertos— y la facturación por comando, que en un sistema que hace varios
comandos por petición es una factura que crece justo cuando el producto funciona. En local no hay
tope y no se paga por comando.

Lo que sí hay que cuidar, y está puesto en el `compose`:

- **`maxmemory 512mb` con `allkeys-lru`.** El límite es obligatorio, no un adorno: la política de
  expulsión solo actúa cuando hay un límite, y sin él Redis crecería hasta agotar la memoria del
  servidor compitiendo con PostgreSQL.
- **AOF activo, con volumen propio.** Las sesiones abiertas viven aquí, y la ausencia de esa clave
  significa «sesión cerrada». Sin persistencia, cada reinicio del contenedor sería un cierre de
  sesión general.

El único Redis que se sigue usando por fuera es el de tu máquina de desarrollo, a través de
`REDIS_URL` en el `.env`. En el servidor, el `compose` **sobrescribe** esa variable con
`redis://cache:6379/0`, así que da igual lo que ponga el `.env` del repositorio: el despliegue nunca
va a hablar con el Redis de desarrollo.

## Qué no hacer

- **No** publicar el puerto de PostgreSQL ni el de Redis. Un `- "5432:5432"` en el `compose`
  convierte un descuido de configuración en una brecha.
- **No** poner `--reload` en producción: vigila todo el árbol, reinicia con cada escritura y deja
  conexiones abiertas al apagarse.
- **No** montar el panel aquí. El frontend en una CDN es gratis, más rápido para quien lo usa y
  libera al servidor del único trabajo que no depende de la base de datos.
- **No** apuntar `VITE_API_BASE` al API *a través del panel*. El navegador tiene que hablar con el
  API directamente, o cada flujo de eventos de presencia pasará por dos proxies.

## Un servidor es un punto único de fallo

Para el arranque es una decisión consciente y razonable. Cuando el panel pase a ser crítico para tus
clientes, el siguiente paso es un segundo servidor con el API y Caddy, dejando la base de datos en
uno de los dos. **Redis tiene que ser compartido antes de esa réplica**: con el caché y el bus de
presencia en la memoria de cada proceso, dos réplicas mostrarían estados distintos y el panel
mentiría sobre quién está conectado.
