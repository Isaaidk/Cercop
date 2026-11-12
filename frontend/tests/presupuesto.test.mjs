// El indicador de presupuesto del paso «Tu proforma». Repite la regla del backend
// (`dominio/presupuesto.py`) para avisar antes de generar; el servidor es quien rechaza.
import assert from 'node:assert/strict'
import test from 'node:test'

import { presupuestoValido, usoDelPresupuesto } from '../src/utils/presupuesto.js'

const lineas = (cantidad, precio) => [{ cantidad, precio_unitario: precio }]

test('sin presupuesto conocido no hay indicador', () => {
  assert.equal(usoDelPresupuesto({ subtotal: 10, total: 11.5 }, [], null), null)
  assert.equal(presupuestoValido({ valor: 0 }), null)
  assert.equal(presupuestoValido({ valor: 'abc' }), null)
})

test('sin dato de IVA se compara el subtotal', () => {
  const uso = usoDelPresupuesto({ subtotal: 1000, total: 1150 }, lineas(10, 100), { valor: 1000 })
  assert.equal(uso.supera, false)
  assert.equal(uso.base, 'sin IVA')
  assert.equal(uso.porcentaje, 100)
})

test('con IVA incluido se compara el total y se bloquea si pasa', () => {
  const uso = usoDelPresupuesto({ subtotal: 1000, total: 1150 }, lineas(10, 100), {
    valor: 1100,
    incluye_iva: true,
  })
  assert.equal(uso.supera, true)
  assert.equal(uso.ancho, 100)
  assert.equal(Math.round(uso.exceso), 50)
})

test('avisa si se queda muy corto o si el total parece escrito como unitario', () => {
  const corto = usoDelPresupuesto({ subtotal: 300, total: 345 }, lineas(1, 300), { valor: 1000 })
  assert.equal(corto.avisos.length, 1)
  assert.match(corto.avisos[0], /30 %/)
  const unitario = usoDelPresupuesto({ subtotal: 9000, total: 10350 }, lineas(10, 900), { valor: 1000 })
  assert.equal(unitario.supera, true)
  assert.match(unitario.avisos.join(' '), /precio unitario/)
})
