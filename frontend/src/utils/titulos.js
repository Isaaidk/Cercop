/**
 * Títulos de proforma únicos en la empresa. La misma regla que `backend/.../dominio/titulos.py`:
 * dos títulos son el mismo si solo cambian mayúsculas, tildes, guiones o espacios.
 */

const TOPE = 300

export function normalizarTitulo(titulo) {
  return String(titulo || '')
    .replace(/[‐-―−]/g, '-')
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
    .replace(/^[ .]+|[ .]+$/g, '')
}

export function tituloRepetido(titulo, existentes = []) {
  const clave = normalizarTitulo(titulo)
  return Boolean(clave) && existentes.some((otro) => normalizarTitulo(otro) === clave)
}

/** El mismo título si nadie lo usa; si no, con «(2)», «(3)»… al final, el primero libre. */
export function tituloLibre(titulo, existentes = []) {
  const usados = new Set(existentes.map(normalizarTitulo))
  const limpio = String(titulo || '').split(/\s+/).filter(Boolean).join(' ').slice(0, TOPE)
  if (!usados.has(normalizarTitulo(limpio))) return limpio
  const raiz = limpio.replace(/\s*\(\d{1,4}\)\s*$/, '')
  for (let numero = 2; numero < 10000; numero += 1) {
    const sufijo = ` (${numero})`
    const candidato = `${raiz.slice(0, TOPE - sufijo.length)}${sufijo}`
    if (!usados.has(normalizarTitulo(candidato))) return candidato
  }
  return limpio
}
