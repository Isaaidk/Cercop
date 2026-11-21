// La espera del asistente: que nunca parezca colgado y que un fallo diga qué hacer.
import assert from 'node:assert/strict'
import test from 'node:test'

import { conTiempoMaximo, falloDeEnvio, textoEspera } from '../src/utils/asistente.js'

test('el texto de espera avanza con el tiempo', () => {
  assert.equal(textoEspera(0), 'Pensando')
  assert.equal(textoEspera(8), 'Buscando los datos')
  assert.match(textoEspera(20), /puede tardar/)
  assert.match(textoEspera(60), /más de lo normal/)
})

test('mucha demanda (503) respeta el Retry-After y no pierde el mensaje', () => {
  const r = falloDeEnvio({ estado: 503, codigo: 'saturado', esperaSeg: 40 })
  assert.equal(r.esperaSeg, 40)
  assert.match(r.mensaje, /no se perdió/)
  assert.match(r.mensaje, /40 s/)
  assert.equal(falloDeEnvio({ estado: 503 }).esperaSeg, 10)
})

test('demasiados mensajes (429) pide esperar', () => {
  const r = falloDeEnvio({ estado: 429, esperaSeg: 12 })
  assert.equal(r.esperaSeg, 12)
  assert.match(r.mensaje, /12 s/)
})

test('tardanza, sin conexión y error del servidor', () => {
  assert.match(falloDeEnvio({ codigo: 'tardanza' }).mensaje, /tardando/)
  assert.match(falloDeEnvio({ estado: 0, codigo: 'sin_conexion' }).mensaje, /conexión/)
  assert.equal(falloDeEnvio({ estado: 500, message: 'Algo pasó' }).mensaje, 'Algo pasó')
  assert.equal(falloDeEnvio(null).esperaSeg, 0)
})

test('conTiempoMaximo deja pasar lo rápido y corta lo lento', async () => {
  assert.equal(await conTiempoMaximo(Promise.resolve(7), 50), 7)
  const lenta = new Promise((resolver) => setTimeout(() => resolver('tarde'), 200))
  await assert.rejects(conTiempoMaximo(lenta, 20), (error) => error.codigo === 'tardanza')
})
