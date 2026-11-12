// La frase que resume una alerta y la lectura del perfil comercial. Se prueban porque las tres
// pantallas de «Oportunidades para ti» dependen de que digan lo mismo que el backend hará.
import assert from 'node:assert/strict'
import test from 'node:test'

import { perfilComercial, resumirAlerta, unirConO, usd } from '../src/utils/oportunidades.js'

test('unirConO arma la enumeración en castellano', () => {
  assert.equal(unirConO([]), '')
  assert.equal(unirConO(['a']), 'a')
  assert.equal(unirConO(['a', 'b']), 'a o b')
  assert.equal(unirConO(['a', 'b', 'c']), 'a, b o c')
})

test('usd muestra raya para lo no publicado', () => {
  assert.equal(usd(null), '—')
  assert.equal(usd(0), '—')
  assert.equal(usd('x'), '—')
  assert.match(usd(7000), /7\.000/)
})

test('resumirAlerta no inventa una alerta sin palabras ni CPC', () => {
  assert.equal(resumirAlerta({ provincia: 'Pichincha' }), '')
})

test('resumirAlerta cuenta qué, dónde, cuánto y cuándo', () => {
  const frase = resumirAlerta({
    palabras: ['impresoras', 'tóner'],
    cpc: ['45230'],
    provincia: 'Pichincha',
    canton: 'Quito',
    presupuesto_min: '',
    presupuesto_max: 7000,
    frecuencia: 'semanal',
  })
  assert.match(frase, /^Te avisaremos en un resumen semanal/)
  assert.match(frase, /«impresoras» o «tóner»/)
  assert.match(frase, /del CPC 45230/)
  assert.match(frase, /en Quito \(Pichincha\)/)
  assert.match(frase, /de hasta/)
})

test('resumirAlerta sin lugar dice todo el país', () => {
  assert.match(resumirAlerta({ cpc: ['87150'], frecuencia: 'inmediata' }), /al instante.*en todo el país\.$/)
})

test('perfilComercial separa CPC de palabras como el radar', () => {
  const perfil = {
    palabras: [{ texto: 'limpieza' }],
    ofertas: [{ nombre: 'Detergente', cpc: '35321' }],
    experiencia: [{ cpc: '85330' }],
    cobertura: [{ provincia: 'PICHINCHA' }],
  }
  const leido = perfilComercial(perfil, [{ texto: '87150' }, { texto: 'desinfección' }])
  assert.deepEqual(leido.cpc.sort(), ['35321', '85330', '87150'])
  assert.deepEqual(leido.palabras.sort(), ['desinfección', 'limpieza'])
  assert.deepEqual(leido.productos, ['Detergente'])
  assert.deepEqual(leido.provincias, ['Pichincha'])
  assert.equal(leido.vacio, false)
})

test('perfilComercial vacío se reconoce', () => {
  assert.equal(perfilComercial(null, null).vacio, true)
})
