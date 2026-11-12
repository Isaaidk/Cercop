# Guía de diseño del panel (rediseño 2026-11)

Objetivo que pidió el cliente: **moderno, fácil de entender, que el usuario no se agobie**. Cada pantalla responde a una pregunta y tiene **una acción principal**.

## Estructura

- **Menú lateral izquierdo** (fijo en escritorio, cajón en móvil) con las áreas y sus pantallas. Reemplaza la fila de pastillas y pestañas de arriba.
  1. **Inicio** — resumen del día: ínfimas nuevas que te calzan, cierres próximos, avisos.
  2. **Buscar oportunidades** — Ínfimas cuantías · Procesos con oferta (OCDS) · Mapa · Estadísticas.
  3. **Oportunidades para ti** (antes «Inteligencia comercial») — Recomendadas (radar) · Mis alertas y avisos · Precios y competencia (mercado).
  4. **Ofertar** — Preparar oferta (documentos) · Mis ofertas (CRM).
  5. **Mi empresa** — Perfil y RUP · Plantilla de Excel · Usuarios · (plataforma: Empresas).
- Cada ítem del menú lleva **icono + nombre corto**, y el área una frase de una línea que dice para qué sirve.
- La barra superior queda mínima: nombre de la pantalla actual, búsqueda rápida si aplica, avisos, cuenta.

## Color

- Base **neutra**: fondos blancos y grises muy suaves, texto gris oscuro. **Un solo color de acento** (el azul `--acento`) para la acción principal, el enlace y el elemento seleccionado.
- Los colores de estado (`--ok`, `--aviso`, `--error`, `--info`) **solo** en insignias pequeñas (texto + fondo suave), **nunca** en bordes de fila, fondos de bloques grandes ni barras de color. Nada de semáforos llenando la tabla.
- Urgencia del plazo: una insignia discreta («Cierra hoy», «2 días») con texto; rojo solo si cierra hoy o mañana.

## Tipografía y espacio

- Escala existente (`--t-*`, `--e-*`). Títulos de pantalla `--t-xl`; texto base `--t-base`. Más aire, menos bordes: separar con espacio antes que con líneas.
- Tarjetas con borde `--borde` de 1 px y radio `--r-3`; sombra solo al pasar el ratón.

## Patrones

- **Estado vacío** con explicación de una frase + el botón que lo resuelve.
- **Ayuda contextual**: un «?» o un texto de una línea bajo el título, no párrafos.
- **Pasos** (asistente) solo cuando el proceso es lineal (preparar una oferta). Indicador de pasos arriba, botón «Siguiente» abajo a la derecha, «Atrás» a la izquierda.
- **Botones**: una acción principal por bloque (`boton--principal`); el resto secundarias o fantasma.
- **Formularios**: autollenar todo lo que ya sabemos (perfil, RUP, SRI, ficha del proceso) y marcarlo con «autollenado · revisa»; el usuario solo completa lo que falta.
- Accesible: foco visible, `aria-*`, contraste AA, `prefers-reduced-motion`.

## Reglas para quien edite

- Solo tokens de `main.css`; nada de colores sueltos en hex.
- No cambiar funcionalidades ni llamadas al API: es un rediseño de presentación y flujo.
- Cada componente sigue funcionando en móvil (≤ 640 px) y en tema oscuro.
