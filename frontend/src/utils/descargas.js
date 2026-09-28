/**
 * Guardar en disco un archivo que la API ya ha entregado.
 *
 * La descarga se hace con `fetch` —porque necesita la cabecera del token— así que el navegador no la
 * trata como una descarga: los bytes llegan a la memoria de la página y hay que ofrecerlos
 * explícitamente. Eso es lo que hace la etiqueta `<a download>` con una dirección de objeto.
 *
 * El enlace se añade al documento antes de pulsarlo porque algunos navegadores ignoran el `click()`
 * de un elemento que no está en el árbol, y se retira después para no dejar basura en el DOM.
 */

/** Segundos que se espera antes de liberar la dirección del objeto. Ver `guardarArchivo`. */
const ESPERA_LIBERACION_MS = 60_000

export function guardarArchivo(contenido, nombre) {
  const url = URL.createObjectURL(contenido)
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = nombre || 'descarga'
  enlace.rel = 'noopener'
  enlace.style.display = 'none'

  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()

  // La dirección del objeto **no** se libera de inmediato. `click()` solo inicia la descarga; si se
  // revoca en el acto, algunos navegadores cancelan el guardado a medio escribir y el archivo sale
  // corrupto o no sale. Un minuto es de sobra para que la lectura termine y evita que la memoria del
  // blob quede retenida indefinidamente si el usuario exporta muchas veces seguidas.
  setTimeout(() => URL.revokeObjectURL(url), ESPERA_LIBERACION_MS)
}
