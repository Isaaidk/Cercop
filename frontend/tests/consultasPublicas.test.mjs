// Las mismas reglas que `backend/pruebas/unidad/test_consulta_ruc.py` y `test_historial.py`.
// Se corre con: npm test
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  contratoDe,
  propuestaDesdeSri,
  resumirHistorial,
  terminoDeBusqueda,
} from '../src/utils/consultasPublicas.js'

const RUC = '2390030234001'

const CONTRIBUYENTE = {
  numeroRuc: '1792146739001',
  razonSocial: 'SUMINISTROS ANDINOS S.A.',
  estadoContribuyenteRuc: 'ACTIVO',
  actividadEconomicaPrincipal: 'VENTA AL POR MAYOR DE MAQUINARIA.',
  tipoContribuyente: 'SOCIEDAD',
  regimen: 'GENERAL',
  categoria: null,
  obligadoLlevarContabilidad: 'SI',
  informacionFechasContribuyente: { fechaInicioActividades: '2016-03-14 00:00:00.0' },
  representantesLegales: [{ identificacion: '1712345678', nombre: 'PEREZ ANDRADE ISAAC' }],
  contribuyenteFantasma: 'NO',
  transaccionesInexistente: 'NO',
}
const ESTABLECIMIENTOS = [
  { nombreFantasiaComercial: 'ANDINOS OFICINA', direccionCompleta: 'PICHINCHA / QUITO / IÑAQUITO / AV. AMAZONAS N31-120', estado: 'ABIERTO', matriz: 'SI' },
  { direccionCompleta: 'GUAYAS / GUAYAQUIL / TARQUI / AV. 9 DE OCTUBRE 100', estado: 'ABIERTO', matriz: 'NO' },
  { direccionCompleta: 'AZUAY / CUENCA / SUCRE / CALLE LARGA 5', estado: 'CERRADO', matriz: 'NO' },
]

test('la propuesta llena lo que el SRI publica', () => {
  const p = propuestaDesdeSri(CONTRIBUYENTE, ESTABLECIMIENTOS)
  assert.equal(p.identidad.razon_social, 'SUMINISTROS ANDINOS S.A.')
  assert.equal(p.identidad.nombre_comercial, 'Andinos Oficina')
  assert.equal(p.identidad.tipo_persona, 'juridica')
  assert.equal(p.identidad.regimen_tributario, 'General')
  assert.equal(p.identidad.obligado_contabilidad, true)
  assert.equal(p.identidad.fecha_inicio_actividades, '2016-03-14')
  assert.equal(p.identidad.ciudad, 'Quito')
  assert.ok(p.identidad.direccion.startsWith('Av. Amazonas'))
  assert.equal(p.representante.cedula, '1712345678')
  assert.deepEqual(p.cobertura, [
    { provincia: 'Pichincha', canton: 'Quito' },
    { provincia: 'Guayas', canton: 'Guayaquil' },
  ])
  assert.deepEqual(p.avisos, [])
})

test('un RUC suspendido avisa, y las provincias salen con la grafía oficial', () => {
  const p = propuestaDesdeSri({ ...CONTRIBUYENTE, estadoContribuyenteRuc: 'SUSPENDIDO' }, [
    { direccionCompleta: 'MANABI / PORTOVIEJO / X / CALLE 1', estado: 'ABIERTO' },
    { direccionCompleta: 'SANTO DOMINGO DE LOS TSACHILAS / SANTO DOMINGO / X / Y', estado: 'ABIERTO' },
  ])
  assert.ok(p.avisos[0].includes('suspendido'))
  assert.deepEqual(p.cobertura.map((c) => c.provincia), ['Manabí', 'Santo Domingo de los Tsáchilas'])
})

test('persona natural y RIMPE', () => {
  const p = propuestaDesdeSri(
    { ...CONTRIBUYENTE, numeroRuc: '1712345678001', tipoContribuyente: 'PERSONAS NATURALES', regimen: 'RIMPE', categoria: 'NEGOCIO POPULAR', obligadoLlevarContabilidad: 'NO' },
    [],
  )
  assert.equal(p.identidad.tipo_persona, 'natural')
  assert.equal(p.identidad.regimen_tributario, 'RIMPE · Negocio Popular')
  assert.equal(p.identidad.obligado_contabilidad, false)
})

test('el nombre se busca sin forma societaria ni comillas', () => {
  assert.equal(terminoDeBusqueda('Suministros Andinos S.A.'), 'SUMINISTROS ANDINOS')
  assert.equal(terminoDeBusqueda('ÁNDES CIA. LTDA.'), 'ÁNDES')
  assert.equal(terminoDeBusqueda('ASOCIACION LA CANASTA "ASOCANASTA"'), 'ASOCIACION LA CANASTA')
  assert.equal(terminoDeBusqueda('Comercial S.A. del Sur'), 'COMERCIAL S.A. DEL SUR')
})

function registro(ruc = RUC, cpc = '134929123', fecha = '2026-01-06') {
  return {
    releases: [{
      ocid: `ocds-${cpc}-${fecha}`,
      date: `${fecha}T00:00:00-05:00`,
      buyer: { id: 'EC-RUC-1791825314001', name: 'FUNDACION CALASANZ' },
      tender: { title: 'Orden de compra', description: 'Orden de compra para adquirir los siguientes productos', value: { amount: 222.01 } },
      parties: [{ id: `EC-RUC-${ruc}-821234`, roles: ['supplier'] }],
      awards: [{
        value: { amount: 222.01 },
        suppliers: [{ id: `EC-RUC-${ruc}-821234` }],
        items: [
          { description: 'CANASTA FRUTAS', classification: { id: cpc, scheme: 'CPC', description: 'CANASTA DE FRUTAS' } },
          { classification: { id: '99', scheme: 'OTRO' } },
        ],
      }],
    }],
  }
}

test('un contrato solo cuenta si el adjudicatario tiene ese RUC', () => {
  const propio = contratoDe(registro(), RUC)
  assert.deepEqual(propio.cpc, { 134929123: 'CANASTA DE FRUTAS' })
  assert.deepEqual(propio.productos, ['CANASTA FRUTAS'])
  assert.equal(propio.monto, 222.01)
  assert.equal(contratoDe(registro('1790000000001'), RUC), null)
  assert.equal(contratoDe({ nada: 1 }, RUC), null)
})

test('los CPC se cuentan y la experiencia sale ordenada y con los productos comprados', () => {
  const contratos = [
    contratoDe(registro(RUC, '111', '2024-03-01'), RUC),
    contratoDe(registro(RUC, '111', '2026-02-01'), RUC),
    contratoDe(registro(RUC, '222', '2025-06-01'), RUC),
  ]
  const r = resumirHistorial(RUC, contratos, { total: 30, revisados: 3, termino: 'X' })
  assert.deepEqual(r.cpc[0], { codigo: '111', descripcion: 'CANASTA DE FRUTAS', veces: 2 })
  assert.deepEqual(r.experiencia.map((e) => e.anio), [2026, 2025, 2024])
  assert.equal(r.experiencia[0].objeto, 'CANASTA FRUTAS') // no «Orden de compra para adquirir…»
  assert.equal(r.verificados, 3)
  assert.ok(r.aviso.includes('RUP'))
})
