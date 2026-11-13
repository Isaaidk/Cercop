# Salida a Ecuador desde casas (alta disponibilidad)

## Por qué hace falta

El portal de compras públicas (`www.compraspublicas.gob.ec`) **no responde a las IP de Railway**.
Se comprobó el 2026-11-13 con `GET /v1/plataforma/salida-portal` (solo superadmin): desde Railway
las páginas del portal no contestan en 15 s; desde Ecuador y desde otros centros de datos, sí. Los
**datos abiertos** (OCDS) sí responden a Railway. Sin una salida que no sea de Railway, el worker
no lee necesidades nuevas ni baja TDR.

## Las dos clases de salida, y cómo se combinan

| Salida | Variable del worker | Cuándo |
|---|---|---|
| Proxy fijo (VPS en Ecuador, `deploy/proxy-ecuador/instalar.sh`) | `NCO_PROXY_URLS=http://usuario:clave@IP:3128` | Base estable, 24/7 |
| Dispositivos de casa por Tailscale | `TAILSCALE_AUTHKEY` + `TAILSCALE_EXIT_NODES=100.x.y.z,100.a.b.c` | Respaldo, o salida principal sin VPS |

`start.sh` **suma** las dos: abre un túnel por cada dispositivo y lo añade a los proxies fijos. El
worker (`salidas.py`) reparte las peticiones por menor carga; una salida que falla 3 veces seguidas
descansa 2 minutos y el trabajo sigue por las demás. Con dos casas y un VPS, se cae una casa y
nadie lo nota.

## Qué dispositivo usar en cada casa

Tiene que estar **encendido siempre**, conectado por cable si se puede, y gastar poca luz.

| Dispositivo | Consumo | Notas |
|---|---|---|
| Raspberry Pi 4/5 (o similar) | ~5 W | La mejor opción. Con cable de red y fuente oficial. |
| Router con Tailscale (p. ej. GL.iNet) | ya está encendido | Sirve de nodo de salida sin otro aparato. |
| Mini PC o portátil viejo con Linux | 10–20 W | Desactivar suspensión. |
| PC con Windows encendido | 50 W+ | Funciona, pero se apaga, se actualiza y se reinicia. |
| TV box / teléfono Android viejo enchufado | ~3 W | La app de Tailscale permite «Run as exit node». Menos estable. |

No sirven los teléfonos de uso diario: se apagan, cambian de red y ahorran batería cortando la app.

## Paso a paso en cada dispositivo

1. **Instalar Tailscale** (`curl -fsSL https://tailscale.com/install.sh | sh` en Linux/Raspberry; el
   instalador oficial en Windows/Android) y entrar con **la misma cuenta** de Tailscale que usa el
   worker.
2. **Linux / Raspberry: permitir reenvío de tráfico**
   ```bash
   echo 'net.ipv4.ip_forward = 1' | sudo tee /etc/sysctl.d/99-tailscale.conf
   echo 'net.ipv6.conf.all.forwarding = 1' | sudo tee -a /etc/sysctl.d/99-tailscale.conf
   sudo sysctl -p /etc/sysctl.d/99-tailscale.conf
   ```
3. **Anunciarlo como nodo de salida**
   - Linux: `sudo tailscale up --advertise-exit-node`
   - Windows / Android: en la app, «Run as exit node».
4. **Aprobarlo** en la consola de Tailscale: *Machines* → el dispositivo → *Edit route settings* →
   marcar *Use as exit node*. En el mismo menú: **Disable key expiry** (si no, a los 180 días deja de
   funcionar sin avisar).
5. **Anotar su IP de Tailscale** (`100.x.y.z`, columna *Addresses*).
6. **Arranque automático**: en Linux, `sudo systemctl enable --now tailscaled`; en Windows, la app
   arranca con el sistema; en el router, activar Tailscale en su panel.

## En Railway (servicio `worker`)

- `TAILSCALE_EXIT_NODES` = las IP `100.x` de todos los dispositivos, separadas por coma.
- `TAILSCALE_AUTHKEY` = una clave **reutilizable, efímera y con etiqueta** `tag:railway` (consola de
  Tailscale → *Settings* → *Keys*). Efímera: los contenedores viejos desaparecen del tailnet solos.
- Si además hay VPS: `NCO_PROXY_URLS` con su URL. Se suman.
- Se puede dejar de usar `TAILSCALE_EXIT_NODE_IP` (una sola salida): `TAILSCALE_EXIT_NODES` la reemplaza.

Comprobar: en los logs del worker sale «Túneles listos. Salidas del worker: …» (con las claves
tapadas) y luego peticiones `NCORegistroDetalle.cpe … 200`.

## Seguridad: que Railway no pueda entrar a la red de tu casa

Un nodo de salida da internet, pero por defecto el tailnet deja que sus miembros se vean entre sí.
**Hay que limitar al worker a salir a internet**, sin acceso a los equipos de la casa. En la consola
de Tailscale → *Access controls*, una política mínima:

```json
{
  "tagOwners": { "tag:railway": ["autogroup:admin"] },
  "acls": [
    { "action": "accept", "src": ["tag:railway"], "dst": ["autogroup:internet:*"] },
    { "action": "accept", "src": ["autogroup:member"], "dst": ["*:*"] }
  ]
}
```

- `tag:railway` solo llega a internet a través de los nodos de salida: ni a los dispositivos ni a la
  red local de la casa (impresoras, cámaras, router).
- En cada dispositivo de casa, **no** activar «Allow LAN access» para otros, ni compartir subredes
  (`--advertise-routes`) salvo que se sepa para qué.
- Revocar en la consola cualquier clave o máquina que ya no se use.

## Cuánto internet consume

Poco: una ficha del portal pesa decenas de KB y un TDR medio ~0,5 MB. Con cientos de ínfimas al día
son del orden de 1–3 GB al mes, repartidos entre las salidas. No se nota en un plan de hogar.

## Lo que hay que tener en cuenta

- **Permiso de cada dueño de casa**: el portal verá su IP haciendo estas consultas. Pedirlo por
  escrito.
- **Velocidad del portal (429)**: el SERCOP limita las peticiones por IP. Más casas = más margen,
  porque el worker reparte.
- **Internet con CGNAT** (muy común en Ecuador): no importa; Tailscale atraviesa el CGNAT y no hace
  falta abrir puertos en el router. Si no hay conexión directa usa sus relés (algo más lento, pero
  funciona).
- **Si se cae una casa**: el worker la enfría y sigue con las demás. Si se caen todas y no hay VPS,
  no se leen fichas ni TDR hasta que vuelva una; el resto del aplicativo sigue funcionando.
- **Recomendación**: 1 VPS en Ecuador como base + 1 o 2 casas de respaldo. Solo casas también
  funciona, con al menos 2 para no depender de una.
