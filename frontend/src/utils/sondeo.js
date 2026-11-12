/**
 * Esperas de los sondeos (estado del TDR, latido de presencia) que no castigan al servidor.
 *
 * Con 500 a 1.000 personas, lo que más peticiones genera no es lo que alguien pulsa sino lo que se
 * repite solo. Tres reglas:
 *
 * 1. **Pestaña oculta, sondeo en pausa.** Quien deja el panel en segundo plano no necesita saber
 *    cada dos segundos cómo va su TDR: se espera a que vuelva a la pestaña y se pregunta entonces.
 * 2. **Espera creciente** (`siguientePausa`): los primeros segundos son los que importan; después,
 *    preguntar tan seguido no adelanta nada.
 * 3. **Un poco de azar** (`conAzar`): tras un despliegue o un corte, cientos de paneles reintentan a
 *    la vez; repartirlos en ±10 % evita que lleguen todos en el mismo segundo.
 */

/** La pausa siguiente: crece por `factor` hasta `maximo`. */
export function siguientePausa(pausa, { factor = 1.3, maximo = 5000 } = {}) {
  const base = Number.isFinite(pausa) && pausa > 0 ? pausa : 1000
  return Math.min(Math.round(base * factor), maximo)
}

/** `ms` con un ±`margen` de azar, para que muchos clientes no coincidan. */
export function conAzar(ms, margen = 0.1, azar = Math.random) {
  const delta = ms * margen * (azar() * 2 - 1)
  return Math.max(0, Math.round(ms + delta))
}

/** ¿Está la pestaña a la vista? Fuera del navegador (pruebas) se considera visible. */
export function pestanaVisible() {
  return typeof document === 'undefined' || !document.hidden
}

/** Resuelve cuando la pestaña vuelve a estar a la vista (o ya lo está). */
export function hastaQueSeVea() {
  if (pestanaVisible()) return Promise.resolve()
  return new Promise((resolver) => {
    const alCambiar = () => {
      if (!document.hidden) {
        document.removeEventListener('visibilitychange', alCambiar)
        resolver()
      }
    }
    document.addEventListener('visibilitychange', alCambiar)
  })
}

/** Espera `ms` y, si la pestaña quedó oculta, sigue esperando hasta que vuelva. */
export async function esperarVisible(ms) {
  await new Promise((resolver) => setTimeout(resolver, ms))
  await hastaQueSeVea()
}
