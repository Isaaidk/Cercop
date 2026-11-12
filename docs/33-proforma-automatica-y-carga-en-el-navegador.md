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

Sigue el formulario de proformas de ínfima cuantía del SOCE: datos del proveedor, detalle del objeto de compra (No., CPC con su nombre completo, descripción, unidad, cantidad, valor unitario ofertado con cinco decimales, valor total, USD.), TOTAL, vigencia de la proforma y documentos anexos. Después, las secciones propias de la oferta: condiciones, cumplimiento del TDR con un recuadro de firma por requisito, declaración, firma y el Formulario de Perfil de Integridad.

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
