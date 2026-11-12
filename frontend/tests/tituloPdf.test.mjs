// El título grande del PDF es el que escribió la persona; sin él, «PROFORMA» o «COTIZACIÓN».
import assert from 'node:assert/strict'
import test from 'node:test'

import { tituloDelDocumento } from '../src/utils/proformaPdf.js'

test('el PDF lleva arriba el título que puso la persona, en mayúsculas', () => {
  assert.equal(
    tituloDelDocumento({ tipo: 'proforma', titulo: 'Proforma — Mantenimiento  de impresoras · NIC-1' }),
    'PROFORMA — MANTENIMIENTO DE IMPRESORAS · NIC-1',
  )
})

test('sin título propio queda el genérico', () => {
  assert.equal(tituloDelDocumento({ tipo: 'proforma', titulo: '' }), 'PROFORMA')
  assert.equal(tituloDelDocumento({ tipo: 'cotizacion' }), 'COTIZACIÓN')
})
