# ruff: noqa: E501  (el TDR de ejemplo va tal cual, con sus renglones largos)
"""Lectura del TDR por su estructura numerada, requisitos medibles y condiciones en una frase.

Caso del reporte del cliente: «CONTRATACIÓN DEL SERVICIO DE ESTERILIZACIÓN PARA EL CONTROL
POBLACIONAL CANINO Y FELINO EN EL CANTÓN SAN PEDRO DE PIMAMPIRO».
"""

from __future__ import annotations

import io

from pypdf import PdfReader

from contratacion.aplicacion.casos_uso.preparar_documentos import _extras
from contratacion.dominio.anexos import OTRO, TDR, formato_de_proforma, garantias_mencionadas
from contratacion.dominio.documentos import (
    checklist,
    extraer_secciones,
    nombre_de_descarga,
    numerales_de,
    sin_referencia,
)
from contratacion.dominio.entidad import completar_entidad, datos_entidad_de_texto
from contratacion.dominio.oferta import (
    borrador_plantilla,
    faltantes,
    limpiar_respuesta,
    responder_requisito,
)
from contratacion.dominio.requisitos import (
    alcance_breve,
    condiciones_de_tdr,
    es_requisito_operativo,
    plazo_breve,
    plazo_ejecucion,
)
from contratacion.infraestructura.adaptadores.salida.oficina import parrafos_de
from contratacion.infraestructura.adaptadores.salida.proforma_pdf import (
    armar_proforma,
    titulo_sin_objeto,
)

# TDR de ejemplo con la estructura del de esterilización canina y felina de un GAD municipal (texto
# de una entidad pública, resumido, con los datos de contacto genéricos del municipio).
TDR_ESTERILIZACION = """GOBIERNO AUTÓNOMO DESCENTRALIZADO MUNICIPAL DE SAN PEDRO DE PIMAMPIRO
TÉRMINOS DE REFERENCIA
1. ANTECEDENTES
El GAD Municipal ejecuta desde el año 2022 campañas de control poblacional de perros y gatos.
2. JUSTIFICACIÓN
Desde el enfoque de bienestar animal, el proyecto promueve una alternativa ética para el control de la población de perros y gatos.
La sobrepoblación canina genera problemas de salud pública en el cantón.
3. OBJETO DE CONTRATACIÓN
CONTRATACIÓN DEL SERVICIO DE ESTERILIZACIÓN PARA EL CONTROL POBLACIONAL CANINO Y FELINO EN EL CANTÓN SAN PEDRO DE PIMAMPIRO
4. OBJETIVOS
4.1. Objetivo General
Contribuir al control poblacional canino y felino del cantón mediante esterilizaciones quirúrgicas.
4.2. Objetivos Específicos
Sensibilizar a la ciudadanía sobre la tenencia responsable de mascotas.
5. ALCANCE
Un mínimo de 193 procedimientos quirúrgicos distribuidos entre caninos y felinos, machos y hembras, a fin de tener un control en el incremento de la misma.
6. METODOLOGÍA DE TRABAJO
El contratista deberá aplicar protocolos de bioseguridad en cada jornada de esterilización.
Desde el enfoque de bienestar animal, el proyecto promueve una alternativa ética para el control de la población.
Las cirugías serán realizadas por un médico veterinario con título registrado en la SENESCYT.
Se contará con al menos 2 mesas quirúrgicas y equipo de anestesia inhalatoria.
6.1. Protocolo para el desarrollo de campañas
6.1.1. Fase preparatoria y difusión
La difusión de cada campaña se realizará con al menos 5 días de anticipación.
6.1.2. Recepción
Los pacientes deberán presentarse con un ayuno mínimo de 8 horas.
6.1.3. Identificación y entrega al usuario
Cada paciente será identificado con un collar numerado y entregado a su propietario con las indicaciones postoperatorias por escrito.
7. PRODUCTOS O SERVICIOS ESPERADOS
Informe final con el registro fotográfico de los 193 procedimientos realizados.
8. PLAZO DE EJECUCIÓN
El presente cronograma refleja 3 jornadas de esterilización distribuidas en el plazo de 180 días correspondiente a los meses de junio a noviembre, contados a partir de la suscripción de la orden de compra.
9. FORMA DE PAGO
El pago se realizará contra entrega del informe final, previa presentación de la factura y del acta de entrega recepción a satisfacción de la entidad. No se otorgará anticipo. El administrador de la orden de compra verificará el número de procedimientos realizados antes de autorizar el pago.
Dirección: Calle Olmedo y Flores, Pimampiro
Teléfono: 06 293 7124
Email: municipio@pimampiro.gob.ec
Web: www.pimampiro.gob.ec
"""


_PLAZO_LARGO = (
    "El presente cronograma refleja 3 jornadas de esterilización distribuidas en el plazo de "
    "180 días correspondiente a los meses de junio a noviembre."
)
_JUSTIFICACION = (
    "Desde el enfoque de bienestar animal, el proyecto promueve una alternativa ética para el "
    "control de la población de perros y gatos."
)


def _secciones() -> dict[str, str]:
    return extraer_secciones(TDR_ESTERILIZACION)


# --- 1. Lectura por la estructura numerada -------------------------------------------------------


def test_los_apartados_numerados_se_leen_por_separado_y_conservan_su_numeral() -> None:
    secciones = _secciones()
    numerales = numerales_de(secciones)
    assert numerales["objetivos"] == "4. Objetivos"
    assert numerales["alcance"] == "5. Alcance"
    assert numerales["metodologia"] == "6. Metodología de trabajo"
    assert numerales["protocolo"] == "6.1. Protocolo para el desarrollo de campañas"
    assert numerales["entregables"] == "7. Productos o servicios esperados"
    assert numerales["forma_pago"] == "9. Forma de pago"
    assert "193 procedimientos" in secciones["alcance"]
    assert "Objetivo General" not in secciones["objetivos"]  # el subtítulo no es contenido
    assert "Contribuir al control" in secciones["objetivos"]
    # Lo técnico (metodología, protocolo) no se mezcla con lo comercial (productos, pago).
    assert "Informe final" not in secciones["protocolo"]
    assert "factura" not in secciones["entregables"]
    assert "6.1.2 Recepción." in secciones["protocolo"]
    # El pie con el correo y la web no cae dentro de la forma de pago.
    assert "pimampiro.gob.ec" not in secciones["forma_pago"]


def test_un_apartado_numerado_desconocido_corta_el_anterior() -> None:
    texto = (
        "5. ALCANCE\nUn mínimo de 10 visitas técnicas.\n6. OBLIGACIONES DE LA ENTIDAD\n"
        "Entregar la información necesaria.\n"
    )
    secciones = extraer_secciones(texto)
    assert "Entregar" not in secciones["alcance"]
    assert numerales_de(secciones)["apartado_6"] == "6. Obligaciones de la entidad"


def test_una_lista_numerada_dentro_de_un_apartado_no_es_un_apartado_nuevo() -> None:
    texto = "3. ALCANCE\n1. RUC ACTIVO\n2. Diez visitas al mes.\n"
    secciones = extraer_secciones(texto)
    assert "RUC ACTIVO" in secciones["alcance"]
    assert not any(clave.startswith("apartado_") for clave in secciones)


def test_un_parrafo_que_nombra_un_protocolo_no_abre_un_apartado() -> None:
    texto = "5. ALCANCE\nProtocolos de bioseguridad en cada jornada\nUn mínimo de 3 jornadas.\n"
    secciones = extraer_secciones(texto)
    assert "protocolo" not in secciones
    assert "bioseguridad" in secciones["alcance"]


# --- 2. Requisitos medibles, en el orden del TDR y con su numeral --------------------------------


def test_los_requisitos_son_factores_operativos_en_el_orden_del_tdr() -> None:
    requisitos = checklist(_secciones())
    textos = [sin_referencia(r) for r in requisitos]
    assert requisitos[0].startswith("Un mínimo de 193 procedimientos")
    assert requisitos[0].endswith("(TDR 5. Alcance)")
    assert any(
        "bioseguridad" in r and r.endswith("(TDR 6. Metodología de trabajo)") for r in requisitos
    )
    assert any("8 horas" in r and r.endswith("(TDR 6.1.2. Recepción)") for r in requisitos)
    assert any(r.endswith("(TDR 6.1.3. Identificación y entrega al usuario)") for r in requisitos)
    assert any(t.startswith("Plazo de entrega: 180 días contados") for t in textos)
    # Nada de justificación, objetivos ni subtítulos sueltos.
    assert not any("enfoque de bienestar" in t for t in textos)
    assert not any("Sensibilizar" in t or "Contribuir" in t for t in textos)
    assert not any(t.startswith(("6.1.1", "Fase preparatoria")) for t in textos)
    # El orden sigue los numerales: alcance (5) → metodología (6) → protocolo (6.1) → productos.
    posicion = {
        clave: next(i for i, t in enumerate(textos) if clave in t)
        for clave in ("193", "bioseguridad", "ayuno", "Informe final")
    }
    assert (
        posicion["193"] < posicion["bioseguridad"] < posicion["ayuno"] < posicion["Informe final"]
    )


def test_una_frase_de_justificacion_no_es_requisito() -> None:
    assert not es_requisito_operativo(_JUSTIFICACION)
    assert not es_requisito_operativo(
        "La sobrepoblación canina genera problemas de salud pública en el cantón."
    )
    assert es_requisito_operativo("El contratista deberá aplicar protocolos de bioseguridad.")
    assert es_requisito_operativo(
        "Un mínimo de 193 procedimientos quirúrgicos, a fin de tener control."
    )
    assert es_requisito_operativo("RUC activo.")
    assert es_requisito_operativo("PLAZO DE ENTREGA: 15 días")
    assert not es_requisito_operativo("Valor unitario: $ 45,00 por procedimiento")


def test_la_respuesta_no_se_confunde_con_la_cita_del_numeral() -> None:
    respuesta = responder_requisito(
        "Se contará con al menos 2 mesas quirúrgicas. (TDR 8. Personal y equipo)",
        condiciones={},
        empresa={"razon_social": "Vet S.A."},
        perfil={},
    )
    assert "Personal ofrecido" not in respuesta and "(TDR" not in respuesta


def test_la_ia_no_cuela_frases_de_justificacion_como_requisitos() -> None:
    base = borrador_plantilla(secciones=_secciones(), perfil={}, entidad="GAD", objeto="")
    respuesta = {
        "cumplimiento": [
            {"requisito": _JUSTIFICACION, "como_cumple": "Aceptamos."},
            {"requisito": base["cumplimiento"][0]["requisito"], "como_cumple": "Cumplimos."},
        ],
        "plazo_entrega": _PLAZO_LARGO,
    }
    limpio = limpiar_respuesta(respuesta, base, modelo="prueba")
    assert [f["como_cumple"] for f in limpio["cumplimiento"]] == ["Cumplimos."]
    assert limpio["condiciones"]["plazo_entrega"].startswith("180 días contados")


# --- 5 y 6. Alcance y condiciones en una frase ---------------------------------------------------


def test_el_plazo_largo_se_resume_en_la_frase_estandar() -> None:
    assert plazo_breve(_PLAZO_LARGO) == (
        "180 días contados a partir del día siguiente de la suscripción de la orden de compra."
    )
    assert plazo_breve("15 días calendario") == "15 días calendario"
    assert plazo_ejecucion(_PLAZO_LARGO) == "180 días"
    assert plazo_breve("Treinta días, según el cronograma adjunto").startswith("Treinta días")


def test_las_condiciones_del_tdr_van_cortas_y_el_detalle_aparte() -> None:
    condiciones = condiciones_de_tdr(_secciones())
    assert condiciones["plazo_entrega"].startswith("180 días contados a partir del día siguiente")
    assert condiciones["plazo_ejecucion"] == "180 días"
    assert len(condiciones["forma_pago"]) <= 161
    assert condiciones["alcance"].startswith("Un mínimo de 193 procedimientos")
    assert (
        "3 jornadas" in condiciones["detalle"]
        and "No se otorgará anticipo" in condiciones["detalle"]
    )
    assert (
        alcance_breve("El servicio cubre el cantón. Un mínimo de 50 visitas.")
        == "Un mínimo de 50 visitas."
    )


def test_el_borrador_trae_alcance_y_detalle() -> None:
    borrador = borrador_plantilla(secciones=_secciones(), perfil={}, entidad="GAD", objeto="")
    assert borrador["alcance"].startswith("Un mínimo de 193")
    assert borrador["condiciones"]["plazo_entrega"].endswith("suscripción de la orden de compra.")
    assert borrador["condiciones"]["plazo_ejecucion"] == "180 días"
    assert "cronograma" in borrador["detalle_condiciones"]


def test_alcance_y_detalle_se_guardan_en_extras_con_tope() -> None:
    extras = _extras(
        {
            "alcance": "  Un mínimo   de 193 procedimientos ",
            "detalle_condiciones": "a\n\n b  c\n" + "x" * 9000,
        }
    )
    assert extras["alcance"] == "Un mínimo de 193 procedimientos"
    assert extras["detalle_condiciones"].startswith("a\nb c\n")
    assert len(extras["detalle_condiciones"]) <= 6000


# --- 3. Correo y sitio web de la entidad --------------------------------------------------------


def test_correo_y_sitio_web_de_la_entidad_salen_del_membrete() -> None:
    datos = datos_entidad_de_texto(TDR_ESTERILIZACION)
    assert datos["correo"] == "municipio@pimampiro.gob.ec"
    assert datos["web"] == "www.pimampiro.gob.ec"
    assert datos["telefono"] == "06 293 7124"


def test_el_sitio_del_sercop_o_del_proveedor_no_es_el_de_la_entidad() -> None:
    texto = (
        "Publicado en www.compraspublicas.gob.ec. El RUC se valida en www.sri.gob.ec.\n"
        "Correo del oferente: ventas@proveedor.com\nPágina web del oferente: www.proveedor.com\n"
    )
    datos = datos_entidad_de_texto(texto)
    assert "web" not in datos and "correo" not in datos
    # El dominio del correo institucional con forma de dirección sí cuenta, sin etiqueta.
    assert (
        datos_entidad_de_texto("Contacto: tthh@gadx.gob.ec - visítenos en www.gadx.gob.ec")["web"]
        == "www.gadx.gob.ec"
    )
    assert completar_entidad({"ruc": "1"}, {"web": "www.gadx.gob.ec"})["web"] == "www.gadx.gob.ec"


def test_correo_y_web_de_la_entidad_se_guardan_e_imprimen_solo_si_hay() -> None:
    extras = _extras(
        {"entidad": {"ruc": "1060000420001", "correo": "m@x.gob.ec", "web": "www.x.gob.ec"}}
    )
    assert extras["entidad"]["web"] == "www.x.gob.ec"
    con = _documento(entidad=extras["entidad"])
    sin = _documento(entidad={"ruc": "1060000420001"})
    assert "Sitio web de la entidad: www.x.gob.ec" in parrafos_de(con)
    assert not any("Sitio web" in p or "Correo de la entidad" in p for p in parrafos_de(sin))
    texto_pdf = _texto(armar_proforma(con)[0])
    assert "www.x.gob.ec" in texto_pdf and "m@x.gob.ec" in texto_pdf
    assert "Sitio web de la entidad" not in _texto(armar_proforma(sin)[0])


# --- 4. Formato de proforma de la propia entidad --------------------------------------------------

_FORMATO = """GAD MUNICIPAL DE SAN PEDRO DE PIMAMPIRO
ÍNFIMA CUANTÍA N° IC-GADMSPP-2026-045
PROFORMA
Nombre del oferente: ______________________ RUC: ______________
No. CPC Descripción Cantidad V. Unitario V. Total
1 863400011 Servicio de esterilización canina y felina 193
PLAZO DE EJECUCIÓN: ________
FORMA DE PAGO: ________
GARANTÍA: El oferente presentará una garantía de cumplimiento del contrato.
Firma y sello del oferente
"""


def test_se_detecta_el_formato_de_proforma_de_la_entidad() -> None:
    formato = formato_de_proforma({"nombre": "Documento 3", "tipo": OTRO}, _FORMATO)
    assert formato is not None
    assert formato["nombre"] == "Documento 3"
    assert "Forma de pago" in formato["senales"] and "Plazo de ejecución" in formato["senales"]
    assert formato["garantias"] == ["Garantía de fiel cumplimiento"]


def test_un_tdr_con_la_tabla_del_presupuesto_no_es_un_formato_de_proforma() -> None:
    tdr = (
        "TÉRMINOS DE REFERENCIA\nPresentación de proformas hasta el viernes.\nPROFORMA\n"
        "No. CPC Descripción Cantidad V. Unitario V. Total\nPLAZO DE EJECUCIÓN: 30 días\n"
        "FORMA DE PAGO: contra entrega\n"
    )
    assert formato_de_proforma({"nombre": "TDR.pdf", "tipo": TDR}, tdr) is None
    explicito = tdr + "ANEXO 1: FORMATO DE PROFORMA\nFirma del oferente: ________\n"
    assert formato_de_proforma({"nombre": "TDR.pdf", "tipo": TDR}, explicito) is not None
    assert formato_de_proforma({"nombre": "Informe.pdf", "tipo": OTRO}, TDR_ESTERILIZACION) is None


def test_garantias_mencionadas() -> None:
    assert garantias_mencionadas("Se exige garantía técnica de 12 meses y póliza de seguro.") == [
        "Garantía técnica",
        "Póliza de seguro",
    ]


# --- 7. Tabla de cumplimiento sin firma por fila; título sin repetir el objeto -------------------


def _texto(contenido: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(contenido)).pages)


def _documento(**extras: object) -> dict[str, object]:
    return {
        "tipo": "proforma",
        "titulo": "Proforma — Contratación del servicio de esterilización · NIC-1060000420001-2026-00010",
        "entidad": "GAD Municipal de San Pedro de Pimampiro",
        "objeto": "Contratación del servicio de esterilización para el control poblacional canino",
        "lineas": [
            {
                "descripcion": "Esterilización",
                "cantidad": 193,
                "precio_unitario": 40,
                "subtotal": 7720,
            }
        ],
        "cifras": {"subtotal": 7720, "impuesto": 0, "impuesto_porcentaje": 0, "total": 7720},
        "extras": {
            "empresa": {
                "razon_social": "Vet Andina S.A.",
                "ruc": "1792146739001",
                "representante": "Ana Pérez",
            },
            "fecha": "19/11/2026",
            "condiciones": {
                "validez": "45 días",
                "plazo_entrega": "180 días contados a partir del día siguiente de la suscripción de la orden de compra.",
            },
            "alcance": "Un mínimo de 193 procedimientos quirúrgicos.",
            "detalle_condiciones": "Plazo de entrega (según el TDR): El presente cronograma refleja 3 jornadas.",
            "cumplimiento": [
                {"requisito": f"Requisito {n}", "como_cumple": "Cumplimos."} for n in range(1, 4)
            ],
            **extras,
        },
    }


def test_la_tabla_de_cumplimiento_no_lleva_firma_por_fila() -> None:
    contenido, cajas = armar_proforma(_documento(integridad=False))
    texto = _texto(contenido)
    assert "Cómo cumple el oferente" in texto
    assert texto.count("Firma electrónica") == 1  # el rótulo del único recuadro, no una columna
    assert len(cajas) == 1  # solo el recuadro de firma final
    assert "DECLARACIÓN DEL OFERENTE" in texto


def test_alcance_y_detalle_salen_en_el_pdf_de_respaldo_y_en_el_word() -> None:
    texto = _texto(armar_proforma(_documento())[0])
    assert "Alcance:" in texto and "193 procedimientos" in texto
    assert "DETALLE DE LAS CONDICIONES" in texto and "3 jornadas" in texto
    parrafos = parrafos_de(_documento())
    assert "Alcance: Un mínimo de 193 procedimientos quirúrgicos." in parrafos
    assert any("3 jornadas" in p for p in parrafos)


def test_el_titulo_no_repite_el_objeto() -> None:
    objeto = "Contratación del servicio de esterilización para el control poblacional canino"
    assert (
        titulo_sin_objeto("Proforma — Contratación del servicio de esterilización · NIC-1", objeto)
        == "Proforma · NIC-1"
    )
    assert titulo_sin_objeto("Proforma de esterilización 2026", objeto) == (
        "Proforma de esterilización 2026"
    )
    texto = _texto(armar_proforma(_documento(integridad=False))[0])
    assert "PROFORMA · NIC-1060000420001-2026-00010" in texto
    assert texto.count("Contratación del servicio de esterilización") == 1  # solo en el objeto


# --- Extras del cliente: nombre de la descarga y aviso de datos de la empresa -------------------


def test_la_descarga_se_llama_con_el_codigo_del_proceso() -> None:
    assert nombre_de_descarga("NIC-1060000420001-2026-00010", "pdf") == (
        "ProformaCercoapp_NIC-1060000420001-2026-00010.pdf"
    )
    assert nombre_de_descarga("", "docx") == "ProformaCercoapp.docx"
    assert nombre_de_descarga("a/b:c?", "pdf", "_firmado") == "ProformaCercoapp_a-b-c_firmado.pdf"


def test_catalogo_y_experiencia_son_recomendados_no_faltantes() -> None:
    perfil = {
        "razon_social": "Vet Andina",
        "ruc": "1792146739001",
        "email_contacto": "a@b.ec",
        "telefono": "0999999999",
        "direccion": "Av. 1",
        "ciudad": "Quito",
        "tipo_persona": "natural",
    }
    lista = faltantes(perfil)
    assert lista and all(dato.get("opcional") for dato in lista)
    assert not any(dato["campo"] == "representante" for dato in lista)
    juridica = faltantes({**perfil, "tipo_persona": "juridica"})
    assert any(d["campo"] == "representante" and not d.get("opcional") for d in juridica)
