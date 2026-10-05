#!/usr/bin/env bash
#
# Copia de seguridad de la base de datos, cifrada y **verificada**.
#
# Por qué esto existe
# -------------------
# Es lo único de todo el sistema que no se puede recuperar de otra forma. Los datos de contratación
# se pueden volver a ingerir desde SERCOP, pero las empresas, los usuarios, los consentimientos y
# las palabras clave que cada cliente configuró no: eso solo está aquí.
#
# Las dos reglas que convierten un volcado en una copia
# ----------------------------------------------------
# 1. **Cifrada.** El volcado lleva datos personales —`usuario.email`, `consentimiento`,
#    `solicitud_arco`, `punto_contacto_entidad`—. Una copia sin cifrar en un almacén de objetos es
#    una brecha esperando a que alguien liste el cubo. Por eso el cifrado no es opcional y hay que
#    pedir explícitamente lo contrario para saltárselo.
# 2. **Verificada.** Aquí está lo que casi nadie hace y es lo que separa una copia de un archivo del
#    que se *supone* algo: el volcado se abre con `pg_restore --list` **antes** de darlo por bueno.
#    Un volcado truncado —disco lleno, contenedor reiniciado a media escritura— se comprime y se
#    cifra sin protestar, y solo se descubre el día que hace falta. Comprobar el índice cuesta un
#    segundo y es la diferencia entre tener copias y creer que se tienen.
#
# Variables (se leen del `.env` del repositorio):
#   BD_USUARIO, BD_NOMBRE        lo que hay que copiar
#   CLAVE_PUBLICA_AGE            clave pública de `age`. Obligatoria salvo `--sin-cifrar`.
#   COPIA_DIR                    dónde dejar las copias (por defecto `deploy/copias`)
#   COPIA_DIAS                   cuántos días conservar en local (por defecto 14)
#   COPIA_REMOTO                 destino de `rclone` (por ejemplo `b2:cubeta/contratacion`). Opcional.
#
# Uso:
#   deploy/copias.sh                 copia normal
#   deploy/copias.sh --sin-cifrar    sin cifrar (solo para una prueba local)
#
# Para el cron del servidor, una vez al día a las 3 de la madrugada:
#   0 3 * * *  /ruta/al/repositorio/deploy/copias.sh >> /var/log/copias-contratacion.log 2>&1

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$RAIZ/deploy/docker-compose.yml" --env-file "$RAIZ/.env")

CIFRAR=1
for argumento in "$@"; do
  case "$argumento" in
    --sin-cifrar) CIFRAR=0 ;;
    *) echo "Opción no reconocida: $argumento" >&2; exit 2 ;;
  esac
done

# El `.env` se lee sin `source`: un fichero de entorno con un valor que lleve espacios o comillas
# rompería el script entero al interpretarlo como código.
leer_del_entorno() {
  local clave="$1" por_defecto="${2:-}"
  local valor
  valor="$(grep -E "^${clave}=" "$RAIZ/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  # Se quitan las comillas envolventes si las hay.
  valor="${valor%\"}"; valor="${valor#\"}"
  valor="${valor%\'}"; valor="${valor#\'}"
  printf '%s' "${valor:-$por_defecto}"
}

BD_USUARIO="$(leer_del_entorno BD_USUARIO contratacion)"
BD_NOMBRE="$(leer_del_entorno BD_NOMBRE contratacion)"
CLAVE_PUBLICA_AGE="$(leer_del_entorno CLAVE_PUBLICA_AGE)"
COPIA_DIR="$(leer_del_entorno COPIA_DIR "$RAIZ/deploy/copias")"
COPIA_DIAS="$(leer_del_entorno COPIA_DIAS 14)"
COPIA_REMOTO="$(leer_del_entorno COPIA_REMOTO)"

if [ "$CIFRAR" -eq 1 ] && [ -z "$CLAVE_PUBLICA_AGE" ]; then
  cat >&2 <<'FIN'
Falta CLAVE_PUBLICA_AGE en el `.env`, y sin ella la copia iría sin cifrar.

  Para crearla (una sola vez; la privada se guarda FUERA de este servidor):
    age-keygen -o clave-copias.txt
    # la línea «Public key: age1...» es la que va en CLAVE_PUBLICA_AGE

  Si la clave privada se pierde, las copias dejan de poder abrirse. Si se pierde la privada y
  además está guardada en el mismo servidor que se está copiando, el cifrado no sirve de nada:
  quien entre en el servidor tendrá las dos.

  Para una prueba local sin cifrado: `copias.sh --sin-cifrar`.
FIN
  exit 3
fi

if [ "$CIFRAR" -eq 1 ] && ! command -v age >/dev/null 2>&1; then
  echo "Hace falta el programa 'age' para cifrar. En Debian/Ubuntu:  apt install age" >&2
  exit 3
fi

mkdir -p "$COPIA_DIR"

MARCA="$(date +%Y-%m-%d_%H%M%S)"
SUFIJO=".dump.zst"
TRABAJO="$(mktemp -d)"
trap 'rm -rf "$TRABAJO"' EXIT

echo "[$(date +%H:%M:%S)] Copiando $BD_NOMBRE…"
INICIO=$SECONDS

# ---------------------------------------------------------------------------
# 1. El volcado
# ---------------------------------------------------------------------------
# `--format=custom` y no SQL plano, por una razón práctica: permite restaurar **una tabla** o
# **excluir** una, y comprimirlo después sin que haya que volver a generar el archivo. Y lo que es
# más importante aquí: es el único formato que `pg_restore --list` sabe leer, que es la verificación
# del paso 2.
#
# El volcado se pide al **contenedor de la base**, no a un cliente de la máquina: `pg_dump` no admite
# versiones de servidor más nuevas que la suya, así que usar el cliente que va dentro de la misma
# imagen de PostgreSQL elimina esa clase de fallo.
"${COMPOSE[@]}" exec -T bd pg_dump \
  --username "$BD_USUARIO" \
  --dbname "$BD_NOMBRE" \
  --format=custom \
  --compress=0 \
  > "$TRABAJO/base.dump"

TAMANO_CRUDO=$(du -m "$TRABAJO/base.dump" | cut -f1)
echo "  volcado: ${TAMANO_CRUDO} MB"
if [ "$TAMANO_CRUDO" -lt 1 ]; then
  echo "  El volcado sale vacío. Algo va mal: se aborta en lugar de guardar una copia inútil." >&2
  exit 4
fi

# ---------------------------------------------------------------------------
# 2. La verificación
# ---------------------------------------------------------------------------
# Es el paso que justifica el script. `pg_restore --list` recorre el índice del archivo; si está
# truncado o corrupto, falla **ahora** y no el día que haga falta restaurarlo.
echo "  verificando el índice…"
if ! "${COMPOSE[@]}" exec -T bd pg_restore --list < "$TRABAJO/base.dump" > "$TRABAJO/indice.txt"; then
  echo "  El volcado no se puede leer: NO se guarda como copia válida." >&2
  exit 4
fi

TABLAS=$(grep -c 'TABLE DATA' "$TRABAJO/indice.txt" || true)
echo "  ${TABLAS} tablas con datos en el índice"
if [ "$TABLAS" -lt 5 ]; then
  echo "  Solo $TABLAS tablas: un esquema vacío no es una copia. Se aborta." >&2
  exit 4
fi

# ---------------------------------------------------------------------------
# 3. Comprimir y cifrar
# ---------------------------------------------------------------------------
if command -v zstd >/dev/null 2>&1; then
  Compresor=(zstd -q -10 -T0 -o "$TRABAJO/base.dump.zst" "$TRABAJO/base.dump")
else
  # `zstd` no está en todas las imágenes. `gzip` comprime peor y tarda más, pero está en todas.
  Compresor=(sh -c "gzip -9 -c '$TRABAJO/base.dump' > '$TRABAJO/base.dump.zst'")
fi
"${Compresor[@]}"

ARCHIVO="$COPIA_DIR/copia-$MARCA"
if [ "$CIFRAR" -eq 1 ]; then
  age --encrypt --recipient "$CLAVE_PUBLICA_AGE" \
      --output "$ARCHIVO$SUFIJO.age" "$TRABAJO/base.dump.zst"
  ARCHIVO="$ARCHIVO$SUFIJO.age"
else
  mv "$TRABAJO/base.dump.zst" "$ARCHIVO$SUFIJO"
  ARCHIVO="$ARCHIVO$SUFIJO"
fi

# Los permisos se ponen a mano porque `umask` de un cron no es el de una sesión interactiva, y una
# copia con datos personales legible por todo el sistema es media brecha.
chmod 600 "$ARCHIVO"

TAMANO=$(du -m "$ARCHIVO" | cut -f1)
echo "  guardada: $(basename "$ARCHIVO") (${TAMANO} MB, ${SECONDS}s)"

# ---------------------------------------------------------------------------
# 4. Las plantillas de Excel
# ---------------------------------------------------------------------------
# Van aparte del volcado porque **no están en la base**: el archivo de cada empresa vive en un
# volumen del servidor y la tabla solo guarda su referencia. Copiar solo PostgreSQL dejaría las
# plantillas fuera de la copia, y perderlas no es irrecuperable —cada empresa tiene su archivo— pero
# sí es pedirle a cada cliente que vuelva a subirlo.
#
# Se archiva **desde dentro del contenedor**, que es el único sitio donde el volumen tiene nombre
# estable: fuera, el nombre real lleva el prefijo del proyecto del compose.
echo "  archivando las plantillas de Excel…"
if "${COMPOSE[@]}" exec -T api tar -czf - -C /app plantillas > "$TRABAJO/plantillas.tar.gz" 2>/dev/null; then
  TAMANO_PLANTILLAS=$(du -m "$TRABAJO/plantillas.tar.gz" | cut -f1)
  ARCHIVO_PLANTILLAS="$COPIA_DIR/plantillas-$MARCA.tar.gz"
  if [ "$CIFRAR" -eq 1 ]; then
    age --encrypt --recipient "$CLAVE_PUBLICA_AGE" \
        --output "$ARCHIVO_PLANTILLAS.age" "$TRABAJO/plantillas.tar.gz"
    ARCHIVO_PLANTILLAS="$ARCHIVO_PLANTILLAS.age"
  else
    mv "$TRABAJO/plantillas.tar.gz" "$ARCHIVO_PLANTILLAS"
  fi
  chmod 600 "$ARCHIVO_PLANTILLAS"
  echo "  plantillas: $(basename "$ARCHIVO_PLANTILLAS") (${TAMANO_PLANTILLAS} MB)"
  if [ -n "$COPIA_REMOTO" ] && command -v rclone >/dev/null 2>&1; then
    rclone copy "$ARCHIVO_PLANTILLAS" "$COPIA_REMOTO" --no-traverse
  fi
else
  echo "  AVISO: no se pudieron archivar las plantillas. ¿Está levantado el servicio api?" >&2
fi

# ---------------------------------------------------------------------------
# 5. Fuera del servidor
# ---------------------------------------------------------------------------
# Una copia que vive solo en el servidor que se está copiando no protege del caso más probable: que
# ese servidor desaparezca. Si `rclone` está configurado, se sube; si no, se avisa **en cada
# ejecución**, porque un aviso que solo sale una vez deja de leerse.
if [ -n "$COPIA_REMOTO" ] && command -v rclone >/dev/null 2>&1; then
  echo "  subiendo a $COPIA_REMOTO…"
  rclone copy "$ARCHIVO" "$COPIA_REMOTO" --no-traverse
elif [ -n "$COPIA_REMOTO" ]; then
  echo "  AVISO: COPIA_REMOTO está definido pero falta 'rclone'. La copia se queda en el servidor."
else
  echo "  AVISO: sin COPIA_REMOTO, esta copia no sale del servidor. Un incendio se lleva las dos."
fi

# ---------------------------------------------------------------------------
# 6. Rotación local
# ---------------------------------------------------------------------------
# El almacén de objetos guarda el histórico; en el servidor solo hacen falta los últimos días. Se
# borra por antigüedad y con la fecha del **nombre**, no la del sistema de archivos: un archivo
# copiado con `cp` de un sitio a otro tendría una fecha que no es la de la copia.
# Se usa `if` y no `[ ... ] && echo`, que es la forma habitual de escribirlo y aquí **rompería el
# script**: bajo `set -e`, una condición falsa al final de una línea se convierte en el código de
# salida del comando compuesto, y el script terminaría con error precisamente el día en que la
# rotación no tiene nada que borrar —que es el caso normal—. Un cron que devuelve error todas las
# noches es un cron que se acaba silenciando, y con él los avisos que sí importan.
BORRADAS=$(find "$COPIA_DIR" -maxdepth 1 -name 'copia-*' -type f -mtime "+$COPIA_DIAS" -print -delete | wc -l)
if [ "$BORRADAS" -gt 0 ]; then
  echo "  rotación: $BORRADAS copia(s) de más de $COPIA_DIAS días borradas"
fi

# Las plantillas se rotan con el mismo criterio. Se borran por separado para que el recuento de
# arriba siga significando «copias de la base», que es lo que alguien espera leer ahí.
find "$COPIA_DIR" -maxdepth 1 -name 'plantillas-*' -type f -mtime "+$COPIA_DIAS" -delete

RESTANTES=$(find "$COPIA_DIR" -maxdepth 1 -name 'copia-*' -type f | wc -l)
echo "[$(date +%H:%M:%S)] Hecho. $RESTANTES copia(s) en $COPIA_DIR"
