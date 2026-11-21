// Qué ítem pedido corresponde a cada línea de la proforma («la entidad pide 3, aquí hay 20»).
// Caso real: una ínfima de ferretería con todos los ítems bajo el mismo CPC 621650011.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cantidadDistinta,
  emparejarLinea,
  parecido,
  referenciaDeItem,
} from '../src/utils/emparejarLineas.js'

const CPC = '621650011'
const ferreteria = [
  { numero: 1, cpc: CPC, descripcion: 'BROCHA 4"', cantidad: 3, unidad: 'UNIDAD' },
  { numero: 2, cpc: CPC, descripcion: 'FLEXOMETRO 5 MTS', cantidad: 20, unidad: 'UNIDAD' },
  { numero: 3, cpc: CPC, descripcion: 'BROCHA 2"', cantidad: 10, unidad: 'UNIDAD' },
  { numero: 4, cpc: CPC, descripcion: 'CINTA AISLANTE NEGRA', cantidad: 50, unidad: 'ROLLO' },
]

const lineasDesdeItems = (items) =>
  items.map((item, posicion) => ({
    descripcion: `${item.descripcion}\n• Especificación copiada del TDR`,
    cantidad: item.cantidad,
    cpc: item.cpc,
    item_ref: referenciaDeItem(item, posicion),
  }))

test('con un mismo CPC para todos, cada línea va con su propio ítem (sin avisos falsos)', () => {
  const lineas = lineasDesdeItems(ferreteria)
  lineas.forEach((linea, n) => assert.equal(emparejarLinea(linea, ferreteria), ferreteria[n]))
  assert.deepEqual(lineas.map((linea) => cantidadDistinta(linea, ferreteria)), [null, null, null, null])
})

test('sin referencia, la descripción decide entre ítems que comparten CPC', () => {
  const linea = { descripcion: 'FLEXOMETRO 5 MTS\n• Cinta de acero', cantidad: 20, cpc: CPC }
  assert.equal(emparejarLinea(linea, ferreteria), ferreteria[1])
  assert.equal(cantidadDistinta(linea, ferreteria), null)
  const cambiada = { ...linea, cantidad: 7 }
  assert.deepEqual(cantidadDistinta(cambiada, ferreteria), { pedido: ferreteria[1], pedida: 20, escrita: 7 })
})

test('una descripción con detalle añadido sigue casando con su ítem', () => {
  const linea = { descripcion: 'Brocha de 4" marca Wilson, cerda natural', cantidad: 3, cpc: CPC }
  assert.equal(emparejarLinea(linea, ferreteria), ferreteria[0])
})

test('nunca empareja por CPC solo cuando varios ítems lo comparten', () => {
  const linea = { descripcion: 'Martillo de uña', cantidad: 1, cpc: CPC }
  assert.equal(emparejarLinea(linea, ferreteria), null)
  assert.equal(cantidadDistinta(linea, ferreteria), null)
})

test('si dos ítems se parecen igual, no se elige ninguno', () => {
  assert.equal(emparejarLinea({ descripcion: 'BROCHA', cantidad: 5, cpc: CPC }, ferreteria), null)
})

test('un CPC que solo tiene un ítem basta', () => {
  const pedidos = [
    { numero: 1, cpc: '111', descripcion: 'Papel bond A4', cantidad: 10 },
    { numero: 2, cpc: '222', descripcion: 'Tóner HP 85A', cantidad: 2 },
  ]
  const linea = { descripcion: 'Cartucho compatible', cantidad: 3, cpc: '222' }
  assert.equal(emparejarLinea(linea, pedidos), pedidos[1])
  assert.equal(cantidadDistinta(linea, pedidos).pedida, 2)
})

test('un CPC que no está entre los pedidos no se empareja', () => {
  assert.equal(emparejarLinea({ descripcion: 'BROCHA 4"', cantidad: 3, cpc: '999' }, ferreteria), null)
})

test('sin CPC en la línea se busca por descripción entre todos los ítems', () => {
  assert.equal(emparejarLinea({ descripcion: 'Cinta aislante negra 3M', cantidad: 50, cpc: '' }, ferreteria), ferreteria[3])
})

test('una referencia que ya no existe cae en la descripción', () => {
  const linea = { descripcion: 'BROCHA 2"', cantidad: 10, cpc: CPC, item_ref: 'n:99' }
  assert.equal(emparejarLinea(linea, ferreteria), ferreteria[2])
})

test('ítems sin número se referencian por su posición', () => {
  const sinNumero = ferreteria.map(({ numero, ...resto }) => resto)
  const lineas = lineasDesdeItems(sinNumero)
  assert.equal(lineas[2].item_ref, 'p:2')
  assert.equal(emparejarLinea(lineas[2], sinNumero), sinNumero[2])
})

test('el parecido ignora tildes, comillas y mayúsculas', () => {
  assert.equal(parecido('FLEXÓMETRO 5 mts', 'FLEXOMETRO 5 MTS'), 1)
  assert.ok(parecido('BROCHA 4"', 'BROCHA 2"') < 0.6)
})

test('sin ítems pedidos no hay emparejamiento', () => {
  assert.equal(emparejarLinea({ descripcion: 'x', cpc: CPC }, []), null)
  assert.equal(emparejarLinea({ descripcion: 'x', cpc: CPC }, undefined), null)
})
