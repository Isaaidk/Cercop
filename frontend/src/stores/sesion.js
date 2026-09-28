/**
 * Estado de la sesión y del consentimiento.
 *
 * Es un almacén propio y no una biblioteca de gestión de estado porque el panel tiene tres cosas que
 * recordar y una dependencia menos es una cosa menos que se rompe al desplegar.
 *
 * La decisión que importa de este archivo
 * ---------------------------------------
 * **Si falta aceptar los términos no se guarda aquí y se decide aquí, sino que lo dice el servidor.**
 * Este almacén se limita a repetir lo que respondió la API. Si el panel dedujera por su cuenta que
 * ya está todo aceptado —porque hay una marca en el navegador, por ejemplo—, bastaría con editar esa
 * marca para entrar sin aceptar; y además, el día que se publique una versión nueva de los términos,
 * el panel no se enteraría.
 */

import { computed, reactive } from 'vue'

import { api } from '@/api/endpoints'
import {
  alCaducarSesion,
  alSuspenderEmpresa,
  guardarAcceso,
  guardarRenovacion,
  leerRenovacion,
  olvidarTokens,
} from '@/api/cliente'
import { esAdministrativo, puedeExportar } from '@/utils/roles'

const estado = reactive({
  usuario: null,
  rol: null,
  sesionId: null,
  nombre: '',
  email: '',
  cargando: false,
  error: '',
  /** Políticas que el servidor dice que faltan por aceptar. */
  pendientes: [],
  /** Catálogo completo de políticas, con versión y huella. */
  catalogo: [],
  /** `true` cuando el servidor confirmó que no falta nada. `null` mientras no se sabe. */
  alDia: null,
  /** El servidor cortó el acceso a toda la empresa. */
  suspendida: false,
  /** El aviso exacto que mandó el servidor, para no reescribirlo aquí y que digan lo mismo. */
  motivoSuspension: '',
})

// Cuando el cliente HTTP no consigue renovar el token, la sesión se ha perdido de verdad. Se limpia
// aquí para que la aplicación muestre la pantalla de acceso en lugar de seguir intentando peticiones
// que van a fallar una detrás de otra.
//
// El mensaje que se enseña es el que mandó el servidor, y no uno genérico. Importa: «hay otra
// persona conectada en tu cuenta» y «tu sesión ha caducado» llevan a hacer cosas distintas, y el
// segundo mensaje ante el primero haría buscar un fallo del sistema donde hay alguien usando la
// cuenta con las mismas credenciales.
alCaducarSesion((motivo, mensaje) => {
  estado.usuario = null
  estado.sesionId = null
  estado.pendientes = []
  estado.alDia = null
  estado.error = mensaje || (motivo === 'caducada' ? 'Tu sesión ha caducado. Vuelve a entrar.' : '')
})

// La empresa entera quedó suspendida. No se cierra la sesión: se marca la bandera y el armazón
// enseña **solo** el aviso, que es lo único que se puede hacer desde ahí.
alSuspenderEmpresa((mensaje) => {
  estado.suspendida = true
  estado.motivoSuspension = mensaje
})

export const sesion = {
  estado,

  estaIdentificado: computed(() => Boolean(estado.usuario)),
  /** Solo un rol administrativo ve el panel de accesos y la presencia de los demás. */
  esAdministrativo: computed(() => esAdministrativo(estado.rol)),
  /** Puede descargar el histórico. El servidor vuelve a comprobarlo antes de entregar el archivo. */
  puedeExportar: computed(() => puedeExportar(estado.rol)),
  debeAceptar: computed(() => estado.pendientes.length > 0),

  async entrar(email, contrasena) {
    estado.cargando = true
    estado.error = ''
    try {
      const datos = await api.iniciarSesion(email.trim(), contrasena)
      aplicarSesion(datos)
      // Después de entrar se pregunta por el consentimiento. Es una petición más y evita tener que
      // confiar en el resumen que viene con la sesión, que es un dato que puede haber quedado atrás
      // si un administrador publicó una versión nueva mientras esta persona estaba dentro.
      await this.refrescarConsentimiento()
      return true
    } catch (error) {
      estado.error = error.message
      return false
    } finally {
      estado.cargando = false
    }
  },

  /**
   * Recupera la sesión al abrir el panel, si queda un token de renovación.
   *
   * Se hace con el endpoint de renovación y no con el de consulta porque el de acceso dura minutos:
   * al recargar la página casi nunca sirve, y el de renovación sí, que es exactamente para lo que
   * existe.
   */
  async recuperar() {
    const token = leerRenovacion()
    if (!token) return false

    try {
      const datos = await api.renovarSesion(token)
      aplicarSesion(datos)
      await this.refrescarConsentimiento()
      return true
    } catch {
      olvidarTokens()
      return false
    }
  },

  async refrescarConsentimiento() {
    try {
      const datos = await api.estadoConsentimiento()
      estado.pendientes = datos.politicas || []
      estado.catalogo = datos.catalogo || []
      estado.alDia = !datos.hay_pendientes
      return datos
    } catch (error) {
      // Un fallo aquí no puede dejar entrar con la puerta abierta: si no se pudo comprobar, el
      // panel trata el estado como «pendiente» y deja que el servidor decida en la siguiente
      // petición, que negará el paso. Falla cerrada.
      estado.alDia = false
      estado.error = error.message
      return null
    }
  },

  async aceptar(tipo, version, hash) {
    const datos = await api.aceptarPolitica(tipo, version, hash)
    estado.pendientes = datos.politicas || []
    estado.catalogo = datos.catalogo || []
    estado.alDia = !datos.hay_pendientes
    return datos
  },

  async revocar(tipo) {
    const datos = await api.revocarPolitica(tipo)
    estado.pendientes = datos.politicas || []
    estado.catalogo = datos.catalogo || []
    estado.alDia = !datos.hay_pendientes
    return datos
  },

  async salir() {
    const token = leerRenovacion()

    // Un solo cierre. Antes se avisaba primero del cierre de ventana y después se cerraba sesión, y
    // como la primera revocación ganaba, la sesión quedaba marcada como «se cerró la ventana» aunque
    // el usuario hubiera pulsado «Salir». El motivo que se guarda tiene que ser el que pasó.
    if (token) {
      try {
        await api.cerrarSesion(token, 'logout')
      } catch {
        /* la sesión se cierra igual en el navegador */
      }
    }

    olvidarTokens()
    estado.usuario = null
    estado.sesionId = null
    estado.nombre = ''
    estado.email = ''
    estado.rol = null
    estado.pendientes = []
    estado.catalogo = []
    estado.alDia = null
  },
}

function aplicarSesion(datos) {
  guardarAcceso(datos.token_acceso)
  guardarRenovacion(datos.token_renovacion)

  estado.usuario = datos.usuario_id
  estado.sesionId = datos.sesion_id
  estado.nombre = datos.nombre || datos.email || ''
  estado.email = datos.email || ''
  estado.rol = datos.rol
  estado.error = ''
}
