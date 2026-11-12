# 37 · Asistente (chat)

Un chat dentro del panel para personas que no quieren aprender cada pantalla: «recomiéndame
ínfimas», «cómo va el NIC-…», «crea una alerta de impresoras en Pichincha». Responde en español
sencillo y debajo muestra **tarjetas** con los datos (ínfimas, un proceso, la empresa, alertas,
proformas, un RUC), con botones para ir a la pantalla que corresponde o preparar la proforma.

## Dos caminos

1. **Camino rápido, sin modelo y sin cobrar** (`dominio/intencion.py`). Reglas fijas, sin tildes ni
   mayúsculas, reconocen lo que se pide casi siempre: saludo, ayuda, recomendaciones («propuestas
   para ti»), estado de un proceso por su código, mis alertas, mis ofertas, datos de mi empresa,
   consulta de un RUC en el SRI, historial de contratos de un RUC y «proforma para <código>». Se
   llama directamente a la herramienta: responde en lo que tarda la consulta (medido en local: 0,05
   a 0,5 s), no gasta créditos y funciona aunque la IA esté caída.
   Ante la duda, el detector manda al modelo: una lista solo se reconoce si el mensaje no trae
   filtros («propuestas» sí; «propuestas de limpieza en Guayas» no).
2. **Modelo con herramientas** (`aplicacion/casos_uso/asistente.py`). Lo demás va al modelo
   configurado en `IA_URL` (API de chat de OpenAI con `tools`). Recibe un prompt de sistema con la
   empresa (nombre, RUC, CPC, provincias) y la fecha de Ecuador, los últimos 12 mensajes **solo como
   texto**, y como mucho `ASISTENTE_MAX_RONDAS` vueltas de herramientas (por defecto 4); la última
   vuelta va sin herramientas para obligarlo a contestar. Temperatura 0,1 y 700 tokens.

## Créditos

Se cobra `COSTO_PREGUNTA` (1 crédito) **solo cuando el modelo contesta**. El descuento se hace
antes de llamar (es atómico) y se devuelve si el modelo falla, como en `preparar_documentos`. El
camino rápido nunca cobra. Sin IA configurada, con el circuito `ia` abierto o sin créditos, el
asistente responde una frase con sugerencias que sí funcionan sin IA: nunca un 500.

## Herramientas (`aplicacion/asistente/herramientas.py`)

Cada una llama a un caso de uso **existente** con el actor de la sesión, así que RLS, roles y vistas
concedidas se aplican igual que en la pantalla de origen. Los argumentos del modelo se validan
(tipos, listas recortadas, provincias reales, RUC válido) y al modelo solo le llegan como mucho 8
filas, resumidas en una línea cada una y marcadas como **datos, no instrucciones**. Las tarjetas
salen de los datos, no del texto generado.

| Herramienta | Caso de uso | Tarjetas |
|---|---|---|
| `buscar_infimas(texto, provincia, cpc, presupuesto_max, solo_abiertas)` | `buscar_registros.buscar` (NCO) | `infimas` |
| `propuestas_para_ti(orden, provincia)` | `ver_propuestas` | `infimas` (`ver_mas: propuestas`) |
| `estado_proceso(codigo)` | `buscar` por código + «Mis ofertas» | `proceso`, `accion` |
| `datos_empresa()` | perfil + lista de CPC | `empresa`, `accion` |
| `crear_alerta(nombre, palabras, cpc, provincias, frecuencia)` | repositorio de alertas + `previsualizar_alerta` | `alerta`, `accion` |
| `listar_alertas()` | alertas de la persona | `alertas`, `accion` |
| `mis_ofertas(etapa)` | `ver_ofertas` | `ofertas`, `accion` |
| `consultar_ruc(ruc)` | `consultar_ruc_publico` (SRI) | `ruc` |
| `historial_ruc(ruc)` | SRI (razón social) + historial OCDS | `datos`, `procesos_ruc` |
| `precio_referencia(texto_o_cpc)` | `ver_precios` | `datos` |
| `competidores(texto_o_cpc)` | `ver_proveedores` | `datos` |
| `preparar_proforma(codigo \| registro_id)` | `buscar` por código | `accion` (`preparar_oferta`) |

Una alerta vigila una sola provincia: si se piden varias, se usa la primera y el asistente lo dice.

### Historial de un RUC: de dónde sale y sus límites

Sale de los **datos abiertos del SERCOP (OCDS)**, con el mismo adaptador que «Consultar mis
contratos» del perfil (`salida/historial.py`, circuito `ocds_historial`): se busca por la razón
social que publica el SRI y cada proceso se verifica por RUC en su `record`.

- Cubre los **últimos 3 años** (el actual y los dos anteriores).
- Solo **procesos con oferta** (OCDS): **no incluye ínfimas cuantías**.
- «Procesos» es lo que la búsqueda por nombre encuentra como adjudicado (puede incluir homónimos);
  «Ganados» y «Monto adjudicado» son solo los **verificados por RUC** entre los 12 más recientes.
- No hay participaciones perdidas: OCDS publica al adjudicatario, no a todos los oferentes.
- El portal limita las consultas por minuto (responde 429); entonces el asistente lo dice y pide
  reintentar. La respuesta se recuerda 30 minutos por RUC.

## Guardado

Migración `0038`: `asistente_conversaciones` y `asistente_mensajes`, con RLS forzada por empresa;
el adaptador filtra además por `usuario_id`, porque la conversación es privada de cada persona. Se
guarda el texto, las tarjetas y las sugerencias de cada mensaje, no el historial interno del modelo.
Topes aplicados al escribir, en la misma transacción: 200 mensajes por conversación y 50
conversaciones por persona.

## API (`/v1/asistente`, con sesión)

- `GET /inicio` → saludo, contadores (propuestas, alertas activas, ofertas abiertas y las que
  cierran en 48 h; cada uno `null` si su consulta falla), sugerencias, conversaciones, `ultima_id`,
  `ia_disponible` y `creditos`.
- `GET /conversaciones`, `GET|PATCH|DELETE /conversaciones/{id}` (404 si no es de quien pregunta).
- `POST /mensajes` `{texto (1..2000), conversacion_id}` → la conversación, los dos mensajes y
  `creditos: {gastados, saldo}`.

Topes por persona: 20 mensajes y 30 inicios por minuto.

Pestañas a las que mandan las tarjetas `accion` / `ver_mas`: `propuestas`, `ofertas`, `alertas`,
`mis-ofertas`, `empresa`, `documentos`.
