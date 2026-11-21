// La barra de tiempo del plazo de proformas: porcentaje transcurrido, nivel de urgencia, texto de
// lo que queda y los casos raros (sin fechas, ya cerrado, mismo día, horas sin zona de Ecuador).
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  avanceDelPlazo,
  diasParaProforma,
  instanteEcuador,
  textoRestante,
} from '../src/utils/plazo.js'

const HORA = 3_600_000
const DIA = 24 * HORA
const ec = (texto) => Date.parse(`${texto}-05:00`)

test('instanteEcuador lee las horas sin zona como hora de Ecuador', () => {
  assert.equal(instanteEcuador('2026-11-23T17:00:00'), Date.parse('2026-11-23T22:00:00Z'))
  assert.equal(instanteEcuador('2026-11-23 17:00'), Date.parse('2026-11-23T22:00:00Z'))
  // Con zona explícita se respeta la que trae.
  assert.equal(instanteEcuador('2026-11-23T17:00:00Z'), Date.parse('2026-11-23T17:00:00Z'))
  // Solo fecha: el límite cierra al final del día; la publicación cuenta desde el principio.
  assert.equal(instanteEcuador('2026-11-23', { finDelDia: true }), ec('2026-11-23T23:59:59'))
  assert.equal(instanteEcuador('2026-11-23'), ec('2026-11-23T00:00:00'))
  assert.equal(instanteEcuador(''), null)
  assert.equal(instanteEcuador(null), null)
  assert.equal(instanteEcuador('no es fecha'), null)
})

test('avanceDelPlazo mide el porcentaje transcurrido entre publicación y límite', () => {
  const publicada = '2026-11-18T09:00:00'
  const cierra = '2026-11-23T09:00:00'
  // A mitad de camino (2,5 días de 5).
  const mitad = avanceDelPlazo(publicada, cierra, ec('2026-11-20T21:00:00'))
  assert.equal(mitad.porcentaje, 50)
  assert.equal(mitad.nivel, 'atencion')
  assert.equal(mitad.texto, 'Quedan 2 días y 12 horas')
  assert.equal(mitad.cerrado, false)

  // Recién publicada: verde.
  const inicio = avanceDelPlazo(publicada, cierra, ec('2026-11-18T10:00:00'))
  assert.equal(inicio.porcentaje, 1)
  assert.equal(inicio.nivel, 'holgado')

  // A un día del cierre: urgente aunque no llegue al 85 %.
  const manana = avanceDelPlazo(publicada, cierra, ec('2026-11-22T09:00:00'))
  assert.equal(manana.porcentaje, 80)
  assert.equal(manana.nivel, 'urgente')
  assert.equal(manana.texto, 'Quedan 1 día')
})

test('avanceDelPlazo con el plazo ya cerrado: 100 % y sin tiempo restante', () => {
  const cerrado = avanceDelPlazo('2026-11-18T09:00:00', '2026-11-23T09:00:00', ec('2026-11-24T09:00:00'))
  assert.equal(cerrado.porcentaje, 100)
  assert.equal(cerrado.nivel, 'cerrado')
  assert.equal(cerrado.cerrado, true)
  assert.equal(cerrado.restanteMs, 0)
  assert.equal(cerrado.texto, 'Plazo cerrado')
})

test('avanceDelPlazo sin fechas o con fechas que no sirven', () => {
  assert.equal(avanceDelPlazo('2026-11-18T09:00:00', null), null)
  assert.equal(avanceDelPlazo(null, ''), null)
  // Sin publicación: no hay porcentaje, pero sí lo que queda.
  const sinInicio = avanceDelPlazo(null, '2026-11-23T09:00:00', ec('2026-11-21T09:00:00'))
  assert.equal(sinInicio.porcentaje, null)
  assert.equal(sinInicio.texto, 'Quedan 2 días')
  // Publicación posterior al límite (dato sucio): tampoco hay porcentaje.
  const alReves = avanceDelPlazo('2026-11-25T09:00:00', '2026-11-23T09:00:00', ec('2026-11-21T09:00:00'))
  assert.equal(alReves.porcentaje, null)
  // Reloj anterior a la publicación: 0 %, nunca negativo.
  const antes = avanceDelPlazo('2026-11-18T09:00:00', '2026-11-23T09:00:00', ec('2026-11-17T09:00:00'))
  assert.equal(antes.porcentaje, 0)
})

test('avanceDelPlazo con publicación y cierre el mismo día', () => {
  const plazo = avanceDelPlazo('2026-11-19T08:00:00', '2026-11-19T17:00:00', ec('2026-11-19T14:00:00'))
  assert.equal(plazo.porcentaje, 67)
  assert.equal(plazo.nivel, 'urgente')
  assert.equal(plazo.texto, 'Quedan 3 horas')
  // Límite solo con fecha: cierra al final del día de Ecuador.
  const soloFecha = avanceDelPlazo('2026-11-19', '2026-11-19', ec('2026-11-19T12:00:00'))
  assert.equal(soloFecha.porcentaje, 50)
  assert.equal(soloFecha.texto, 'Quedan 11 horas y 59 minutos')
})

test('textoRestante en días, horas y minutos', () => {
  assert.equal(textoRestante(4 * DIA + 3 * HORA), '4 días y 3 horas')
  assert.equal(textoRestante(DIA), '1 día')
  assert.equal(textoRestante(5 * HORA + 20 * 60_000), '5 horas y 20 minutos')
  assert.equal(textoRestante(HORA), '1 hora')
  assert.equal(textoRestante(20 * 60_000), '20 minutos')
  assert.equal(textoRestante(30_000), 'menos de un minuto')
  assert.equal(textoRestante(0), '')
})

test('diasParaProforma usa la hora de Ecuador y un reloj inyectable', () => {
  assert.equal(diasParaProforma('2026-11-23T17:00:00', ec('2026-11-19T17:00:00')), 4)
  assert.equal(diasParaProforma('2026-11-23T17:00:00', ec('2026-11-23T08:00:00')), 0)
  assert.equal(diasParaProforma('2026-11-23T17:00:00', ec('2026-11-24T08:00:00')), -1)
  assert.equal(diasParaProforma(null), null)
})
