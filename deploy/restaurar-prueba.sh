#!/usr/bin/env bash
#
# Restauración de prueba: **demuestra** que la copia se puede abrir.
#
# Por qué esto es un archivo aparte y no un párrafo en la documentación
# -------------------------------------------------------------------
# Una copia que nunca se ha restaurado no es una copia: es un archivo del que se *supone* algo. Y el
# modo de fallo es silencioso —el cifrado funciona, el tamaño parece razonable, el nombre lleva la
# fecha— hasta el día en que hace falta de verdad, que es el peor día para descubrirlo.
#
# Este script levanta un PostgreSQL desechable, restaura ahí la copia más reciente y compara los
# recuentos con la base viva. Si algo no cuadra, se ve ahora.
#
# Criterio de comparación, y por qué no es «que coincidan»
# -------------------------------------------------------
# `registro` recibe contrataciones de SERCOP cada quince minutos, así que una copia de esta madrugada
# **nunca** tendrá las mismas filas que la base de ahora. Exigir igualdad daría un fallo permanente y
# el script se acabaría ignorando, que es la forma habitual en que una comprobación deja de servir.
#
# Lo que sí se exige: que ninguna tabla que tiene datos en la base esté **vacía** en la copia. Eso es
# lo que detecta un volcado truncado, una tabla saltada o una restauración parcial. Las diferencias
# de recuento se informan, y quien mira decide si son del tamaño esperado.
#
# Uso:
#   deploy/restaurar-prueba.sh                        la copia más reciente
#   deploy/restaurar-prueba.sh ruta/a/copia.dump.zst.age

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$RAIZ/deploy/docker-compose.yml" --env-file "$RAIZ/.env")

leer_del_entorno() {
  local clave="$1" por_defecto="${2:-}"
  local valor
  valor="$(grep -E "^${clave}=" "$RAIZ/.env" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  valor="${valor%\"}"; valor="${valor#\"}"
  valor="${valor%\'}"; valor="${valor#\'}"
  printf '%s' "${valor:-$por_defecto}"
}

BD_USUARIO="$(leer_del_entorno BD_USUARIO contratacion)"
BD_NOMBRE="$(leer_del_entorno BD_NOMBRE contratacion)"
COPIA_DIR="$(leer_del_entorno COPIA_DIR "$RAIZ/deploy/copias")"

# Tablas que se comparan. No son todas: son las que, si faltaran, significarían que la copia no
# sirve. `registro` es el histórico; las demás son lo que **no** se puede volver a ingerir desde
# SERCOP, y por eso son las que de verdad importan.
TABLAS=(registro negocio usuario sesion termino acceso_vista)

if [ "${1:-}" != "" ]; then
  COPIA="$1"
else
  COPIA="$(find "$COPIA_DIR" -maxdepth 1 -name 'copia-*' -type f | sort | tail -n1)"
fi

if [ ! -f "$COPIA" ]; then
  echo "No hay ninguna copia que restaurar en $COPIA_DIR." >&2
  exit 2
fi

echo "Copia a probar: $(basename "$COPIA") ($(du -m "$COPIA" | cut -f1) MB)"

TRABAJO="$(mktemp -d)"
CONTENEDOR="prueba-restauracion-$$"

limpiar() {
  docker rm -f "$CONTENEDOR" >/dev/null 2>&1 || true
  rm -rf "$TRABAJO"
}
trap limpiar EXIT

# ---------------------------------------------------------------------------
# 1. Abrir la copia
# ---------------------------------------------------------------------------
# El descifrado y la descompresión se prueban aquí, que es la mitad del valor de este script: una
# clave privada `age` equivocada, o una clave pública con la que se cifró algo que ya no se puede
# abrir, se descubre en este paso y no en el peor momento.
case "$COPIA" in
  *.age)
    if ! command -v age >/dev/null 2>&1; then
      echo "La copia está cifrada y falta 'age'. En Debian/Ubuntu:  apt install age" >&2
      exit 3
    fi
    IDENTIDAD="${CLAVE_PRIVADA_AGE:-$RAIZ/deploy/clave-copias.txt}"
    if [ ! -f "$IDENTIDAD" ]; then
      echo "Falta la clave privada de age en $IDENTIDAD." >&2
      echo "Sin ella la copia no se puede abrir, y eso es exactamente lo que este script viene a comprobar." >&2
      exit 3
    fi
    echo "  descifrando…"
    age --decrypt --identity "$IDENTIDAD" "$COPIA" > "$TRABAJO/base.dump.zst"
    ;;
  *)
    cp "$COPIA" "$TRABAJO/base.dump.zst"
    ;;
esac

if command -v zstd >/dev/null 2>&1 && zstd --test -q "$TRABAJO/base.dump.zst" >/dev/null 2>&1; then
  zstd -q -d -o "$TRABAJO/base.dump" "$TRABAJO/base.dump.zst"
else
  gzip -d -c "$TRABAJO/base.dump.zst" > "$TRABAJO/base.dump"
fi
echo "  descomprimida: $(du -m "$TRABAJO/base.dump" | cut -f1) MB"

# ---------------------------------------------------------------------------
# 2. Un PostgreSQL desechable
# ---------------------------------------------------------------------------
# Se levanta **sin publicar puertos y sin volumen**: es una caja que se tira al terminar. Si algo
# saliera mal, no puede tocar la base de verdad ni dejar restos.
echo "  levantando un PostgreSQL desechable…"
docker run -d --name "$CONTENEDOR" \
  -e POSTGRES_PASSWORD=prueba \
  -e POSTGRES_DB="$BD_NOMBRE" \
  postgres:17-alpine >/dev/null

for intento in $(seq 1 60); do
  if docker exec "$CONTENEDOR" pg_isready -U postgres -d "$BD_NOMBRE" >/dev/null 2>&1; then
    break
  fi
  if [ "$intento" -eq 60 ]; then
    echo "El PostgreSQL de prueba no arrancó." >&2
    exit 4
  fi
  sleep 1
done

# ---------------------------------------------------------------------------
# 3. Restaurar
# ---------------------------------------------------------------------------
# `--no-owner` porque en la caja desechable no existen los roles del servidor de verdad, y lo que se
# comprueba aquí son **los datos**, no a quién pertenecen los objetos. `--exit-on-error` es lo
# contrario de lo habitual y es lo correcto en una prueba: un error que se ignora convertiría este
# script en una ceremonia que siempre dice que todo va bien.
echo "  restaurando…"
docker cp "$TRABAJO/base.dump" "$CONTENEDOR:/tmp/base.dump" >/dev/null
if ! docker exec "$CONTENEDOR" pg_restore \
      --username postgres \
      --dbname "$BD_NOMBRE" \
      --no-owner --no-privileges \
      --exit-on-error \
      /tmp/base.dump 2>"$TRABAJO/errores.txt"; then
  echo "LA RESTAURACIÓN HA FALLADO. La copia NO sirve:" >&2
  head -n 20 "$TRABAJO/errores.txt" >&2
  exit 5
fi

# ---------------------------------------------------------------------------
# 4. Comparar
# ---------------------------------------------------------------------------
# Los recuentos se piden de dos formas distintas y no es un capricho: contra la base viva hay que
# pasar por `docker compose exec`, porque el nombre real del contenedor lleva el prefijo del
# proyecto (`contratacion-bd-1`) y un `docker exec bd` fallaría con «no such container».
#
# `tr -d '[:space:]'` limpia el salto de línea de `psql`, que si no rompe las comparaciones
# aritméticas de más abajo con un «integer expression expected» que no dice nada.
contar_en_copia() {
  docker exec "$CONTENEDOR" psql --username postgres --dbname "$BD_NOMBRE" \
    --tuples-only --no-align --command "SELECT count(*) FROM $1" 2>/dev/null | tr -d '[:space:]'
}

contar_en_viva() {
  "${COMPOSE[@]}" exec -T bd psql --username "$BD_USUARIO" --dbname "$BD_NOMBRE" \
    --tuples-only --no-align --command "SELECT count(*) FROM $1" 2>/dev/null | tr -d '[:space:]'
}

echo
printf '%-18s %10s %10s %10s\n' "tabla" "copia" "viva" "diferencia"
FALLOS=0
for tabla in "${TABLAS[@]}"; do
  en_copia="$(contar_en_copia "$tabla")"
  en_viva="$(contar_en_viva "$tabla")"

  if [ -z "$en_copia" ]; then
    printf '%-18s %10s %10s %10s\n' "$tabla" "AUSENTE" "$en_viva" "-"
    echo "  La tabla «$tabla» no existe en la copia."
    FALLOS=$((FALLOS + 1))
    continue
  fi

  if [ -z "$en_viva" ]; then
    printf '%-18s %10s %10s %10s\n' "$tabla" "$en_copia" "SIN DATO" "-"
    echo "  No se pudo contar «$tabla» en la base viva. ¿Está levantado el despliegue?"
    FALLOS=$((FALLOS + 1))
    continue
  fi

  diferencia=$((en_viva - en_copia))
  printf '%-18s %10s %10s %10s\n' "$tabla" "$en_copia" "$en_viva" "+$diferencia"

  # La comprobación de verdad: una tabla con datos en la base no puede estar vacía en la copia.
  if [ "$en_viva" -gt 0 ] && [ "$en_copia" -eq 0 ]; then
    echo "  La tabla «$tabla» tiene $en_viva filas en la base y 0 en la copia."
    FALLOS=$((FALLOS + 1))
  fi
  if [ "$diferencia" -lt 0 ]; then
    echo "  La copia tiene MÁS filas que la base: eso no puede pasar. Algo se cruzó."
    FALLOS=$((FALLOS + 1))
  fi
done

echo
if [ "$FALLOS" -eq 0 ]; then
  echo "CORRECTO: la copia se abre, se restaura y tiene los datos que debe tener."
  echo "Las diferencias de recuento son las contrataciones ingeridas desde el volcado."
else
  echo "HAY $FALLOS PROBLEMA(S). Esa copia no se puede dar por buena." >&2
  exit 6
fi
