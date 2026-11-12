// Títulos de proforma únicos: misma regla que el backend (`dominio/titulos.py`).
import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizarTitulo, tituloLibre, tituloRepetido } from '../src/utils/titulos.js'

test('tildes, mayúsculas, guiones y espacios no hacen distinto a un título', () => {
  assert.equal(normalizarTitulo('Proforma — Sillas  de Oficína'), normalizarTitulo('proforma - sillas de oficina'))
  assert.ok(tituloRepetido('PROFORMA – Sillas', ['Proforma - sillas']))
  assert.ok(!tituloRepetido('Proforma — Mesas', ['Proforma — Sillas']))
  assert.ok(!tituloRepetido('', ['']))
})

test('el título libre numera el siguiente que nadie usa', () => {
  const usados = ['Proforma — Sillas', 'Proforma — Sillas (2)']
  assert.equal(tituloLibre('Proforma — Sillas', usados), 'Proforma — Sillas (3)')
  assert.equal(tituloLibre('Proforma — Sillas (2)', usados), 'Proforma — Sillas (3)')
  assert.equal(tituloLibre('Proforma — Mesas', usados), 'Proforma — Mesas')
})
