/**
 * El sonido de aviso: tres golpes cortos de marimba, el instrumento de Esmeraldas.
 *
 * Se sintetiza en el navegador (Web Audio), así que no hay archivo que descargar ni música de nadie:
 * cada nota es una onda base más su cuarto armónico —lo que le da a la marimba su timbre de madera—
 * con un ataque inmediato y una caída rápida. Dura menos de un segundo.
 *
 * Solo suena con el panel abierto: la notificación del sistema usa el sonido del teléfono o la
 * computadora, que el navegador no deja cambiar. Se puede apagar (`fijarSonido(false)`); la
 * preferencia se guarda en este navegador.
 */

const CLAVE = 'cercoapp.sonido'
// Sol, Si, Re agudo: un arpegio alegre que sube, como un «¡hay algo!».
const NOTAS = [
  { frecuencia: 784, inicio: 0 },
  { frecuencia: 988, inicio: 0.11 },
  { frecuencia: 1175, inicio: 0.22 },
]

let contexto = null

export function sonidoActivo() {
  try {
    return localStorage.getItem(CLAVE) !== 'no'
  } catch {
    return true
  }
}

export function fijarSonido(activo) {
  try {
    localStorage.setItem(CLAVE, activo ? 'si' : 'no')
  } catch {
    // Sin almacenamiento (modo privado): vale para esta visita.
  }
}

function golpe(ctx, destino, frecuencia, cuando) {
  const volumen = ctx.createGain()
  volumen.gain.setValueAtTime(0.0001, cuando)
  volumen.gain.exponentialRampToValueAtTime(0.35, cuando + 0.005)
  volumen.gain.exponentialRampToValueAtTime(0.0001, cuando + 0.45)
  volumen.connect(destino)
  for (const [multiplo, nivel] of [
    [1, 1],
    [4, 0.25],
  ]) {
    const onda = ctx.createOscillator()
    const parcial = ctx.createGain()
    onda.type = 'sine'
    onda.frequency.setValueAtTime(frecuencia * multiplo, cuando)
    parcial.gain.value = nivel
    onda.connect(parcial).connect(volumen)
    onda.start(cuando)
    onda.stop(cuando + 0.5)
  }
}

/** Suena una vez. `forzar` ignora la preferencia (botón «Probar sonido»). */
export async function sonarAviso({ forzar = false } = {}) {
  if (!forzar && !sonidoActivo()) return
  const Contexto = globalThis.AudioContext || globalThis.webkitAudioContext
  if (!Contexto) return
  try {
    contexto = contexto || new Contexto()
    if (contexto.state === 'suspended') await contexto.resume()
    const salida = contexto.createGain()
    salida.gain.value = 0.6
    salida.connect(contexto.destination)
    const ahora = contexto.currentTime + 0.02
    for (const nota of NOTAS) golpe(contexto, salida, nota.frecuencia, ahora + nota.inicio)
  } catch {
    // Sin audio (permiso del navegador, pestaña en segundo plano): el aviso se ve igual.
  }
}
