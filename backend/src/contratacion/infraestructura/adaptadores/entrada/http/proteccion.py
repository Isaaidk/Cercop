"""Cabeceras de seguridad, freno por IP y tope de cuerpo en las puertas de entrada.

El bloqueo por cuenta ya frena a quien prueba contraseñas contra un correo. Este freno cubre al que
prueba muchos correos desde la misma IP y al que crea cuentas en serie. Vive en memoria de cada
proceso: con varios procesos de API el tope efectivo es el de cada uno multiplicado por los
procesos, y sigue cortando un ataque automatizado.

La IP sale de `ip_cliente`, que es la única función que decide quién es «quien llama». Ver allí por
qué no se puede fiar de la primera dirección de `X-Forwarded-For` (auditoría de seguridad, doc 38).
"""

from __future__ import annotations

import ipaddress
import itertools
import json
import os
import time
from collections import deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from contratacion.dominio.politicas import POLITICAS_PUBLICAS

# Ruta y método → (peticiones, segundos).
_LIMITES: dict[tuple[str, str], tuple[int, int]] = {
    ("POST", "/v1/auth/sesion"): (20, 300),
    # La ruta real del alta es `/v1/registro/empresa`: la clave anterior, `/v1/registro`, no
    # coincidía con ninguna ruta y el registro quedaba sin freno.
    ("POST", "/v1/registro/empresa"): (5, 3600),
    # Respaldo público de la consulta al SRI del formulario de registro.
    ("POST", "/v1/registro/consulta-ruc"): (20, 600),
    # Las rutas de la oferta ya no están aquí: su tope es por persona (`limites.py`). Una IP puede
    # ser una oficina entera, y con tope por IP se acaba el cupo de todos a la vez.
    ("POST", "/v1/ia/compras"): (10, 3600),
    # Lectura pública de los textos legales (`/terminos`, `/privacidad`). Holgado para quien los lee
    # —son dos textos que no cambian—, y corto para quien los pidiera en bucle. Una entrada por tipo
    # porque la tabla compara la ruta exacta; salen de la misma tupla que usa el enrutador.
    **{("GET", f"/v1/politicas/publicas/{tipo}"): (60, 600) for tipo in POLITICAS_PUBLICAS},
}
_TOPE_IPS = 50_000

_CABECERAS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

# Política de contenido de las respuestas JSON: no cargan nada ni se dejan enmarcar.
CSP_API = "default-src 'none'; frame-ancestors 'none'"


class FrenoPorIp:
    def __init__(self) -> None:
        self._marcas: dict[tuple[str, str, str], deque[float]] = {}

    def permite(self, clave: tuple[str, str, str], tope: int, ventana: int) -> int:
        """0 si pasa; si no, los segundos que faltan para que vuelva a pasar."""
        ahora = time.monotonic()
        if len(self._marcas) > _TOPE_IPS:
            self._podar(ahora, ventana)
        # Se saca y se vuelve a meter para que el diccionario quede ordenado por último uso: la
        # poda quita por el principio, y ahí tienen que estar las claves olvidadas, no la del que
        # sigue probando.
        marcas = self._marcas.pop(clave, None) or deque()
        self._marcas[clave] = marcas
        while marcas and ahora - marcas[0] > ventana:
            marcas.popleft()
        if len(marcas) >= tope:
            return max(1, int(ventana - (ahora - marcas[0])))
        marcas.append(ahora)
        return 0

    def _podar(self, ahora: float, ventana: int) -> None:
        """Libera memoria sin regalar intentos a nadie.

        Antes se vaciaba el diccionario entero al pasar del tope, y eso era una puerta: quien lo
        llenara con cincuenta mil claves —IPv6 da direcciones de sobra— borraba también las marcas
        de la IP que estaba atacando y volvía a empezar de cero. Ahora se quitan primero las claves
        sin marcas vigentes y, si aún sobra, las de uso más lejano: la IP que está probando
        contraseñas ahora mismo es justo la que se usó la última.
        """
        caducadas = [c for c, m in self._marcas.items() if not m or ahora - m[-1] > ventana]
        for clave in caducadas:
            del self._marcas[clave]
        exceso = len(self._marcas) - _TOPE_IPS // 2
        if exceso > 0:
            for clave in list(itertools.islice(self._marcas, exceso)):
                del self._marcas[clave]


def ip_cliente(peticion: Request, saltos: int | None = None) -> str:
    """IP de quien llama, sin dejar que la elija quien llama.

    El despliegue en Railway arranca uvicorn con `--forwarded-allow-ips '*'`. Con eso uvicorn pone
    en `client.host` la **primera** dirección de `X-Forwarded-For`, que es la que escribe el
    cliente: cambiándola en cada intento se esquivaba el freno de inicio de sesión y de registro, y
    la IP que se guardaba en la sesión y en la aceptación de los términos era la que el cliente
    quisiera.

    La dirección fiable es la que añade **el último proxy de confianza**, que siempre va al final
    de la cabecera. `PROXY_SALTOS` dice cuántos proxys propios hay delante de la API: con `1`
    (Railway, o Caddy en el `docker-compose`) se toma la última; con `0` —el valor por defecto, lo
    correcto sin proxy delante— la cabecera se ignora y se usa la conexión directa.
    """
    cliente = getattr(peticion, "client", None)
    directa = str(cliente.host) if cliente and cliente.host else "desconocida"
    if saltos is None:
        saltos = _saltos_de(peticion)
    if saltos <= 0:
        return directa
    cabeceras = getattr(peticion, "headers", None)
    if cabeceras is None:
        return directa
    partes = [
        parte.strip()
        for valor in cabeceras.getlist("x-forwarded-for")
        for parte in valor.split(",")
        if parte.strip()
    ]
    if len(partes) < saltos:
        return directa
    try:
        return str(ipaddress.ip_address(partes[-saltos]))
    except ValueError:
        return directa


def _saltos_de(peticion: Request) -> int:
    """`PROXY_SALTOS` de los ajustes de la aplicación, o 0 si la petición no los trae."""
    ajustes = getattr(getattr(getattr(peticion, "app", None), "state", None), "ajustes", None)
    return int(getattr(ajustes, "proxy_saltos", 0) or 0)


def clave_de_ip(ip: str) -> str:
    """Llave del freno para una IP. Una IPv6 cuenta por su red /64.

    Una sola conexión doméstica recibe una red /64 entera: más direcciones de las que nadie puede
    gastar. Contar cada una por separado dejaría probar contraseñas sin fin desde la misma casa.
    """
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(direccion, ipaddress.IPv6Address):
        if direccion.ipv4_mapped is not None:
            return str(direccion.ipv4_mapped)
        return str(ipaddress.ip_network(f"{direccion}/64", strict=False))
    return str(direccion)


def ips_exentas() -> frozenset[str]:
    """IP que no pasan por el freno: solo para una prueba de carga, y se quitan al terminar.

    `FRENO_IPS_EXENTAS=203.0.113.7,198.51.100.2`. Vacía por defecto. Existe porque la preparación
    de la prueba inicia sesión con cientos de cuentas desde una sola máquina, y el freno —20 inicios
    por IP cada 5 minutos— la cortaría en la cuenta 21.
    """
    crudas = os.getenv("FRENO_IPS_EXENTAS", "")
    return frozenset(ip.strip() for ip in crudas.split(",") if ip.strip())


def crear_proteccion(
    *, produccion: bool, exentas: frozenset[str] | None = None, saltos: int = 0
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    freno = FrenoPorIp()
    sin_freno = ips_exentas() if exentas is None else exentas

    async def proteger(
        peticion: Request, siguiente: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        ruta = peticion.url.path.rstrip("/")
        limite = _LIMITES.get((peticion.method, ruta))
        if limite:
            ip = ip_cliente(peticion, saltos)
            if ip not in sin_freno:
                # La llave lleva la ruta normalizada: con la cruda, `/v1/auth/sesion/` contaba
                # aparte de `/v1/auth/sesion`.
                espera = freno.permite((peticion.method, ruta, clave_de_ip(ip)), *limite)
                if espera:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": f"Demasiados intentos. Vuelve a probar en {espera} segundos.",
                            "codigo": "demasiados_intentos",
                        },
                        headers={"Retry-After": str(espera), **_CABECERAS},
                    )
        respuesta = await siguiente(peticion)
        for nombre, valor in _CABECERAS.items():
            respuesta.headers.setdefault(nombre, valor)
        respuesta.headers.setdefault("Cache-Control", "no-store")
        # La política de contenido va solo en las respuestas JSON, que son las de la API y nunca
        # deben ejecutarse ni enmarcarse. Los PDF y Word que se descargan no la llevan, porque
        # `default-src 'none'` deja en blanco el visor de PDF de algunos navegadores, y `/docs`
        # (solo fuera de producción) tampoco, porque carga sus scripts de un CDN.
        if respuesta.headers.get("content-type", "").startswith("application/json"):
            respuesta.headers.setdefault("Content-Security-Policy", CSP_API)
        if produccion:
            respuesta.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return respuesta

    return proteger


class LimiteDeCuerpo:
    """Tope de tamaño del cuerpo de **cualquier** petición, antes de que nadie lo lea.

    Los topes de cada ruta (8 MB del RUP, 64 KB del certificado…) se comprueban cuando el archivo
    ya está recibido: Starlette guarda en disco las partes de un formulario antes de llamar a la
    ruta, así que un cuerpo de varios gigas llenaba el disco del contenedor aunque la ruta lo
    rechazara después. Este middleware corta en cuanto la cuenta pasa del tope, tanto si el
    cliente declara `Content-Length` como si manda el cuerpo por trozos.
    """

    def __init__(self, app: ASGIApp, *, maximo_bytes: int) -> None:
        self._app = app
        self._maximo = maximo_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._maximo <= 0:
            await self._app(scope, receive, send)
            return

        declarado = _content_length(scope)
        if declarado is not None and declarado > self._maximo:
            await _responder_413(send, self._maximo)
            return

        recibidos = 0
        empezada = False

        async def recibir() -> Message:
            nonlocal recibidos
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                recibidos += len(mensaje.get("body", b""))
                if recibidos > self._maximo:
                    # `HTTPException` y no otra: FastAPI convierte cualquier otro fallo al leer el
                    # cuerpo en un 400 genérico, y este caso tiene su propio código.
                    raise HTTPException(status_code=413, detail=_mensaje_413(self._maximo))
            return mensaje

        async def enviar(mensaje: Message) -> None:
            nonlocal empezada
            if mensaje["type"] == "http.response.start":
                empezada = True
            await send(mensaje)

        try:
            await self._app(scope, recibir, enviar)
        except HTTPException as error:
            if error.status_code != 413 or empezada:
                raise
            await _responder_413(send, self._maximo)


def _content_length(scope: Scope) -> int | None:
    for nombre, valor in scope.get("headers") or ():
        if nombre == b"content-length":
            try:
                return int(valor)
            except ValueError:
                return None
    return None


def _mensaje_413(maximo: int) -> str:
    return f"La petición pasa del máximo de {max(1, maximo // (1024 * 1024))} MB."


async def _responder_413(send: Send, maximo: int) -> None:
    cuerpo = json.dumps(
        {"detail": _mensaje_413(maximo), "codigo": "cuerpo_demasiado_grande"},
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(cuerpo)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": cuerpo})
