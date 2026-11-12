// El PDF se arma en el navegador: aquí se comprueba con Node que sale completo y con sus recuadros.
import assert from 'node:assert/strict'
import test from 'node:test'

import { armarProformaPdf, dolaresEnLetras } from '../src/utils/proformaPdf.js'

const documento = {
  tipo: 'proforma',
  titulo: 'Proforma',
  entidad: 'Cuerpo de Bomberos',
  objeto: 'Adquisición de baterías',
  lineas: [
    { cpc: '464200017', cpc_nombre: 'BATERIA PARA VEHICULOS 12V', descripcion: 'Batería caja 27H â€“ 940Amp', unidad: 'Unidad', cantidad: 2, precio_unitario: 35, subtotal: 70 },
  ],
  cifras: { subtotal: 70, impuesto: 0, impuesto_porcentaje: 0, total: 70 },
  extras: {
    fecha: '10/11/2026',
    codigo: 'NIC-0968570550001-2026-00042',
    empresa: { razon_social: 'Suministros Andinos S.A.', ruc: '1792146739001', provincia: 'Pichincha', canton: 'Quito', pais: 'ECUADOR' },
    condiciones: { validez: '45 días' },
    cumplimiento: [{ requisito: 'Entrega en bodega', como_cumple: 'Se acepta.' }],
  },
}

test('el PDF lleva una sola firma: el recuadro bajo los datos del oferente', async () => {
  const { blob, cajas } = await armarProformaPdf(documento)
  const bytes = Buffer.from(await blob.arrayBuffer())
  assert.equal(bytes.subarray(0, 5).toString(), '%PDF-')
  assert.equal(cajas.length, 1)
  for (const { pagina, caja } of cajas) {
    assert.ok(pagina >= 0)
    const [x1, y1, x2, y2] = caja
    assert.ok(x1 >= 0 && x1 < x2 && x2 <= 595 && y1 >= 0 && y1 < y2 && y2 <= 842)
  }
})

test('sin integridad y en cotización no se agrega el formulario', async () => {
  const sin = await armarProformaPdf({ ...documento, extras: { ...documento.extras, integridad: false } })
  const cotizacion = await armarProformaPdf({ ...documento, tipo: 'cotizacion' })
  assert.equal(sin.cajas.length, 1)
  assert.equal(cotizacion.cajas.length, 1)
})

test('el total en letras sigue el modelo del SOCE', () => {
  assert.equal(dolaresEnLetras(83607), 'OCHENTA Y TRES MIL SEISCIENTOS SIETE DÓLARES')
  assert.equal(dolaresEnLetras(1), 'UN DÓLAR')
  assert.equal(dolaresEnLetras(100), 'CIEN DÓLARES')
  assert.equal(dolaresEnLetras(1250.05), 'MIL DOSCIENTOS CINCUENTA DÓLARES CON 05/100')
  assert.equal(dolaresEnLetras(2000000), 'DOS MILLONES DÓLARES')
})
