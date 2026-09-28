"""Plataforma SERCOP multi-tenant — backend.

Monolito modular con arquitectura hexagonal: `dominio` (reglas) ← `aplicacion` (casos de uso y
puertos) ← `infraestructura` (adaptadores). El sistema legado vive fuera de este paquete y se
mantiene intacto durante la migración por fases.
"""

from __future__ import annotations

__version__ = "0.1.0"
