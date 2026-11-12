/**
 * Bajar el TDR de una ínfima desde la fila de la tabla, sin abrir el detalle.
 *
 * Si el archivo ya está listo en el almacén temporal, se baja. Si no, se pide al worker y se espera
 * a que lo deje listo. La API nunca abre una conexión al portal: esto solo sondea su estado.
 */
import { api } from '@/api/endpoints'
import { guardarArchivo } from '@/utils/descargas'

const ESPERA_MS = 2000
const INTENTOS = 30

const esperar = (ms) => new Promise((resolver) => setTimeout(resolver, ms))

async function leerEstado(registroId) {
  const respuesta = await api.estadoTdr(registroId)
  return respuesta.documentos || []
}

/**
 * Descarga los anexos listos de la ínfima. Devuelve cuántos archivos bajó.
 *
 * El servidor solo pide y lista los que sirven para la proforma (TDR, pliegos, especificaciones y
 * el acta más reciente): las actas anteriores no llegan aquí.
 */
export async function descargarTdr(registroId) {
  let estado = await leerEstado(registroId)

  if (!estado.some((fila) => fila.estado === 'listo')) {
    await api.pedirTdr(registroId)
    for (let intento = 0; intento < INTENTOS; intento += 1) {
      await esperar(ESPERA_MS)
      estado = await leerEstado(registroId)
      if (estado.some((fila) => fila.estado === 'listo' || fila.estado === 'error')) break
    }
  }

  const listos = estado.filter((fila) => fila.estado === 'listo')
  if (!listos.length) {
    throw new Error(
      'El TDR todavía no está listo. Vuelve a pulsar Descargar en un minuto.',
    )
  }

  let bajados = 0
  for (const fila of listos) {
    try {
      const { contenido, nombre } = await api.archivoTdr(registroId, fila.id)
      guardarArchivo(contenido, nombre || fila.nombre)
      bajados += 1
    } catch (fallo) {
      // Si el archivo temporal venció, se vuelve a pedir y el siguiente clic ya lo encuentra.
      await api.pedirTdr(registroId).catch(() => {})
      throw fallo
    }
  }
  return bajados
}

/**
 * Un nombre que se pueda leer para un documento de la ficha.
 *
 * El portal guarda como nombre la dirección de descarga cuando la celda no trae texto
 * («../GE/ExeGENBajarArchivoGeneral.cpe?Archivo=…»). Enseñarla tal cual da una hilera de enlaces
 * ilegibles; esos archivos se numeran y los que sí tienen nombre lo conservan.
 */
export function nombreLegible(documento, posicion) {
  const nombre = String(documento?.nombre || '').trim()
  const parecEnlace =
    !nombre || /^(\.{0,2}\/|https?:)/i.test(nombre) || nombre.includes('?') || /bajararchivo/i.test(nombre)
  return parecEnlace ? `Documento ${posicion}` : nombre
}
