/**
 * Qué página se está viendo, según la dirección del navegador.
 *
 * Por qué no hay biblioteca de enrutado
 * -------------------------------------
 * La parte pública son cuatro direcciones fijas —la portada, la entrada, el registro y la página de
 * contratación pública— y ninguna lleva parámetros ni se anida dentro de otra. Una biblioteca de
 * enrutado resolvería eso mismo con más piezas que mantener: una dependencia más que se actualiza,
 * que puede romper la compilación al desplegar y que hay que conocer antes de tocar nada. El
 * proyecto ya declara esa preferencia en `stores/sesion.js` —«una dependencia menos es una cosa
 * menos que se rompe al desplegar»—, así que aquí se sigue el mismo criterio.
 *
 * Lo que sí hacía falta, y es lo que hay aquí, son tres cosas pequeñas:
 *
 * 1. Traducir la dirección a un nombre de página y el nombre a una dirección.
 * 2. Navegar sin recargar cuando alguien pulsa un enlace interno.
 * 3. Enterarse de los botones «atrás» y «adelante» del navegador.
 *
 * Lo que **no** hay aquí, a propósito
 * ----------------------------------
 * Este módulo no sabe nada de sesiones. No decide si alguien puede ver el panel ni si le faltan
 * términos por aceptar: eso lo responde el servidor y lo aplica `App.vue`. Aquí solo se dice **qué
 * dirección se pidió**. Si esta pieza dedujera permisos, bastaría con escribir otra dirección en la
 * barra del navegador para saltarse la puerta.
 */

import { readonly, ref } from 'vue'

/**
 * Las direcciones públicas, con el nombre que usa `App.vue` para decidir qué pantalla pinta.
 *
 * El nombre y la dirección se mantienen juntos a propósito: separados, añadir una página son dos
 * ediciones en dos sitios y es cuestión de tiempo que una de las dos se olvide.
 */
export const RUTAS = Object.freeze({
  inicio: '/',
  login: '/login',
  registro: '/registro',
  contratacion: '/contratacion-publica-ecuador',
})

/** El camino inverso, para traducir una dirección escrita a mano en un nombre de página. */
const PAGINA_POR_RUTA = Object.freeze({
  [RUTAS.inicio]: 'inicio',
  [RUTAS.login]: 'login',
  [RUTAS.registro]: 'registro',
  [RUTAS.contratacion]: 'contratacion',
})

/**
 * La dirección sin la barra final.
 *
 * `/login/` y `/login` son la misma página. Si existieran las dos, serían dos direcciones sirviendo
 * el mismo contenido, y habría que elegir cuál se declara canónica y mantener la otra redirigida.
 * Se quita la barra aquí y así la duplicada no llega a existir.
 */
function sinBarraFinal(ruta) {
  if (!ruta || ruta.length <= 1) return ruta || '/'
  return ruta.replace(/\/+$/, '') || '/'
}

/**
 * Qué página corresponde a la dirección que hay ahora mismo en el navegador.
 *
 * Una dirección desconocida devuelve `no-encontrada` y **no** cae en la portada: caer en la portada
 * haría que cualquier dirección inventada respondiera con un 200 y contenido, que es exactamente lo
 * que un buscador entiende por «esta dirección existe». El servidor entrega el mismo documento para
 * todas —lo hace Caddy con `try_files`—, así que la única pieza que puede distinguirlas es esta.
 */
function paginaDeLaDireccion() {
  const ruta = sinBarraFinal(window.location.pathname)
  return PAGINA_POR_RUTA[ruta] || 'no-encontrada'
}

/** La página actual. Es la única fuente de verdad de este módulo. */
const pagina = ref(paginaDeLaDireccion())

/** Se expone de solo lectura: cambiar la página se hace con `ir`, que además mueve la dirección. */
export const paginaActual = readonly(pagina)

/**
 * Cambia de página sin recargar.
 *
 * `reemplazar` sustituye la entrada del historial en lugar de añadir una. Se usa al corregir una
 * dirección que no corresponde —por ejemplo, `/login` con la sesión ya abierta—: dejar esa entrada
 * haría que el botón «atrás» devolviera a una dirección que se acaba de corregir, y quedaría un
 * rebote sin salida entre las dos.
 */
export function ir(paginaDestino, { reemplazar = false } = {}) {
  const ruta = RUTAS[paginaDestino]
  if (!ruta) return

  const yaEstamos = sinBarraFinal(window.location.pathname) === ruta

  if (!yaEstamos) {
    if (reemplazar) window.history.replaceState({}, '', ruta)
    else window.history.pushState({}, '', ruta)

    // Se vuelve arriba: sin esto, pulsar «Ingresar» desde el final de la portada dejaría la pantalla
    // de acceso desplazada a la altura a la que estaba la portada, y parecería que no ha pasado nada.
    window.scrollTo(0, 0)
  }

  // `pushState` y `replaceState` no avisan a nadie de que han cambiado la dirección, así que la
  // página se recalcula aquí. Escuchar `popstate` no sirve para esto: ese evento es solo para los
  // botones del navegador.
  pagina.value = paginaDeLaDireccion()
}

// Los botones «atrás» y «adelante» sí avisan, y solo ellos.
window.addEventListener('popstate', () => {
  pagina.value = paginaDeLaDireccion()
  window.scrollTo(0, 0)
})

/**
 * Navegar sin recargar cuando se pulsa un enlace interno.
 *
 * Sin esto, cada enlace de la portada recargaría la aplicación entera: se vería un instante en
 * blanco mientras el navegador vuelve a pedir y a ejecutar todo el panel. Se atiende en el documento
 * y no en cada enlace para que valga también para los enlaces que se añadan más adelante.
 */
function alPulsar(evento) {
  if (evento.defaultPrevented || evento.button !== 0) return

  // Con una tecla modificadora se está pidiendo abrir en otra pestaña o en otra ventana, y ahí manda
  // el navegador: interceptarlo sería quitarle a la persona algo que ya ha pedido.
  if (evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return

  const enlace = evento.target instanceof Element ? evento.target.closest('a[href]') : null
  if (!enlace) return
  if (enlace.target && enlace.target !== '_self') return
  if (enlace.hasAttribute('download')) return

  const destino = enlace.getAttribute('href')
  // Solo se atienden direcciones internas. `#`, `mailto:`, `tel:` y cualquier otro dominio se dejan
  // al navegador, que hará lo correcto con ellos.
  if (!destino || !destino.startsWith('/')) return

  const ruta = sinBarraFinal(destino.split('#')[0].split('?')[0])
  const nombre = PAGINA_POR_RUTA[ruta]
  // Una dirección interna que este módulo no sepa pintar también se deja al navegador: hará la
  // petición, el servidor entregará el documento y la aplicación mostrará «no encontrada». Es mejor
  // eso que interceptarla para acabar en una pantalla que no es la que se pidió.
  if (!nombre) return

  evento.preventDefault()
  ir(nombre)
}

document.addEventListener('click', alPulsar)
