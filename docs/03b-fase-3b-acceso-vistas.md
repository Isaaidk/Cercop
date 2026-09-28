# Fase 3.5 — Acceso a vistas por suscripción

| Campo | Valor |
|---|---|
| Estado | **Completada** — 2026-09-27 |
| Depende de | F3 |
| Casos de uso | CU-15, CU-16 |
| Requisitos | RF-20, RF-21, RF-22 |

## 1. Objetivo

Que el administrador conceda o retire el acceso de un usuario a cada vista del panel **por plazos
cerrados**, sin escribir fechas ni tocar la base: elige «7 días», «30 días», «3 meses», «6 meses» o
«1 año», pulsa *dar acceso*, y el backend calcula y hace cumplir el vencimiento.

Es la pieza que convierte el producto en algo vendible por suscripción: el mismo código sirve para
una prueba de 7 días, para un mes suelto y para una anualidad.

## 2. Análisis de alternativas

Se evaluaron cinco formas de modelar la concesión. La decisión y su porqué:

| # | Alternativa | A favor | En contra | Veredicto |
|---|---|---|---|---|
| A | Columnas en `usuario` (`acceso_hasta`, `vistas text[]`) | Una sola fila, consulta trivial | **Un único vencimiento para todas las vistas**: no se puede dar «Ofertas 7 días» y «Necesidades 1 año». Sin historial: quién concedió y cuándo se pierde. Renovar sobrescribe, así que no hay auditoría. No soporta el producto real | **Descartada** |
| B | Tabla nueva `acceso_vista`, una fila por (usuario, vista) | Periodo independiente por vista · historial *append-only* · revocar sin borrar · RLS natural por `negocio_id` · extender es insertar, no sobrescribir | Una tabla más y un `join` | **Elegida** |
| C | Guardar solo el plazo (`plazo_dias`) y calcular el vencimiento al leer | Ahorra una columna | El vencimiento **se mueve solo**: el mismo registro significa cosas distintas según cuándo se lea. Imposible auditar «cuándo venció de verdad». Cambiar el catálogo reescribe el pasado. No se puede indexar «quién vence hoy» | **Descartada** |
| D | Tabla de planes y políticas que la concesión hereda | Es el destino natural de un SaaS maduro | Sobredimensionado para «por el momento el admin da el acceso». Añade un nivel de indirección que hoy no aporta nada | **Aplazada** (ver §7) |
| E | Job periódico que marca `vencido` | Estado explícito y fácil de listar | **Un job que falla en silencio regala acceso.** La seguridad no puede depender de que un proceso se ejecute a tiempo | **Insuficiente por sí sola**; se usa solo como higiene |

### 2.1 La decisión, en una frase

**`acceso_vista` con una fila por concesión, vencimiento absoluto guardado y comprobado al leer.**

### 2.2 Las cinco reglas que hacen que esto sea seguro

1. **Denegar por defecto.** La ausencia de fila es la ausencia de permiso. Conceder inserta; retirar
   marca `revocado_en`. «Dar acceso» y «deshabilitar la vista» son el mismo modelo, no dos.
2. **El vencimiento es un instante absoluto, guardado.** El plazo es un atajo de la interfaz; la
   verdad es `vence_en`. El cliente **nunca** envía una fecha.
3. **Se comprueba al leer, no al limpiar.** `vence_en > now() AND revocado_en IS NULL`. Una
   comparación de fechas no puede fallar; un proceso en segundo plano sí. El job solo marca y avisa.
4. **El historial no se sobrescribe.** Revocar es una marca suave; extender es una fila nueva. La
   concesión vigente es la de `vence_en` más lejano, así que **extender nunca acorta**.
5. **El aislamiento lo impone la base.** `negocio_id` en la tabla y política RLS: un administrador no
   puede conceder nada fuera de su negocio aunque manipule la petición.

### 2.3 Reglas de negocio del plazo

| Plazo | Código | Cálculo | Nota |
|---|---|---|---|
| 7 días | `7d` | `desde + 7 × 24 h` | Duración exacta |
| 30 días | `30d` | `desde + 30 × 24 h` | Duración exacta, no «un mes» |
| 3 meses | `3m` | Meses de calendario con ajuste de día | 31 de enero → 30 de abril |
| 6 meses | `6m` | Meses de calendario con ajuste de día | |
| 1 año | `1a` | 12 meses de calendario | 29 de febrero → 28 de febrero |

Los dos primeros son duraciones (`30 días` es una cifra comercial, no un mes). Los tres últimos son
calendario, porque «un año» debe caer en el mismo día del año siguiente. El ajuste de día evita el
error clásico: sin él, «3 meses desde el 31 de enero» desbordaría a marzo.

### 2.4 Efecto sobre la caché

El permiso **no puede cachearse mucho tiempo**: si se retira el acceso y la respuesta sigue en
caché, el usuario conserva la vista. Por eso el TTL del permiso es corto (≤ 60 s) y la revocación
sube además una generación por usuario, de modo que la siguiente lectura falla el acierto sin
esperar al vencimiento natural.

## 3. Diseño

```
  Admin pulsa "dar acceso"          Ordenador de la vista
        │                                   │
        ▼                                   ▼
  POST /v1/accesos                    GET /v1/<vista>/...
   plazo = "30d"  ──┐                  ¿vence_en > now()?
                    │                        │
     el backend calcula                       │
     vence_en = otorgado_en + 30d              │
                    │                         │
                    ▼                         ▼
            acceso_vista  ───────────▶ permiso vigente (RLS por negocio)
```

| Regla | Definición |
|---|---|
| Conceder | Inserta una fila vigente desde ahora; recalcula `vence_en`; registra en `auditoria` |
| Extender | Inserta otra fila; la vigente pasa a ser la de vencimiento más lejano |
| Retirar | Marca `revocado_en` en todas las filas activas de ese par (usuario, vista) |
| Vigencia | `vence_en > now() AND revocado_en IS NULL` |
| Vistas | Conjunto cerrado en el código; el cliente no puede inventar una vista nueva |
| Aviso | Se marca «por vencer» a 7 días, para que el administrador pueda renovar a tiempo |

## 4. Criterios de aceptación

- [x] Conceder «30 días» y leer el acceso: el vencimiento es exactamente ahora + 30 x 24 h
- [x] Conceder «3 meses» el 31 de enero y leer: vence el 30 de abril, no el 2 de marzo
- [x] Un acceso vencido **no** concede la vista, aunque nadie haya ejecutado ningún proceso
- [x] Retirar el acceso deja de concederlo en la siguiente comprobación, con la caché activa
- [x] Extender un acceso vigente **nunca** lo acorta
- [x] Retirar y volver a conceder deja dos filas de historial, no una reescrita
- [x] Un administrador no puede conceder ni ver accesos de otro negocio
- [x] El cliente no puede enviar una fecha ni un plazo fuera del catálogo: la petición se rechaza
- [x] El tablero devuelve **todas** las vistas, con estado explícito para las que no tienen acceso

## 5. Implementaciones realizadas

| Componente | Archivo | Qué resuelve |
|---|---|---|
| Reglas del dominio | `dominio/acceso.py` | `Vista`, `Plazo`, `AccesoVista`, `concesion_vigente`, `tablero`, `negocio_objetivo` |
| Errores | `dominio/errores.py` | `ErrorDominio`, `DatoInvalido`, `SinPermiso`, `NoEncontrado` |
| Puerto | `aplicacion/puertos/accesos.py` | Contrato en objetos del dominio, no en filas |
| Casos de uso | `aplicacion/casos_uso/gestionar_acceso.py` | Conceder, retirar, consultar, listar usuarios, exigir acceso |
| Actor | `aplicacion/actor.py` | Quién ejecuta, con su negocio y su rol |
| Persistencia | `salida/bd/accesos.py` | Concesiones bajo contexto de negocio |
| Migración | `alembic/versions/0003_acceso_vistas.py` | Tabla, índices y política de RLS |
| Migración correctiva | `alembic/versions/0004_politicas_contexto_vacio.py` | `NULLIF(..., '')` en todas las políticas (ver §7.1) |
| Endpoints | `routers/accesos.py` | Catálogo, listado, tablero, conceder y retirar |

### 5.1 Lo que hace segura la funcionalidad

- **El cliente nunca envía una fecha.** Manda un código del catálogo y el servidor calcula el
  vencimiento. Un cliente manipulado no puede concederse diez años.
- **El vencimiento se comprueba al leer.** No hay ningún proceso que marque caducidades, así que un
  `job` que no se ejecuta no puede regalar acceso.
- **Retirar es inmediato, con caché incluida.** La retirada sube la generación del usuario, de modo
  que el permiso cacheado queda inservible en la petición siguiente, no al minuto.
- **El aislamiento lo impone la base.** `acceso_vista` lleva `negocio_id` y política RLS; la comprobación
  de rol del dominio es la primera barrera, no la única.
- **La vista es un conjunto cerrado.** Añadir una exige código y migración, que es lo que se quiere en
  una frontera de autorización.

## 6. Pruebas ejecutadas y resultado real

| Conjunto | Cantidad | Resultado |
|---|---|---|
| `pruebas/unidad/test_acceso.py` | 38 | **38 pasan** |
| `pruebas/integracion/test_acceso_vistas.py` | 15 | **15 pasan** |

Las pruebas de integración se conectan con un **rol de aplicación real** (`NOSUPERUSER NOBYPASSRLS`),
porque con un superusuario el aislamiento no se aplica y la prueba no demostraría nada. Se comprueba
explícitamente que ese rol no puede saltarse RLS: si esa prueba falla, todas las demás sobre el
aislamiento son decorativas.

## 7. Defectos y hallazgos

### 7.1 Una conexión reutilizada fallaba en lugar de denegar

La documentación de la fase 1 afirmaba que, sin contexto, `current_setting(..., true)` devuelve `NULL`
y la comparación deniega. Es cierto **la primera vez**. A partir de ahí no: una variable de
configuración propia, una vez fijada, deja un marcador en la sesión, y al revertirse el `SET LOCAL` el
marcador queda con valor **vacío**, no inexistente. Y `''::uuid` no es `NULL`: es un error.

Con un grupo de conexiones reutilizándolas, el efecto era que la segunda petición que llegara por una
conexión ya usada devolvía **un error de servidor** en lugar de denegar. Se corrigió en la migración
**0004** cambiando la expresión por `NULLIF(current_setting('app.negocio_id', true), '')::uuid`. No se
editó la migración 0002 porque ya estaba aplicada: una migración aplicada no se reescribe.

Lo encontró `test_sin_contexto_no_se_ve_ninguna_concesion`, que es exactamente la prueba que existía
para verificar esa afirmación.

### 7.2 El rol de la aplicación se salta RLS

`scripts/estado_esquema.py` informa de que el rol de la conexión tiene `rolbypassrls=True`. Es el rol
`postgres` de Supabase. Las políticas y las pruebas son correctas, pero **mientras `DATABASE_URL`
apunte ahí, en producción no se aplican**. Es la tarea pendiente R-05, ahora medida.

## 8. Evidencia de aceptación

```text
$ PRUEBAS_INTEGRACION=1 pytest pruebas/integracion -q
29 passed

$ alembic current
0004 (head)

$ python scripts/estado_esquema.py
Tablas  : las 13 esperadas existen
Aislamiento: activo y forzado en las 12 tablas
  AVISO: este rol es superusuario=False y puede saltarse RLS=True.
```

Y sobre la base real, con un rol sin privilegios:

```text
PASSED test_las_tablas_de_acceso_tienen_aislamiento_forzado
PASSED test_el_rol_de_aplicacion_no_puede_saltarse_el_aislamiento
PASSED test_un_negocio_no_ve_los_accesos_de_otro
PASSED test_un_negocio_no_puede_conceder_en_nombre_de_otro
PASSED test_sin_contexto_no_se_ve_ninguna_concesion
PASSED test_la_base_rechaza_un_vencimiento_anterior_a_la_concesion
PASSED test_la_base_rechaza_un_plazo_fuera_del_catalogo
```

## 9. Deuda técnica declarada

| Tema | Motivo | Fase |
|---|---|---|
| Las vistas todavía no se exigen en los endpoints de lectura | `exigir_acceso_a_vista` está implementado y probado, pero conectarlo al token es de F4 | F4 |
| Sin canal de presencia | El listado muestra usuarios **registrados**; verde/rojo de conexión llega con el SSE | F4 |
| Sin aviso de vencimiento | El cálculo (`por_vencer`) existe; falta el correo o el aviso en el panel | F4 |
| Sin planes | La tabla de planes que hereda concesiones es la evolución natural, pero hoy no aporta nada | Futuro |

