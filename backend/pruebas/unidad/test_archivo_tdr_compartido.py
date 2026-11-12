"""El API no comparte disco con el worker: toma el anexo de la copia guardada en la base."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any

from contratacion.aplicacion.casos_uso.atender_tdr import archivo_local


class _Repo:
    def __init__(self, copias: dict[str, bytes]) -> None:
        self.copias = copias
        self.pedidas = 0

    async def contenido_archivo(self, sha256: str) -> bytes | None:
        self.pedidas += 1
        return self.copias.get(sha256)


def _fila(ruta: Path, huella: str) -> dict[str, Any]:
    return {"ruta": str(ruta), "sha256": huella}


def test_si_el_archivo_esta_en_disco_no_pregunta_a_la_base(tmp_path: Path) -> None:
    contenido = b"%PDF-1.4 tdr"
    huella = hashlib.sha256(contenido).hexdigest()
    ruta = tmp_path / huella
    ruta.write_bytes(contenido)
    repo = _Repo({})
    assert asyncio.run(archivo_local(repo, _fila(ruta, huella))) == ruta  # type: ignore[arg-type]
    assert repo.pedidas == 0


def test_sin_archivo_en_disco_lo_escribe_desde_la_base(tmp_path: Path) -> None:
    contenido = b"%PDF-1.4 tdr del worker"
    huella = hashlib.sha256(contenido).hexdigest()
    ruta = tmp_path / "tdr" / huella
    repo = _Repo({huella: contenido})
    assert asyncio.run(archivo_local(repo, _fila(ruta, huella))) == ruta  # type: ignore[arg-type]
    assert ruta.read_bytes() == contenido


def test_copia_alterada_o_ausente_no_se_usa(tmp_path: Path) -> None:
    huella = hashlib.sha256(b"original").hexdigest()
    ruta = tmp_path / huella
    alterada = _Repo({huella: b"otra cosa"})
    assert asyncio.run(archivo_local(alterada, _fila(ruta, huella))) is None  # type: ignore[arg-type]
    assert not ruta.exists()
    assert asyncio.run(archivo_local(_Repo({}), _fila(ruta, huella))) is None  # type: ignore[arg-type]
    # Una ruta que no termina en la huella no se escribe nunca.
    otra = tmp_path / "otro_nombre"
    assert asyncio.run(archivo_local(_Repo({huella: b"original"}), _fila(otra, huella))) is None  # type: ignore[arg-type]
