# Migrar los datos de Supabase al servidor propio

Esta es la parte del **camino B** que no se puede improvisar. El código no cambia: cambia dónde vive
PostgreSQL, y con él desaparecen los tres costes que tiene la base remota —los ~281 ms por bloque, el
límite de conexiones del proveedor y el bloqueo de asesoría que se cae porque el servidor cierra la
conexión ociosa—.

Se hace **una vez**, con una ventana de corte de minutos, y se puede volver atrás en un minuto
porque el proyecto de Supabase se queda intacto.

## Antes de empezar

1. **Saber cuánto se va a mover.** Con el proyecto actual configurado:

   ```
   cd backend
   .\.venv\Scripts\python.exe scripts\estado_datos.py
   ```

   Con eso se sabe el tamaño del histórico, que es el 90 % de los datos. El resto —negocios,
   usuarios, sesiones, consentimientos— son miles de filas.

2. **Tener el servidor levantado menos la API.** El `compose` completo, pero con la API y el worker
   parados: se migra sobre una base sin nadie escribiendo.

3. **Elegir la región del servidor.** Con usuarios en Ecuador y la fuente oficial también allí, un
   centro de datos en la costa este de Estados Unidos es el compromiso habitual. **No importa que
   Supabase esté en N. Virginia para el destino**: eso solo afecta a lo que tarde la copia, no al
   funcionamiento posterior.

## Preparar el destino

```
docker compose -f deploy/docker-compose.yml up -d bd cache proxy
docker compose -f deploy/docker-compose.yml exec -T bd \
  psql -U "$BD_USUARIO" -d "$BD_NOMBRE" -c "SELECT version();"
```

No se ejecutan las migraciones todavía: van a venir dentro de la copia, con su tabla
`alembic_version` al día.

## La copia

**Antes de nada, comprobar por dónde se puede llegar al origen.** Este proyecto está en Supabase y su
host directo resuelve **solo por IPv6**:

```
db.kcffuarcfhybanljcuta.supabase.co  ->  2600:1f18:... (solo IPv6, sin IPv4)
```

Es lo normal en el plan gratuito: la dirección IPv4 es un añadido de pago. Y tiene una consecuencia
que no se ve hasta que falla: **un contenedor de Docker no tiene IPv6 por defecto**, así que un
`docker compose exec bd pg_dump ...` contra ese host no llega. El error que aparece —«no se puede
resolver el nombre» o «red inalcanzable»— no dice nada de IPv6 y se pierde un rato buscando en el
sitio equivocado.

Hay dos salidas, y la segunda es la que funciona siempre:

**a) Ejecutar `pg_dump` en el servidor, no dentro del contenedor.** Sirve si el servidor tiene IPv6
en funcionamiento (comprobarlo con `ping6 -c1 db.<ref>.supabase.co` antes de contar con ello).

**b) Usar el agrupador de *sesión*.** Supabase tiene dos agrupadores y solo uno sirve para copiar:

| Puerta | Host | ¿Sirve para `pg_dump`? |
|---|---|---|
| Directa | `db.<ref>.supabase.co:5432` | Sí, pero **solo por IPv6** |
| Agrupador de **sesión** | `aws-0-us-east-1.pooler.supabase.com:5432` | **Sí**: es IPv4 y mantiene la sesión |
| Agrupador de **transacción** | `...pooler.supabase.com:6543` | **No**: corta la sesión y la copia sale inconsistente |

Los dos agrupadores comparten host y se distinguen **por el puerto**. El de sesión usa el 5432 —el
mismo número que la conexión directa, lo que invita a confundirlos— y el de transacción el 6543. La
regla es sencilla: **el 6543 nunca se usa aquí, ni para copiar ni para el `pg_dump`**.

Con el agrupador de sesión, el usuario lleva el sufijo del proyecto: `postgres.kcffuarcfhybanljcuta`.
El host exacto (`aws-0` o `aws-1`) se copia del cuadro de conexión del panel de Supabase: aquí los dos
resuelven por IPv4, pero solo uno es el del proyecto.

La copia, con el cliente del **contenedor de destino** para que `pg_dump` y el servidor que recibe
sean de la misma versión:

```
# DATABASE_URL_ORIGEN apunta al agrupador de SESIÓN (puerto 5432), nunca al de transacción (6543).
docker compose -f deploy/docker-compose.yml exec -T bd \
  pg_dump --no-owner --no-privileges --format=custom \
          --dbname "$DATABASE_URL_ORIGEN" > copia-supabase.pgc
```

Para `pg_dump` en sí, la conexión directa por IPv6 también vale y es preferible si está disponible
—se salta un intermediario—, pero entonces el comando se ejecuta con el cliente de la máquina que sí
tenga IPv6, no dentro del contenedor.

Las dos banderas no son opcionales:

- **`--no-owner`**: el propietario de cada objeto en Supabase es un rol que no existe en el servidor
  de destino. Sin esto, la restauración falla o deja objetos cuyo dueño no está.
- **`--no-privileges`**: los permisos concedidos a los roles de Supabase (`anon`, `authenticated`,
  `service_role`) no tienen sentido aquí, y arrastrarlos solo añade ruido que luego nadie sabe
  interpretar.

## La restauración

```
docker compose -f deploy/docker-compose.yml exec -T bd \
  pg_restore --no-owner --no-privileges --clean --if-exists \
             --dbname "$BD_NOMBRE" < copia-supabase.pgc
```

`pg_restore` devuelve un código distinto de cero si encuentra avisos, aunque la restauración haya
ido bien. Antes de darla por fallida, mira **qué** avisos son: los de «no existe el rol» y «no se
puede comentar» son esperables con las dos banderas puestas.

## Comprobar que no falta nada

Esto es lo que convierte una restauración en una migración. **No basta con que el comando termine
sin error.**

**1 · Los recuentos.**

```
# En el origen y en el destino, comparar. Tienen que coincidir.
docker compose -f deploy/docker-compose.yml exec -T bd \
  psql -U "$BD_USUARIO" -d "$BD_NOMBRE" -c \
  "SELECT (SELECT count(*) FROM registro) AS registros,
          (SELECT count(*) FROM negocio)  AS negocios,
          (SELECT count(*) FROM usuario)  AS usuarios;"
```

**2 · El esquema, no solo los datos.** Un `pg_dump --schema-only` de los dos lados y comparar es la
forma de detectar una política de RLS o una función que se quedó por el camino:

```
docker compose -f deploy/docker-compose.yml exec -T bd \
  pg_dump --schema-only --no-owner --no-privileges --dbname "$DATABASE_URL_ORIGEN" > esquema-origen.sql
docker compose -f deploy/docker-compose.yml exec -T bd \
  pg_dump --schema-only --no-owner --no-privileges --dbname "$BD_NOMBRE" > esquema-destino.sql
```

Deben aparecer: las políticas `aislamiento_*`, las funciones `conteo_suscriptores`,
`resolver_cuenta` y `listar_negocios`, los índices GIN y `alembic_version`.

**3 · La aplicación, contra la base nueva.**

```
docker compose -f deploy/docker-compose.yml up -d migraciones api worker
curl -s http://127.0.0.1:8001/listo
```

`alembic upgrade head` tiene que decir que ya está al día: la versión vino dentro de la copia. Y
`/listo` tiene que responder con `postgres` y `cache` en `ok`.

**4 · Con los ojos.** Abre el panel, entra con una cuenta real y comprueba que la tabla, el mapa y
las gráficas muestran lo mismo que mostraban contra Supabase.

## Volver atrás

Durante un tiempo, volver es cambiar una variable: el proyecto de Supabase sigue ahí y no se ha
tocado. Basta con devolver `DATABASE_URL` a su valor anterior y levantar la API. Por eso conviene
**no borrar el proyecto de Supabase** hasta que hayan pasado unos días de uso real.

## Después

1. **Copias de seguridad.** Es lo primero, y no es negociable: hasta que exista una copia cifrada y
   **una restauración probada**, el sistema tiene menos protección que antes, no más. El procedimiento
   está en `deploy/README.md`.
2. **Comprobar el bloqueo de la ingesta.** Con la base en el mismo host, la conexión ociosa del
   bloqueo ya no la cierra nadie por el camino. Deja el worker corriendo un ciclo completo y mira los
   registros: no debería aparecer el aviso de «No se pudo soltar el bloqueo».
3. **Ajustar el pool.** `BD_POOL_SIZE` y `BD_MAX_OVERFLOW` cuentan contra un PostgreSQL que ya es
   tuyo, así que el techo lo pone la memoria del servidor y no un proveedor. Con 4 GB, los valores
   por defecto (10 + 10) sobran.
4. **Anotar la versión de PostgreSQL** que se ha desplegado. Las actualizaciones de versión mayor son
   lo único que sigue necesitando una ventana y una prueba previa.
