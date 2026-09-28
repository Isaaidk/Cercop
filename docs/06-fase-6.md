# Fase 6 — Exportación sin tope, frontend propio y retiro del legado

| Campo | Valor |
|---|---|
| Estado | Pendiente |
| Depende de | F3, F4, F5 |
| Casos de uso | CU-07, CU-09 |
| Requisitos | RF-10, RF-13, RNF-03, OE-2 |

## 1. Objetivo

Cerrar el producto: exportar **todos** los procesos que el cliente filtró o marcó, con el
frontend como servicio independiente, y eliminar el andamiaje de compatibilidad.

## 2. Alcance

**Incluido:** exportación a Excel sin tope en dos modos (`criterios` = todo lo que coincide con los
filtros; `seleccion` = los procesos marcados explícitamente) · generación asíncrona en el `worker`
por encima de un umbral de filas, con enlace temporal de descarga · exportación en línea para
conjuntos pequeños · registro de cada exportación (auditoría y retención) · frontend movido a la
carpeta `frontend/` como servicio aparte · login, gate de consentimiento, panel del administrador y
vista de procesos nuevos · migración de las cuatro pestañas actuales · retiro del shim de
compatibilidad y de las cachés en memoria.

**Excluido:** rediseño visual completo, aplicación móvil, facturación.

## 3. Reglas de exportación

| Modo | Definición |
|---|---|
| `criterios` | Todos los registros que cumplen los filtros vigentes. **Sin tope de filas.** |
| `seleccion` | Los procesos marcados explícitamente por el cliente (se guarda la lista de claves naturales, no en la URL) |
| Umbral | Por encima de `export_async_umbral_filas` la exportación va al `worker` y se entrega por enlace |
| Enlace | Temporal, expira según `export_ttl_horas` (por defecto 24 h) |
| Origen de datos | Siempre la base o la caché. **Nunca** una consulta en vivo a la fuente oficial |
| Rendimiento | La generación **no** puede ejecutarse en el hilo del event loop |

## 4. Criterios de aceptación

- [ ] Exportar 200.000 filas sin degradar el p95 de la API
- [ ] El archivo contiene **todas** las filas filtradas, no una muestra
- [ ] La exportación por selección incluye únicamente los procesos marcados
- [ ] El enlace de descarga expira pasado el TTL
- [ ] Cada exportación queda registrada con usuario, negocio, filtros y número de filas
- [ ] Las cuatro pestañas actuales funcionan igual que antes
- [ ] `grep` de rutas legadas devuelve 0 resultados tras el retiro del shim
- [ ] No quedan cachés en memoria de proceso

## 5. Riesgos

| Riesgo | Mitigación |
|---|---|
| RS-06 Exportación masiva tumba el worker | Proceso separado, escritura en streaming, umbral y tope de concurrencia |
| Pérdida de funcionalidad al retirar el legado | Migrar pestaña por pestaña y retirar el shim solo al final |
| Enlaces de descarga filtrados | Enlaces firmados y de vida corta, validados por negocio |

## 6. Implementaciones realizadas

_(Se completa al cerrar la fase.)_

## 7. Pruebas ejecutadas y resultado real

_(Se completa al cerrar la fase.)_

## 8. Evidencia de aceptación

```
(Se completa al cerrar la fase.)
```
