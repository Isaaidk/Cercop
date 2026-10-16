/**
 * Copiar un texto al portapapeles del sistema.
 *
 * Por qué no basta `navigator.clipboard`
 * --------------------------------------
 * La API moderna exige un **contexto seguro** (HTTPS o `localhost`). En producción se cumple, así
 * que el camino normal es ese. Pero un despliegue servido por HTTP dentro de una red interna —o el
 * acceso por la IP de la máquina, que no es `localhost`— no lo es, y ahí `navigator.clipboard` ni
 * existe: sin el respaldo, el botón de copiar no haría nada en esas instalaciones y no habría
 * ninguna pista de por qué.
 *
 * El respaldo es la técnica de siempre —un `textarea` fuera de la pantalla, seleccionar y
 * `execCommand('copy')`—, desaconsejada pero todavía funcional en todos los navegadores, y la única
 * salida cuando la API moderna no está disponible o el navegador rechaza la operación.
 *
 * Devuelve un booleano en lugar de lanzar: quien llama solo necesita saber si salió bien, para
 * enseñar «Copiado» o el aviso de que hay que copiarlo a mano. Un rechazo del navegador —el permiso
 * denegado, un documento sin foco— no puede convertirse en una excepción sin capturar.
 */

/** ¿Se puede usar la API moderna en esta página? */
function hayApiModerna() {
  if (typeof navigator === 'undefined' || !navigator.clipboard) return false
  // `isSecureContext` es lo que decide de verdad: por HTTP la propiedad existe pero el navegador
  // rechaza la escritura. Comprobarlo aquí ahorra un intento condenado en cada pulsación.
  return typeof window !== 'undefined' && window.isSecureContext === true
}

/**
 * Copia `texto` y devuelve si se pudo.
 *
 * Asíncrona porque el camino moderno lo es; el respaldo se resuelve en el acto.
 */
export async function copiarAlPortapapeles(texto) {
  const valor = String(texto ?? '')
  if (!valor) return false

  if (hayApiModerna()) {
    try {
      await navigator.clipboard.writeText(valor)
      return true
    } catch {
      // El navegador puede negarse —permiso denegado, documento sin foco—, así que se intenta el
      // respaldo antes de dar la copia por perdida.
      return copiarConTextarea(valor)
    }
  }
  return copiarConTextarea(valor)
}

/**
 * Respaldo: un `textarea` seleccionado y `execCommand('copy')`.
 *
 * Va fuera de la pantalla en lugar de oculto con `display: none` —un elemento no visible no se puede
 * seleccionar— y se retira siempre, incluso si la copia falla, para no dejar basura en el DOM. Se
 * marca `readonly` para que en móvil no aparezca el teclado al enfocarlo.
 */
function copiarConTextarea(valor) {
  let area = null
  try {
    area = document.createElement('textarea')
    area.value = valor
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.top = '-1000px'
    area.style.opacity = '0'
    document.body.appendChild(area)

    area.select()
    area.setSelectionRange(0, valor.length)
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area?.remove()
  }
}
