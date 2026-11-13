"""Tope de peticiones por **usuario** en las rutas de oferta.

El freno por IP de `proteccion.py` sirve para lo que se hace sin sesión (iniciar sesión, registrar
una empresa): ahí la IP es lo único que hay. Para las rutas de la oferta es el criterio
equivocado: una oficina, una universidad o un operador móvil sacan a cientos de personas por la
misma IP, y todas compartirían el mismo tope. Aquí la llave es la persona autenticada, así que lo
que gasta una no se le descuenta a otra.

Vive en memoria de cada proceso, como el freno por IP: con varios procesos de API el tope
efectivo es el de cada uno multiplicado por los procesos.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import HTTPException

from contratacion.aplicacion.encolador import ENCOLADORES
from contratacion.infraestructura.adaptadores.entrada.http.dependencias import ActorDep
from contratacion.infraestructura.adaptadores.entrada.http.proteccion import FrenoPorIp


class LimitePorUsuario:
    """Dependencia de FastAPI: `Depends(LimitePorUsuario("nombre", tope, ventana_seg))`."""

    def __init__(self, nombre: str, tope: int, ventana_seg: int) -> None:
        self._nombre = nombre
        self._tope = tope
        self._ventana = ventana_seg
        self._freno = FrenoPorIp()

    async def __call__(self, actor: ActorDep) -> None:
        espera = self._freno.permite(
            (self._nombre, "usuario", str(actor.usuario_id)), self._tope, self._ventana
        )
        if espera:
            raise HTTPException(
                status_code=429,
                detail=f"Estás pidiendo demasiado rápido. Vuelve a probar en {espera} segundos.",
                headers={"Retry-After": str(espera)},
            )


class Turno:
    """Dependencia de FastAPI que hace pasar la ruta entera por el encolador de su tipo.

    `Depends(Turno("lectura"))`. Es una dependencia con `yield`: el turno se toma antes de ejecutar
    la ruta y se suelta al terminar, falle o no. La empresa de quien llama es la llave del reparto
    justo (ver `aplicacion/encolador.py`).
    """

    def __init__(self, tipo: str) -> None:
        self._encolador = ENCOLADORES[tipo]

    async def __call__(self, actor: ActorDep) -> AsyncIterator[None]:
        empresa = str(actor.negocio_id or actor.usuario_id)
        async with self._encolador.turno(empresa):
            yield
