// Modelo de proforma de ínfima (formato por defecto) y páginas finales opcionales.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ADHIERE,
  armarProformaPdf,
  formatoDe,
  PAGINAS_FINALES,
  paginasActivas,
  textoCompromiso,
  totalesIva,
} from '../src/utils/proformaPdf.js'

async function textoDe(blob) {
  const pdfjs = await import('pdfjs-dist/legacy/build/pdf.mjs')
  const datos = new Uint8Array(await blob.arrayBuffer())
  const pdf = await pdfjs.getDocument({ data: datos, useSystemFonts: false, isEvalSupported: false }).promise
  const paginas = []
  for (let n = 1; n <= pdf.numPages; n += 1) {
    const contenido = await (await pdf.getPage(n)).getTextContent()
    paginas.push(contenido.items.map((i) => i.str).join(' '))
  }
  return paginas
}

const documento = {
  tipo: 'proforma',
  titulo: 'Proforma',
  entidad: 'Fundación Museos de la Ciudad',
  objeto: 'Adquisición de materiales de ferretería',
  lineas: [
    { descripcion: 'BROCHA 4"', cpc: '369900011', unidad: 'UNIDAD', cantidad: 10, precio_unitario: 2.5, subtotal: 25, origen: 'ficha' },
    { descripcion: 'FLEXOMETRO 5 MTS', cpc: '369900011', unidad: 'UNIDAD', cantidad: 3, precio_unitario: 1.125, subtotal: 3.38, origen: 'ficha' },
  ],
  cifras: { subtotal: 28.38, impuesto: 4.26, impuesto_porcentaje: 15, total: 32.64 },
  extras: {
    fecha: '21/11/2026',
    entidad: { ruc: '1768152560001', direccion: 'García Moreno N1-47, Quito' },
    empresa: { razon_social: 'FERRETERÍA EL CLAVO S.A.', ruc: '1792345678001', telefono: '02 245 6789', email: 'ventas@elclavo.ec', direccion: 'Av. 10 de Agosto', ciudad: 'Quito' },
    condiciones: { validez: '30 días', garantia: '6 meses' },
    cumplimiento: [{ requisito: 'Entrega en bodega', como_cumple: 'Se acepta.' }],
  },
}

test('PAGINAS_FINALES: ids que lee el servidor, con etiqueta, descripción y valor por defecto', () => {
  assert.deepEqual(PAGINAS_FINALES.map((p) => p.id), ['respaldo', 'cumplimiento', 'declaracion', 'compromiso', 'integridad'])
  for (const pagina of PAGINAS_FINALES) {
    assert.ok(pagina.etiqueta && pagina.descripcion && typeof pagina.porDefecto === 'boolean')
  }
  assert.equal(PAGINAS_FINALES.find((p) => p.id === 'compromiso').porDefecto, false)
})

test('páginas activas: por defecto, elección explícita y compatibilidad con integridad: false', () => {
  assert.deepEqual(paginasActivas({ tipo: 'proforma' }), { respaldo: true, cumplimiento: true, declaracion: true, compromiso: false, integridad: true })
  assert.equal(paginasActivas({ tipo: 'proforma', extras: { integridad: false } }).integridad, false)
  assert.equal(paginasActivas({ tipo: 'proforma', extras: { paginas_finales: { compromiso: true } } }).compromiso, true)
  const cotizacion = paginasActivas({ tipo: 'cotizacion', extras: { paginas_finales: { compromiso: true } } })
  assert.equal(cotizacion.compromiso, false)
  assert.equal(cotizacion.integridad, false)
})

test('el formato por defecto de la proforma es el modelo de ínfima', () => {
  assert.equal(formatoDe({ tipo: 'proforma' }), 'infima')
  assert.equal(formatoDe({ tipo: 'proforma', extras: { formato_proforma: 'soce' } }), 'soce')
  assert.equal(formatoDe({ tipo: 'cotizacion' }), 'soce')
})

test('totales con base imponible e IVA', () => {
  assert.deepEqual(totalesIva({ subtotal: 100, impuesto: 15, impuesto_porcentaje: 15, total: 115 }), [
    ['SUBTOTAL', 100], ['BASE IMPONIBLE 15%', 100], ['BASE IMPONIBLE 0%', 0], ['IVA 15%', 15], ['TOTAL', 115],
  ])
  const sin = Object.fromEntries(totalesIva({ subtotal: 50, impuesto: 0, impuesto_porcentaje: 0, total: 50 }))
  assert.equal(sin['BASE IMPONIBLE 15%'], 0)
  assert.equal(sin['BASE IMPONIBLE 0%'], 50)
})

test('la primera página sigue el modelo y lo demás va en páginas finales', async () => {
  const { blob, cajas } = await armarProformaPdf(documento)
  const paginas = await textoDe(blob)
  const primera = paginas[0]
  for (const esperado of ['PROFORMA', 'Cliente:', 'FUNDACIÓN MUSEOS DE LA CIUDAD', 'Proveedor (Razón Social):', 'UNIDAD DE MEDIDA', 'VALOR UNITARIO', 'BASE IMPONIBLE 15%', 'IVA 15%', 'Forma de Pago:', 'Vigencia de la Oferta:', 'Lugar de entrega:', 'Atentamente,', '$ 1.125']) {
    assert.ok(primera.includes(esperado), esperado)
  }
  assert.ok(!primera.includes('369900011'), 'el CPC va al respaldo')
  assert.ok(primera.includes(ADHIERE))
  assert.equal(cajas.length, 1)
  const resto = paginas.slice(1).join(' ')
  assert.ok(resto.includes('DOCUMENTO DE RESPALDO'))
  assert.ok(resto.includes('CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA'))
  assert.ok(resto.includes('FORMULARIO DE PERFIL DE INTEGRIDAD'))
  assert.ok(!resto.includes('CARTA DE COMPROMISO'))
})

test('sin páginas finales queda una hoja; la carta de compromiso trae su recuadro de firma', async () => {
  const nada = { respaldo: false, cumplimiento: false, declaracion: false, integridad: false }
  const sola = await armarProformaPdf({ ...documento, extras: { ...documento.extras, paginas_finales: nada } })
  assert.equal((await textoDe(sola.blob)).length, 1)
  const conCarta = await armarProformaPdf({ ...documento, extras: { ...documento.extras, paginas_finales: { ...nada, compromiso: true } } })
  const paginas = await textoDe(conCarta.blob)
  assert.equal(paginas.length, 2)
  assert.ok(paginas[1].includes('CARTA DE COMPROMISO'))
  assert.ok(paginas[1].includes('por mis propios derechos'))
  assert.equal(conCarta.cajas.length, 2)
  assert.equal(conCarta.cajas[1].pagina, 1)
})

test('el texto de la carta de compromiso es el del modelo', () => {
  const texto = textoCompromiso({ razon: 'X S.A.', ruc: '1792345678001', entidad: 'GAD', objeto: 'Pintura' })
  assert.ok(texto.startsWith('Yo, X S.A. con RUC: 1792345678001 por mis propios derechos me comprometo con la GAD, respecto del proceso Pintura'))
  assert.ok(texto.endsWith('normativa legal vigente.'))
})
