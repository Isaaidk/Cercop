/**
 * Presencia: quién tiene el panel abierto, en verde o en rojo.
 *
 * Cómo funciona, y por qué no se usa `EventSource`
 * -----------------------------------------------
 * El canal de eventos de la API **exige la cabecera `Authorization`**, y `EventSource` no permite
 * enviar cabeceras. La alternativa habitual sería poner el token en la dirección —`?token=...`—, y
 * eso lo escribiría en el registro de cada intermediario por el que pase la petición: el proxy, el
 * balanceador, el servidor. Se usa `fetch` con lectura por partes, que envía la cabecera como
 * cualquier otra petición.
 *
 * El latido va aparte, cada 30 segundos, y es lo que mantiene la señal viva. Sin él, la persona
 * pasaría a rojo sola al vencer la señal aunque siguiera delante del panel.
 *
 * El cierre se avisa con `fetch` y `keepalive`, no con `navigator.sendBeacon`: por la misma razón
 * que arriba. `sendBeacon` tampoco admite cabeceras, y aceptar el token por el cuerpo sería abrir
 * una segunda forma de autenticarse, que es donde se acumulan los descuidos.
 */

import { onBeforeUnmount, onMounted, readonly, ref } from 'vue'

import { api } from '@/api/endpoints'
import { leerAcceso } from '@/api/cliente'
import { sesion as almacenSesion } from '@/stores/sesion'

export function usePresencia() {
  const conectados = ref(0)
  const total = ref(0)
  const personas = ref([])
  const alcance = ref('proceso')
  const enVivo = ref(false)
  const error = ref('')

  let controlador = null
  let temporizadorLatido = null
  let intervaloLatido = 30_000
  let detener = false

  async function latir() {
    const sesionId = almacenSesion.estado.sesionId
    if (!sesionId) return

    try {
      const respuesta = await api.latir(sesionId)
      // El servidor dice cada cuánto repetir. Se obedece en lugar de fijar el valor aquí: si alguien
      // cambia la configuración, los paneles ya abiertos se ajustan solos en el latido siguiente.
      if (respuesta?.repetir_en_seg) {
        intervaloLatido = respuesta.repetir_en_seg * 1000
      }
    } catch {
      // Un latido perdido no es grave: la señal sigue viva un rato y el siguiente la renovará. Si
      // fallara siempre, el punto se apagaría solo, que es exactamente lo que debe pasar.
    }
  }

  function programarLatido() {
    clearInterval(temporizadorLatido)
    temporizadorLatido = setInterval(latir, intervaloLatido)
  }

  async function consumirEventos() {
    controlador = new AbortController()

    try {
      const respuesta = await fetch(`${import.meta.env.VITE_API_BASE || ''}/v1/presencia/eventos`, {
        headers: {
          Accept: 'text/event-stream',
          ...(leerAcceso() ? { Authorization: `Bearer ${leerAcceso()}` } : {}),
        },
        signal: controlador.signal,
      })

      if (!respuesta.ok || !respuesta.body) {
        throw new Error(`El canal de presencia respondió ${respuesta.status}.`)
      }

      enVivo.value = true
      const lector = respuesta.body.getReader()
      const decodificador = new TextDecoder()
      let pendiente = ''

      while (!detener) {
        const { value, done } = await lector.read()
        if (done) break

        pendiente += decodificador.decode(value, { stream: true })

        // El protocolo separa los eventos con una línea en blanco. Lo que quede después del último
        // separador es un evento a medias y hay que conservarlo para la vuelta siguiente.
        const bloques = pendiente.split('\n\n')
        pendiente = bloques.pop() || ''

        for (const bloque of bloques) aplicarEvento(bloque)
      }
    } catch (fallo) {
      if (!detener) {
        error.value = fallo.message
        enVivo.value = false
      }
    }
  }

  function aplicarEvento(bloque) {
    let nombre = 'mensaje'
    const datos = []

    for (const linea of bloque.split('\n')) {
      if (linea.startsWith('event:')) nombre = linea.slice(6).trim()
      else if (linea.startsWith('data:')) datos.push(linea.slice(5).trim())
    }

    if (!datos.length) return

    let cuerpo
    try {
      cuerpo = JSON.parse(datos.join('\n'))
    } catch {
      return
    }

    // La instantánea trae el cuadro completo y es la que manda: llega cada quince segundos y corrige
    // cualquier aviso perdido. Los eventos individuales solo sirven para que el cambio se vea al
    // instante sin esperar a la siguiente relectura.
    if (nombre === 'instantanea' || Array.isArray(cuerpo.usuarios)) {
      personas.value = cuerpo.usuarios || []
      conectados.value = cuerpo.conectados || 0
      total.value = cuerpo.total || 0
      alcance.value = cuerpo.alcance || 'proceso'
      return
    }

    if (cuerpo.usuario) {
      const indice = personas.value.findIndex((p) => p.usuario_id === cuerpo.usuario.usuario_id)
      const copia = [...personas.value]
      if (indice === -1) copia.push(cuerpo.usuario)
      else copia[indice] = cuerpo.usuario

      personas.value = copia
      conectados.value = copia.filter((p) => p.estado === 'verde').length
      total.value = copia.length
    }
  }

  //
  // No se escucha `pagehide` ni ningún otro evento de descarga, y a propósito. Se hacía: la página
  // avisaba al servidor al irse y el servidor revocaba la sesión. El problema es que `pagehide`
  // también salta al **recargar**, así que pulsar F5 cerraba la sesión; y como el token de
  // renovación vive en `sessionStorage` —que sobrevive a la recarga—, la página volvía con el token
  // de una sesión ya revocada y el usuario aparecía en el acceso sin haber hecho nada.
  //
  // Ya no hace falta el aviso: al cerrar la pestaña de verdad el token se va con ella y el punto de
  // presencia pasa a rojo cuando vence el latido. Y la sesión no se cierra por cerrar una ventana,
  // sino al pulsar «Salir», al superar el tope de sesiones o al caducar.
  onMounted(async () => {
    await latir()
    programarLatido()
    consumirEventos()
  })

  onBeforeUnmount(() => {
    detener = true
    clearInterval(temporizadorLatido)
    controlador?.abort()
  })

  return {
    conectados: readonly(conectados),
    total: readonly(total),
    personas: readonly(personas),
    alcance: readonly(alcance),
    enVivo: readonly(enVivo),
    error: readonly(error),
  }
}
