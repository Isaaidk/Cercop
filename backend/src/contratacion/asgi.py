"""Punto de entrada ASGI del proceso `api`.

Ejecutar:
    uvicorn contratacion.asgi:app --port 8001 --reload

La aplicación se construye al importar el módulo, por lo que la validación de la configuración
ocurre aquí: si falta un secreto obligatorio, el proceso no arranca.
"""

from __future__ import annotations

from contratacion.infraestructura.app import crear_app

app = crear_app()
