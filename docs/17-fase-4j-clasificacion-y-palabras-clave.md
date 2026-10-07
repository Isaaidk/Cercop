# Fase 4.10 — Clasificar por código y deshacer de verdad una palabra clave

> Documento de fase según la plantilla de `documentacion.md` § 9.2.

## 1. Objetivo

Cerrar dos defectos que se tapaban entre sí y que, juntos, hacían que el panel pareciera roto en dos
sitios distintos:

- **El filtro por clasificación devolvía casi nada.** Quien buscaba por CPC obtenía un puñado de
  filas donde debía haber cientos: parte del histórico tenía la clasificación sin leer, y la parte
  que la tenía se buscaba por el **texto** de la descripción, no por el código.
- **Una palabra clave dada de baja no se podía volver a dar de alta en quince minutos.** El panel
  decía que ya estaba, y no estaba.

## 2. Alcance

**Incluido**

- Filtrar por **código de CPC** contra la columna de códigos, con el modo `todas` / `cualquiera`
  aplicado también a los códigos.
- El interruptor **«solo CPC»**: buscar por clasificación sin exigir además las palabras clave.
- La **baja de una palabra clave** de verdad, con su endpoint, y la ventana de re-encolado arreglada.
- El arreglo de la carrera del panel al quitar una clasificación.
- El listado de ofertas, que buscaba con el borrador del formulario en lugar de con lo aplicado, y
  que sumaba las palabras con «y» cuando debía hacerlo con «o».
- La retirada de la columna «Estado del proceso» del listado de ofertas, que no aportaba nada a esa
  pestaña.

**Excluido**

- Cambiar el índice de texto completo de la descripción del CPC: sigue siendo el que hace que buscar
  «lavado» encuentre la clasificación por su nombre, y es lo que se quiere al escribir una palabra.

## 3. Implementaciones realizadas

| Qué | Dónde |
|---|---|
| Reconocimiento de un término como código (`^\d{6,}$`) | `dominio/busqueda.py` (`PATRON_CODIGO_CPC`, `es_codigo_cpc`) |
| Criterio `solo_cpc` y su huella de caché | `dominio/busqueda.py` (`Filtros.solo_cpc`, `canonico`, `descripcion`) |
| Filtro por código contra `cpc_codigos` (`@>` o `&&` según el modo) | `bd/consultas.py` (`_filtro_cpc`) |
| Parámetro `solo_cpc` en la API | `routers/busqueda.py` |
| Caso de uso de baja de un término | `casos_uso/encolar_termino.py` (`quitar_termino`) |
| Endpoint de baja | `routers/terminos.py` (`POST /v1/terminos/quitar`) |
| Ventana de re-encolado por término y no por el histórico | `casos_uso/encolar_termino.py` (`en_cola`) |
| Baja por chip, interruptor «solo CPC» y arreglo de la carrera | `frontend/src/components/GestorPalabras{Clave,Cpc}.vue`, `stores/filtros.js` |
| Modo «o» y criterios aplicados en el listado de ofertas | `frontend/src/components/OfertasTab.vue` |
| `quitarTermino` | `frontend/src/api/endpoints.js` |

## 4. Decisiones tomadas y justificación

### 4.1 El código se busca contra los códigos, no contra la descripción

`cpc_codigos` ya existía —y ya tenía su índice— pero **no lo usaba ninguna consulta**: el filtro
comparaba el término contra el texto de las descripciones. Para un código como `871410032` eso es
buscar un número dentro de una frase: funcionaba solo si alguien había escrito la descripción con ese
número dentro. Ahora un término que parece un código (`^\d{6,}$`) se compara contra el arreglo de
códigos, con `@>` cuando el modo es «todas» —el proceso tiene que tener **ese** código— y con `&&`
cuando es «cualquiera» —le vale tener alguno de los pedidos—. Las palabras siguen por el índice de
texto: son dos preguntas distintas y merecen dos caminos.

### 4.2 `solo_cpc` tiene que entrar en la huella de la caché

El interruptor cambia el resultado con los mismos criterios visibles, así que si no entrara en la
clave del caché, dos consultas distintas compartirían entrada y una de las dos recibiría la respuesta
de la otra. Entra como `"sc"` en `canonico()`, y hay una prueba que lo comprueba: es el tipo de
defecto que no da error, solo resultados de otra consulta.

### 4.3 La baja de un término necesitaba un camino que no existía

`RepositorioTerminos.desuscribir` estaba escrito y **no lo llamaba nadie**: no había forma de darse
de baja. El caso de uso `quitar_termino` lo llama y devuelve un booleano —«¿se quitó algo?»— en lugar
de fallar si no había nada que quitar: pedir dos veces lo mismo no es un error.

Y el motivo de que la baja no surtiera efecto estaba en la ventana de re-encolado: `en_cola` miraba
la **última ingesta del término**, que puede ser de hace un cuarto de hora, así que volver a darlo de
alta no encolaba nada y el chip reaparecía sin que nadie hubiera buscado. Ahora la ventana se mide
contra el intervalo de ingesta derivado de la configuración, y una suscripción **nueva** siempre
entra en cola.

### 4.4 El panel quitaba la clasificación y no esperaba la respuesta

`quitarCpc` lanzaba la petición y modificaba la lista sin esperarla: si la petición fallaba, la
pantalla ya había borrado algo que el servidor seguía teniendo. Ahora se espera, y solo entonces se
toca la lista. Lo mismo en la baja de palabras clave, que además recarga la lista desde el servidor
en lugar de suponer el resultado.

### 4.5 El listado de ofertas buscaba con lo que no estaba aplicado

Dos defectos en la misma función: los parámetros salían del **borrador** del formulario en lugar de
los criterios aplicados —así que la tabla se movía antes de pulsar «Aplicar»— y las palabras se
sumaban con «y», cuando en un listado de ofertas lo que se quiere es «cualquiera de estas». La
columna «Estado del proceso» se retira: en esa pestaña no acota nada útil y ensuciaba la lectura.

## 5. Casos de uso y requisitos cubiertos

- CU-01 (consultar el histórico con filtros) y CU-05 (localizar una contratación concreta).
- CU-06 (gestionar las palabras clave), que ahora tiene también la baja.
- RF-04, RF-06, OE-3.

## 6. Pruebas ejecutadas y resultado real

- `ruff check` → `All checks passed` · `ruff format --check` → 225 archivos ya formateados
- `mypy` → `Success: no issues found in 208 source files`
- `pytest pruebas/unidad` → **738 pasan** (2 de `test_encolar_termino.py` nuevas, 7 en
  `test_consultas_bd.py`, 4 en `test_busqueda.py` y 3 en `test_criterios_cpc.py`)
- `vite build` → 86 módulos en 2,5 s
- Contra la base real, `scripts/verificar_cpc_lista.py 871410032` → **11 filas**
- El atraso de fichas sin leer quedó a cero: **64 fichas leídas, 0 pendientes**; las ínfimas de NCO
  son 6.397 filas y **6.393 tienen código de CPC**.

## 7. Evidencia de aceptación

- Un código de CPC filtra por código y una palabra sigue filtrando por texto, con una prueba por
  camino.
- El modo `cualquiera` usa `&&` y el modo `todas` usa `@>`, comprobado en el SQL generado.
- `solo_cpc` sin códigos no filtra nada (una prueba que protege el caso degenerado).
- La baja de un término devuelve `{"quitado": true}` la primera vez y `false` si no había nada, sin
  error en ninguno de los dos casos.
- La consulta por código **no** se guarda en caché, que era la regla que ya aplicaba `Filtros.cacheable`.

## 8. Deuda técnica y pendientes

- El código de CPC solo existe en las ínfimas de NCO: OCDS no publica clasificación, así que el
  criterio es útil en una pestaña y vacío en la otra. Está declarado, no es un defecto nuevo.
- La descripción del CPC sigue buscándose por texto completo con `simple`; para términos numéricos
  muy cortos puede devolver más de lo esperado.

## 9. Riesgos abiertos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Un término que parece un código pero es una palabra (`2024`) se busca por código y no encuentra nada | El patrón exige seis dígitos o más; con menos sigue por texto |
| La baja de un término no encola pero tampoco borra lo ya ingerido | Es lo correcto: el histórico ya está guardado y no se pierde; solo deja de vigilarese |

## 10. Aprobación

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-10-06 |
| Migraciones | sin cambios de esquema |
| Comprobaciones | ruff, ruff format, mypy, 738 pruebas unitarias y `vite build` en verde |
