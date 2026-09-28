"""Imprime el contrato de la API en texto legible.

Se genera desde la propia aplicación, así que lo que muestra es exactamente lo que hay montado:
sirve para construir el frontend sin adivinar rutas ni parámetros, y para detectar en una revisión
que un endpoint ha desaparecido o ha cambiado de forma.

    python scripts/contrato_api.py            # todas las rutas
    python scripts/contrato_api.py registros  # solo las que contienen ese texto
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from contratacion.infraestructura.app import crear_app  # noqa: E402

METODOS = ("get", "post", "put", "patch", "delete")


def main() -> None:
    filtro = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    esquema = crear_app().openapi()

    for ruta, operaciones in sorted(esquema["paths"].items()):
        if filtro and filtro not in ruta.lower():
            continue
        for metodo in METODOS:
            operacion = operaciones.get(metodo)
            if operacion is None:
                continue
            print(f"\n{metodo.upper():<6} {ruta}")
            print(f"       {operacion.get('summary', '')}")

            parametros = [p for p in operacion.get("parameters", []) if p.get("in") == "query"]
            if parametros:
                print("       parámetros de consulta:")
                for parametro in parametros:
                    obligatorio = "obligatorio" if parametro.get("required") else "opcional"
                    tipo = parametro.get("schema", {}).get("type", "?")
                    print(f"         - {parametro['name']} ({tipo}, {obligatorio})")

            cuerpo = operacion.get("requestBody")
            if cuerpo:
                referencia = (
                    cuerpo.get("content", {})
                    .get("application/json", {})
                    .get("schema", {})
                    .get("$ref", "")
                )
                nombre = referencia.rsplit("/", 1)[-1] if referencia else "en línea"
                print(f"       cuerpo: {nombre}")
                propiedades = (
                    esquema.get("components", {})
                    .get("schemas", {})
                    .get(nombre, {})
                    .get("properties")
                )
                for campo, detalle in (propiedades or {}).items():
                    print(f"         - {campo}: {detalle.get('type', '?')}")

            print(f"       respuestas: {', '.join(sorted(operacion.get('responses', {})))}")


if __name__ == "__main__":
    main()
