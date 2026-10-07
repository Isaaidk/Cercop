# Fase 4.14 — El panel de ofertas: el detalle y la url

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

**Fecha:** 2026-10-06 · **Estado:** implementado y verificado contra el portal, la API y el panel.

## 1. Objetivo

**Que abrir un proceso no descoloque la pantalla, y que su dirección abra de verdad.** La petición
original era literal: «Panel de ofertas al abrir una oferta se va a todo de lado, darle una
estructura y orden y arreglar url de las ofertas ya que son urls que no sirven». Son dos defectos
distintos y los dos están medidos:

- **Al abrir el detalle, el panel se iba de lado.** El detalle se pintaba *dentro* de la tabla, como
  una fila más con una celda que ocupaba las siete columnas. La rejilla de campos que había dentro
  mide como la tabla y la tabla mide como su fila más ancha, así que abrir un proceso estiraba el
  ancho total por encima de la pantalla: las columnas cambiaban de tamaño y aparecía el
  desplazamiento horizontal justo cuando la persona estaba leyendo.
- **Las direcciones de las ofertas no servían.** El sistema anterior componía
  `.../PLATAFORMA/datos-abiertos/proceso/<ocid>` para cada proceso de OCDS. Comprobado hoy contra el
  portal: **404**. Es decir, cada oferta del panel viejo llevaba a una página de error.

## 2. Alcance

**Incluido**

- El detalle de un proceso en un **cajón lateral**, fuera de la tabla, con el contenido agrupado en
  secciones y un solo proceso abierto a la vez.
- La **dirección del proceso en el portal**, compuesta con el `ocid` en el servidor y servida en el
  mismo campo que ya usaban las ínfimas (`enlace_publico`), con la ruta correcta verificada.
- El código de cada fila como enlace, con el mismo trato que en la tabla de ínfimas.
- Ocho pruebas nuevas del módulo de enlaces.

**Excluido (deliberadamente)**

- **La tabla de ínfimas no se toca.** Su detalle sigue siendo una fila desplegable, y es lo correcto:
  ahí el contenido es una tabla de ítems con su CPC, que se lee bien en el ancho de la tabla, y nadie
  se ha quejado de que se descoloque. Llevar las dos al mismo patrón sería cambiar lo que funciona
  por simetría.
- **La paridad de filtros con el panel de ínfimas** —provincia, estado, plazo, CPC, descripción— es
  la otra mitad de la petición original («que funcionen similar a los de ínfimas cuantías») y va
  aparte: es una tanda entera y se hace después.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| La ruta del portal y la composición de la dirección con el `ocid` | `dominio/enlaces.py` (`PORTAL_OCDS`, `PATRON_OCID`, `enlace_ocds`, `enlace_del_registro`) |
| El enlace del registro, publicado o compuesto, en el único sitio por el que pasan las filas | `salida/bd/consultas.py` |
| El cajón: secciones, enlace al portal, cierre con Escape y con el velo, foco y bloqueo del desplazamiento | `frontend/src/components/CajonDetalleOferta.vue` |
| El cajón conectado a la tabla, el código como enlace y el detalle incrustado retirado | `frontend/src/components/OfertasTab.vue` |
| Ocho pruebas: la ruta del portal, las negativas y el orden entre publicado y compuesto | `pruebas/unidad/test_enlaces.py` |

## 4. Decisiones tomadas y justificación

### 4.1 Un cajón lateral, y por qué no un diálogo centrado

Las dos formas sacan el detalle de la tabla, que es lo que arregla el descoloque. Se eligió el cajón
lateral por lo que se está mirando: el detalle se **compara** con la fila —el mismo proceso, sus
datos al lado de la lista de la que salió—, y un cajón a la derecha deja la tabla visible mientras el
diálogo centrado la tapa. Además el cajón es el patrón que el panel ya usa para los filtros en el
móvil, así que no se está inventando un lenguaje.

Lo que el cajón hace y no se ve en una captura:

- **Una sola fila abierta.** Guardar la fila y no su identificador evita que el cajón y la lista se
  separen: no hay que ir a buscar nada a ningún sitio para pintarlo.
- **Escape cierra, y el velo también.** El foco va al botón de cerrar al abrirse y vuelve a la fila
  al cerrarse, así que quien navega con el teclado no se pierde detrás del velo.
- **El desplazamiento de la página se bloquea** —con el cajón abierto, la rueda del ratón movería la
  tabla de debajo y el usuario volvería al cajón con la lista en otro sitio— y se **compensa el ancho
  de la barra** que desaparece al bloquearlo. Esto se descubrió midiendo: sin la compensación, el
  área visible de la tabla pasaba de 925 a 948 píxeles, que es exactamente el movimiento que este
  cambio viene a evitar.

### 4.2 La dirección: se comprueba contra el portal, no se adivina

El módulo de enlaces tenía escrito, con razón, que **no** se debía componer una dirección a partir
del `ocid`: «daría una URL con pinta de buena que llevaría a una página de error». Eso era cierto
para la ruta que usaba el sistema anterior y **no** para la que usa el portal. Lo que se hizo fue
medirlo:

| Dirección | Resultado |
|---|---|
| `.../PLATAFORMA/datos-abiertos/proceso/ocds-5wno2w-SIE-UTSC-2026-00004-457832` | **404 Not Found** |
| `.../PLATAFORMA/datos-abiertos/proceso/3288448` (el identificador interno) | **404 Not Found** |
| `.../PLATAFORMA/ocds/ocds-5wno2w-SIE-UTSC-2026-00004-457832` | **200** — «Procedimiento: ocds-…», con el objeto, la entidad, las etapas y el presupuesto |

La tercera es la que usa el buscador de procedimientos del portal (se llegó a ella desde su propio
listado, no por deducción), y es la que se compone. La diferencia con la primera está **en la ruta,
no en el identificador**, que es lo que despistaba.

Y sigue sin inventarse nada: si la fuente no publica enlace y el registro no trae `ocid`, no hay
enlace. El `ocid` se valida antes de entrar en la dirección —se rechaza cualquier valor con barra,
interrogante, almohadilla o espacio— porque un dato así compondría una dirección que apunta a otro
sitio, y eso es un enlace roto, que es peor que no ofrecer ninguno.

El orden también es una decisión: **primero lo que publica la fuente**. La fuente NCO publica el
suyo y es el que ella eligió; si algún día lo cambia de ruta, el panel sigue bien sin tocar nada. La
dirección compuesta solo rellena el hueco que OCDS deja.

### 4.3 Secciones, y los bloques sin datos no se pintan

Catorce campos seguidos no dicen nada: el identificador interno, el importe y la provincia pesan
distinto y se miran por motivos distintos. Van en cinco bloques —el proceso, la entidad y el lugar,
el dinero, el proveedor, las fechas— y **los que se quedan sin ningún dato no se pintan**. En la
comprobación de hoy se vio funcionando: el proceso de muestra no trae proveedor ni presupuesto, y el
cajón salió con cuatro bloques en lugar de cinco, sin huecos vacíos.

El enlace al portal va arriba y destacado porque es **la única acción** del cajón, y cuando no hay
dirección se dice en lugar de dejar un botón que no lleva a ninguna parte.

### 4.4 El enlace es el mismo dato para la tabla, el mapa y el Excel

La dirección se compone en el **servidor**, en el único sitio por el que pasan todas las filas que
salen de la base (`_con_enlace`), y viaja en `enlace_publico`. El panel solo la pinta. Esa decisión
ya existía y aquí se aprovecha: el código del Excel sale con hipervínculo sin tocar la exportación,
y el día que cambie la ruta del portal se cambia en un sitio.

## 5. Casos de uso y requisitos cubiertos

- **Mirar un proceso sin perder la lista**: el cajón se abre a un lado y la tabla no se mueve.
- **Abrir el proceso de verdad**: el enlace lleva a la ficha del portal, con sus etapas y sus
  documentos.
- **Copiar el código para pegarlo en otro sitio**: sigue siendo texto seleccionable, y además se
  puede pulsar.

## 6. Verificación

### 6.1 La tabla no se mueve (medido en el panel)

Con el panel en marcha y una empresa temporal —creada y borrada para esta comprobación—, en la
pestaña de Ofertas con 104.316 procesos:

| | Detalle cerrado | Detalle abierto |
|---|---|---|
| Ancho total de la tabla | 1205 px | **1205 px** |
| Ancho de las 7 columnas | `260 · 130 · 256 · 117 · 217 · 130 · 95` | **idénticas** |
| Área visible de la tabla | 925 px | **925 px** |

Sin la compensación de la barra de desplazamiento, la tercera fila sería `925 → 948 px`: esos 23
píxeles son el movimiento que se veía al abrir el detalle.

Y el cajón, comprobado en el mismo navegador: `role="dialog"`, título con el código del proceso, los
bloques **«El proceso», «La entidad y el lugar», «El dinero», «Las fechas»** en ese orden —el del
proveedor no se pinta porque ese proceso no lo trae—, el enlace al portal con
`rel="noopener noreferrer"`, el foco en el botón de cerrar al abrirse, el desplazamiento de la página
bloqueado y devuelto al cerrar, y el cierre funcionando con **Escape** y con el velo.

### 6.2 La url, comprobada contra el portal

Las tres direcciones de la tabla del § 4.2 se pidieron hoy desde el navegador. La que sirve devuelve
el proceso real: título, entidad compradora, fecha, etapa de planeación y presupuesto. La que usaba
el sistema anterior devuelve 404, que es el defecto que se arregla.

### 6.3 El enlace llega al panel y al Excel

En la pestaña de Ofertas, las 25 filas de la página traen su enlace con el `ocid` de su proceso:

```
href  = https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/ocds/ocds-5wno2w-SIE-UTSC-2026-00004-457832
title = «Abrir SIE-UTSC-2026-00004-457832 en el portal de la fuente»
```

Y `scripts/verificar_exportacion.py` sigue pasando entero: el mismo `enlace_publico` es el que
convierte la celda del código en un hipervínculo del libro de Excel.

### 6.4 Comprobaciones automáticas

- `ruff check` → `All checks passed` · `ruff format --check` → 236 archivos
- `mypy` → `Success: no issues found in 211 source files`
- `pytest pruebas/unidad` → **772 pasan** (8 nuevas)
- `vite build` → 90 módulos

Las ocho pruebas nuevas fijan lo que no se ve: que la ruta compuesta sea la del portal, que un `ocid`
con barra o interrogante **no** produzca enlace, que sin `ocid` no haya dirección, que lo publicado
por la fuente mande sobre lo compuesto y que sin ninguna de las dos cosas el registro se quede sin
enlace.

### 6.5 Lo que no se ha comprobado igual que lo haría una persona

La pestaña del navegador desde la que se verificó **no repinta** (no está visible), así que la
comprobación se hizo conduciendo la aplicación y midiendo el DOM: anchos, atributos, foco y
contenido. Los números son la evidencia del defecto y de su arreglo, pero **no hay captura de
pantalla**: el aspecto del cajón queda por ver a ojo del usuario.

De paso, la comprobación dejó dos cosas vistas que no eran del cambio: al recargar la página la
sesión se recuperó sola (renovación silenciosa, fase 3) y al borrar la empresa temporal el panel
volvió solo a la pantalla de acceso.

## 7. Evidencia de aceptación

- El ancho de la tabla y el de sus columnas son idénticos con el detalle abierto y cerrado (§ 6.1).
- La dirección del portal abre el proceso y la del sistema anterior da 404 (§ 6.2).
- El enlace viaja en la API y la exportación pasa entera (§ 6.3).
- 772 pruebas unitarias, `ruff` y `mypy` limpios.

## 8. Deuda técnica y pendientes

1. **Los filtros de la pestaña de ofertas siguen siendo suyos.** Tiene palabras clave, entidad, tipo
   de contratación, tipo de compra, código, fechas y fuente; el panel de ínfimas tiene además
   provincia —con casillas—, estado, plazo, CPC y descripción del producto. Es la otra mitad de la
   petición original y la siguiente tanda.
2. **El cajón no tiene enlace a los documentos del proceso.** El portal los publica dentro de su
   ficha, y traerlos aquí sería otra vez inventar direcciones: si algún día se quieren, se miran en
   la propia ficha.
3. Las pruebas de carga con k6 siguen pendientes.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| El portal cambia su ruta y los enlaces compuestos dejan de abrir | Lo que publica la fuente manda; para OCDS habría que cambiar **una** constante, y hay una prueba que la fija para que el cambio sea consciente |
| Un `ocid` con caracteres raros compone una dirección que apunta a otro sitio | Se valida con un patrón y se rechaza lo que no sea un identificador, en lugar de escapar y esperar que el portal lo entienda |
| El cajón bloquea el desplazamiento y no lo devuelve | El bloqueo y su compensación se quitan al desmontar; comprobado que la página queda como estaba al cerrar |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | ninguna (es contrato de dominio y panel) |
| Comprobaciones | ruff, ruff format, mypy, 772 pruebas unitarias, el portal, el panel con una empresa temporal y `verificar_exportacion.py` |
| Pendiente del usuario | mirar el cajón a ojo (§ 6.5) y decidir si los filtros de ofertas van en la siguiente tanda (§ 8.1) |
