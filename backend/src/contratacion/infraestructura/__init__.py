"""Capa de infraestructura: adaptadores concretos y arranque de la aplicación.

Aquí viven FastAPI, SQLAlchemy, Redis y los clientes de las fuentes externas. Es la única capa
que puede depender de librerías de terceros.
"""

from __future__ import annotations
