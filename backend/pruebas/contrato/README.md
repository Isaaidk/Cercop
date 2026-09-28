# Pruebas de contrato

Verifican que el parseo de las respuestas de la fuente oficial no cambie sin que nos enteremos.

**Regla:** nunca se llama a la fuente real desde aquí. Se usan respuestas grabadas como fixtures, en
`pruebas/contrato/fixtures/`.

Se implementa en la fase 2:

- `test_nco_parseo.py` — campo `url` con HTML embebido, separación provincia/cantón, limpieza de `contacto`.
- `test_ocds_parseo.py` — mapeo del detalle (`record`): estado, periodos, proveedor, monto.
- `test_esquema_fuente.py` — un cambio en el conjunto de claves sube `esquema_version` y alerta.
- `test_shim_legacy.py` — las rutas de compatibilidad devuelven la forma exacta del contrato antiguo,
  incluido el alias `dir` ↔ `dir_orden`.

**Cómo grabar una fixture:** ejecutarlo a mano, una sola vez, con presupuesto de peticiones y
guardando el JSON íntegro en `fixtures/`. Nunca en el pipeline de integración continua.
