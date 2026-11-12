# Registro por RUC, RUP en PDF, alertas interactivas, ficha de ínfima y carga

## Registro empezando por el RUC

`PantallaRegistro.vue` pide primero el RUC. Con 13 dígitos bien formados (`rucConForma`, igual que `ruc_valido`) consulta al SRI desde el navegador y, si no llega, por `POST /v1/registro/consulta-ruc` (sin sesión, 20 por IP cada 10 min). Llena razón social, dirección, ciudad y sugiere el representante legal; cada campo traído lleva la marca «del SRI». En paralelo busca en los datos abiertos (OCDS) los contratos adjudicados al RUC y propone sus **CPC** (chips seleccionables) y su **experiencia**.

Al registrar, `perfil` viaja con el alta y `sembrar_perfil` / `sembrar_cpc` dejan el perfil, los contactos, la cobertura, la actividad, la experiencia y los CPC vigilados. Todo se filtra por lista blanca; un fallo al sembrar no deshace el registro.

**Corregido:** el freno por IP del alta apuntaba a `/v1/registro`, que no es ninguna ruta; el alta no tenía tope. Ahora es `/v1/registro/empresa`.

## RUP en PDF

El RUP **no tiene consulta pública**: «Imprimir RUP» y «CPC x CIIU» exigen entrar al SOCE con usuario y contraseña. Por eso la empresa sube el certificado en PDF desde «Perfil de empresa → Carga tu RUP y tus CPC».

- `POST /v1/empresa/perfil/leer-rup` (multipart, 8 MB, 10/min): `pypdf` → `dominio/rup.py::leer_rup`. Devuelve RUC, razón social, estado en el RUP, correo, teléfono, dirección, ciudad, representante y **cada CPC con su descripción**. No guarda.
- `POST /v1/empresa/perfil/aplicar-rup`: carga lo elegido. Cada CPC entra en los CPC vigilados y en «Qué ofreces» (sección 0-4 bien, 5-9 servicio, con «CPC xxxxx» en la descripción). No duplica.

Se validó con un PDF real que trae **los dos certificados** (RUC del SRI, 2 páginas, y RUP del SERCOP, 1 página). De ahí salen: RUC, razón social, tipo de contribuyente, régimen, contabilidad, estado y categoría en el RUP, dirección completa con referencia, ciudad, provincia, celular, correo, titular o representante, las **actividades económicas con su CIIU** (incluida la que cruza de página) y **cada CPC con su descripción completa** (aunque ocupe dos líneas). `pruebas/unidad/datos/rup_y_ruc_ejemplo.txt` es ese texto con los datos personales reemplazados.

Al cargar, además de los CPC, entran las actividades CIIU (`negocio_actividad`) y la cobertura.

## Worker: las ínfimas llegan con sus CPC

Antes, la vuelta corta (150 s) traía las ínfimas nuevas sin leer su ficha; los CPC llegaban en el ciclo completo (15 min, después de OCDS) y con una ficha a la vez. Ahora:

- si la vuelta corta trae nuevas, lee sus fichas en la misma pasada (`FICHAS_POR_VIGILANCIA`, 60 por defecto) y solo entonces sube la generación de la caché: la ínfima aparece en el panel ya con sus CPC;
- dos fichas en vuelo también sin proxy (el limitador sigue imponiendo 0,6 s entre peticiones);
- el listado expone `items_leidos`, y el panel dice «Leyendo CPC…» en vez de dejar la celda vacía.

## Alertas

- `ConstructorAlerta.vue`: chips de palabras y CPC, sugerencias del perfil y de los CPC vigilados, provincia en lista, rangos de presupuesto, frecuencia segmentada, nombre sugerido y **vista previa en vivo** (`POST /v1/alertas/vista-previa`, misma regla que el worker, caché de 2 min por criterio).
- **Corregido:** la revisión de una alerta miraba solo 40 candidatos desde la última revisión; una alerta diaria perdía casi todo. Ahora 2.000.

## Ficha de ínfima

`FichaInfima.vue` reemplaza el detalle desplegado: acciones (Llenar TDR y proforma, Bajar TDR, Ver en el portal, Copiar código), línea de tiempo del plazo, objeto completo, ítems con CPC, documentos, y en el lateral entidad (con RUC sacado del código), contacto con enlaces, y el resto de datos plegado. La tabla muestra «Llenar TDR» en cada fila, un borde por urgencia y un resumen de la página. En móvil las fichas ahora tienen acciones.

## Carga

- Las pestañas del panel se montan al abrirse por primera vez (antes todas al entrar: cada inicio de sesión pedía radar, mercado, perfil y documentos). Su código se baja aparte: el paquete principal pasó de 682 kB a 480 kB.
- `Documentos` atiende el código inicial al montarse (`immediate`), porque ahora puede montarse justo con «Llenar TDR».
- **Corregido:** `preparar_documentos.py` usaba `datos_entidad` sin importarla; leer un TDR fallaba.

## Pruebas

`test_registro_por_ruc.py`, `test_rup.py`, `test_alertas_vista_previa.py` y las nuevas de `test_vigilancia_listado.py`.

## Mis ofertas (CRM)

Pestaña nueva en «Preparar oferta» (`MisOfertas.vue`, `GET/PATCH /v1/mis-ofertas`). Tablero por etapa con arrastrar y soltar, calendario de cierres, lista, y panel de detalle con nota y monto adjudicado. Indicadores: tasa de éxito (adjudicadas / resueltas), adjudicado, en juego y cierres en 7 días.

Lo que se guarda: 5 columnas en `proforma` (migración 0037: `etapa`, `etapa_en`, `monto_adjudicado`, `nota` ≤ 500, `recordado_en`). Las cifras se calculan al leer.

**Recordatorio:** el worker avisa en el panel (`aviso`) de cada proforma en borrador cuyo proceso cierra en menos de 24 h. Una vez por proforma.

**RLS:** el worker lee proformas y alertas de todas las empresas con funciones `SECURITY DEFINER` (`proformas_por_cerrar`, `alertas_activas`). Antes, las alertas dependían de que el rol tuviera `rolbypassrls` (riesgo R-05): al cerrarlo se habrían apagado sin error.

## Precio de referencia, competidores y proforma desde el aviso

- La ficha de la ínfima muestra, para su CPC principal (5 dígitos), la mediana y el rango adjudicado y los 5 proveedores que más ganan. Usa `/v1/mercado/precios` y `/v1/mercado/proveedores`, y se recuerda por CPC en la sesión.
- Cada aviso del radar con proceso trae «Preparar proforma», que abre «Preparar oferta» con el proceso cargado (`listar_avisos` devuelve el `codigo`).

## Prueba de carga contra el despliegue

`FRENO_IPS_EXENTAS` deja pasar sin freno la IP de la máquina que prepara y corre la prueba (la preparación inicia sesión con cientos de cuentas). Vacía por defecto; se quita al terminar.

## Proforma: datos de la entidad, título y firma (2026-11-12)

- **Entidad desde los anexos** (`dominio/entidad.py`): RUC, dirección, teléfono y correo de la entidad se sacan del texto del TDR, del pliego y del acta (membrete, pie, cláusulas), sin confundirlos con los del proveedor ni con los huecos del formulario. La ficha del portal manda; los anexos completan. Antes, al subir el TDR a mano, el bloque «Entidad» salía con RUC, dirección y teléfono vacíos.
- **Título editable**: «Título de la proforma» se sugiere como «Proforma — objeto · código» y se puede cambiar. Sale bajo el encabezado del PDF y es el título en «Mis ofertas».
- **Firma con el sello de FirmaEC** (`salida/firma.py`): QR a la izquierda y, en Courier, «Validar únicamente en FirmaEC.», «Firmado electrónicamente por:» y el nombre en negrita. El QR lleva el mismo formato que FirmaEC (comprobado leyendo el QR de un PDF firmado con FirmaEC): `FIRMADO POR / RAZON / LOCALIZACION / FECHA (-05:00) / VALIDAR CON: www.firmadigital.gob.ec`; la última línea dice «Firmado digitalmente con CercoApp», porque decir FirmaEC sería falso. Dependencia nueva: `qrcode`.

## Propuestas para ti (2026-11-12)

`GET /v1/propuestas` y la pantalla `PropuestasParaTi.vue` (primer ítem de «Oportunidades para ti», con acceso destacado en Inicio): todas las ínfimas vigentes con plazo abierto que la empresa puede ofertar. Interés por CPC (prefijo de al menos 4 dígitos, en los dos sentidos; CPC vigilados, del RUP y de la experiencia) o por lo que ofrece; respeta cobertura (provincia/cantón) y rango de presupuesto, sin excluir lo que no publica presupuesto. Cada propuesta dice por qué se sugiere. Paginación real, caché de 120 s por empresa con huella de criterios. Con la empresa de prueba: 76 propuestas, consulta en 0,36 s.

## Proforma: todos los anexos y títulos únicos (2026-11-12)

**Todos los anexos de la ínfima.** Antes solo se leían PDF y `.txt`, y un anexo sin apartados
titulados (un formulario, una tabla de ítems) se descartaba. Ahora:

- `infraestructura/adaptadores/salida/texto_anexos.py` lee PDF, Word `.docx` (cuerpo, tablas,
  encabezados y pies: ahí va el membrete de la entidad), Excel `.xlsx` (fila por fila, «|» entre
  celdas) y ZIP con esos archivos (sin ZIP dentro de ZIP; topes de 30 archivos y 40 MB
  descomprimidos; rutas con `..` se ignoran). `.doc`, `.xls` y `.rar` se avisan con qué hacer.
- Cada anexo leído aporta apartados, presupuesto, datos de la entidad **y su texto**.
  `dominio/anexos.py::contexto_de_anexos` junta el texto de todos (6.000 caracteres por archivo,
  24.000 en total) en el apartado `contexto_anexos` de la lectura. El panel lo muestra plegado y la
  IA lo recibe como `texto_de_todos_los_anexos` (14.000 caracteres) para armar líneas, cantidades,
  plazos y condiciones.
- La regla de actas no cambia: solo la más reciente, y lo que corrige manda.
- Un anexo bajado que no se puede leer aparece como `sin_texto` con el motivo (escaneo, formato
  antiguo); el escaneo se puede subir en el recuadro, que tiene OCR.
- Lo que se sube a mano también acepta Word, Excel y ZIP.

**Títulos únicos.** `dominio/titulos.py`: dos títulos son el mismo si solo cambian mayúsculas,
tildes, guiones o espacios. `crear_proforma` rechaza un título repetido (409) y sugiere el siguiente
libre («… (2)»). `GET /v1/documentos/proformas/titulos` da los usados; el panel avisa al escribir,
ofrece «Usar «… (2)»» y el título sugerido ya sale libre.
