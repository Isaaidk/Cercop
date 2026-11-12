# Roles, perfil de empresa, TDR y salidas

Cinco fases. Cada una se puede desplegar cuando la migración que le corresponde ya está aplicada. El orden es `0026` → `0027` → `0028` → `0029`.

```bash
cd backend
alembic upgrade head
```

Hay que reiniciar el API y el worker después. Las sesiones emitidas con `admin_negocio`, `consultor` o `lector` siguen entrando: el servidor las lee como dueño o como usuario. Al volver a iniciar sesión el token ya trae el código nuevo.

## Fase 1 — Tres roles, filtros y orden de la base

### Roles

| Código | Quién | Qué hace |
| --- | --- | --- |
| `super_admin` | Superadministrador | Igual que antes: cualquier empresa, plazos, desbloqueo, clave temporal. No se crea desde el panel. |
| `dueno_empresa` | Dueño de la empresa | Reemplaza a `admin_negocio`. Usuarios, claves y perfil de **su** empresa. No concede plazos. |
| `usuario` | Usuario regular | Reemplaza a `consultor` y a `lector`. Siempre pertenece a una empresa. Consulta, filtra, exporta y ve el TDR. No administra. |

La migración `0026` crea `rol`, `permiso` y `rol_permiso`, traduce las filas viejas y cambia el `CHECK` de `usuario.rol` por una clave foránea. Quién puede hacer qué lo decide `PERMISOS_POR_ROL` en `backend/src/contratacion/dominio/roles.py`. Las tablas son el catálogo; autorizar no depende de Redis.

El dueño solo puede asignar `usuario`. No puede crear otro dueño ni un superadministrador.

### Filtros

No se rediseñaron. Se comprobó el contrato que ya tenían:

- Un código CPC va a `registro.cpc_codigos` (`@>` si el modo es «todas», `&&` si es «cualquiera»).
- Un nombre de CPC va a `cpc_busqueda`, no al texto libre.
- `solo_cpc` deja de exigir palabras clave. No apaga la descripción, la provincia ni las fechas.
- Sin `solo_cpc`, CPC y palabras se exigen juntos.
- `cpc_clave` sigue siendo de la empresa, con RLS. Dueño y usuarios de la misma empresa comparten la lista.

El cantón se guardaba en el panel y no se enviaba a la API. Se quitó de `frontend/src/stores/filtros.js` y de la ficha de `PanelFiltros.vue`. La provincia sigue siendo el filtro geográfico.

### Orden

La migración `0028`:

- Rehace el RLS de `plantilla_excel`, `exportacion_columnas` y `cpc_clave` con `NULLIF`, para que un setting vacío no se confunda con «sin empresa».
- Borra las concesiones de la vista `contrataciones` (ya copiadas a `ofertas` en `0025`) y quita ese valor del `CHECK`.
- Índice parcial `ix_auditoria_solicitud_plazo` para «pidió más tiempo».
- Retira `conjunto_termino`, `conjunto_terminos`, `filtro_guardado` y `exportacion`, que no usaba la aplicación. Se conservan `solicitud_arco` y `punto_contacto_entidad`.
- Crea la función `asegurar_particiones()`, que el mantenimiento del worker llama en cada vuelta para los tres meses siguientes.

`backend/scripts/estado_esquema.py` lista las tablas nuevas.

## Fase 2 — Perfil de la empresa

Migración `0027`. El perfil no es una ficha de contacto: es la fuente con la que la fase 5 rellena el TDR.

- Columnas nuevas en `negocio`: razón social, nombre comercial, tipo de persona, sitio, logo, estado RUP, inicio de actividades, obligado a contabilidad, régimen. El RUC, si viene, tiene 13 dígitos (`CHECK` `NOT VALID` para no romper filas viejas) y es único cuando no está vacío.
- `negocio_dedicacion`: tipo de contratación (`bienes`, `servicios`, `obras`, `consultoria`) y procedimiento (`infima`, `subasta_inversa`, `catalogo`, `licitacion`).
- `negocio_contacto`, `negocio_actividad`, `negocio_cobertura`, `negocio_documento` (solo metadatos), `negocio_experiencia`, `negocio_personal`, `negocio_equipo`.

Todas con `negocio_id`, RLS forzada e índice por empresa.

API, con permiso `empresa.editar_perfil` para escribir:

- `GET /v1/empresa/perfil` y `PUT /v1/empresa/perfil`
- `POST` y `DELETE /v1/empresa/perfil/{coleccion}` para dedicaciones, contactos, actividades, cobertura, documentos, experiencia, personal y equipo.

En el panel, la pestaña **Perfil de empresa** (dueño y superadministrador) abre con «A qué licitaciones se dedica».

## Fase 3 — Varias salidas y fichas en paralelo

`backend/start.sh` lee `TAILSCALE_EXIT_NODES` (IPs separadas por coma). Levanta un `tailscaled` por nodo, cada uno con su proxy `localhost:1055`, `1056`, …, y exporta `NCO_PROXY_URLS`. Si esa variable no está, sigue valiendo `TAILSCALE_EXIT_NODE_IP` y un solo proxy.

`PoolSalidas` (`salida/fuentes/salidas.py`) tiene un cliente por proxy. Elige la salida con menos peticiones en vuelo. Tras tres fallos, esa salida se enfría dos minutos y el reintento usa otra. Si había proxies y no queda ninguno sano, no se sale directo desde el datacenter. Sin proxies configurados (desarrollo), se sale directo, como antes.

`FuenteNco` usa el pool. Las fichas de CPC corren en paralelo: dos por cada salida configurada (`planificador._concurrencia_fichas`). Con una sola salida, o ninguna, siguen de una en una.

Los dispositivos de salida tienen que tener IP residencial de Ecuador. Una PC o una Raspberry en casa con `tailscale up --advertise-exit-node` da salida aunque el celular esté apagado.

## Fase 4 — Ver el TDR sin guardarlo en la base

No se pudo abrir el portal desde este entorno (las peticiones de datacenter las descarta). El parser se apoya en la ficha que ya estaba en las pruebas: una tabla `Documento | Pliego.pdf`, más cualquier `<a href>` de la misma página. La misma descarga de la ficha CPC lee los documentos; no hay una petición extra.

- `registro.documentos` (jsonb, migración `0029`) guarda nombre y enlace.
- `documento_tdr` guarda estado (`pendiente`, `listo`, `error`), hash, tamaño, mime, ruta y `campos_pedido`. El binario no entra en PostgreSQL.
- `POST /v1/tdr/{registro_id}` exige `tdr.ver`, deja la fila en pendiente, anota `tdr.ver` en auditoría y responde 202. La API no habla con el portal.
- El worker, en cada vistazo del bucle, descarga **un** pendiente con `client.stream` en trozos de 64 KB, tope 25 MB, sha256 al vuelo y renombrado atómico. Carpeta `tdr_dir` (por defecto `tdr`), poda al pasar de 2 GB, vencimiento a las 24 horas.
- `GET /v1/tdr/{registro_id}/archivo/{documento_id}` lo sirve con `Content-Disposition: inline` si ya está listo.
- En el detalle de una ínfima, `VisorTdr.vue` pide el documento y sondea cada 2 segundos (hasta un minuto). El archivo se descarga con el token de la sesión y el PDF se muestra en un iframe desde esa copia local. Una URL directa no llevaría `Authorization` y el visor recibiría 401.

## Fase 5 — Rellenar el TDR con el perfil

`proponer` en `dominio/relleno.py` compara la dedicación, el CPC de la empresa (`cpc_clave`) y la cobertura con la ínfima. Si no hay dedicación, o no coinciden el tipo, el procedimiento, el CPC o la provincia, responde `aplica: false` y los motivos. No arma anexos.

Si coincide, el JSON trae oferente (razón social, RUC, representante legal, RUP, régimen), experiencia cuyo CPC o tipo encaja, personal, equipo y habilitantes, según lo que `campos_pedido` pida.

- `GET /v1/tdr/{registro_id}/relleno` exige `tdr.rellenar` (dueño y superadministrador). El usuario regular ve el pliego y no el borrador. Una ínfima (fuente `NCO`) se clasifica como procedimiento ínfima; el resto se clasifica por el texto del proceso.
- `GET /v1/tdr/{registro_id}/borrador.docx` genera el DOCX en memoria y no lo guarda.

El visor muestra el borrador al lado de la vista previa cuando el rol puede rellenar.

## Pruebas

```bash
cd backend
python -m pytest pruebas/unidad/test_roles_tres.py pruebas/unidad/test_salidas.py pruebas/unidad/test_relleno_tdr.py pruebas/unidad/test_cpc.py pruebas/unidad/test_acceso.py pruebas/unidad/test_recoger_items.py -q
```

## Qué queda fuera

- No se reescribe el PDF del pliego. El borrador sale de una plantilla propia.
- No hay subida del archivo de habilitantes: `negocio_documento` guarda la ruta y el hash cuando alguien los tenga en el almacén.
- Crear particiones de meses que ya cayeron en `auditoria_predeterminada` puede fallar con un aviso. Esas filas siguen en la partición predeterminada, que no se elimina.
- El spike contra el portal real hay que repetirlo desde una salida de Ecuador para confirmar la forma exacta de los enlaces de descarga. Si el enlace viene vacío, el pedido queda en `error` con «La ficha no trae enlace de descarga.»
