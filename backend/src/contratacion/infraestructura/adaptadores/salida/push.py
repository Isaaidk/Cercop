"""Envío de notificaciones web (Web Push con claves VAPID).

Solo lo usa el worker. Sin claves configuradas no se envía nada y no falla nada: los avisos siguen
apareciendo en el panel como antes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

registro = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultado:
    ok: bool
    # 404/410: el navegador ya no tiene esa suscripción (la persona la quitó o borró datos).
    caducada: bool = False


class EnviadorPush:
    def __init__(self, *, clave_privada: str, contacto: str) -> None:
        self._clave = clave_privada.strip()
        self._contacto = contacto.strip() or "mailto:soporte@cercoapp.ec"

    @property
    def activo(self) -> bool:
        return bool(self._clave)

    async def enviar(self, suscripcion: dict[str, Any], carga: dict[str, Any]) -> Resultado:
        if not self.activo:
            return Resultado(ok=False)
        return await asyncio.to_thread(self._enviar, suscripcion, carga)

    def _enviar(self, suscripcion: dict[str, Any], carga: dict[str, Any]) -> Resultado:
        from pywebpush import WebPushException, webpush  # type: ignore[import-untyped]

        try:
            webpush(
                subscription_info={
                    "endpoint": suscripcion["endpoint"],
                    "keys": {"p256dh": suscripcion["p256dh"], "auth": suscripcion["auth"]},
                },
                data=json.dumps(carga, ensure_ascii=False),
                vapid_private_key=self._clave,
                vapid_claims={"sub": self._contacto},
                ttl=6 * 3600,
                timeout=10,
            )
            return Resultado(ok=True)
        except WebPushException as exc:
            codigo = getattr(exc.response, "status_code", None)
            if codigo in (404, 410):
                return Resultado(ok=False, caducada=True)
            registro.warning("Push rechazado (%s): %s", codigo, str(exc)[:200])
            return Resultado(ok=False)
        except Exception as exc:  # noqa: BLE001 - una suscripción rota no para las demás
            registro.warning("Push no enviado: %s: %s", type(exc).__name__, str(exc)[:200])
            return Resultado(ok=False)
