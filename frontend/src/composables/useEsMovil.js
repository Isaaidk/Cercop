/**
 * ¿La ventana está en el ancho de móvil?
 *
 * El panel de filtros se comporta de dos maneras distintas según el ancho: en escritorio es una
 * columna fija al lado del contenido y en móvil un cajón que se desliza por encima. El mismo botón
 * —la hamburguesa de la barra superior— gobierna los dos, y **no puede tratarlos igual**: en
 * escritorio «visible» significa que la columna está a la vista, y en móvil significa que el cajón
 * está abierto. Además arrancan al revés: la columna se ve al abrir el panel y el cajón no.
 *
 * Por eso la decisión no puede quedar solo en CSS, que es donde vive el aspecto pero no el estado.
 * Aquí se lee el ancho de verdad, con la misma medida que la consulta de medios del componente
 * —1023 px—: si una de las dos cambiara sin la otra, el botón gobernaría una cosa y la pantalla
 * mostraría otra.
 */

import { onBeforeUnmount, readonly, ref } from 'vue'

/** El mismo ancho que la consulta de medios de `VistaPanel.vue`. */
export const ANCHO_DE_MOVIL = '(max-width: 1023px)'

export function useEsMovil() {
  // Se lee al construir y no en `onMounted` para que la primera pintura ya sea la correcta: si
  // empezara en `false`, en un móvil el panel se pintaría un instante como escritorio.
  const consulta = window.matchMedia?.(ANCHO_DE_MOVIL) || null
  const esMovil = ref(Boolean(consulta?.matches))

  function alCambiar(evento) {
    esMovil.value = evento.matches
  }

  // `addEventListener` en lugar de `addListener`, que está obsoleto y no existe en los navegadores
  // recientes. Sin `consulta` —un entorno sin `matchMedia`— el ancho queda fijo en el de la primera
  // lectura, que es el comportamiento razonable cuando no hay a quién preguntar.
  consulta?.addEventListener('change', alCambiar)
  onBeforeUnmount(() => consulta?.removeEventListener('change', alCambiar))

  return readonly(esMovil)
}
