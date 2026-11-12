# Perfil de empresa y consulta de RUC

## Qué hace

`POST /v1/empresa/perfil/consulta-ruc` con `{ "ruc": "<13 dígitos>" }` consulta al SRI y devuelve una **propuesta** de perfil. No guarda nada: la pantalla muestra lo que se llenaría, la persona elige y aplica.

Exige el permiso `empresa.editar_perfil` (dueño y superadministrador). Valida la forma del RUC antes de llamar al SRI.

| El SRI publica | Se propone para |
| --- | --- |
| Razón social, nombre de fantasía | Razón social, nombre comercial |
| Tipo de contribuyente | Tipo de persona |
| Régimen y categoría | Régimen tributario |
| Obligado a llevar contabilidad | Obligado a contabilidad |
| Fecha de inicio de actividades | Inicio de actividades |
| Representante legal (cédula y nombre) | Contacto «representante legal» |
| Establecimientos (matriz) | Dirección y ciudad |
| Establecimientos abiertos | Cobertura por provincia y cantón |
| Actividad económica principal | Actividad (como texto: el SRI no da el código CIIU) |
| Estado, contribuyente fantasma, transacciones inexistentes | Avisos |

**No lo publica el SRI**, y queda a mano: correo, teléfono, CIIU y estado en el RUP.

## Limitaciones

- **No es una API documentada.** Es el servicio REST que usa la página pública «Consulta de RUC» del SRI (`srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest/...`). Puede cambiar o bloquear sin aviso. Si falla, la pantalla dice que se llenen los datos a mano; nada más depende de él.
- **RUP.** No se encontró un servicio público del SERCOP que devuelva el estado de un proveedor en el RUP. El estado se elige a mano. Si el SERCOP publica uno, se agrega como segundo adaptador junto a `salida/sri.py`.
- Desde un datacenter el SRI puede responder distinto que desde una conexión residencial. No se probó el despliegue.

## Archivos

| Pieza | Archivo |
| --- | --- |
| Cliente del SRI | `backend/src/contratacion/infraestructura/adaptadores/salida/sri.py` |
| Del SRI a la propuesta | `backend/src/contratacion/dominio/consulta_ruc.py` |
| Caso de uso y ruta | `aplicacion/casos_uso/gestionar_perfil.py`, `routers/perfil.py` |
| Pantalla | `frontend/src/components/PerfilEmpresa.vue`, `ColeccionPerfil.vue` |
| Pruebas | `backend/pruebas/unidad/test_consulta_ruc.py` (el SRI se simula) |

Además, guardar la identidad ahora convierte `fecha_inicio_actividades` a fecha: antes, mandar ese campo fallaba con un error de base de datos.

## Historial de contratos y CPC (datos abiertos)

`POST /v1/empresa/perfil/consulta-contratos` con `{ "ruc", "razon_social" }`. No guarda nada; exige `empresa.editar_perfil` y tiene tope de 6 por minuto por persona.

**El RUP no tiene consulta pública** (se buscó en la documentación del SERCOP, en el portal y en los datos abiertos: ninguna ruta lo expone). Lo que sí existe, documentado, es la API de Contrataciones Abiertas (OCDS): `search_ocds` con el filtro `supplier` (por nombre) y `record` (el proceso completo, con el RUC del adjudicatario y los CPC de lo adjudicado). De ahí se arma una **aproximación honesta**: los CPC con los que la empresa ya vendió al Estado y los contratos que puede declarar como experiencia. Es historial, no habilitación.

- La búsqueda por nombre trae homónimos: cada candidato se **verifica por RUC** en su `record`.
- El nombre se corta en la primera comilla, paréntesis o coma y se le quitan las formas societarias del final. El filtro busca el texto tal cual dentro del nombre del adjudicatario.
- Acotado: 3 años, los 12 procesos más recientes, 4 consultas a la vez. Tarda unos 12 s la primera vez; la respuesta se recuerda 30 minutos (un minuto si no hubo resultados).
- Un proveedor que vende con otro nombre o solo por catálogo puede salir sin resultados.

Archivos: `dominio/historial.py`, `salida/historial.py`, ruta en `routers/perfil.py`, tarjeta en `PerfilEmpresa.vue`, pruebas en `test_historial.py`.
