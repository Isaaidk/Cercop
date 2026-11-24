"""Créditos de IA: qué cuesta cada uso y qué paquetes se pueden comprar.

El precio vive aquí y no en la interfaz: si el panel mandara la cantidad de créditos, cualquiera
podría pedir un paquete de mil créditos al precio del de cincuenta.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from contratacion.dominio.errores import DatoInvalido

# Cada empresa empieza con 100 créditos (pedido del cliente, 2026-11). El super admin no gasta:
# ver `aplicacion/creditos_actor.py`. Solo el super admin otorga más.
REGALO_INICIAL = 100
COSTO_GENERAR_OFERTA = 3
# Con el modelo avanzado (más caro por token y más lento): pedido del cliente, 2026-11.
COSTO_GENERAR_OFERTA_AVANZADO = 5
COSTO_PREGUNTA = 1


@dataclass(frozen=True, slots=True)
class Paquete:
    codigo: str
    nombre: str
    creditos: int
    precio_usd: Decimal


PAQUETES: tuple[Paquete, ...] = (
    Paquete("basico", "Básico", 100, Decimal("5.00")),
    Paquete("pro", "Profesional", 500, Decimal("20.00")),
    Paquete("empresa", "Empresa", 2000, Decimal("60.00")),
)


def paquete(codigo: str) -> Paquete:
    for candidato in PAQUETES:
        if candidato.codigo == codigo:
            return candidato
    raise DatoInvalido("Ese paquete de créditos no existe.")


def costo_generar_oferta(avanzado: bool) -> int:
    return COSTO_GENERAR_OFERTA_AVANZADO if avanzado else COSTO_GENERAR_OFERTA
