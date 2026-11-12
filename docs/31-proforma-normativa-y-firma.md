# Proforma conforme a la norma, extracción del TDR y firma en cada recuadro

## Qué dice la norma (y qué no)

Fuentes leídas: la presentación del SERCOP «Necesidades de ínfima cuantía – envío de proformas» (enero 2023) y la Resolución **R.E-SERCOP-2026-0005** (vigente, 7-ago-2026).

- La proforma de ínfima cuantía **tiene los efectos de la oferta** (art. 149 del Reglamento, según la presentación). La entidad publica la necesidad con objeto, especificaciones o TDR, contacto y término de proformas (mínimo 1 día).
- **La firma electrónica no es exigible en la proforma**: en la ínfima cuantía solo lo es en el instrumento que formaliza la contratación (contrato, orden de compra o factura), según el Oficio Circular SERCOP-SERCOP-2020-0022-C, num. 4.3. El sistema la ofrece como opcional.
- La Resolución 2026-0005 expide el **Formulario de Perfil de Integridad del Proveedor** (Anexo I), que se presenta con la oferta, y el modelo de **Declaración Juramentada de Integridad** (Anexo II), que es notarial y se otorga antes de suscribir el contrato. No se pudo confirmar en las fuentes si el Anexo I se exige en la ínfima cuantía; por eso va incluido por defecto en la proforma y se puede quitar.

Los artículos del Reglamento se renumeraron con el decreto 193 (oct-2025). No se citan números de artículo del reglamento nuevo que no se hayan leído.

## Qué cambió

| Pieza | Archivo |
| --- | --- |
| Verificación de la oferta (errores que bloquean la firma, avisos) | `dominio/verificacion.py`, `GET /v1/documentos/proformas/{id}/verificacion` |
| Recuadros de firma registrados al maquetar (uno por requisito, el final y el del Anexo I) | `salida/proforma_pdf.py` (`armar_proforma`, `armar_ficha`) |
| Anexo I con el texto del modelo oficial | `salida/proforma_pdf.py` (`_integridad`) |
| Una firma PAdES por recuadro, encadenadas; sello compacto en las celdas | `salida/firma.py` |
| Campos «ETIQUETA: valor» del formulario del TDR, aunque el PDF salga en una línea | `dominio/documentos.py` (`extraer_campos`) |
| Condiciones de la oferta tomadas del TDR antes que de frases adivinadas | `dominio/oferta.py` |
| Datos clave del TDR, casilla de integridad, revisión y firma en el panel | `frontend/src/components/Documentos.vue` |

## Reglas de la verificación

Bloquean la firma: razón social, RUC con forma válida (13 dígitos, provincia, establecimiento ≠ 000), contacto, entidad, objeto, fecha, líneas con descripción, cantidad y precio, totales coherentes, vigencia, plazo de entrega y forma de pago. Avisan: representante, dirección, código del proceso, unidad, IVA distinto de 0 y 15 %, lugar y garantía, requisitos sin respuesta, proforma sin Anexo I.

El RUC se valida solo por su forma; no se consulta el SRI.

## Pruebas

```bash
cd backend
python -m pytest pruebas/unidad/test_proforma_normativa.py -q
```
