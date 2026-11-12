// Las esperas de los sondeos: crecen con tope y se reparten con azar para que mil paneles no
// pregunten en el mismo segundo.
import assert from 'node:assert/strict'
import test from 'node:test'

import { conAzar, esperarVisible, pestanaVisible, siguientePausa } from '../src/utils/sondeo.js'

test('siguientePausa crece y se detiene en el máximo', () => {
  assert.equal(siguientePausa(1000), 1300)
  assert.equal(siguientePausa(4000), 5000)
  assert.equal(siguientePausa(1500, { maximo: 4000 }), 1950)
  assert.equal(siguientePausa(3500, { maximo: 4000 }), 4000)
  assert.equal(siguientePausa(0), 1300)
})

test('conAzar se queda dentro del ±10 %', () => {
  assert.equal(conAzar(30_000, 0.1, () => 0), 27_000)
  assert.equal(conAzar(30_000, 0.1, () => 1), 33_000)
  assert.equal(conAzar(30_000, 0.1, () => 0.5), 30_000)
})

test('fuera del navegador la pestaña cuenta como visible y la espera termina', async () => {
  assert.equal(pestanaVisible(), true)
  await esperarVisible(1)
})
