"""Cruza el perfil de la empresa con una ínfima y arma el borrador, o explica por qué no.

No abre el PDF. Compara la dedicación, el CPC y la provincia. Si algo no coincide, no rellena:
un anexo armado para una licitación que la empresa no atiende sería peor que no entregar nada.
"""

from __future__ import annotations

from typing import Any

from contratacion.dominio.perfil import clasificar_objeto, clasificar_procedimiento


def proponer(
    perfil: dict[str, Any],
    *,
    provincia: str | None,
    cpc_codigos: list[str],
    tipo_texto: str | None,
    es_infima: bool,
    campos_pedido: list[str],
) -> dict[str, Any]:
    """Borrador, o la lista de motivos por los que no aplica."""
    motivos: list[str] = []
    dedicaciones = list(perfil.get("dedicaciones") or [])
    if not dedicaciones:
        motivos.append("La empresa no declaró a qué licitaciones se dedica.")
    else:
        tipo = clasificar_objeto(tipo_texto)
        procedimiento = clasificar_procedimiento(tipo_texto, es_infima=es_infima)
        if not any(_dedicacion_coincide(fila, tipo, procedimiento) for fila in dedicaciones):
            motivos.append(
                "Ninguna dedicación coincide con el tipo o el procedimiento de esta ínfima."
            )

    claves = {str(item).strip() for item in (perfil.get("cpc") or []) if str(item).strip()}
    codigos = {str(codigo).strip() for codigo in cpc_codigos if str(codigo).strip()}
    if claves and codigos and claves.isdisjoint(codigos):
        motivos.append("El CPC de la ínfima no está entre los que vigila la empresa.")

    cobertura = {
        str(fila.get("provincia") or "").strip().lower()
        for fila in perfil.get("cobertura") or []
        if str(fila.get("provincia") or "").strip()
    }
    if cobertura and provincia and provincia.strip().lower() not in cobertura:
        motivos.append(f"La empresa no oferta en {provincia}.")

    if motivos:
        return {"aplica": False, "motivos": motivos, "anexos": {}}

    pedidos = set(campos_pedido) or {"experiencia", "personal", "equipo", "declaraciones"}
    representante = next(
        (
            fila
            for fila in perfil.get("contactos") or []
            if fila.get("tipo") == "representante_legal"
        ),
        None,
    )
    anexos: dict[str, Any] = {
        "oferente": {
            "razon_social": perfil.get("razon_social") or perfil.get("nombre"),
            "ruc": perfil.get("ruc"),
            "direccion": perfil.get("direccion"),
            "telefono": perfil.get("telefono"),
            "email": perfil.get("email_contacto"),
            "representante": representante,
            "estado_rup": perfil.get("estado_rup"),
            "regimen_tributario": perfil.get("regimen_tributario"),
            "obligado_contabilidad": perfil.get("obligado_contabilidad"),
        }
    }
    if "experiencia" in pedidos:
        anexos["experiencia"] = _coincidentes(
            perfil.get("experiencia") or [], cpc_codigos, tipo_texto
        )
    if "personal" in pedidos:
        anexos["personal"] = list(perfil.get("personal") or [])
    if "equipo" in pedidos:
        anexos["equipo"] = list(perfil.get("equipo") or [])
    if "declaraciones" in pedidos:
        anexos["habilitantes"] = list(perfil.get("documentos") or [])
    return {"aplica": True, "motivos": [], "anexos": anexos}


def _dedicacion_coincide(fila: dict[str, Any], tipo: str | None, procedimiento: str | None) -> bool:
    procedimiento_ok = not procedimiento or fila.get("tipo_procedimiento") == procedimiento
    tipo_ok = not tipo or fila.get("tipo_contratacion") == tipo
    return procedimiento_ok and tipo_ok


def _coincidentes(
    filas: list[dict[str, Any]], cpc_codigos: list[str], tipo_texto: str | None
) -> list[dict[str, Any]]:
    tipo = clasificar_objeto(tipo_texto)
    codigos = {str(codigo).strip() for codigo in cpc_codigos}
    salida = []
    for fila in filas:
        cpc = str(fila.get("cpc") or "").strip()
        propio = fila.get("tipo_contratacion")
        if cpc and codigos and cpc not in codigos:
            continue
        if propio and tipo and propio != tipo:
            continue
        salida.append(fila)
    return salida


def _texto(valor: Any) -> str:
    return " ".join(str(valor or "").split())


def _dinero(valor: Any) -> str:
    try:
        return f"USD {float(valor):,.2f}"
    except (TypeError, ValueError):
        return ""


def _unir(*partes: Any) -> str:
    return " · ".join(parte for parte in (_texto(p) for p in partes) if parte)


def presentar_anexos(anexos: dict[str, Any]) -> list[dict[str, Any]]:
    """Los anexos como secciones que se pueden leer, en la pantalla y en el Word.

    Antes el borrador se enseñaba como un volcado de diccionarios, con los nombres internos de cada
    campo. Aquí cada sección sale con etiquetas en español y sin identificadores. Las de tipo
    `datos` son pares etiqueta/valor; las de tipo `lista`, una línea por elemento.
    """
    secciones: list[dict[str, Any]] = []
    oferente = anexos.get("oferente") or {}
    if oferente:
        representante = oferente.get("representante") or {}
        contabilidad = oferente.get("obligado_contabilidad")
        pares = [
            ("Razón social", _texto(oferente.get("razon_social"))),
            ("RUC", _texto(oferente.get("ruc"))),
            ("Dirección", _texto(oferente.get("direccion"))),
            ("Teléfono", _texto(oferente.get("telefono"))),
            ("Correo", _texto(oferente.get("email"))),
            (
                "Representante legal",
                _unir(
                    representante.get("nombre"),
                    representante.get("cargo"),
                    representante.get("cedula"),
                ),
            ),
            ("Estado en el RUP", _texto(oferente.get("estado_rup"))),
            ("Régimen tributario", _texto(oferente.get("regimen_tributario"))),
            (
                "Obligado a llevar contabilidad",
                "" if contabilidad is None else ("Sí" if contabilidad else "No"),
            ),
        ]
        secciones.append(
            {
                "titulo": "Datos del oferente",
                "tipo": "datos",
                "filas": [{"etiqueta": e, "valor": v} for e, v in pares if v],
            }
        )
    for clave, titulo, formato in _LISTAS:
        if clave in anexos:
            filas = [texto for texto in (formato(f) for f in anexos[clave] or []) if texto]
            secciones.append({"titulo": titulo, "tipo": "lista", "filas": filas})
    return secciones


def _experiencia(fila: dict[str, Any]) -> str:
    return _unir(
        fila.get("entidad"),
        fila.get("objeto"),
        _dinero(fila.get("monto")),
        fila.get("anio"),
        f"CPC {fila['cpc']}" if fila.get("cpc") else "",
    )


def _personal(fila: dict[str, Any]) -> str:
    anios = f"{fila['anios']} años" if fila.get("anios") else ""
    return _unir(fila.get("perfil"), fila.get("titulo"), anios)


def _equipo(fila: dict[str, Any]) -> str:
    return _unir(f"{fila.get('nombre')} x{fila.get('cantidad') or 1}", fila.get("estado"))


def _habilitante(fila: dict[str, Any]) -> str:
    vence = f"vence {fila['vence_en']}" if fila.get("vence_en") else ""
    return _unir(fila.get("tipo"), fila.get("nombre"), vence)


_LISTAS = (
    ("experiencia", "Experiencia que coincide", _experiencia),
    ("personal", "Personal técnico", _personal),
    ("equipo", "Equipo y recursos", _equipo),
    ("habilitantes", "Documentos habilitantes", _habilitante),
)
