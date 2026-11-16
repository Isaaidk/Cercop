"""Prueba de carga del trabajo pesado, ejecutada **dentro** de un entorno de ensayo de Railway.

Por qué existe: lanzar cientos de usuarios virtuales desde una red ajena (una oficina, un operador
con inspección de tráfico) mide la red de en medio, cuando no la corta. Aquí todo corre en el mismo
proyecto que el API: se crean las cuentas, se baja k6, se lanza `carga/pesado.js` contra el dominio
público del entorno y el resumen sale por el registro del servicio. Al terminar se borran las
cuentas. **Nunca** en producción: se niega si `RAILWAY_ENVIRONMENT_NAME` es `production`.

Uso, como comando de arranque de un servicio del entorno de ensayo (con `DATABASE_URL` del dueño):

    python scripts/carga_en_railway.py

Variables: `CARGA_API` (dominio público del API, obligatorio), `CARGA_USUARIOS` (600),
`VUS_PANEL` (400), `VUS_OFERTA` (150), `DURACION` (6m), `SUBIDA` (2m), `CARGA_RAMA` (main).
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

K6 = "v2.4.0"
CARPETA = Path("/tmp/carga")


def _bajar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as respuesta:
        return bytes(respuesta.read())


def _correr(*orden: str) -> int:
    print("$", " ".join(orden), flush=True)
    return subprocess.call(list(orden))


def main() -> int:
    entorno = os.getenv("RAILWAY_ENVIRONMENT_NAME", "")
    if entorno == "production":
        print("carga_en_railway: se niega a correr en producción.", flush=True)
        return 2
    api = os.environ["CARGA_API"].rstrip("/")
    rama = os.getenv("CARGA_RAMA", "main")
    crudo = f"https://raw.githubusercontent.com/Isaaidk/Cercop/{rama}/carga"

    (CARPETA / "muestras").mkdir(parents=True, exist_ok=True)
    (CARPETA / "pesado.js").write_bytes(_bajar(f"{crudo}/pesado.js"))
    (CARPETA / "muestras" / "tdr_prueba.pdf").write_bytes(
        _bajar(f"{crudo}/muestras/tdr_prueba.pdf")
    )
    paquete = _bajar(
        f"https://github.com/grafana/k6/releases/download/{K6}/k6-{K6}-linux-amd64.tar.gz"
    )
    with tarfile.open(fileobj=io.BytesIO(paquete)) as tar:
        miembro = next(m for m in tar.getmembers() if m.name.endswith("/k6"))
        (CARPETA / "k6").write_bytes(tar.extractfile(miembro).read())  # type: ignore[union-attr]
    (CARPETA / "k6").chmod(0o755)

    script = Path(__file__).with_name("preparar_carga.py")
    usuarios = os.getenv("CARGA_USUARIOS", "600")
    credenciales = str(CARPETA / "credenciales.json")
    try:
        for intento in range(3):
            codigo = _correr(sys.executable, str(script), "--borrar") or _correr(
                sys.executable,
                str(script),
                "--usuarios",
                usuarios,
                "--api",
                api,
                "--salida",
                credenciales,
            )
            if codigo == 0:
                break
            print(f"preparar_carga falló (intento {intento + 1}); se reintenta.", flush=True)
            time.sleep(10)
        else:
            return 1

        entorno_k6 = {
            **os.environ,
            "K6_NO_USAGE_REPORT": "true",
        }
        argumentos = [
            str(CARPETA / "k6"),
            "run",
            "--quiet",
            "-e",
            f"BASE_URL={api}",
            "-e",
            "PERMITIR_REMOTO=1",
            "-e",
            f"SALIDA={CARPETA / 'resultado.json'}",
        ]
        for nombre in ("VUS_PANEL", "VUS_OFERTA", "DURACION", "SUBIDA"):
            if os.getenv(nombre):
                argumentos += ["-e", f"{nombre}={os.environ[nombre]}"]
        argumentos.append(str(CARPETA / "pesado.js"))
        print("$", " ".join(argumentos), flush=True)
        resultado = subprocess.call(argumentos, env=entorno_k6, cwd=CARPETA)
        print(f"k6 terminó con código {resultado} (99 = algún umbral no se cumplió).", flush=True)
    finally:
        _correr(sys.executable, str(script), "--borrar")
        Path(credenciales).unlink(missing_ok=True)
    print("CARGA_TERMINADA", flush=True)
    return 0


if __name__ == "__main__":
    codigo = main()
    # El servicio no debe reiniciarse y repetir la prueba: se queda dormido hasta que se borre.
    while True:
        time.sleep(3600)
