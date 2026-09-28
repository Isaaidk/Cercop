"""Catálogo de mapeos por defecto de la fuente NCO.

Estas reglas reproducen la normalización que ya estaba **verificada** en el sistema anterior: los
mismos nombres de campo y las mismas limpiezas. No son una invención nueva.

Son solo un punto de partida: se siembran la primera vez y a partir de ahí manda la tabla
`campo_mapeo`, donde un administrador puede añadir, desactivar o corregir reglas sin desplegar.

Detalles que resuelven casos reales de esta fuente:

- `provincia` llega como «AZUAY - CUENCA», así que se recorta a la provincia.
- `url` llega como HTML con un `<a href=...>` dentro; se extrae el enlace.
- `objeto_contratacion` y `contacto` traen etiquetas y `<br/>` embebidos.
"""

from __future__ import annotations

from typing import Any

PATRON_ETIQUETA = r"href\s*=\s*['\"]?([^'\"\s>]+)"
PATRON_PROVINCIA = r"^(.*?)\s+-\s+"

MAPEOS_POR_DEFECTO: tuple[dict[str, Any], ...] = (
    {
        "clave_cruda": "tipo_necesidad",
        "campo_canonico": "tipo_necesidad",
        "etiqueta": "Tipo de Necesidad",
        "tipo_dato": "texto",
        "orden": 10,
        "ancho_excel": 20,
    },
    {
        "clave_cruda": "codigo_contratacion",
        "campo_canonico": "codigo",
        "etiqueta": "Código Necesidad de Contratación",
        "tipo_dato": "texto",
        "requerido": True,
        "orden": 20,
        "ancho_excel": 34,
    },
    {
        "clave_cruda": "fecha_publicacion",
        "campo_canonico": "fecha_publicacion",
        "etiqueta": "Fecha de Publicación",
        "tipo_dato": "fecha_hora",
        "orden": 30,
        "ancho_excel": 20,
    },
    {
        "clave_cruda": "provincia",
        "campo_canonico": "provincia",
        "etiqueta": "Provincia",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "regex", "patron": PATRON_PROVINCIA},
        "orden": 40,
    },
    {
        "clave_cruda": "canton",
        "campo_canonico": "canton",
        "etiqueta": "Cantón",
        "tipo_dato": "texto",
        "orden": 50,
    },
    {
        "clave_cruda": "objeto_contratacion",
        "campo_canonico": "objeto_compra",
        "etiqueta": "Descripción del Objeto de compra",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "html_a_texto"},
        "orden": 60,
        "ancho_excel": 60,
    },
    {
        "clave_cruda": "estado",
        "campo_canonico": "estado",
        "etiqueta": "Estado de la Necesidad",
        "tipo_dato": "texto",
        "orden": 70,
        "ancho_excel": 20,
    },
    {
        "clave_cruda": "fecha_limite_propuesta",
        "campo_canonico": "fecha_limite_proformas",
        "etiqueta": "Fecha límite para la entrega de proformas",
        "tipo_dato": "fecha_hora",
        "orden": 80,
        "ancho_excel": 24,
    },
    {
        "clave_cruda": "razon_social",
        "campo_canonico": "entidad",
        "etiqueta": "Entidad Contratante",
        "tipo_dato": "texto",
        "orden": 90,
        "ancho_excel": 45,
    },
    {
        "clave_cruda": "url",
        "campo_canonico": "enlace",
        "etiqueta": "Enlace al detalle",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "regex", "patron": PATRON_ETIQUETA},
        "orden": 100,
        "ancho_excel": 45,
    },
    {
        "clave_cruda": "direccion_entrega",
        "campo_canonico": "direccion_entrega",
        "etiqueta": "Dirección de Entrega",
        "tipo_dato": "texto",
        "orden": 110,
        "ancho_excel": 45,
    },
    {
        "clave_cruda": "contacto",
        "campo_canonico": "contacto",
        "etiqueta": "Contacto",
        "tipo_dato": "texto",
        "transformacion": {"operacion": "html_a_texto"},
        "orden": 120,
        "ancho_excel": 55,
    },
    {
        "clave_cruda": "funcionario_encargado",
        "campo_canonico": "funcionario",
        "etiqueta": "Funcionario Encargado",
        "tipo_dato": "texto",
        "orden": 130,
    },
    {
        "clave_cruda": "email_encargado",
        "campo_canonico": "email",
        "etiqueta": "Email",
        "tipo_dato": "texto",
        "orden": 140,
    },
    {
        "clave_cruda": "telefono_encargado",
        "campo_canonico": "telefono",
        "etiqueta": "Teléfono",
        "tipo_dato": "texto",
        "orden": 150,
    },
    {
        "clave_cruda": "cantidad",
        "campo_canonico": "cantidad",
        "etiqueta": "Cantidad",
        "tipo_dato": "texto",
        "orden": 160,
    },
    {
        "clave_cruda": "valor_unitario",
        "campo_canonico": "valor_unitario",
        "etiqueta": "Valor unitario",
        "tipo_dato": "moneda",
        "orden": 170,
    },
    {
        "clave_cruda": "seq_estado",
        "campo_canonico": "seq_estado",
        "etiqueta": "Secuencia de estado",
        "tipo_dato": "texto",
        "orden": 180,
    },
    {
        # Se quedó fuera del catálogo inicial: el listado la publica en las 1352 filas y, sin mapeo,
        # acababa en `campo_pendiente` en cada ciclo. Es el código numérico del tipo de necesidad
        # —el que usa la fuente para agrupar— y sirve para filtrar por tipo sin depender del texto.
        "clave_cruda": "seq_tipo_necesidad",
        "campo_canonico": "seq_tipo_necesidad",
        "etiqueta": "Secuencia del tipo de necesidad",
        "tipo_dato": "texto",
        "orden": 185,
    },
    {
        "clave_cruda": "tcom_necesidad_contratacion_id",
        "campo_canonico": "id_necesidad",
        "etiqueta": "Identificador de la necesidad",
        "tipo_dato": "texto",
        "orden": 190,
    },
)
