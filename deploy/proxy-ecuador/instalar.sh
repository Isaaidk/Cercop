#!/usr/bin/env bash
# Proxy de salida en Ecuador para el worker de CercoApp.
#
# Por qué: el portal de compras públicas (www.compraspublicas.gob.ec) no responde a las IP de
# Railway (comprobado con GET /v1/plataforma/salida-portal: se queda colgado), así que el worker no
# puede leer necesidades ni bajar TDR desde allí. Un VPS en Ecuador con este proxy le da una IP
# ecuatoriana fija, encendida 24/7, sin depender de ningún PC.
#
# Uso, en un VPS nuevo con Ubuntu 22.04 o 24.04 (como root). Sirve también una VM gratis de Oracle
# Cloud «Always Free» (región Bogotá): abrir antes TCP 3128 en la Security List de la VCN.
#     curl -fsSL <url-de-este-archivo> -o instalar.sh   (o copiarlo a mano)
#     bash instalar.sh
#
# Al terminar imprime la línea NCO_PROXY_URLS=... que se pega en el servicio `worker` de Railway.
#
# Seguridad: el proxy exige usuario y clave, y aunque alguien la consiguiera solo sirve para llegar
# a *.compraspublicas.gob.ec por el puerto 443/80. No es un proxy abierto.
set -euo pipefail

PUERTO="${PUERTO:-3128}"
USUARIO="cerco"

if [ "$(id -u)" -ne 0 ]; then
    echo "Ejecútalo como root (sudo bash instalar.sh)." >&2
    exit 1
fi

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq squid apache2-utils ufw openssl >/dev/null

CLAVE="$(openssl rand -base64 36 | tr -dc 'A-Za-z0-9' | head -c 40)"
htpasswd -bcB /etc/squid/cerco.passwd "$USUARIO" "$CLAVE" >/dev/null
chown proxy:proxy /etc/squid/cerco.passwd
chmod 640 /etc/squid/cerco.passwd

BASICO="$(ls /usr/lib/squid/basic_ncsa_auth 2>/dev/null || ls /usr/lib/squid3/basic_ncsa_auth)"

cat >/etc/squid/squid.conf <<EOF
http_port ${PUERTO}

auth_param basic program ${BASICO} /etc/squid/cerco.passwd
auth_param basic realm cerco
auth_param basic credentialsttl 8 hours
acl autenticado proxy_auth REQUIRED

# Solo el portal de compras públicas y sus subdominios.
acl portal dstdomain .compraspublicas.gob.ec
acl puertos_ok port 80 443
acl SSL_ports port 443
acl CONNECT method CONNECT

http_access deny !puertos_ok
http_access deny CONNECT !SSL_ports
http_access allow autenticado portal
http_access deny all

# Sin caché ni cabeceras que delaten el proxy.
cache deny all
forwarded_for delete
via off
request_header_access X-Forwarded-For deny all

# Bajadas de TDR de hasta 25 MB y fichas lentas del portal.
read_timeout 2 minutes
connect_timeout 30 seconds
access_log daemon:/var/log/squid/access.log squid
EOF

squid -k parse >/dev/null 2>&1
systemctl enable squid >/dev/null 2>&1
systemctl restart squid

# Oracle Cloud: sus imágenes de Ubuntu traen reglas de iptables propias que rechazan todo menos SSH
# (y además hay que abrir el puerto en la «Security List» de la VCN, desde la consola de Oracle).
# Se inserta la regla antes de su REJECT y se guarda para que sobreviva al reinicio.
if iptables -S INPUT 2>/dev/null | grep -q "REJECT"; then
    iptables -I INPUT 5 -p tcp -m state --state NEW --dport "${PUERTO}" -j ACCEPT
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save >/dev/null 2>&1 || true
    fi
    echo "Reglas de iptables (Oracle) ajustadas para el puerto ${PUERTO}."
else
    ufw allow OpenSSH >/dev/null
    ufw allow "${PUERTO}/tcp" >/dev/null
    ufw --force enable >/dev/null
fi

IP="$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')"

echo
echo "Comprobando que el portal responde a través del proxy…"
if curl -fsS -o /dev/null -m 30 -x "http://${USUARIO}:${CLAVE}@127.0.0.1:${PUERTO}" \
    https://www.compraspublicas.gob.ec/ProcesoContratacion/compras/NCO/FrmNCOListado.cpe; then
    echo "  OK: el portal responde desde este servidor."
else
    echo "  AVISO: el portal no respondió desde este servidor. Revisa que el VPS esté en Ecuador." >&2
fi

echo
echo "Listo. En Railway → servicio worker → Variables, añade (y guarda en un gestor de claves):"
echo
echo "    NCO_PROXY_URLS=http://${USUARIO}:${CLAVE}@${IP}:${PUERTO}"
echo
echo "Con esa variable el worker ya no levanta Tailscale. Esta clave no se vuelve a mostrar."
