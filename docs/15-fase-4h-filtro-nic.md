# Fase 4.8 — Buscar una ínfima cuantía por su NIC

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

## 1. Objetivo

Poder **localizar una necesidad de contratación concreta por su código**. El panel acotaba por
palabras clave, por clasificación CPC, por provincia, por estado y por fechas, pero no por el
identificador que la ficha publica y que todo el mundo cita: el **NIC**
(«NIC-1768120280001-2022-00003»). Quien tiene ese código delante —en un correo, en una ficha
impresa, en el portal— y quiere ver esa necesidad en el panel no tenía forma de pedirla.

## 2. Alcance

**Incluido**

- Un campo **NIC de la ínfima cuantía** en el panel de filtros, junto a los demás criterios y por
  tanto sujeto al botón de aplicar.
- Búsqueda **por fragmento**, que es como se usa de verdad: el código entero casi nunca se recuerda.
- La prueba de la costura entre la petición y los criterios, y un apartado 9 en
  `scripts/verificar_filtros.py` que lo comprueba contra la base real.

**Excluido (deliberadamente)**

- **No se toca la API ni el esquema.** El criterio `codigo` ya existía en `Filtros`, ya llegaba al
  `WHERE` de la consulta y ya viajaba a la tabla, a las gráficas y a la exportación. Lo que faltaba
  era que el panel lo ofreciera con el nombre del negocio.
- **No se añade al listado de ofertas.** Esa pestaña tiene su propio formulario y ya incluye un campo
  «Código», que es el mismo criterio.
- **No se valida el formato.** Un NIC inventado devuelve cero, que es la respuesta correcta; validar
  la forma sería rechazar códigos que la fuente publique mañana con otro patrón.

## 3. Implementaciones realizadas

| Componente | Archivo / símbolo | Qué hace |
|---|---|---|
| Panel (almacén) | `frontend/src/stores/filtros.js` → `estado.codigo` | El criterio, en el borrador y entre los que viajan a la API. Entra en `CAMPOS_DE_CRITERIO`, en `hayFiltros`, en `cuantos`, en `parametros` y en `limpiarTodo`. |
| Panel (control) | `frontend/src/components/PanelFiltros.vue` | El campo «NIC de la ínfima cuantía», con la pista de que vale un fragmento. |
| Pruebas | `backend/pruebas/unidad/test_criterios_cpc.py` | Dos casos nuevos: el NIC llega a los criterios como `codigo`, y sin parámetro no hay criterio. |
| Medida | `backend/scripts/verificar_filtros.py` § 9 | Toma un NIC real, lo busca entero, por fragmento, inventado y acotado a ínfimas. |

## 4. Decisiones tomadas y justificación

**Se reutiliza `codigo` y no se crea un criterio `nic`.** El NIC **es** el código de la necesidad:
el mapeo de la fuente lo traduce (`codigo_contratacion` → `codigo`, en `nco_mapeos.py`) y es lo que
la tabla pinta en su primera columna. Un criterio nuevo con su propia condición SQL sería una copia
de la que ya existe, y dos condiciones que **deben** coincidir acaban separándose en el primer
arreglo: el síntoma sería un filtro que encuentra unas filas y otras no.

**Compara por fragmento, no por igualdad.** `Filtros.codigo` ya se documenta así («quien busca un
proceso teclea los últimos dígitos») y es lo que hace útil el campo: se pega el código del portal o
se recuerdan seis dígitos, y las dos cosas encuentran la necesidad. La comparación es `ILIKE`, así
que las mayúsculas y las minúsculas dan igual.

**No se guarda en el caché, y ya estaba decidido.** `Filtros.cacheable` excluye `codigo` por el
mismo motivo que el texto libre: es lo que teclea cada persona, su espacio de combinaciones es
ilimitado y casi ninguna se repite. No hay nada que cambiar; se comprueba en la verificación para
que no se pierda por el camino.

**Pasa por el botón de aplicar, como el resto del panel lateral.** No es una excepción como «Ver
solo hoy»: el NIC es un criterio más y aplicar todos juntos es lo que mantiene coherentes la tabla,
las gráficas y el mapa.

## 5. Casos de uso y requisitos cubiertos

| ID | Descripción | Estado |
|---|---|---|
| CU-03 | Consulta del histórico con filtros: el NIC es un criterio más de esa consulta, y entra en la clave de caché igual que los demás | Cubierto |

No añade requisitos nuevos: es un criterio de búsqueda sobre datos que ya se servían.

## 6. Pruebas ejecutadas y resultado real

| Prueba | Comando | Resultado |
|---|---|---|
| Unidad (2 nuevas) | `pytest pruebas/unidad` | **723 passed** |
| Lint y tipos | `ruff check .` · `ruff format --check` · `mypy src pruebas scripts` | `All checks passed!` · archivos tocados ya formateados · `no issues found in 207 source files` |
| Compilación del panel | `npx vite build --outDir <fuera del proyecto>` | `✓ 86 modules transformed` · `built in 2.13s` |
| NIC contra la base real | sonda de solo lectura (mismas consultas que el apartado 9 de `scripts/verificar_filtros.py`) | **1** fila para el NIC completo · **39** para su fragmento · **0** para un código inventado · `cacheable = False` |

## 7. Evidencia de aceptación

Un NIC real de la base (`NIC-0360016310001-2026-00053`), buscado con el mismo criterio que envía el
panel:

```
NIC de muestra: NIC-0360016310001-2026-00053
  codigo completo      -> 1
  fragmento 26-00053 -> 39
  inexistente          -> 0
  + categoria=infimas  -> 1
  cacheable            -> False
```

Las cuatro invariantes que importan están ahí: el código completo encuentra **su** fila; un fragmento
suyo encuentra esa y sus vecinas —por eso el fragmento acota pero no promete exactitud—; un código
inventado devuelve **cero** en lugar del listado entero; y la búsqueda **no** se guarda en el caché.

Y el guion permanente incorpora estas cuatro comprobaciones como **apartado 9**
(`scripts/verificar_filtros.py`), que es la forma de repetirlas sin depender de una sonda suelta.

## 8. Deuda técnica y pendientes

- **El NIC solo existe en NCO.** En el mapa, con la familia puesta en «todas», el criterio compara
  contra el código de cualquier fuente; como los códigos de OCDS no empiezan por `NIC-`, en la
  práctica no devuelve ofertas, pero un fragmento numérico corto podría casar con el título de una.
  Si molesta, el arreglo es añadir `categoria=infimas` al criterio cuando lleve forma de NIC.
- **No hay ayuda de formato.** El campo no dice que el código empieza por `NIC-`; lo sugiere el
  marcador de ejemplo, que es lo mínimo.
- **El guion de verificación completo es lento contra la base remota.** Medido el 2026-10-02: con
  la API y el worker levantados compiten por las conexiones del agrupador y alguna tanda se queda
  esperando; conviene **pararlos antes de pasarlo**, como ya advertía la documentación de operación.
  Por eso la comprobación del NIC se hizo primero con una sonda de solo lectura de cinco consultas,
  que es exactamente lo que el apartado 9 repite.

## 9. Riesgos abiertos y mitigaciones

- **Un código muy largo no cabe en el campo.** Es un campo de texto normal: se desplaza al escribir.
  No hay riesgo de recorte en el valor.
- **El fragmento puede traer vecinos.** Es deliberado y la pista del campo lo dice; quien quiera
  exactitud pega el código completo.

## 10. Aprobación

| Rol | Nombre | Fecha | Veredicto |
|---|---|---|---|
| Ingeniero QA | — | 2026-10-02 | Pendiente de revisión formal |
| Revisor de Código | — | 2026-10-02 | Pendiente de revisión formal |
