/**
 * La política de contraseñas, pedida al servidor.
 *
 * Por qué no está escrita aquí
 * ----------------------------
 * La política vive en el código del servidor (`dominio/credenciales.py`) y es la única que decide. Una
 * copia en el navegador —«mínimo 8 caracteres»— se queda atrás el día que el servidor pase a exigir
 * 12, y entonces el formulario rechaza una contraseña que el servidor habría aceptado, o al revés.
 * Aquí solo se pide una vez y se guarda.
 *
 * Lo que **no** se puede comprobar desde aquí
 * ------------------------------------------
 * El servidor rechaza además las contraseñas que aparecen en las listas de las más usadas y las que
 * contienen el propio correo. Esas listas no viajan al navegador: son un dato del servidor y enviarlas
 * sería publicarlas. Así que la comprobación de aquí es una ayuda para escribir, no un veredicto: el
 * que manda es el mensaje que devuelve la API, y se muestra tal cual.
 */

import { api } from '@/api/endpoints'

/** Requisitos con valores por defecto prudentes, mientras llega la respuesta del servidor. */
const POR_DEFECTO = {
  longitud_minima: 12,
  longitud_maxima: 128,
  caracteres_distintos_minimos: 4,
}

let memorizados = null
let enCurso = null

/** Requisitos de contraseña. Se piden una sola vez y se recuerdan. */
export async function obtenerRequisitos() {
  if (memorizados) return memorizados
  if (enCurso) return enCurso

  enCurso = (async () => {
    try {
      const respuesta = await api.requisitosDeRegistro()
      memorizados = { ...POR_DEFECTO, ...(respuesta?.contrasena || {}) }
    } catch {
      // Si no se puede preguntar, se usan los valores por defecto. Son los del servidor en el momento
      // de escribir esto, así que el formulario funciona; si hubieran cambiado, el servidor lo dirá al
      // enviar, que es donde tiene que decirlo de todas formas.
      memorizados = { ...POR_DEFECTO }
    } finally {
      enCurso = null
    }
    return memorizados
  })()

  return enCurso
}

/**
 * Qué le falta a una contraseña, como lista de comprobaciones con su estado.
 *
 * Devuelve **todas** las comprobaciones y no solo las que fallan: el formulario las pinta como una
 * lista que se va completando, y para eso necesita saber también cuáles ya se cumplen. Una lista que
 * solo muestra errores obliga a adivinar qué está bien.
 */
export function revisarContrasena(texto, requisitos, email = '') {
  const valor = texto || ''
  const minimo = requisitos?.longitud_minima ?? POR_DEFECTO.longitud_minima
  const maximo = requisitos?.longitud_maxima ?? POR_DEFECTO.longitud_maxima
  const distintos = requisitos?.caracteres_distintos_minimos ?? POR_DEFECTO.caracteres_distintos_minimos

  const usuarioDelCorreo = String(email).split('@')[0].trim().toLowerCase()

  return [
    {
      clave: 'longitud',
      etiqueta: `Al menos ${minimo} caracteres`,
      cumple: valor.length >= minimo,
    },
    {
      clave: 'maximo',
      etiqueta: `Como mucho ${maximo} caracteres`,
      cumple: valor.length > 0 && valor.length <= maximo,
    },
    {
      clave: 'variedad',
      etiqueta: `Al menos ${distintos} caracteres distintos`,
      cumple: new Set(valor).size >= distintos,
    },
    {
      clave: 'sin-correo',
      etiqueta: 'No contiene tu correo electrónico',
      cumple: !(usuarioDelCorreo.length >= 4 && valor.toLowerCase().includes(usuarioDelCorreo)),
    },
  ]
}

/** ¿Cumple todo lo comprobable desde el navegador? */
export function contrasenaAceptable(texto, requisitos, email = '') {
  return revisarContrasena(texto, requisitos, email).every((fila) => fila.cumple)
}
