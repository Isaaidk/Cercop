#!/bin/sh
# Arranque del contenedor con la salida de NCO por un túnel de Tailscale.
#
# Para qué existe
# ---------------
# El servidor del listado de necesidades (`www.compraspublicas.gob.ec`) descarta en silencio las
# conexiones que llegan de centros de datos: el proceso se queda dos minutos esperando y termina con
# `ConnectTimeout`, sin que el portal llegue a ver la petición. No es un problema del código ni del
# tiempo de espera, y cambiar de región no lo arregla.
#
# La salida es hablarle a ese servidor desde una conexión que el portal acepte. Este guion levanta
# Tailscale en modo espacio de usuario, sale por un nodo externo —un móvil con datos de Ecuador— y
# deja un **proxy HTTP local** en `localhost:1055` por el que solo sale la fuente NCO.
#
# Uso desde el servicio `worker` de Railway (Custom Start Command):
#
#     sh /app/start.sh python -m contratacion.tareas.worker
#
# Y desde el `api`, si algún día lo necesitara:
#
#     sh /app/start.sh sh -c "alembic upgrade head && exec uvicorn contratacion.asgi:app …"
#
# Variables que espera (secrets del servicio, NUNCA escritas aquí):
#
#   TAILSCALE_AUTHKEY        clave de autenticación del tailnet
#   TAILSCALE_EXIT_NODE_IP   IP de Tailscale del nodo de salida (`100.x.y.z`)
#   TAILSCALE_HOSTNAME       opcional, por defecto `railway-worker`
#
# Y una advertencia sobre la clave: las de Tailscale **caducan** (90 días por defecto). Si caduca,
# el túnel deja de levantarse y el worker se queda sin NCO. Conviene crearla sin caducidad o
# acordarse de rotarla.

set -eu

ESTADO=/tmp/tailscaled.state
SOCKET=/tmp/tailscaled.sock
PROXY=localhost:1055

# Las rutas no son las de por defecto a propósito. `tailscaled` guarda su estado en
# `/var/lib/tailscale` y abre el socket en `/var/run/tailscale`, y ninguna de las dos es escribible
# por el usuario `app` con el que corre el contenedor. Sin esto, el demonio no arranca y el fallo
# aparece como un problema de permisos que no tiene nada que ver con el portal.

_tunel() {
    if [ -z "${TAILSCALE_AUTHKEY:-}" ] || [ -z "${TAILSCALE_EXIT_NODE_IP:-}" ]; then
        echo "Sin TAILSCALE_AUTHKEY o TAILSCALE_EXIT_NODE_IP: se arranca sin túnel."
        return 0
    fi

    echo "Levantando el demonio de Tailscale…"
    tailscaled \
        --tun=userspace-networking \
        --state="$ESTADO" \
        --socket="$SOCKET" \
        --outbound-http-proxy-listen="$PROXY" &

    # Se espera al socket, no a un `sleep` fijo: en una máquina fría el demonio tarda más y el
    # `tailscale up` de después fallaría con «no se puede conectar con tailscaled», que es un error
    # que apunta al sitio equivocado.
    intentos=0
    while [ ! -S "$SOCKET" ]; do
        intentos=$((intentos + 1))
        if [ "$intentos" -ge 30 ]; then
            echo "El demonio no abrió el socket en 15 s: se arranca sin túnel." >&2
            return 0
        fi
        sleep 0.5
    done

    echo "Conectando al tailnet y fijando la salida por ${TAILSCALE_EXIT_NODE_IP}…"
    # `--accept-dns=false` no es opcional aquí: por defecto Tailscale intenta reescribir
    # `/etc/resolv.conf`, y el contenedor corre sin privilegios. El portal es un nombre público y se
    # resuelve por el DNS normal, así que no se pierde nada.
    if ! tailscale --socket="$SOCKET" up \
        --authkey="${TAILSCALE_AUTHKEY}" \
        --exit-node="${TAILSCALE_EXIT_NODE_IP}" \
        --hostname="${TAILSCALE_HOSTNAME:-railway-worker}" \
        --accept-dns=false; then
        echo "No se pudo conectar al tailnet: se arranca SIN túnel." >&2
        return 0
    fi

    # Esta línea es la que hace que todo lo anterior sirva de algo. El túnel por sí solo no cambia
    # nada: hay que decirle al cliente HTTP que salga por el proxy local. Sin ella, el worker sigue
    # yendo directo y NCO sigue fallando igual, con el túnel levantado y sin usar.
    #
    # Solo se exporta `NCO_PROXY_URL` y no `HTTPS_PROXY` a propósito: OCDS entra perfectamente sin
    # proxy, y hacerlo pasar por el móvil gastaría datos y añadiría latencia para nada.
    export NCO_PROXY_URL="http://${PROXY}"
    echo "Túnel listo. NCO saldrá por ${NCO_PROXY_URL}."
}

_tunel

if [ "$#" -eq 0 ]; then
    set -- python -m contratacion.tareas.worker
fi

echo "Iniciando: $*"
# `exec` para que el proceso sustituya al guion: así recibe las señales de parada del contenedor
# —que es lo que hace que Railway pueda reiniciarlo limpiamente— y no queda un `sh` en medio.
exec "$@"
