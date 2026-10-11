# Pasar los datos de Supabase a la base del despliegue

> **Se hizo el 2026-10-07, pero no por este camino.** La copia la hizo
> **`backend/scripts/copiar_base.py`**, un script del propio repositorio: **124.677 filas en 24
> tablas**, comprobadas una a una. Este documento describe el camino de `pg_dump`/`pg_restore`, que
> **no** se usó —la máquina no tiene cliente de PostgreSQL y el script no lo necesita— y queda como
> alternativa para un servidor con Docker.
>
> Lo que **sigue siendo válido** de aquí: las cifras, la trampa del agrupador de transacción (el 6543
> nunca), el vaciado del destino antes de copiar, las comprobaciones del final y la vuelta atrás.

La base de Supabase y la del despliegue tienen **el mismo esquema**: las dos lo construyó Alembic a
partir de las mismas migraciones. Eso cambia por completo el problema. No hay que decidir qué tablas
importan, ni en qué orden crearlas, ni traducir tipos: lo único que falta en la nueva son **las
filas**. Todo lo demás —tablas, particiones, políticas de aislamiento, funciones, índices— ya está
hecho.

Así que esto no es «volcar y restaurar una base», es **copiar el contenido**.

## Cuánto hay que mover

Medido contra la base anterior el 2026-10-07:

| | |
|---|---|
| Base completa | 710 MB |
| `registro` (el histórico) | 110.366 filas · 679 MB · **el 97 %** |
| `registro_historial` (particionada) | 13.041 filas · 17 MB |
| `negocio` | 20 filas |
| `usuario` | 24 filas |
| `termino` | 42 filas |
| Todo lo demás | por debajo de 300 kB |

Casi todo el peso son los datos públicos del SERCOP, que son los mismos para cualquier cliente. El
dato que no se puede reconstruir —y que no se recupera volviendo a ingestir— son esas **pocas decenas
de filas** del plano de negocio: empresas, cuentas, consentimientos, vistas concedidas y palabras
clave.

## Dónde se ejecuta esto

**No en tu portátil.** Tu portátil no llega a la base del despliegue: vive en una red privada de
Railway y no se puede alcanzar desde fuera. Y al revés tampoco: la del despliegue no llega a tu
portátil.

Pero hay un sitio que **sí ve las dos**: el contenedor de la base dentro de Railway. Hacia fuera
alcanza Supabase (su agrupador de sesión es IPv4 normal), y hacia dentro es la base misma. Ahí es
donde se hace la copia, y por eso **el proxy TCP no hace falta para esto**: no hay nada que exponer a
internet ni ninguna contraseña que sacar de la plataforma.

Si ya creaste un proxy TCP, `:1123` es el puerto de destino y por eso el proxy acepta la conexión y
la corta en el acto —no hay nada escuchando ahí—. El de dentro es **5432**. Aun así, para migrar los
datos puedes dejarlo cerrado.

## Antes de empezar

1. **Para el `api` y el `worker`.** El `worker` ingestando mientras se copia deja una foto que no
   corresponde a ninguna realidad, y el `api` atendiendo sobre una base que se está vaciando da
   errores que parecen defectos del código. En Railway: servicio → **⋮** → *Restart* no sirve para
   parar; hay que quitar el *Start Command* o poner un `sleep` —lo más simple es **cambiar la
   variable del `worker` a `INTERVALO_VIGILANCIA_SEG=86400`** y borrar temporalmente el dominio del
   `api` para que nadie entre. Lo importante: **nadie escribiendo**.

2. **Comprueba que el destino está al día.** Las migraciones corren al arrancar el `api`. Si está
   Online, el esquema está en la revisión `0021`. Si el origen estuviera en una revisión anterior, se
   migra primero el origen (`alembic upgrade head` contra Supabase) y se vuelve a empezar.

3. **Abre la consola del servicio `bd`** (la base, no el `api`) y comprueba con qué cuentas:

   ```bash
   pg_dump --version
   env | sort | grep -iE "postgres|^pg|database"
   ```

   El `pg_dump` tiene que ser **17 o superior**: `pg_dump` no puede leer de un servidor más nuevo que
   él, y el origen es **PostgreSQL 17.6**. El `env` dice cómo se llaman las variables del contenedor
   (`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` en la imagen oficial, o `PGUSER`/`PGPASSWORD`/…
   en la plantilla de Railway). Los comandos de abajo usan `${POSTGRES_*}`: cámbialos por lo que veas.

## Paso 1 · La dirección del origen, como variable

En el servicio `bd` → **Variables** → añade:

| Variable | Valor |
|---|---|
| `DATABASE_URL_ORIGEN` | La cadena de Supabase, **con el agrupador de sesión** (`…pooler.supabase.com:5432`) |

Dos avisos que cuestan una hora si se ignoran:

- **El puerto 6543 es el agrupador de transacción y no sirve.** Corta la sesión entre sentencia y
  sentencia; el volcado sale incompleto y, peor, sale **sin error**. El de sesión usa el **5432**.
- Guardar la variable **reinicia el servicio `bd`**. El volumen no se pierde, pero el contenedor se
  recrea y cualquier `psql` abierto se cae.

## Paso 2 · El volcado

En la consola del `bd`:

```bash
pg_dump --format=custom --data-only --load-via-partition-root \
        --no-owner --no-privileges \
        --dbname "$DATABASE_URL_ORIGEN" \
        --file /tmp/copia.pgc

ls -lh /tmp/copia.pgc
```

Cada bandera está por un motivo concreto:

- **`--data-only`** es la decisión importante: vuelca filas y nada más. Sin esto vendrían también las
  extensiones de Supabase —`supabase_vault`, `pg_stat_statements`— que en Railway no existen, y el
  propietario de cada objeto, que es un rol de Supabase que aquí no está. Se saltaría medio archivo a
  base de errores para acabar con un esquema duplicado encima del que ya funciona.
- **`--load-via-partition-root`** evita un fallo que no se entiende hasta que se ve. El histórico está
  **particionado por mes** y las particiones se crearon cuando se creó la base: el origen tiene
  septiembre, octubre y noviembre de 2026; el destino, las del mes en que se desplegó. Volcando por
  particiones, `pg_restore` buscaría `registro_historial_202609` en el destino y no la encontraría.
  Con esta bandera los datos van por la tabla padre y es PostgreSQL quien los reparte —lo que no tenga
  partición cae en la predeterminada, que existe en las dos.
- **`--no-owner` y `--no-privileges`** quitan de en medio los roles de Supabase (`anon`,
  `authenticated`, `service_role`) y los permisos que no significan nada aquí.

Deja el archivo en `/tmp` dentro del contenedor y no restaures directamente por tubería: son unos
cientos de megabytes por internet, y si la consola se corta a mitad es mejor repetir solo la
restauración que volver a descargarlo todo.

## Paso 3 · Vaciar el destino

El `worker` pudo haber ingestado algo en los días del despliegue. Restaurar encima dejaría claves
duplicadas, así que se vacía primero —todo menos la tabla que lleva la cuenta de las migraciones:

```bash
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "
  SELECT 'TRUNCATE TABLE '
         || string_agg(format('%I.%I', schemaname, tablename), ', ')
         || ' CASCADE;'
  FROM pg_tables
  WHERE schemaname = 'public' AND tablename <> 'alembic_version'" \
| psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -
```

No se pierde nada que no esté en Supabase, que sigue intacto.

## Paso 4 · Restaurar

```bash
export PGPASSWORD="$POSTGRES_PASSWORD"

pg_restore --data-only --no-owner \
           --host 127.0.0.1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
           /tmp/copia.pgc
```

`pg_restore` devuelve un código distinto de cero cuando hay avisos, aunque todo haya ido bien. Antes
de darlo por fallido, mira **cuáles** son: los de «no existe el rol» son esperables y no afectan a los
datos.

## Paso 5 · Comprobar que no falta nada

Esto es lo que convierte una restauración en una migración. Que el comando termine no dice nada.

```bash
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT (SELECT count(*) FROM registro)          AS registro,
         (SELECT count(*) FROM registro_historial) AS historial,
         (SELECT count(*) FROM negocio)           AS negocios,
         (SELECT count(*) FROM usuario)           AS usuarios,
         (SELECT count(*) FROM termino)           AS terminos,
         (SELECT count(*) FROM acceso_vista)      AS vistas;"
```

Y tienen que salir exactamente estas cifras, que son las del origen medidas antes de empezar:

| Tabla | Filas |
|---|---|
| `registro` | **110.366** |
| `registro_historial` | **13.041** |
| `negocio` | **20** |
| `usuario` | **24** |
| `termino` | **42** |
| `acceso_vista` | **64** |

Si un número no cuadra, no sigas: arreglarlo con la base ya en uso es mucho más caro que ahora.

Después, arranca el `api` y el `worker` otra vez y comprueba:

```bash
curl -s https://api-production-6dbc.up.railway.app/listo
```

Y entra al panel con una cuenta real: la tabla, el mapa y las gráficas tienen que mostrar lo mismo
que mostraban contra Supabase.

## Volver atrás

Supabase **no se toca** en ningún momento de este procedimiento. Volver es cambiar `DATABASE_URL` en
el `api` por la dirección de Supabase y reiniciar. Por eso conviene no borrar el proyecto de Supabase
hasta que pasen unos días de uso real.

## Lo que no está comprobado

- **Ningún paso de este documento se ha ejecutado todavía.** Está escrito a partir del esquema real,
  de las migraciones reales y de las cifras reales de la base anterior, pero los comandos de la
  consola de Railway no se han corrido ni una vez.
- **El tiempo que tarda.** Son unos 700 MB leídos por internet y recomprimidos. Con el formato
  personalizado (comprimido) el archivo queda muy por debajo de eso, pero no hay una medida: si
  tarda mucho más de lo razonable, la primera sospecha es el agrupador de transacción.
- **Que el usuario de Railway sea el dueño de las tablas.** Lo es si las creó Alembic al arrancar el
  `api`, que es lo que ocurre; pero si alguien las creó con otro rol, las políticas de aislamiento
  podrían filtrar filas durante la restauración y faltarían datos **sin ningún error visible**.
  Merece la pena leer los recuentos del paso 5 con esa posibilidad en la cabeza.
