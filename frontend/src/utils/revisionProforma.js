/**
 * La lista «Revisa antes de generar» de «Preparar oferta», ordenada para leerse de un vistazo.
 *
 * Cada problema llega como `{ id, mensaje, nivel, seccion, grupo }`: `nivel` es `error` (impide
 * generar) o `aviso` (no impide nada); `seccion` dice en qué bloque del formulario está y `grupo`
 * junta los que son iguales en varias líneas («5 líneas sin valor unitario»), que se pliegan.
 */

export const SECCIONES = [
  { id: 'entidad', etiqueta: 'Datos de la entidad' },
  { id: 'lineas', etiqueta: 'Líneas y precios' },
  { id: 'condiciones', etiqueta: 'Condiciones' },
  { id: 'otros', etiqueta: 'Otros' },
]

// Cómo se resume un grupo de problemas iguales. `n` es cuántas líneas.
const RESUMENES = {
  'sin-descripcion': (n) => `${n} líneas sin descripción`,
  'sin-precio': (n) => `${n} líneas sin valor unitario`,
  'precio-cero': (n) => `${n} líneas con valor unitario en 0`,
  'cantidad-cero': (n) => `${n} líneas sin cantidad`,
  'cantidad-distinta': (n) => `${n} líneas con cantidad distinta a la pedida`,
  'condicion-falta': (n) => `Faltan ${n} condiciones obligatorias`,
}

/** A partir de cuántos problemas iguales se pliegan en una sola fila. */
export const PLEGAR_DESDE = 3

/**
 * Agrupa por nivel y sección, y pliega los problemas repetidos.
 * Devuelve `{ errores, avisos }`; cada uno es una lista de secciones
 * `{ id, etiqueta, filas: [{ clave, resumen?, problemas: [...] }] }`.
 */
export function agruparProblemas(problemas) {
  const lista = Array.isArray(problemas) ? problemas : []
  const armar = (nivel) =>
    SECCIONES.map(({ id, etiqueta }) => {
      const propios = lista.filter((p) => p.nivel === nivel && (p.seccion || 'otros') === id)
      const filas = []
      const porGrupo = new Map()
      for (const problema of propios) {
        const grupo = problema.grupo && RESUMENES[problema.grupo] ? problema.grupo : ''
        if (!grupo) {
          filas.push({ clave: `${problema.id}|${problema.mensaje}`, problemas: [problema] })
          continue
        }
        if (!porGrupo.has(grupo)) {
          const fila = { clave: `grupo-${grupo}`, grupo, problemas: [] }
          porGrupo.set(grupo, fila)
          filas.push(fila)
        }
        porGrupo.get(grupo).problemas.push(problema)
      }
      // Un grupo corto se enseña suelto: plegar dos líneas no ahorra nada.
      const finales = filas.flatMap((fila) => {
        if (!fila.grupo || fila.problemas.length >= PLEGAR_DESDE) {
          return [fila.grupo ? { ...fila, resumen: RESUMENES[fila.grupo](fila.problemas.length) } : fila]
        }
        return fila.problemas.map((p) => ({ clave: `${p.id}|${p.mensaje}`, problemas: [p] }))
      })
      return { id, etiqueta, filas: finales }
    }).filter((seccion) => seccion.filas.length)
  return { errores: armar('error'), avisos: armar('aviso') }
}

/** Redondeo a centavos como lo hace el servidor (por línea). */
const centavos = (valor) => Math.round((Number(valor) + Number.EPSILON) * 100) / 100

/**
 * Cuánto se separan el total por líneas redondeadas (el que guarda el servidor) y el total sin
 * redondear (el que usa su revisión antes de firmar). Con precios de 3 o más decimales en varias
 * líneas, pasa de un centavo y la revisión del servidor dice «los totales no coinciden», un error
 * que no se arregla guardando otra vez. Devuelve la diferencia en dólares (0 si no hay).
 */
export function descuadreDeRedondeo(lineas) {
  const filas = (Array.isArray(lineas) ? lineas : []).filter(
    (linea) => linea && linea.precio_unitario !== '' && linea.precio_unitario != null,
  )
  if (!filas.length) return 0
  const porLinea = centavos(
    filas.reduce((suma, linea) => suma + centavos(Number(linea.cantidad) * Number(linea.precio_unitario)), 0),
  )
  const sinRedondear = centavos(
    filas.reduce((suma, linea) => suma + Number(linea.cantidad) * Number(linea.precio_unitario), 0),
  )
  const diferencia = Math.abs(porLinea - sinRedondear)
  return diferencia > 0.0095 ? centavos(diferencia) : 0
}

/** Si un precio trae más de dos decimales. */
export function masDeDosDecimales(valor) {
  const numero = Number(valor)
  return Number.isFinite(numero) && Math.abs(numero * 100 - Math.round(numero * 100)) > 1e-6
}

// A qué parte del armado lleva cada hallazgo de la revisión del servidor (`dominio/verificacion.py`).
const DONDE = {
  empresa: { etiqueta: 'Datos de tu empresa', accion: 'perfil' },
  proceso: { etiqueta: 'Entidad y objeto', accion: 'documento' },
  detalle: { etiqueta: 'Líneas y precios', accion: 'documento' },
  condiciones: { etiqueta: 'Condiciones', accion: 'documento' },
  cumplimiento: { etiqueta: 'Respuestas al TDR', accion: 'documento' },
}

/**
 * Lo que impide firmar, según la revisión del servidor, agrupado por dónde se corrige. Cada grupo
 * dice qué hacer: `perfil` (completar «Perfil y RUP» y volver a generar) o `documento` (corregir en
 * el paso 3 y volver a generar). Una lista vacía: se puede firmar.
 */
export function bloqueosDeFirma(verificacion) {
  const errores = Array.isArray(verificacion?.errores) ? verificacion.errores : []
  const grupos = new Map()
  for (const fila of errores) {
    const donde = DONDE[fila?.donde] ? fila.donde : 'detalle'
    if (!grupos.has(donde)) grupos.set(donde, { donde, ...DONDE[donde], textos: [] })
    const texto = String(fila?.texto || '').trim()
    if (texto && !grupos.get(donde).textos.includes(texto)) grupos.get(donde).textos.push(texto)
  }
  return [...grupos.values()]
}
