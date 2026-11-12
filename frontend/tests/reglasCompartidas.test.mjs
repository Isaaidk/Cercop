// Las mismas comprobaciones que `backend/pruebas/unidad/test_reglas_compartidas.py`, con los mismos
// casos (`compartido/reglas_consultas.json`). Si una regla cambia en un lado y no en el otro, falla.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  contratoDe,
  propuestaDesdeSri,
  resumirHistorial,
  terminoDeBusqueda,
} from '../src/utils/consultasPublicas.js'

const CASOS = JSON.parse(
  readFileSync(new URL('../../compartido/reglas_consultas.json', import.meta.url), 'utf-8'),
)

test('término de búsqueda', () => {
  for (const [entrada, esperado] of CASOS.termino_de_busqueda) {
    assert.equal(terminoDeBusqueda(entrada), esperado, entrada)
  }
})

test('propuesta del SRI', () => {
  const { contribuyente, establecimientos, esperado } = CASOS.sri
  const p = propuestaDesdeSri(contribuyente, establecimientos)
  for (const [clave, valor] of Object.entries(esperado.identidad)) {
    assert.equal(p.identidad[clave], valor, clave)
  }
  assert.ok(p.identidad.direccion.startsWith(esperado.direccion_empieza))
  assert.deepEqual(p.representante, esperado.representante)
  assert.deepEqual(p.cobertura, esperado.cobertura)
  assert.deepEqual(p.avisos, esperado.avisos)
})

test('persona natural y RIMPE', () => {
  const caso = CASOS.sri_natural_rimpe
  const { identidad } = propuestaDesdeSri(caso.contribuyente, caso.establecimientos)
  for (const [clave, valor] of Object.entries(caso.esperado)) assert.equal(identidad[clave], valor, clave)
})

test('contrato por RUC', () => {
  const { ruc, record, record_homonimo: homonimo, esperado_contrato: esperado } = CASOS.ocds
  const contrato = contratoDe(record, ruc)
  assert.deepEqual(contrato.cpc, esperado.cpc)
  assert.equal(contrato.monto, esperado.monto)
  assert.deepEqual(contrato.productos, esperado.productos)
  assert.equal(contratoDe(homonimo, ruc), null)
})

test('resumen del historial', () => {
  const { ruc, record, resumen } = CASOS.ocds
  const contratos = resumen.registros.map(([cpc, fecha]) => {
    const release = JSON.parse(JSON.stringify(record.releases[0]))
    release.date = `${fecha}T00:00:00-05:00`
    release.awards[0].items[0].classification.id = cpc
    return contratoDe({ releases: [release] }, ruc)
  })
  const r = resumirHistorial(ruc, contratos, { total: 30, revisados: 3, termino: 'X' })
  assert.deepEqual(r.cpc[0], resumen.esperado.cpc_primero)
  assert.deepEqual(r.experiencia.map((e) => e.anio), resumen.esperado.anios)
  assert.equal(r.experiencia[0].objeto, resumen.esperado.objeto_primero)
  assert.equal(r.verificados, resumen.esperado.verificados)
})
