/**
 * Las familias de contratación y cómo se llaman en pantalla.
 *
 * Una «familia» es de dónde sale la contratación: las **ínfimas cuantías** que publica el listado de
 * necesidades, o los **procesos con oferta** que publica OCDS. Son dos orígenes distintos, con campos
 * distintos, y se consultan por separado; verlas juntas es una opción, no la mezcla de las dos.
 *
 * El nombre vive aquí y solo aquí porque aparece en tres sitios que tienen que decir lo mismo: el
 * selector del mapa, el titular de la tabla y la pista de cada gráfica. Cuando cada uno tenía su
 * copia, bastaba reescribir una para que la pantalla dijera dos cosas distintas de lo mismo y las
 * cifras no cuadraran sin que nada explicara por qué.
 */

export const FAMILIAS = [
  // `null` es «las dos» y va primero a propósito: es la vista completa, y la que menos sorprende al
  // abrir el mapa.
  { id: null, etiqueta: 'Ambas' },
  { id: 'infimas', etiqueta: 'Ínfimas cuantías' },
  { id: 'ofertas', etiqueta: 'Ofertas' },
]

/** El nombre de una familia, para decir **qué** se está mirando encima de una gráfica. */
export function nombreDeFamilia(categoria) {
  const familia = FAMILIAS.find((opcion) => opcion.id === categoria)
  return familia && familia.id ? familia.etiqueta : 'Ambas familias'
}
