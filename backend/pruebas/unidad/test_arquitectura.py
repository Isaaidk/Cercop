"""Reglas de la arquitectura hexagonal, comprobadas sobre el código fuente.

La dirección de las dependencias es la que sostiene todo lo demás: el **dominio** no conoce a nadie,
la **aplicación** conoce al dominio y a sus propios puertos, y la **infraestructura** conoce a todos
e implementa los puertos. Mientras se cumpla, una regla de negocio se prueba sin levantar nada y un
adaptador se cambia sin tocar las reglas.

Estas pruebas leen los `import` con `ast` —sin importar los módulos— y fallan en dos casos:

1. Si el dominio importa la aplicación, la infraestructura o una biblioteca de E/S.
2. Si un caso de uso que **no** está en la lista de deuda conocida importa la infraestructura. La
   lista existe porque hay módulos antiguos que todavía no pasan por puertos (ver
   `docs/36-arquitectura-y-resiliencia.md`); la prueba impide que crezca y también falla si uno de
   ellos ya se corrigió y sigue en la lista, para que se quite y no vuelva a entrar.
"""

from __future__ import annotations

import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2] / "src" / "contratacion"

# Bibliotecas de entrada y salida: su presencia en el dominio significa que una regla de negocio
# está hablando con el mundo exterior.
BIBLIOTECAS_DE_E_S = ("fastapi", "starlette", "sqlalchemy", "asyncpg", "httpx", "redis")

# Casos de uso que todavía importan adaptadores concretos. **No añadir entradas**: un caso de uso
# nuevo depende de un puerto de `aplicacion/puertos/` y la inyección se hace en el enrutador o en
# `tareas/`. Cada entrada es deuda con fecha; se quita al pasarla a puertos.
DEUDA_CONOCIDA = frozenset(
    {
        "aplicacion/casos_uso/atender_tdr.py",
        "aplicacion/casos_uso/ejecutar_ingesta.py",
        "aplicacion/casos_uso/generar_oferta.py",
        "aplicacion/casos_uso/preparar_documentos.py",
    }
)


def _importados(ruta: Path) -> set[str]:
    """Todos los módulos que importa un archivo, incluidos los `import` dentro de funciones."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    nombres: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            nombres.add(nodo.module)
    return nombres


def _archivos(capa: str) -> list[Path]:
    return sorted((RAIZ / capa).rglob("*.py"))


def _relativa(ruta: Path) -> str:
    return ruta.relative_to(RAIZ).as_posix()


def _importa(ruta: Path, prefijos: tuple[str, ...]) -> list[str]:
    return sorted(
        nombre
        for nombre in _importados(ruta)
        if any(nombre == p or nombre.startswith(f"{p}.") for p in prefijos)
    )


def test_hay_codigo_que_revisar() -> None:
    """Si la ruta se rompiera, las demás pruebas pasarían sin revisar nada."""
    assert _archivos("dominio")
    assert _archivos("aplicacion")


def test_el_dominio_no_depende_de_nadie() -> None:
    prohibidos = ("contratacion.aplicacion", "contratacion.infraestructura", "contratacion.tareas")
    violaciones = {
        _relativa(ruta): _importa(ruta, prohibidos + BIBLIOTECAS_DE_E_S)
        for ruta in _archivos("dominio")
    }
    violaciones = {ruta: nombres for ruta, nombres in violaciones.items() if nombres}
    assert not violaciones, f"El dominio importa capas externas o E/S: {violaciones}"


def test_la_aplicacion_no_depende_de_la_infraestructura_salvo_la_deuda_conocida() -> None:
    prohibidos = ("contratacion.infraestructura", "contratacion.tareas")
    con_infraestructura = {
        _relativa(ruta) for ruta in _archivos("aplicacion") if _importa(ruta, prohibidos)
    }
    nuevos = con_infraestructura - DEUDA_CONOCIDA
    assert not nuevos, (
        f"Estos módulos de aplicación importan la infraestructura: {sorted(nuevos)}. "
        "Define un puerto en `aplicacion/puertos/` e inyecta el adaptador desde el enrutador."
    )


def test_la_lista_de_deuda_no_guarda_modulos_ya_corregidos() -> None:
    prohibidos = ("contratacion.infraestructura", "contratacion.tareas")
    corregidos = sorted(
        ruta
        for ruta in DEUDA_CONOCIDA
        if not (RAIZ / ruta).exists() or not _importa(RAIZ / ruta, prohibidos)
    )
    assert not corregidos, (
        f"Ya no importan la infraestructura: {corregidos}. Quítalos de DEUDA_CONOCIDA para que no "
        "puedan volver a hacerlo."
    )


def test_los_modulos_ya_pasados_a_puertos_no_retroceden() -> None:
    """Los casos de uso que se pasaron a puertos en la fase de resiliencia, nombrados uno a uno."""
    prohibidos = ("contratacion.infraestructura",)
    for nombre in (
        "gestionar_perfil",
        "revisar_alertas",
        "seguimiento_ofertas",
        "ver_mercado",
        "ver_radar",
    ):
        ruta = RAIZ / "aplicacion" / "casos_uso" / f"{nombre}.py"
        assert not _importa(ruta, prohibidos), f"{nombre} vuelve a importar la infraestructura"


def test_la_aplicacion_no_usa_bibliotecas_web_ni_de_base_de_datos() -> None:
    """HTTP de servidor y SQL son de los adaptadores. `httpx` queda en la deuda de `atender_tdr`."""
    prohibidas = ("fastapi", "starlette", "sqlalchemy", "asyncpg", "redis")
    violaciones = {
        _relativa(ruta): _importa(ruta, prohibidas)
        for ruta in _archivos("aplicacion")
        if _importa(ruta, prohibidas)
    }
    assert not violaciones, f"La aplicación importa bibliotecas de infraestructura: {violaciones}"
