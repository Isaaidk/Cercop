// Las piezas puras de la pantalla «Asistente». Se prueban porque el texto del asistente viene de un
// modelo y se pinta sin `v-html`: si el formato fallara, se vería texto roto o, peor, HTML crudo.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  chipsDeResumen,
  cierreDe,
  enumerar,
  fechaRelativa,
  lugarDe,
  nombreEtapa,
  pestanaDelAsistente,
  primerNombre,
  registroDeTarjeta,
  segmentarTexto,
  textoContador,
  trozosDeLinea,
  usd,
} from '../src/utils/asistente.js'

test('trozosDeLinea separa la negrita y deja el HTML como texto', () => {
  assert.deepEqual(trozosDeLinea('Hay **3 ínfimas** hoy'), [
    { texto: 'Hay ', negrita: false },
    { texto: '3 ínfimas', negrita: true },
    { texto: ' hoy', negrita: false },
  ])
  assert.deepEqual(trozosDeLinea('<script>x</script>'), [{ texto: '<script>x</script>', negrita: false }])
  assert.deepEqual(trozosDeLinea('a ** b'), [{ texto: 'a ** b', negrita: false }])
})

test('segmentarTexto arma párrafos, saltos de línea y listas', () => {
  const bloques = segmentarTexto('Hola\nsegunda línea\n\nTe encontré:\n- **Uno**\n- Dos\nFin')
  assert.equal(bloques.length, 4)
  assert.equal(bloques[0].tipo, 'parrafo')
  assert.equal(bloques[0].lineas.length, 2)
  assert.equal(bloques[1].tipo, 'parrafo')
  assert.equal(bloques[2].tipo, 'lista')
  assert.deepEqual(bloques[2].elementos[0], [{ texto: 'Uno', negrita: true }])
  assert.equal(bloques[3].lineas[0][0].texto, 'Fin')
  assert.deepEqual(segmentarTexto(''), [])
  assert.deepEqual(segmentarTexto(null), [])
})

test('textoContador solo aparece cerca del tope', () => {
  assert.equal(textoContador(10), '')
  assert.match(textoContador(1900), /1\.900 \/ 2\.000/)
})

test('primerNombre saluda por el nombre', () => {
  assert.equal(primerNombre('María José Pérez'), 'María')
  assert.equal(primerNombre('ana@correo.ec'), 'ana')
  assert.equal(primerNombre(''), '')
})

test('fechaRelativa habla en palabras', () => {
  const ahora = new Date(2026, 10, 12, 15, 0)
  assert.equal(fechaRelativa(new Date(2026, 10, 12, 14, 59, 30), ahora), 'Hace un momento')
  assert.equal(fechaRelativa(new Date(2026, 10, 12, 14, 40), ahora), 'Hace 20 min')
  assert.equal(fechaRelativa(new Date(2026, 10, 12, 9, 0), ahora), 'Hace 6 h')
  assert.equal(fechaRelativa(new Date(2026, 10, 11, 23, 0), ahora), 'Ayer')
  assert.equal(fechaRelativa(new Date(2026, 10, 9, 10, 0), ahora), 'Hace 3 días')
  assert.match(fechaRelativa(new Date(2026, 9, 1), ahora), /1 oct/)
  assert.equal(fechaRelativa(null, ahora), '')
})

test('cierreDe dice cuándo cierra y solo pinta rojo hoy o mañana', () => {
  const ahora = new Date(2026, 10, 12, 8, 0)
  assert.deepEqual(cierreDe(new Date(2026, 10, 12, 18, 0), ahora), { texto: 'Cierra hoy', clase: 'etiqueta--error' })
  assert.deepEqual(cierreDe(new Date(2026, 10, 13, 18, 0), ahora), { texto: 'Cierra mañana', clase: 'etiqueta--error' })
  assert.deepEqual(cierreDe(new Date(2026, 10, 14, 18, 0), ahora), { texto: 'Cierra en 2 días', clase: 'etiqueta--aviso' })
  assert.equal(cierreDe(new Date(2026, 10, 25, 18, 0), ahora).clase, '')
  assert.match(cierreDe(new Date(2026, 10, 1), ahora).texto, /^Cerró el/)
  assert.deepEqual(cierreDe(null, ahora), { texto: '', clase: '' })
})

test('usd formatea en dólares y raya lo vacío', () => {
  assert.match(usd(1500), /1\.500/)
  assert.equal(usd(null), '—')
})

test('lugarDe, enumerar y nombreEtapa', () => {
  assert.equal(lugarDe({ canton: 'QUITO', provincia: 'PICHINCHA' }), 'Quito, Pichincha')
  assert.equal(lugarDe({ canton: 'LOJA', provincia: 'LOJA' }), 'Loja')
  assert.equal(enumerar(['a', 'b', 'c']), 'a, b y c')
  assert.equal(enumerar([{ codigo: '1', descripcion: 'Papel' }]), 'Papel')
  assert.equal(enumerar(null), '')
  assert.equal(nombreEtapa('enviada'), 'Enviada')
  assert.equal(nombreEtapa('en_revision'), 'En revision')
})

test('registroDeTarjeta deja la forma que espera Preparar oferta', () => {
  const registro = registroDeTarjeta({ registro_id: 'r1', codigo: 'NIC-1', objeto: 'Papel' })
  assert.equal(registro.id, 'r1')
  assert.equal(registro.codigo, 'NIC-1')
  assert.equal(registro.objeto, 'Papel')
  assert.equal(registroDeTarjeta(null), null)
})

test('chipsDeResumen solo enseña lo que tiene número', () => {
  const chips = chipsDeResumen({ propuestas: 12, alertas: 1, ofertas_abiertas: 0, por_cerrar: null })
  assert.deepEqual(
    chips.map((chip) => chip.texto),
    ['12 ínfimas para ti', '1 alerta activa'],
  )
  assert.ok(chips.every((chip) => chip.mensaje))
  assert.deepEqual(chipsDeResumen(null), [])
})

test('pestanaDelAsistente traduce a los ids reales del panel', () => {
  assert.equal(pestanaDelAsistente('mis-ofertas'), 'misofertas')
  assert.equal(pestanaDelAsistente('alertas'), 'radar')
  assert.equal(pestanaDelAsistente('empresa'), 'perfil')
  assert.equal(pestanaDelAsistente('propuestas'), 'propuestas')
  assert.equal(pestanaDelAsistente('ofertas'), 'ofertas')
  assert.equal(pestanaDelAsistente('empresa', ['propuestas', 'radar']), null)
  assert.equal(pestanaDelAsistente(''), null)
})

test('sugerenciasVisibles quita lo que lleva a una vista oculta', async () => {
  const { sugerenciaVisible, sugerenciasVisibles } = await import('../src/utils/asistente.js')
  const lista = ['Recomiéndame ínfimas', 'Mis ofertas', 'Precio de referencia de tóner', 'Mis alertas']
  assert.deepEqual(sugerenciasVisibles(lista, ['ofertas']), [
    'Mis ofertas',
    'Precio de referencia de tóner',
    'Mis alertas',
  ])
  assert.deepEqual(sugerenciasVisibles(lista, ['necesidades']), [
    'Recomiéndame ínfimas',
    'Mis ofertas',
    'Mis alertas',
  ])
  // Sin saber las vistas no se oculta nada: decide el servidor.
  assert.deepEqual(sugerenciasVisibles(lista, null), lista)
  assert.equal(sugerenciaVisible('Muéstrame las ínfimas que puedo ofertar', []), false)
})
