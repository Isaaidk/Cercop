// CPC jerárquico (QA ciclo 3): un código padre de 2 dígitos o más vale en la lista de CPC.
import assert from 'node:assert/strict'
import test from 'node:test'

import { esCodigoCpc, terminoCpcValido, terminosDeLista } from '../src/utils/terminos.js'

test('un código padre de dos dígitos es un código de CPC', () => {
  assert.equal(esCodigoCpc('87'), true)
  assert.equal(esCodigoCpc('73210.00.1'), true)
  assert.equal(esCodigoCpc('8'), false)
  assert.equal(esCodigoCpc('lavado'), false)
})

test('en la lista de CPC valen palabras de 3 letras o códigos de 2 dígitos', () => {
  assert.equal(terminoCpcValido('87'), true)
  assert.equal(terminoCpcValido('ab'), false)
  assert.equal(terminoCpcValido('aseo'), true)
})

test('pegar una lista acepta códigos cortos solo si se pide', () => {
  assert.deepEqual(terminosDeLista('87, ab, lavado', 3, { codigosCortos: true }), {
    terminos: ['87', 'lavado'],
    cortas: 1,
  })
  assert.deepEqual(terminosDeLista('87, lavado'), { terminos: ['lavado'], cortas: 1 })
})
