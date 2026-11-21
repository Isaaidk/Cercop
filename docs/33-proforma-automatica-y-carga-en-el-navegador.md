# Proforma casi automática y trabajo en el navegador

## Por qué

Con pocas personas a la vez el servidor se agota por CPU y memoria, no por la base. Lo que más gastaba era maquetar PDF y atender consultas lentas a servicios ajenos. Se movió al navegador de quien las pide todo lo que se puede mover.

## Qué corre ahora en el navegador

| Tarea | Antes | Ahora |
| --- | --- | --- |
| PDF de la proforma y la cotización | `fpdf2` en el API | `jsPDF` en el navegador (`utils/proformaPdf.js`), con vista previa |
| Consulta de RUC al SRI | el API | el navegador (`utils/consultasPublicas.js`); el API queda de respaldo |
| Contratos y CPC por proveedor (OCDS) | el API | el navegador, 15 peticiones directas; el API queda de respaldo |

El SRI y los datos abiertos del SERCOP responden con `Access-Control-Allow-Origin: *`, así que el navegador los llama directo. El portal de compras **no** lo permite: el TDR y los ítems siguen en el worker.

El servidor sigue haciendo: guardar los datos de la proforma, **firmar** (recibe el PDF del navegador y solo estampa la firma PAdES, `POST /proformas/{id}/firmar-pdf`; el certificado no se guarda), el Word y la ficha técnica.

## Proforma casi automática

Al leer el TDR, **Armar mi proforma** deja todo listo salvo los precios:

- **Ítems de la entidad** (CPC, nombre, descripción, unidad, cantidad) pasan a la tabla de costos.
- **Datos del proveedor** (RUC, razón social, correo, teléfono, país, provincia, cantón, dirección) salen del perfil.
- **Condiciones** que el TDR trae con etiqueta, vigencia de 45 días calendario, IVA 0 % como el formulario del SOCE.
- **Requisitos** con respuesta de plantilla (sin créditos de IA).

Los ítems se leen **a demanda**: pedir un proceso marca su ficha (`registro.items_prioridad_en`, migración 0036) y el worker la lee primero, sin esperar al ciclo. El panel espera hasta 40 s a que lleguen.

## El PDF

Sigue el formulario de proformas de ínfima cuantía del SOCE: datos del proveedor, detalle del objeto de compra (No., CPC con su nombre completo, descripción, unidad, cantidad, valor unitario ofertado con cinco decimales, valor total, USD.), TOTAL, vigencia de la proforma y documentos anexos. Después, las secciones propias de la oferta: condiciones y alcance, cumplimiento del TDR (sin columna de firma: el PDF se firma una vez, en el recuadro del oferente, marcado en azul), declaración, firma y el Formulario de Perfil de Integridad.

## Pruebas

```bash
cd frontend && npm test            # port de las reglas del SRI/OCDS y generador del PDF
cd backend && python -m pytest pruebas/unidad -q
```

Las reglas de `consultasPublicas.js` repiten las de `dominio/consulta_ruc.py` y `dominio/historial.py`: si una cambia, la otra también.

## Reorganización del panel

- **Navegación:** las cuatro áreas pasaron de tarjetas grandes con texto a una sola fila de pastillas, fija al desplazar, con las pestañas de cada área justo debajo. La cabecera ocupa ~100 px en vez de ~280 px; el texto de apoyo está en el `title`.
- **Aviso del plan:** el plazo ya está en la barra superior. Solo se vuelve un aviso aparte (con botón «Pedir más tiempo») cuando quedan 30 días o menos.
- **Filtros:** en tres grupos plegables («Qué busco», «Dónde», «Más filtros»); las explicaciones largas van bajo un «?». Ya no aparecen en el Radar, que no los usa.
- **Radar:** tarjetas con nota de color, motivos como etiquetas y «Preparar oferta»; avisos, alertas y búsquedas guardadas en pestañas propias.
- **Tabla:** sombras laterales que avisan de que se desliza; la nota de la descarga a Excel va bajo un «?».
- **Roles:** la lista de usuarios solo se monta para quien administra (antes producía un 403 en consola).

## Límites que se dicen en pantalla

El RUP no tiene consulta pública; el historial es lo adjudicado a tu RUC, no tu habilitación. El SRI es un servicio público no oficial. Las condiciones copiadas del TDR se marcan «copiado del TDR · revísalo». El formulario de integridad lleva la advertencia de que no se confirmó que se exija en ínfima cuantía.

## Calidad

CI (`.github/workflows/ci.yml`): ruff, ruff format, mypy (0 errores en 292 archivos), pytest, y en el panel `npm test` + build. Las reglas del SRI y de contratos viven en Python y en JavaScript, y ambas pruebas leen los mismos casos (`compartido/reglas_consultas.json`).

## Modelo de proforma de ínfima y páginas finales (2026-11-21)

- **Formato por defecto** (`extras.formato_proforma = "infima"`): copia el «Modelo de proforma» de
  ínfima cuantía de las entidades. «PROFORMA» centrado; Cliente, Dirección, RUC y Fecha de la
  entidad; Proveedor (Razón Social), RUC, Teléfono, Dirección y Correo; tabla N° | DESCRIPCIÓN |
  CANTIDAD | UNIDAD DE MEDIDA | VALOR UNITARIO | VALOR TOTAL con cabecera celeste; SUBTOTAL, BASE
  IMPONIBLE 15%, BASE IMPONIBLE 0%, IVA 15% y TOTAL (una sola tarifa por proforma: con tarifa todo es
  base gravada, con 0 % todo es base 0 %); Forma de Pago, Vigencia, Plazo, Garantía y Lugar (vacíos →
  «El proponente se adhiere a las condiciones de la contratación» en pago, plazo y lugar);
  «Atentamente», el recuadro de firma y Razón Social y RUC. El formulario del SOCE anterior sigue con
  `"soce"` (es el de la cotización si no se elige). Igual en el PDF del navegador
  (`utils/proformaPdf.js`), el del servidor (`salida/proforma_pdf.py`) y el Word (`salida/oficina.py`).
- **Páginas finales** (`extras.paginas_finales = {id: bool}`, lista en `PAGINAS_FINALES` del
  navegador y `dominio/paginas_finales.py`): `respaldo` (código, CPC de cada ítem, alcance, detalle
  del TDR, presentación, experiencia, personal, equipo), `cumplimiento`, `declaracion`,
  `compromiso` (carta de compromiso del modelo de la entidad, apagada por defecto, con su propio
  recuadro de firma) e `integridad`. `integridad: false` de proformas antiguas se respeta.
- **Líneas fieles al TDR** (`dominio/lineas.py`): solo los ítems de la ficha o, sin ellos, la
  tabla de productos del TDR leída renglón por renglón (cabecera con DESCRIPCIÓN y CANTIDAD,
  renglones numerados desde 1). Ya no se arman con el catálogo de la empresa. Lo que devuelve la IA
  se confronta con esa fuente: se devuelven las líneas publicadas con su cantidad y unidad, y lo que
  no corresponde se quita (`lineas_descartadas` y `aviso`). Sin fuente, una línea de la IA solo queda
  si sus palabras están en el TDR; cantidad o unidad que no aparecen en el texto se marcan en
  `verificar`. Cada línea lleva `origen` (`ficha`, `tdr` o `usuario`), que se guarda con la proforma.
  `POST /v1/documentos/generar` acepta `registro_id` para tomar los ítems de la ficha.

