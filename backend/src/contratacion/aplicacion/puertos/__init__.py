"""Contratos (puertos) entre la aplicación y la infraestructura.

Se declaran con `typing.Protocol` y funciones de módulo, para no forzar el uso de clases.
La infraestructura los implementa; la aplicación solo los conoce por su firma.
"""

from __future__ import annotations
