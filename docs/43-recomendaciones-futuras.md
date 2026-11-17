# Recomendaciones para hacer en el futuro

Fecha: 17 de noviembre de 2026. Ordenadas por lo que más conviene hacer primero.

## 1. Bajar la factura de Railway

| Qué | Ahorro estimado | Esfuerzo |
|---|---|---|
| Revisar cuántos procesos tiene encendidos el **API**. Hoy usa 0,5 GB de RAM en promedio (≈ $5/mes) con casi nada de CPU. Ajustar el número de procesos de uvicorn a lo que pide el tráfico real, y repetir la prueba de 200 usuarios antes de dejarlo. | $2 a $3/mes | Bajo |
| Medir la RAM del worker durante un mes. Hoy usa ≈ 0,13 GB (≈ $1,30/mes), y ahí poco más se puede ahorrar. | — | — |

**No conviene llevar los workers al servidor de la casa.** Ahorraría como mucho $1,30 al mes, pero:
- Obliga a abrir la base de datos a internet.
- Railway cobra la salida de datos hacia la casa.
- Si se va la luz o el internet en la casa, se detienen las ínfimas y las notificaciones sin que nadie se entere.

## 2. Datos del SERCOP

- **Panel de OCDS.** El SERCOP retiró `datosabiertos.compraspublicas.gob.ec`, que ahora redirige a su portal institucional.
  - Si lo publica en otra dirección, hay que apuntar CercoApp a la nueva.
  - Mientras tanto, el panel de procesos OCDS puede llenarse con los archivos del registro de Open Contracting, la misma fuente que ya usa "Buscar mis contratos". Tienen datos hasta el 10 de noviembre de 2026; sirven como histórico, no para procesos abiertos.
- **"Buscar mis contratos"** sigue consultando al SERCOP en vivo y volverá a funcionar cuando el SERCOP habilite otra vez sus datos abiertos.
  - Decisión del 17-11-2026: no importar los archivos anuales del registro de Open Contracting.
  - Se probó: 27 164 RUC en 14 MB, unos 2 minutos por año en Railway. Se revirtió (commit 21de7d6, revertido) para no cargar la base.
  - Si el SERCOP no vuelve, esa es la alternativa ya probada. Se puede recuperar con `git show 21de7d6`.
- **Recomendaciones con contratos.** Cuando haya datos, se puede calcular, por cada CPC:
  - qué entidades lo compran más;
  - cuántos proveedores compiten;
  - el monto típico.

  Serviría para recomendar "a quién venderle" y para estimar precios.

## 3. Pendientes técnicos pequeños

- `/sw.js` (notificaciones) se sirve con `Cache-Control: max-age=14400` y no con `no-cache`. Una mejora del aviso tarda hasta 4 h en llegar a los navegadores. Hay que revisar cómo Railway construye el servicio `panel`.
- En iPhone las notificaciones solo funcionan con CercoApp instalada en la pantalla de inicio. Agregar un `manifest.webmanifest` con el logo y explicar en la campana cómo instalarla.
- El mensaje "Inténtalo en unos minutos" de la consulta en vivo al SERCOP ya solo aparece si nunca se importaron contratos. Se puede quitar cuando la importación lleve unos meses estable.

## 4. Seguridad (ya anotados, siguen pendientes)

- Revisar si la base de producción tiene un **proxy TCP público**. Si nadie lo usa, quitarlo.
- Empresas duplicadas con el mismo RUC en producción: unificarlas.
- Avisos de `pip-audit`: actualizar las dependencias señaladas.
- Revisar la lista de accesos (ACL) antigua del worker.

## 5. Diseño

- El rediseño (colores del logo, modo oscuro, animaciones, revisión de textos) espera tu aprobación del lienzo. Se haría en una rama `rediseno`, tocando solo estilos y plantillas, sin cambiar datos ni lógica.
