"""Contratos adjudicados del SERCOP, leídos de la copia del registro de Open Contracting.

POR QUÉ EXISTE. «Buscar mis contratos» consultaba la API de datos abiertos del SERCOP
(`datosabiertos.compraspublicas.gob.ec`), que el SERCOP retiró en noviembre de 2026: hoy redirige a
su portal institucional. El registro de datos del Open Contracting Partnership
(data.open-contracting.org, publicación 110) guarda la misma información del SERCOP en archivos por
año, y trae algo mejor que la API: el **RUC del adjudicatario** escrito en el identificador
(`EC-RUC-1790012345001-…`), así que no hay que buscar por nombre ni descartar homónimos.

QUÉ SE GUARDA. Lo mínimo para el perfil y las recomendaciones, por RUC, no los contratos enteros:
cuántos contratos y por cuánto, en qué años, sus CPC más frecuentes, las entidades que más le
compran y sus últimos contratos como experiencia (objeto corto). Las descripciones de los CPC y los
nombres de las entidades van **una vez** en sus propias tablas, no repetidas en cada RUC.

CÓMO SE LEE. El archivo de cada año es un `.tar.gz` con un CSV por tabla del estándar OCDS. Se lee
**en flujo**, sin descomprimirlo en disco, y solo cinco de sus tablas (`awards`, `awards_items`,
`awards_suppliers`, `main`, en ese orden dentro del tar). Lo que se retiene en memoria es una tupla
corta por adjudicación del año, que se suelta al pasar al año siguiente.
"""

from __future__ import annotations

import csv
import re
import tarfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, Any

URL_ANIO = "https://data.open-contracting.org/en/publication/110/download?name={anio}.csv.tar.gz"

MAX_CPC = 8
MAX_ENTIDADES = 5
MAX_EXPERIENCIA = 3
LARGO_OBJETO = 90
LARGO_CPC = 100
LARGO_ENTIDAD = 160

_RUC = re.compile(r"EC-RUC-(\d{13})")
_CATEGORIAS = {"goods": "bienes", "services": "servicios", "works": "obras"}
# Adjudicaciones que no llegaron a contrato: no son experiencia.
_ESTADOS_FALLIDOS = {"cancelled", "unsuccessful"}
_GENERICOS = ("orden de compra", "compra de", "certificacion presupuestaria", "certificación")

csv.field_size_limit(16 * 1024 * 1024)


def _lineas(binario: IO[bytes]) -> Iterator[str]:
    for linea in binario:
        yield linea.decode("utf-8", errors="replace")


def _filas(binario: IO[bytes]) -> Iterator[dict[str, str]]:
    yield from csv.DictReader(_lineas(binario))


def _monto(valor: str) -> float:
    try:
        return max(0.0, float(valor))
    except (TypeError, ValueError):
        return 0.0


def _corto(texto: str, largo: int) -> str:
    limpio = " ".join(str(texto or "").split())
    return limpio if len(limpio) <= largo else limpio[: largo - 1].rstrip() + "…"


@dataclass
class Contrato:
    entidad: int
    anio: int
    fecha: str
    monto: float
    cpc: str
    tipo: str
    objeto: str


@dataclass
class Proveedor:
    """Lo que se acumula de un RUC a lo largo de los años leídos."""

    contratos: int = 0
    monto: float = 0.0
    desde: int = 9999
    hasta: int = 0
    cpc: Counter[str] = field(default_factory=Counter)
    entidades: Counter[int] = field(default_factory=Counter)
    recientes: list[Contrato] = field(default_factory=list)

    def sumar(self, contrato: Contrato, codigos: list[str]) -> None:
        self.contratos += 1
        self.monto += contrato.monto
        self.desde = min(self.desde, contrato.anio)
        self.hasta = max(self.hasta, contrato.anio)
        self.cpc.update(codigos)
        self.entidades[contrato.entidad] += 1
        self.recientes.append(contrato)
        if len(self.recientes) > MAX_EXPERIENCIA * 4:
            self._recortar()

    def _recortar(self) -> None:
        self.recientes.sort(key=lambda c: c.fecha, reverse=True)
        del self.recientes[MAX_EXPERIENCIA:]

    def resumen(self) -> dict[str, Any]:
        self._recortar()
        return {
            "contratos": self.contratos,
            "monto": round(self.monto),
            "desde": self.desde,
            "hasta": self.hasta,
            "cpc": [[c, n] for c, n in self.cpc.most_common(MAX_CPC)],
            "entidades": [[e, n] for e, n in self.entidades.most_common(MAX_ENTIDADES)],
            # Experiencia en listas cortas, no en objetos: el nombre de cada clave se repetiría en
            # cada fila. Orden: entidad, año, monto, cpc, tipo, objeto.
            "experiencia": [
                [c.entidad, c.anio, round(c.monto), c.cpc, c.tipo, c.objeto] for c in self.recientes
            ],
        }


@dataclass
class Acumulado:
    """Todo lo leído: proveedores por RUC y los catálogos compartidos."""

    proveedores: dict[str, Proveedor] = field(default_factory=dict)
    cpc: dict[str, str] = field(default_factory=dict)
    entidades: dict[str, int] = field(default_factory=dict)  # nombre → id corto

    def id_entidad(self, nombre: str) -> int:
        nombre = _corto(nombre, LARGO_ENTIDAD) or "Entidad sin nombre"
        if nombre not in self.entidades:
            self.entidades[nombre] = len(self.entidades) + 1
        return self.entidades[nombre]


def leer_anio(archivo: IO[bytes], acumulado: Acumulado, anio_archivo: int) -> int:
    """Suma al acumulado las adjudicaciones de un `.tar.gz` anual. Devuelve cuántas leyó.

    Una adjudicación sin fecha cuenta en el año del archivo.
    """
    # (main_id, award_id) → fecha, monto
    adjudicaciones: dict[tuple[str, str], tuple[str, float]] = {}
    # (main_id, award_id) → códigos CPC (máx. 3) y el primer producto
    items: dict[tuple[str, str], tuple[list[str], str]] = {}
    # (main_id, award_id) → RUCs adjudicatarios
    ganadores: dict[tuple[str, str], list[str]] = {}
    procesos: dict[str, tuple[int, str, str]] = {}  # main_id → entidad, tipo, objeto

    with tarfile.open(fileobj=archivo, mode="r|gz") as tar:
        for miembro in tar:
            nombre = miembro.name.rsplit("/", 1)[-1]
            if nombre not in {"awards.csv", "awards_items.csv", "awards_suppliers.csv", "main.csv"}:
                continue
            binario = tar.extractfile(miembro)
            if binario is None:
                continue
            if nombre == "awards.csv":
                for f in _filas(binario):
                    if f.get("status") in _ESTADOS_FALLIDOS:
                        continue
                    adjudicaciones[(f["main_id"], f["id"])] = (
                        (f.get("date") or "")[:10],
                        _monto(f.get("value_amount", "")),
                    )
            elif nombre == "awards_items.csv":
                for f in _filas(binario):
                    clave = (f["main_id"], f["awards_id"])
                    if clave not in adjudicaciones:
                        continue
                    codigos, producto = items.get(clave, ([], ""))
                    codigo = (f.get("classification_id") or "").strip()
                    if (f.get("classification_scheme") or "").upper() == "CPC" and codigo:
                        if codigo not in codigos and len(codigos) < 3:
                            codigos.append(codigo)
                        if codigo not in acumulado.cpc:
                            acumulado.cpc[codigo] = _corto(
                                f.get("classification_description", ""), LARGO_CPC
                            )
                    if not producto:
                        producto = _corto(f.get("description", ""), LARGO_OBJETO)
                    items[clave] = (codigos, producto)
            elif nombre == "awards_suppliers.csv":
                for f in _filas(binario):
                    clave = (f["main_id"], f["awards_id"])
                    encontrado = _RUC.match(f.get("id") or "")
                    if encontrado and clave in adjudicaciones:
                        ganadores.setdefault(clave, []).append(encontrado.group(1))
            else:  # main.csv
                necesarios = {main_id for main_id, _ in ganadores}
                for f in _filas(binario):
                    if f["id"] not in necesarios:
                        continue
                    objeto = f.get("tender_description") or f.get("tender_title") or ""
                    procesos[f["id"]] = (
                        acumulado.id_entidad(f.get("buyer_name") or ""),
                        _CATEGORIAS.get(f.get("tender_mainProcurementCategory") or "", ""),
                        _corto(objeto, LARGO_OBJETO),
                    )

    leidas = 0
    for clave, rucs in ganadores.items():
        proceso = procesos.get(clave[0])
        if proceso is None:
            continue
        fecha, monto = adjudicaciones[clave]
        codigos, producto = items.get(clave, ([], ""))
        entidad, tipo, objeto = proceso
        if producto and (not objeto or objeto.lower().startswith(_GENERICOS)):
            objeto = producto
        anio = int(fecha[:4]) if fecha[:4].isdigit() else anio_archivo
        fecha = fecha or f"{anio_archivo}-01-01"
        # Un consorcio: el monto se reparte, para no contar dos veces el mismo contrato.
        parte = monto / len(rucs)
        for ruc in dict.fromkeys(rucs):
            principal = codigos[0] if codigos else ""
            contrato = Contrato(entidad, anio, fecha, parte, principal, tipo, objeto)
            acumulado.proveedores.setdefault(ruc, Proveedor()).sumar(contrato, codigos)
            leidas += 1
    return leidas
