/**
 * Notificaciones web del navegador: activar, apagar y saber en qué estado están.
 *
 * El navegador solo deja pedir permiso tras un clic de la persona, así que nada de esto corre solo
 * al abrir el panel (salvo `estadoActual`, que no pide nada). El servidor no recibe preguntas
 * periódicas: los mensajes los empuja el worker.
 */

import { api } from '@/api/endpoints'

const RUTA_SW = '/sw.js'

export function haySoporte() {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

/** En iPhone/iPad solo funcionan con CercoApp instalada en la pantalla de inicio (iOS 16.4+). */
export function esIosSinInstalar() {
  if (typeof navigator === 'undefined') return false
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
  const instalada = window.matchMedia?.('(display-mode: standalone)').matches
  return ios && !instalada
}

function claveABytes(base64) {
  const relleno = '='.repeat((4 - (base64.length % 4)) % 4)
  const crudo = atob((base64 + relleno).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(crudo, (c) => c.charCodeAt(0))
}

async function registro() {
  return (
    (await navigator.serviceWorker.getRegistration(RUTA_SW)) ||
    navigator.serviceWorker.register(RUTA_SW)
  )
}

/** `{ soporte, permiso, suscrito, avisarPerfil }` sin pedir permisos. */
export async function estadoActual() {
  if (!haySoporte()) return { soporte: false, permiso: 'denied', suscrito: false, avisarPerfil: false }
  const permiso = Notification.permission
  const reg = await navigator.serviceWorker.getRegistration(RUTA_SW)
  const sub = reg ? await reg.pushManager.getSubscription() : null
  if (!sub || permiso !== 'granted') return { soporte: true, permiso, suscrito: false, avisarPerfil: false }
  try {
    const estado = await api.estadoPush(sub.endpoint)
    return { soporte: true, permiso, suscrito: !!estado.suscrito, avisarPerfil: !!estado.avisar_perfil }
  } catch {
    return { soporte: true, permiso, suscrito: false, avisarPerfil: false }
  }
}

/** Pide permiso (si hace falta), suscribe este navegador y lo registra en el servidor. */
export async function activar({ avisarPerfil = true } = {}) {
  if (!haySoporte()) throw new Error('Este navegador no permite notificaciones.')
  const { disponible, clave_publica: clave } = await api.clavePush()
  if (!disponible || !clave) throw new Error('Las notificaciones aún no están disponibles.')
  const permiso = await Notification.requestPermission()
  if (permiso !== 'granted') {
    throw new Error(
      'El navegador bloqueó las notificaciones. Actívalas en el candado junto a la dirección.',
    )
  }
  const reg = await registro()
  await navigator.serviceWorker.ready
  const sub =
    (await reg.pushManager.getSubscription()) ||
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: claveABytes(clave) }))
  const datos = sub.toJSON()
  await api.suscribirPush({ endpoint: datos.endpoint, keys: datos.keys, avisar_perfil: avisarPerfil })
  return { suscrito: true, avisarPerfil }
}

/** Apaga en el servidor y en el navegador. Nunca lanza: apagar siempre debe «funcionar». */
export async function desactivar() {
  if (!haySoporte()) return
  try {
    const reg = await navigator.serviceWorker.getRegistration(RUTA_SW)
    const sub = reg ? await reg.pushManager.getSubscription() : null
    if (!sub) return
    await api.bajaPush(sub.endpoint).catch(() => {})
    await sub.unsubscribe().catch(() => {})
  } catch {
    // Nada que hacer: sin registro no hay notificaciones que apagar.
  }
}

/** Llama a `alRecibir({ titulo, cuerpo })` cuando llega un aviso con el panel abierto. */
export function escucharAvisos(alRecibir) {
  if (!haySoporte()) return () => {}
  const manejador = (evento) => {
    if (evento.data?.tipo === 'cercoapp-aviso') alRecibir(evento.data)
  }
  navigator.serviceWorker.addEventListener('message', manejador)
  return () => navigator.serviceWorker.removeEventListener('message', manejador)
}
