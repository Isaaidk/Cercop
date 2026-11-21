// «Revisa antes de generar» agrupada y plegada, el descuadre de redondeo que bloqueaba la firma y
// los bloqueos de firma agrupados por dónde se corrigen.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  agruparProblemas,
  bloqueosDeFirma,
  descuadreDeRedondeo,
  masDeDosDecimales,
} from '../src/utils/revisionProforma.js'

const linea = (n, grupo, nivel = 'aviso') => ({
  id: `linea-${n}-cantidad`,
  mensaje: `Línea ${n + 1}: la entidad pide 3, aquí hay 20.`,
  nivel,
  seccion: 'lineas',
  grupo,
})

test('separa errores y avisos, y agrupa por sección', () => {
  const { errores, avisos } = agruparProblemas([
    { id: 'campo-entidad', mensaje: 'Escribe la entidad.', nivel: 'error', seccion: 'entidad' },
    { id: 'condicion-validez', mensaje: 'Vigencia corta.', nivel: 'aviso', seccion: 'condiciones' },
  ])
  assert.deepEqual(errores.map((s) => s.id), ['entidad'])
  assert.deepEqual(avisos.map((s) => s.id), ['condiciones'])
})

test('cinco avisos iguales se pliegan en una fila con resumen', () => {
  const { avisos } = agruparProblemas([0, 1, 2, 3, 4].map((n) => linea(n, 'cantidad-distinta')))
  assert.equal(avisos[0].filas.length, 1)
  assert.equal(avisos[0].filas[0].resumen, '5 líneas con cantidad distinta a la pedida')
  assert.equal(avisos[0].filas[0].problemas.length, 5)
})

test('dos iguales se muestran sueltos', () => {
  const { avisos } = agruparProblemas([0, 1].map((n) => linea(n, 'cantidad-distinta')))
  assert.equal(avisos[0].filas.length, 2)
  assert.equal(avisos[0].filas[0].resumen, undefined)
})

test('el descuadre aparece con precios de 3 decimales en varias líneas', () => {
  const lineas = Array.from({ length: 6 }, () => ({ cantidad: 1, precio_unitario: 1.125 }))
  assert.ok(descuadreDeRedondeo(lineas) > 0.01)
  assert.equal(descuadreDeRedondeo([{ cantidad: 3, precio_unitario: 2.5 }, { cantidad: 1, precio_unitario: '' }]), 0)
  assert.ok(masDeDosDecimales(1.125))
  assert.ok(!masDeDosDecimales('2.50'))
})

test('los bloqueos de firma se agrupan por dónde se corrigen', () => {
  const grupos = bloqueosDeFirma({
    errores: [
      { codigo: 'ruc', texto: 'El RUC debe tener 13 dígitos.', donde: 'empresa' },
      { codigo: 'precio', texto: 'La línea 1 no tiene precio unitario.', donde: 'detalle' },
      { codigo: 'precio', texto: 'La línea 2 no tiene precio unitario.', donde: 'detalle' },
    ],
  })
  assert.deepEqual(grupos.map((g) => [g.donde, g.accion, g.textos.length]), [
    ['empresa', 'perfil', 1],
    ['detalle', 'documento', 2],
  ])
  assert.deepEqual(bloqueosDeFirma(null), [])
})
