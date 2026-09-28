"""Prepara el archivo de entorno local **sin exponer ningún valor**.

Genera los secretos que falten y los escribe directamente en el archivo; nunca los imprime. La
cadena de conexión se recibe por variable de entorno para que no quede en el código fuente.

    cd backend
    $env:SERCOP_DATABASE_URL = '<uri de postgres>'
    .\\.venv\\Scripts\\python.exe scripts\\preparar_entorno.py
    Remove-Item Env:\\SERCOP_DATABASE_URL

Reglas:
- **Solo añade claves ausentes.** Nunca sobrescribe un valor ya presente, para no rotar secretos de
  forma accidental.
- La salida son únicamente **nombres** de variable, jamás valores.
"""

from __future__ import annotations

import base64
import os
import secrets
import sys
from pathlib import Path

RAIZ_BACKEND = Path(__file__).resolve().parents[1]
RAIZ_REPOSITORIO = RAIZ_BACKEND.parent
DESTINO = RAIZ_REPOSITORIO / ".env"

VARIABLE_DSN = "SERCOP_DATABASE_URL"
REDIS_POR_DEFECTO = "redis://localhost:6379/0"
CORS_POR_DEFECTO = "http://localhost:5173"

CABECERA = "# --- Backend: variables que espera la aplicación (añadidas automáticamente) ---"


def _leer_claves(texto: str) -> set[str]:
    """Nombres de variable ya presentes en el archivo."""
    claves: set[str] = set()
    for linea in texto.splitlines():
        limpia = linea.strip()
        if limpia and not limpia.startswith("#") and "=" in limpia:
            claves.add(limpia.split("=", 1)[0].strip())
    return claves


def _generar_secretos() -> dict[str, str]:
    """Secretos fuertes generados en memoria; no se imprimen en ningún momento."""
    return {
        "JWT_SECRETO": secrets.token_urlsafe(48),
        "CLAVE_CIFRADO_DATOS": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "CLAVE_PEPPER_HMAC": secrets.token_urlsafe(48),
    }


def _candidatas() -> dict[str, str]:
    valores: dict[str, str] = {}

    dsn = os.environ.get(VARIABLE_DSN)
    if dsn:
        valores["DATABASE_URL"] = dsn

    valores["REDIS_URL"] = os.environ.get("SERCOP_REDIS_URL", REDIS_POR_DEFECTO)
    valores["CORS_ORIGINS"] = os.environ.get("SERCOP_CORS_ORIGINS", CORS_POR_DEFECTO)
    valores.update(_generar_secretos())
    return valores


def main() -> int:
    texto = DESTINO.read_text(encoding="utf-8") if DESTINO.exists() else ""
    existentes = _leer_claves(texto)

    faltantes = {clave: valor for clave, valor in _candidatas().items() if clave not in existentes}

    if not faltantes:
        print("Ninguna variable pendiente: el archivo de entorno está completo.")
        return 0

    lineas = [CABECERA, *(f"{clave}={valor}" for clave, valor in faltantes.items())]
    DESTINO.write_text(texto.rstrip("\n") + "\n\n" + "\n".join(lineas) + "\n", encoding="utf-8")

    print(f"Añadidas {len(faltantes)} variables a {DESTINO.name} (los valores NO se muestran):")
    for clave in faltantes:
        print(f"   - {clave}")
    print("\nEjecuta ahora: python scripts/verificar_conexiones.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
