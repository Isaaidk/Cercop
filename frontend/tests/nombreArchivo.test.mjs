// El nombre con que se guarda un anexo: «INFORME DE NECESIDAD.docx» y no `contrataciones.xlsx`.
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  conExtension,
  extensionDeTipo,
  formatoDeTipo,
  nombreDesdeCabecera,
} from '../src/utils/nombreArchivo.js'

const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

test('nombreDesdeCabecera prefiere filename* (UTF-8) a filename', () => {
  assert.equal(
    nombreDesdeCabecera(
      `inline; filename="Terminos de referencia.docx"; filename*=UTF-8''T%C3%A9rminos%20de%20referencia.docx`,
    ),
    'Términos de referencia.docx',
  )
  // Lo que escribe Starlette con un nombre con espacios: solo `filename*=`.
  assert.equal(
    nombreDesdeCabecera(`inline; filename*=utf-8''INFORME%20DE%20NECESIDAD.docx`),
    'INFORME DE NECESIDAD.docx',
  )
  assert.equal(nombreDesdeCabecera('attachment; filename="tdr.pdf"'), 'tdr.pdf')
  assert.equal(nombreDesdeCabecera('attachment; filename=borrador-oferta.docx'), 'borrador-oferta.docx')
})

test('nombreDesdeCabecera sin nombre devuelve el de respaldo', () => {
  assert.equal(nombreDesdeCabecera('', 'contrataciones.xlsx'), 'contrataciones.xlsx')
  assert.equal(nombreDesdeCabecera(null), '')
  assert.equal(nombreDesdeCabecera('inline'), '')
  // Codificación rota: cae a `filename=`.
  assert.equal(nombreDesdeCabecera(`inline; filename="a.pdf"; filename*=UTF-8''%E0%A4%A`), 'a.pdf')
})

test('conExtension añade la extensión real solo si falta', () => {
  assert.equal(conExtension('INFORME DE NECESIDAD', DOCX), 'INFORME DE NECESIDAD.docx')
  assert.equal(conExtension('TDR.pdf', 'application/pdf'), 'TDR.pdf')
  assert.equal(conExtension('foto.JPEG', 'image/jpeg'), 'foto.JPEG')
  assert.equal(conExtension('Anexo 3', 'application/octet-stream'), 'Anexo 3')
  assert.equal(conExtension('', 'application/pdf'), 'documento.pdf')
})

test('extensionDeTipo y formatoDeTipo', () => {
  assert.equal(extensionDeTipo(DOCX), '.docx')
  assert.equal(extensionDeTipo('application/pdf; charset=binary'), '.pdf')
  assert.equal(extensionDeTipo(''), '')
  assert.equal(formatoDeTipo('application/msword'), 'DOC')
})
