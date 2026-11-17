/*
 * Service worker de CercoApp: SOLO notificaciones.
 *
 * No guarda nada en caché ni intercepta peticiones (no hay `fetch`): el panel funciona igual que
 * siempre, con o sin este archivo. Recibe el mensaje que manda el worker del servidor, lo enseña
 * como notificación del sistema y, si el panel está abierto, le avisa para que suene la marimba y
 * muestre el aviso dentro de la página.
 */

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (evento) => evento.waitUntil(self.clients.claim()))

self.addEventListener('push', (evento) => {
  let datos = {}
  try {
    datos = evento.data ? evento.data.json() : {}
  } catch {
    datos = { cuerpo: evento.data ? evento.data.text() : '' }
  }
  const titulo = datos.titulo || 'CercoApp'
  const opciones = {
    body: datos.cuerpo || 'Tienes una oportunidad nueva.',
    icon: '/logo-cercoapp.png',
    badge: '/logo-cercoapp.png',
    tag: datos.tag || 'cercoapp-avisos',
    renotify: true,
    data: { url: datos.url || '/' },
    lang: 'es-EC',
  }
  evento.waitUntil(
    (async () => {
      const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const ventana of ventanas) {
        ventana.postMessage({ tipo: 'cercoapp-aviso', titulo, cuerpo: opciones.body })
      }
      await self.registration.showNotification(titulo, opciones)
    })(),
  )
})

self.addEventListener('notificationclick', (evento) => {
  evento.notification.close()
  const destino = new URL(evento.notification.data?.url || '/', self.location.origin).href
  evento.waitUntil(
    (async () => {
      const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      for (const ventana of ventanas) {
        if (ventana.url.startsWith(self.location.origin) && 'focus' in ventana) {
          return ventana.focus()
        }
      }
      return self.clients.openWindow(destino)
    })(),
  )
})
