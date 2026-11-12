"""Correo de una alerta. Si no hay servidor configurado, no se envía y no es un fallo."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from contratacion.infraestructura.config.ajustes import Ajustes

registro = logging.getLogger(__name__)


def enviar_si_hay_servidor(ajustes: Ajustes, *, destino: str, asunto: str, cuerpo: str) -> bool:
    """Devuelve True solo cuando el mensaje salió. Sin SMTP, devuelve False."""
    if not ajustes.smtp_host or not destino:
        return False
    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = ajustes.smtp_desde or ajustes.smtp_usuario
    mensaje["To"] = destino
    mensaje.set_content(cuerpo)
    try:
        with smtplib.SMTP(ajustes.smtp_host, ajustes.smtp_puerto, timeout=20) as cliente:
            cliente.starttls()
            if ajustes.smtp_usuario:
                cliente.login(ajustes.smtp_usuario, ajustes.smtp_clave)
            cliente.send_message(mensaje)
    except OSError:
        # Solo el dominio del destinatario: el correo completo es un dato personal y el registro
        # lo leen más personas que la base (auditoría de seguridad, doc 38).
        registro.exception(
            "No se pudo enviar la alerta a una cuenta de %s", destino.rpartition("@")[2] or "?"
        )
        return False
    return True
