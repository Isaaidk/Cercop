// El texto del TDR que se pinta en «Preparar oferta». Las lecturas viejas, guardadas antes de que el
// backend limpiara, deben verse igual de legibles que las nuevas.
import assert from 'node:assert/strict'
import test from 'node:test'

import { POR_COMPLETAR, textoLegible, trozosTdr } from '../src/utils/textoTdr.js'

test('los huecos del formulario quedan como un solo marcador', () => {
  assert.equal(
    textoLegible('ACEPTACIÓN: ……………………... con RUC …………………. : certifica'),
    `ACEPTACIÓN: ${POR_COMPLETAR} con RUC ${POR_COMPLETAR}: certifica`,
  )
  assert.equal(
    textoLegible('es de $............ (………. CON 00/100 DOLARES)'),
    `es de $${POR_COMPLETAR} (${POR_COMPLETAR} CON 00/100 DOLARES)`,
  )
  assert.equal(textoLegible('Firma: ____ …… ____'), `Firma: ${POR_COMPLETAR}`)
})

test('respeta montos, elipsis cortas y saltos de línea', () => {
  assert.equal(textoLegible('Total $1.250,50, etc...'), 'Total $1.250,50, etc...')
  assert.equal(textoLegible('Requisitos:\n- La garantía.\n- El soporte.'), 'Requisitos:\n- La garantía.\n- El soporte.')
})

test('une las letras espaciadas', () => {
  assert.equal(textoLegible('I T E M CPC'), 'ITEM CPC')
  assert.equal(textoLegible('anexo A Y B'), 'anexo A Y B')
})

test('limpiar dos veces no cambia nada', () => {
  const una = textoLegible('ACEPTACIÓN: ……… con RUC …… :  I T E M')
  assert.equal(textoLegible(una), una)
})

test('trozosTdr separa los huecos para pintarlos aparte', () => {
  assert.deepEqual(trozosTdr('RUC ……… fin'), [
    { texto: 'RUC ', hueco: false },
    { texto: POR_COMPLETAR, hueco: true },
    { texto: ' fin', hueco: false },
  ])
  assert.deepEqual(trozosTdr(''), [])
})
