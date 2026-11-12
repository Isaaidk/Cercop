// Las reglas puras de `src/utils/ocr.js`: cuándo se hace OCR, cómo se arma el texto y qué se
// rechaza. El OCR de verdad necesita un navegador (canvas y WebAssembly); aquí no se carga ni
// pdf.js ni Tesseract. Se corre con: npm test
import assert from 'node:assert/strict'
import test from 'node:test'

import {
  armarTexto,
  enTramo,
  esImagen,
  esPdf,
  escalaParaImagen,
  escalaParaPagina,
  LADO_MAXIMO,
  limpiarTexto,
  lineasDeItems,
  MAX_BYTES,
  mensajeDeError,
  paginasParaOcr,
  paginaSinTexto,
  pareceEscaneado,
  porcentajeTotal,
  prepararPixeles,
  textoDeArchivo,
  validarArchivo,
} from '../src/utils/ocr.js'

const archivo = (name, type, size = 1000) => ({ name, type, size, arrayBuffer: async () => new ArrayBuffer(size) })

test('reconoce PDF e imágenes por tipo o por extensión', () => {
  assert.equal(esPdf(archivo('rup.pdf', '')), true)
  assert.equal(esPdf(archivo('rup', 'application/pdf')), true)
  assert.equal(esImagen(archivo('foto.JPG', '')), true)
  assert.equal(esImagen(archivo('x', 'image/webp')), true)
  assert.equal(esImagen(archivo('rup.pdf', 'application/pdf')), false)
})

test('valida el archivo antes de cargar nada, con mensajes en español', () => {
  assert.throws(() => validarArchivo(null), /Elige un archivo/)
  assert.throws(() => validarArchivo(archivo('notas.docx', '')), /PDF o una foto/)
  assert.throws(() => validarArchivo(archivo('rup.pdf', 'application/pdf', 0)), /vacío/)
  assert.throws(() => validarArchivo(archivo('rup.pdf', 'application/pdf', MAX_BYTES + 1)), /pasa de 30 MB/)
  assert.doesNotThrow(() => validarArchivo(archivo('rup.pdf', 'application/pdf')))
})

test('textoDeArchivo rechaza un archivo inválido sin cargar librerías', async () => {
  await assert.rejects(textoDeArchivo(archivo('hoja.xlsx', '')), /PDF o una foto/)
})

test('una página sin texto o con solo un pie se reconoce con OCR', () => {
  assert.equal(paginaSinTexto(''), true)
  assert.equal(paginaSinTexto('   \n  '), true)
  assert.equal(paginaSinTexto('Página 1 de 3'), true)
  assert.equal(paginaSinTexto('REGISTRO ÚNICO DE PROVEEDORES certifico que Juan Pérez'), false)
})

test('solo las páginas sin texto van a OCR; un PDF digital no parece escaneado', () => {
  const digital = ['REGISTRO ÚNICO DE CONTRIBUYENTES, PEREZ LOPEZ JUAN CARLOS', 'Actividades económicas: venta al por mayor']
  assert.deepEqual(paginasParaOcr(digital), [])
  assert.equal(pareceEscaneado(digital), false)

  const mixto = [digital[0], '', '2/3']
  assert.deepEqual(paginasParaOcr(mixto), [1, 2])
  assert.equal(pareceEscaneado(mixto), true)
  assert.equal(pareceEscaneado([]), false)
})

// Trozo de `getTextContent()`: transform = [a, b, c, d, x, y].
const item = (str, x, y, { width = str.length * 5, height = 10, hasEOL = false } = {}) => ({
  str,
  transform: [10, 0, 0, 10, x, y],
  width,
  height,
  hasEOL,
})

test('arma un renglón por línea a partir de los trozos de pdf.js', () => {
  const items = [
    item('Bienes, Obras o Servicios Suministrados', 50, 700, { hasEOL: true }),
    // Celdas de una tabla en la misma altura, separadas: llevan espacio entre medias.
    item('73210', 50, 680, { width: 25 }),
    item('SERVICIOS DE ARRENDAMIENTO', 100, 680),
    // Baja de línea sin `hasEOL`: también corta.
    item('85970', 50, 665, { width: 25 }),
    item('SERVICIOS DE ORGANIZACION', 100, 665),
  ]
  assert.deepEqual(lineasDeItems(items), [
    'Bienes, Obras o Servicios Suministrados',
    '73210 SERVICIOS DE ARRENDAMIENTO',
    '85970 SERVICIOS DE ORGANIZACION',
  ])
})

test('no mete espacios dentro de una palabra partida en trozos pegados', () => {
  const items = [item('Certifi', 50, 700, { width: 35 }), item('cado', 85, 700, { width: 20 })]
  assert.deepEqual(lineasDeItems(items), ['Certificado'])
})

test('limpia el texto sin perder los renglones', () => {
  const sucio = 'Calle:\u00a0AV.  SIEMPRE   VIVA\r\n\r\n\r\n\r\nNúmero: S1-100  \n\t Cantón: QUITO'
  assert.equal(limpiarTexto(sucio), 'Calle: AV. SIEMPRE VIVA\n\nNúmero: S1-100\nCantón: QUITO')
})

test('une las páginas con una línea en blanco y salta las vacías', () => {
  assert.equal(armarTexto(['Página uno\nlínea dos', '', '  Página tres  ']), 'Página uno\nlínea dos\n\nPágina tres')
})

test('una página A4 se dibuja a ~220 ppp y una enorme se limita', () => {
  const escala = escalaParaPagina(595, 842)
  assert.ok(Math.abs(escala - 220 / 72) < 1e-9)
  assert.ok(842 * escala <= LADO_MAXIMO)
  const plano = escalaParaPagina(2384, 3370) // A0
  assert.ok(Math.abs(3370 * plano - LADO_MAXIMO) < 1e-6)
})

test('una foto enorme se reduce y una pequeña se amplía hasta el doble', () => {
  assert.ok(Math.abs(4000 * escalaParaImagen(4000, 3000) - LADO_MAXIMO) < 1e-6)
  assert.equal(escalaParaImagen(2000, 1500), 1)
  assert.equal(escalaParaImagen(600, 400), 2)
  assert.equal(escalaParaImagen(0, 0), 1)
})

test('pasa a grises y estira el contraste de un papel gris con tinta gris', () => {
  // 100 píxeles: 90 de «papel» (170) y 10 de «tinta» (90), en color.
  const datos = new Uint8ClampedArray(100 * 4)
  for (let i = 0; i < 100; i += 1) {
    const valor = i < 10 ? 90 : 170
    datos.set([valor, valor, valor + 10, 128], i * 4)
  }
  prepararPixeles(datos)
  const tinta = datos[0]
  const papel = datos[50 * 4]
  assert.equal(tinta, 0)
  assert.equal(papel, 255)
  // Gris de verdad (R = G = B) y opaco.
  assert.equal(datos[50 * 4 + 1], papel)
  assert.equal(datos[50 * 4 + 2], papel)
  assert.equal(datos[50 * 4 + 3], 255)
})

test('una imagen lisa no se estira (no amplifica el ruido)', () => {
  const datos = new Uint8ClampedArray(16 * 4).fill(200)
  prepararPixeles(datos)
  assert.equal(datos[0], 200)
})

test('el porcentaje total avanza por tareas y no se sale de 0–100', () => {
  assert.equal(porcentajeTotal(0, 4, 0), 0)
  assert.equal(porcentajeTotal(1, 4, 0.5), 38)
  assert.equal(porcentajeTotal(3, 4, 1), 100)
  assert.equal(porcentajeTotal(5, 4, 2), 100)
  assert.equal(porcentajeTotal(0, 0), 0)
})

test('el OCR de un PDF ocupa el tramo después de la lectura: la barra no vuelve atrás', () => {
  assert.equal(enTramo(10, 0), 10)
  assert.equal(enTramo(10, 50), 55)
  assert.equal(enTramo(10, 100), 100)
  assert.equal(enTramo(0, 37), 37)
})

test('traduce los errores de pdf.js', () => {
  assert.match(mensajeDeError({ name: 'PasswordException' }), /contraseña/)
  assert.match(mensajeDeError({ name: 'InvalidPDFException' }), /dañado/)
  assert.match(mensajeDeError(new Error('boom')), /No se pudo leer/)
})

test('textoDeArchivo con un entorno simulado: PDF digital sin OCR y escaneado con OCR', async () => {
  const paginasDigitales = [[item('REGISTRO ÚNICO DE PROVEEDORES, certifico que Juan Pérez', 50, 700)]]
  const pdfjsFalso = (paginas) => ({
    getDocument: () => ({
      promise: Promise.resolve({
        numPages: paginas.length,
        getPage: async (n) => ({
          getTextContent: async () => ({ items: paginas[n - 1] }),
          getViewport: ({ scale }) => ({ width: 595 * scale, height: 842 * scale }),
          render: () => ({ promise: Promise.resolve() }),
          cleanup() {},
        }),
        destroy: async () => {},
      }),
    }),
  })
  const contexto = {
    fillRect() {},
    getImageData: () => ({ data: new Uint8ClampedArray(4 * 4) }),
    putImageData() {},
    drawImage() {},
  }
  let terminado = 0
  const entorno = (paginas) => ({
    cargarPdfjs: async () => pdfjsFalso(paginas),
    crearCanvas: (width, height) => ({ width, height, getContext: () => contexto }),
    crearWorker: async (logger) => ({
      setParameters: async () => {},
      recognize: async () => {
        logger({ status: 'recognizing text', progress: 0.5 })
        return { data: { text: 'Texto  reconocido\nde la página' } }
      },
      terminate: async () => {
        terminado += 1
      },
    }),
  })

  const digital = await textoDeArchivo(archivo('rup.pdf', 'application/pdf'), { _entorno: entorno(paginasDigitales) })
  assert.deepEqual(digital, {
    texto: 'REGISTRO ÚNICO DE PROVEEDORES, certifico que Juan Pérez',
    paginas: 1,
    uso_ocr: false,
  })
  assert.equal(terminado, 0)

  const etapas = []
  const porcentajes = []
  const escaneado = await textoDeArchivo(archivo('rup.pdf', 'application/pdf'), {
    _entorno: entorno([...paginasDigitales, []]),
    onProgreso: (p) => {
      etapas.push(p.etapa)
      porcentajes.push(p.porcentaje)
    },
  })
  assert.equal(escaneado.uso_ocr, true)
  assert.equal(escaneado.paginas, 2)
  assert.match(escaneado.texto, /Juan Pérez\n\nTexto reconocido\nde la página$/)
  assert.ok(etapas.includes('cargando_ocr') && etapas.includes('reconociendo'))
  assert.equal(etapas.at(-1), 'listo')
  assert.deepEqual(porcentajes, [...porcentajes].sort((a, b) => a - b), 'el porcentaje solo sube')
  assert.equal(terminado, 1, 'el worker de Tesseract se libera al terminar')

  const muchas = Array.from({ length: 16 }, () => [])
  await assert.rejects(
    textoDeArchivo(archivo('rup.pdf', 'application/pdf'), { _entorno: entorno(muchas) }),
    /16 páginas escaneadas; se reconocen como máximo 15/,
  )
})
