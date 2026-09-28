"""Catálogo de mapeos por defecto de la fuente OCDS.

Reproduce la normalización ya verificada del sistema anterior. Igual que en NCO, es solo el punto de
partida: después manda la tabla `campo_mapeo`.
"""

from __future__ import annotations

from typing import Any

MAPEOS_POR_DEFECTO: tuple[dict[str, Any], ...] = (
    {
        "clave_cruda": "ocid",
        "campo_canonico": "ocid",
        "etiqueta": "OCID",
        "tipo_dato": "texto",
        "requerido": True,
        "orden": 10,
        "ancho_excel": 45,
    },
    {
        "clave_cruda": "date",
        "campo_canonico": "fecha_publicacion",
        "etiqueta": "Fecha de Publicación",
        "tipo_dato": "fecha_hora",
        "orden": 20,
        "ancho_excel": 20,
    },
    {
        "clave_cruda": "title",
        "campo_canonico": "codigo",
        "etiqueta": "Código Necesidad de Contratación",
        "tipo_dato": "texto",
        "orden": 30,
        "ancho_excel": 34,
    },
    {
        "clave_cruda": "internal_type",
        "campo_canonico": "tipo_proceso",
        "etiqueta": "Tipo de Necesidad",
        "tipo_dato": "texto",
        "orden": 40,
        "ancho_excel": 20,
    },
    {
        "clave_cruda": "description",
        "campo_canonico": "objeto_compra",
        "etiqueta": "Descripción del Objeto de compra",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "html_a_texto"},
        "orden": 50,
        "ancho_excel": 60,
    },
    {
        "clave_cruda": "buyer",
        "campo_canonico": "entidad",
        "etiqueta": "Entidad Contratante",
        "tipo_dato": "texto",
        "orden": 60,
        "ancho_excel": 45,
    },
    {
        "clave_cruda": "region",
        "campo_canonico": "provincia",
        "etiqueta": "Provincia",
        "tipo_dato": "texto",
        "orden": 70,
    },
    {
        "clave_cruda": "locality",
        "campo_canonico": "canton",
        "etiqueta": "Cantón",
        "tipo_dato": "texto",
        "orden": 80,
    },
    {
        "clave_cruda": "suppliers",
        "campo_canonico": "proveedor",
        "etiqueta": "Proveedor adjudicado",
        "tipo_dato": "texto",
        "orden": 90,
        "ancho_excel": 40,
    },
    {
        "clave_cruda": "amount",
        "campo_canonico": "monto",
        "etiqueta": "Monto",
        "tipo_dato": "moneda",
        "orden": 100,
        "ancho_excel": 16,
    },
    {
        # `id` NO puede mapearse a `id`: ese nombre ya lo ocupa el identificador del registro
        # (`registro.id`, un uuid) y la API lo sobrescribiría al fundir los datos con la
        # procedencia.
        "clave_cruda": "id",
        "campo_canonico": "id_proceso",
        "etiqueta": "Identificador del proceso en la fuente",
        "tipo_dato": "texto",
        "orden": 110,
    },
    {
        "clave_cruda": "year",
        "campo_canonico": "anio",
        "etiqueta": "Año",
        "tipo_dato": "entero",
        "orden": 120,
    },
    {
        "clave_cruda": "month",
        "campo_canonico": "mes",
        "etiqueta": "Mes",
        "tipo_dato": "entero",
        "orden": 130,
    },
    {
        "clave_cruda": "method",
        "campo_canonico": "metodo",
        "etiqueta": "Método de contratación",
        "tipo_dato": "texto",
        "orden": 140,
    },
    {
        "clave_cruda": "budget",
        "campo_canonico": "presupuesto",
        "etiqueta": "Presupuesto referencial",
        "tipo_dato": "moneda",
        "orden": 150,
        "ancho_excel": 16,
    },
)
