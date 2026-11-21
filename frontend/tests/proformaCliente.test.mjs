// Nombre de la descarga y título sin repetir el objeto (reporte del cliente).
import assert from 'node:assert/strict'
import test from 'node:test'

import { armarProformaPdf, nombreDeDescarga, tituloSinObjeto } from '../src/utils/proformaPdf.js'

test('la descarga se llama ProformaCercoapp_<código>', () => {
  assert.equal(nombreDeDescarga('NIC-1060000420001-2026-00010', 'pdf'), 'ProformaCercoapp_NIC-1060000420001-2026-00010.pdf')
  assert.equal(nombreDeDescarga('', 'docx'), 'ProformaCercoapp.docx')
  assert.equal(nombreDeDescarga('a/b:c?', 'pdf', '_firmado'), 'ProformaCercoapp_a-b-c_firmado.pdf')
})

test('el título de la barra verde no repite el objeto', () => {
  const objeto = 'Contratación del servicio de esterilización para el control poblacional canino'
  assert.equal(
    tituloSinObjeto({ tipo: 'proforma', objeto, titulo: 'Proforma — Contratación del servicio de esterilización… · NIC-1' }),
    'PROFORMA · NIC-1',
  )
  assert.equal(tituloSinObjeto({ tipo: 'proforma', objeto, titulo: 'Mi proforma 2026' }), 'MI PROFORMA 2026')
})

test('correo, web y alcance no rompen el PDF y sigue habiendo un solo recuadro de firma', async () => {
  const { cajas } = await armarProformaPdf({
    tipo: 'proforma',
    titulo: 'Proforma',
    entidad: 'GAD',
    objeto: 'Esterilización',
    lineas: [{ descripcion: 'Esterilización', cantidad: 193, precio_unitario: 40, subtotal: 7720 }],
    cifras: { subtotal: 7720, impuesto: 0, impuesto_porcentaje: 0, total: 7720 },
    extras: {
      integridad: false,
      entidad: { ruc: '1060000420001', correo: 'municipio@pimampiro.gob.ec', web: 'www.pimampiro.gob.ec' },
      condiciones: { plazo_entrega: '180 días contados a partir del día siguiente de la suscripción de la orden de compra.' },
      alcance: 'Un mínimo de 193 procedimientos quirúrgicos.',
      cumplimiento: [{ requisito: 'R', como_cumple: 'Sí' }],
    },
  })
  assert.equal(cajas.length, 1)
})