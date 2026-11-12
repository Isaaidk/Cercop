/**
 * Texto de un documento escaneado o de una foto, sacado **en el navegador** (OCR).
 *
 * CONTRATO (lo usan Perfil y Preparar oferta; no cambiar sin avisar):
 *
 *   textoDeArchivo(archivo, { onProgreso }) -> Promise<{ texto, paginas, uso_ocr }>
 *     - PDF con texto: lo devuelve tal cual, sin OCR (uso_ocr = false).
 *     - PDF escaneado o imagen (jpg, png, webp, bmp, tiff si el navegador la abre): OCR en español.
 *     - onProgreso({ etapa, pagina, paginas, porcentaje, mensaje }) mientras trabaja.
 *     - Lanza Error con mensaje en español si no se puede leer.
 *
 *   esImagen(archivo) -> boolean
 *
 * Por qué en el navegador y no en el servidor: reconocer una página cuesta varios segundos de CPU
 * y la API tiene que aguantar 500–1.000 personas a la vez. En el equipo de quien sube el documento
 * no le cuesta nada al servidor, igual que `consultasPublicas.js` con el SRI. El servidor solo
 * recibe el texto ya sacado (`api.leerRupTexto`).
 *
 * Librerías (versiones fijas en `package.json`), cargadas con `import()` **solo** cuando hacen
 * falta, para que no pesen en el paquete principal:
 *   - `pdfjs-dist` (compilación «legacy», que abre también en navegadores de hace unos años): saca
 *     el texto de un PDF digital y dibuja como imagen las páginas que no lo tienen.
 *   - `tesseract.js` (Tesseract compilado a WebAssembly) con el idioma español. La primera vez el
 *     navegador descarga de jsDelivr, que es lo que `tesseract.js` usa por defecto: el script del
 *     worker (`cdn.jsdelivr.net/npm/tesseract.js@v<versión>/dist/worker.min.js`), el motor WASM
 *     (`cdn.jsdelivr.net/npm/tesseract.js-core@v<versión>/`) y los datos del español
 *     (`cdn.jsdelivr.net/npm/@tesseract.js-data/spa/4.0.0_best_int/spa.traineddata.gz`, el
 *     modelo LSTM «best» de tessdata en enteros). Los datos quedan guardados en IndexedDB, así que
 *     la segunda lectura no los vuelve a bajar. Si algún día hay que servirlos desde nuestro propio
 *     dominio (CSP estricta, red que bloquea el CDN), basta copiar esos archivos y pasar
 *     `workerPath`, `corePath` y `langPath` a `createWorker`.
 *
 * Rendimiento esperado: una página A4 a 220 ppp tarda de 2 a 6 s en un portátil normal y algo más
 * en un móvil; por eso hay un tope de `MAX_PAGINAS_OCR` páginas escaneadas por documento.
 */

// ------------------------------------------------------------------------------- reglas puras
// Todo lo de esta sección no toca el navegador: se prueba con `node --test` (tests/ocr.test.mjs).

/** Páginas escaneadas que se reconocen como máximo: con más, la espera pasa del minuto. */
export const MAX_PAGINAS_OCR = 15
/** Páginas de un PDF digital que se leen como máximo (sacar su texto es barato). */
export const MAX_PAGINAS_PDF = 300
/** Tamaño máximo del archivo: lo abre el navegador, en la memoria del equipo de la persona. */
export const MAX_BYTES = 30 * 1024 * 1024
/** Resolución a la que se dibuja una página escaneada: entre 200 y 300 ppp Tesseract rinde mejor. */
export const PPP_OCR = 220
/** Lado mayor máximo de la imagen que se reconoce: más píxeles solo gastan memoria en un móvil. */
export const LADO_MAXIMO = 3300
/** Por debajo de esto, una foto se amplía: Tesseract falla con letras de menos de ~20 px de alto. */
export const LADO_MINIMO = 1400
/** Con menos letras o cifras que esto, una página «no tiene texto» y se reconoce con OCR. */
export const MINIMO_CARACTERES_PAGINA = 25

export function esImagen(archivo) {
  return /^image\//.test(archivo?.type || '') || /\.(jpe?g|png|webp|bmp|tiff?|heic)$/i.test(archivo?.name || '')
}

export function esPdf(archivo) {
  return archivo?.type === 'application/pdf' || /\.pdf$/i.test(archivo?.name || '')
}

/** Lanza un Error en español si el archivo no se puede intentar leer. */
export function validarArchivo(archivo) {
  if (!archivo || typeof archivo.arrayBuffer !== 'function') {
    throw new Error('Elige un archivo para leer.')
  }
  if (!esPdf(archivo) && !esImagen(archivo)) {
    throw new Error('Solo se puede leer un PDF o una foto (JPG, PNG, WEBP, BMP o TIFF).')
  }
  if (!archivo.size) {
    throw new Error('El archivo está vacío.')
  }
  if (archivo.size > MAX_BYTES) {
    throw new Error(`El archivo pasa de ${Math.round(MAX_BYTES / 1024 / 1024)} MB. Sube uno más liviano.`)
  }
}

/** Letras y cifras de un texto: lo que cuenta para saber si una página trae texto de verdad. */
function caracteresUtiles(texto) {
  return (String(texto || '').match(/[\p{L}\p{N}]/gu) || []).length
}

/**
 * ¿Hay que reconocer esta página con OCR? Sí si casi no trae texto: un escaneo puro no trae nada y
 * muchos escáneres solo añaden un pie («Página 1»). Si el escáner ya le puso capa de texto, se usa.
 */
export function paginaSinTexto(texto) {
  return caracteresUtiles(texto) < MINIMO_CARACTERES_PAGINA
}

/** Índices (desde 0) de las páginas que necesitan OCR, a partir del texto de cada una. */
export function paginasParaOcr(textosPorPagina) {
  return (textosPorPagina || []).flatMap((texto, indice) => (paginaSinTexto(texto) ? [indice] : []))
}

/** Un PDF «parece escaneado» si alguna página no trae texto. */
export function pareceEscaneado(textosPorPagina) {
  return paginasParaOcr(textosPorPagina).length > 0
}

/**
 * Las líneas de una página a partir de los trozos de `getTextContent()` de pdf.js.
 *
 * pdf.js entrega trozos sueltos con su posición (`transform[4]` es x, `transform[5]` es y). El
 * lector del RUP del servidor trabaja **por renglones**, así que se corta línea cuando pdf.js lo
 * marca (`hasEOL`) o cuando el trozo siguiente baja de altura, y se pone un espacio cuando dos
 * trozos de la misma línea están separados (celdas de una tabla: «73210» y su descripción).
 */
export function lineasDeItems(items) {
  const lineas = []
  let actual = ''
  let anterior = null
  for (const item of items || []) {
    if (typeof item?.str !== 'string') continue
    const [, , , d = 0, x = 0, y = 0] = item.transform || []
    const alto = Math.abs(item.height || d || 10)
    if (anterior) {
      if (Math.abs(y - anterior.y) > alto * 0.5) {
        lineas.push(actual)
        actual = ''
      } else if (actual && !/\s$/.test(actual) && !/^\s/.test(item.str)) {
        const hueco = x - anterior.fin
        if (hueco > alto * 0.15) actual += ' '
      }
    }
    actual += item.str
    anterior = item.hasEOL ? null : { y, fin: x + (item.width || 0) }
    if (item.hasEOL) {
      lineas.push(actual)
      actual = ''
    }
  }
  if (actual) lineas.push(actual)
  return lineas.map((linea) => linea.replace(/[ \t\u00a0]+/g, ' ').trim())
}

/** Ordena el texto de una página: un renglón por línea, sin espacios sobrantes ni huecos largos. */
export function limpiarTexto(texto) {
  return String(texto || '')
    .replace(/\r\n?/g, '\n')
    .replace(/[\u00a0\u2000-\u200b\u202f\u3000\t]/g, ' ')
    .split('\n')
    .map((linea) => linea.replace(/ {2,}/g, ' ').trim())
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

/** El texto de todo el documento: las páginas separadas por una línea en blanco. */
export function armarTexto(textosPorPagina) {
  return (textosPorPagina || [])
    .map(limpiarTexto)
    .filter(Boolean)
    .join('\n\n')
}

/** Escala para dibujar una página de `ancho`×`alto` puntos PDF a `ppp`, sin pasar `LADO_MAXIMO`. */
export function escalaParaPagina(ancho, alto, ppp = PPP_OCR) {
  const escala = ppp / 72
  const mayor = Math.max(ancho, alto) * escala
  return mayor > LADO_MAXIMO ? LADO_MAXIMO / Math.max(ancho, alto) : escala
}

/** Escala para una foto: se reduce si es enorme y se amplía (hasta ×2) si es pequeña. */
export function escalaParaImagen(ancho, alto) {
  const mayor = Math.max(ancho, alto)
  if (!mayor) return 1
  if (mayor > LADO_MAXIMO) return LADO_MAXIMO / mayor
  if (mayor < LADO_MINIMO) return Math.min(2, LADO_MINIMO / mayor)
  return 1
}

/**
 * Pasa a grises y estira el contraste, sobre los píxeles RGBA de un canvas (en el sitio).
 *
 * Una foto de un papel suele tener el fondo gris y la tinta gris oscura; Tesseract binariza por su
 * cuenta, pero lo hace mejor si el papel es casi blanco y la tinta casi negra. Se toman los
 * percentiles 1 y 99 del brillo (no el mínimo y el máximo, que una mota o un reflejo estropean) y
 * se lleva ese rango a 0–255. No se binariza aquí: el umbral adaptativo de Tesseract lo hace mejor.
 */
export function prepararPixeles(datos) {
  const total = datos.length / 4
  if (!total) return datos
  const histograma = new Uint32Array(256)
  for (let i = 0; i < datos.length; i += 4) {
    // Luminancia de la recomendación BT.601, con enteros.
    const gris = (datos[i] * 299 + datos[i + 1] * 587 + datos[i + 2] * 114) / 1000
    const valor = Math.round(gris)
    datos[i] = valor
    histograma[valor] += 1
  }
  const corte = Math.floor(total * 0.01)
  let bajo = 0
  let acumulado = 0
  while (bajo < 255 && acumulado + histograma[bajo] <= corte) acumulado += histograma[bajo++]
  let alto = 255
  acumulado = 0
  while (alto > 0 && acumulado + histograma[alto] <= corte) acumulado += histograma[alto--]
  // Una imagen casi lisa (o en blanco) no se estira: solo se amplificaría el ruido.
  const rango = alto - bajo
  const estirar = rango >= 32
  for (let i = 0; i < datos.length; i += 4) {
    let valor = datos[i]
    if (estirar) valor = Math.max(0, Math.min(255, Math.round(((valor - bajo) * 255) / rango)))
    datos[i] = valor
    datos[i + 1] = valor
    datos[i + 2] = valor
    datos[i + 3] = 255
  }
  return datos
}

/** Porcentaje total (0–100) cuando va por la tarea `indice` de `total` y esa va en `fraccion`. */
export function porcentajeTotal(indice, total, fraccion = 0) {
  if (!total) return 0
  const avance = (indice + Math.max(0, Math.min(1, fraccion))) / total
  return Math.max(0, Math.min(100, Math.round(avance * 100)))
}

/**
 * Lleva un porcentaje 0–100 al tramo `desde`–100. En un PDF, sacar el texto ocupa el primer tramo
 * (`LECTURA_PDF`) y el OCR el resto, para que la barra nunca vuelva atrás.
 */
export function enTramo(desde, porcentaje) {
  return Math.round(desde + ((100 - desde) * Math.max(0, Math.min(100, porcentaje))) / 100)
}

/** Parte de la barra de progreso que ocupa sacar el texto de un PDF antes del OCR. */
export const LECTURA_PDF = 10

/** El mensaje en español para un error de pdf.js o de la carga del OCR. */
export function mensajeDeError(error) {
  const nombre = error?.name || ''
  if (nombre === 'PasswordException') {
    return 'El PDF está protegido con contraseña. Quítasela (o imprímelo de nuevo como PDF) y vuelve a subirlo.'
  }
  if (nombre === 'InvalidPDFException' || nombre === 'FormatError') {
    return 'El PDF está dañado o no es un PDF válido.'
  }
  if (error?.ocrEspanol) return error.message
  return 'No se pudo leer el documento en este navegador. Prueba con otro archivo o actualiza el navegador.'
}

function errorEspanol(mensaje, causa) {
  const error = new Error(mensaje, causa ? { cause: causa } : undefined)
  error.ocrEspanol = true
  return error
}

// ------------------------------------------------------------------------- entorno (navegador)
// Lo que depende del navegador va aquí, aparte, para que la prueba en Node pueda poner el suyo
// (canvas de @napi-rs y pdf.js sin worker) y ejercitar el mismo flujo.

let pdfjsCargado = null

async function cargarPdfjsNavegador() {
  if (!pdfjsCargado) {
    pdfjsCargado = (async () => {
      const [pdfjs, trabajador] = await Promise.all([
        import('pdfjs-dist/legacy/build/pdf.mjs'),
        // `?url` hace que Vite copie el worker como archivo aparte y devuelva su dirección.
        import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'),
      ])
      pdfjs.GlobalWorkerOptions.workerSrc = trabajador.default
      return pdfjs
    })().catch((error) => {
      pdfjsCargado = null
      throw error
    })
  }
  return pdfjsCargado
}

const ENTORNO_NAVEGADOR = {
  cargarPdfjs: cargarPdfjsNavegador,
  async crearWorker(logger) {
    const { createWorker } = await import('tesseract.js')
    // 1 = OEM.LSTM_ONLY: la red neuronal, la más precisa con los datos «best_int».
    return createWorker('spa', 1, { logger })
  },
  crearCanvas(ancho, alto) {
    const canvas = document.createElement('canvas')
    canvas.width = ancho
    canvas.height = alto
    return canvas
  },
  async abrirImagen(archivo) {
    // `createImageBitmap` respeta la orientación EXIF de la foto del móvil.
    if (typeof createImageBitmap === 'function') {
      try {
        const mapa = await createImageBitmap(archivo)
        return { imagen: mapa, ancho: mapa.width, alto: mapa.height, cerrar: () => mapa.close?.() }
      } catch {
        // Se intenta con <img>, que en algunos navegadores abre formatos que lo anterior no.
      }
    }
    const direccion = URL.createObjectURL(archivo)
    try {
      const imagen = new Image()
      imagen.decoding = 'async'
      imagen.src = direccion
      await imagen.decode()
      return { imagen, ancho: imagen.naturalWidth, alto: imagen.naturalHeight, cerrar: () => {} }
    } finally {
      URL.revokeObjectURL(direccion)
    }
  },
  liberarCanvas(canvas) {
    // En Safari la memoria de un canvas no se suelta hasta dejarlo en 0×0.
    canvas.width = 0
    canvas.height = 0
  },
}

// ------------------------------------------------------------------------------------- flujo

/**
 * Saca el texto de un PDF (digital o escaneado) o de una foto. Ver el contrato arriba.
 *
 * `etapa` de `onProgreso`: «preparando» (cargando librerías), «leyendo» (sacando el texto de un PDF
 * digital), «cargando_ocr» (bajando el motor y el español; solo tarda la primera vez),
 * «reconociendo» (OCR de una página) y «listo».
 *
 * `_entorno` es solo para pruebas: reemplaza lo que depende del navegador.
 */
export async function textoDeArchivo(archivo, { onProgreso, _entorno } = {}) {
  validarArchivo(archivo)
  const entorno = { ...ENTORNO_NAVEGADOR, ..._entorno }
  const avisar = (datos) => {
    try {
      onProgreso?.(datos)
    } catch {
      // Un fallo de la pantalla no debe cortar la lectura.
    }
  }
  const ocr = crearOcr(entorno, avisar)
  try {
    if (esPdf(archivo)) return await textoDePdf(archivo, entorno, ocr, avisar)
    return await textoDeImagen(archivo, entorno, ocr, avisar)
  } catch (error) {
    if (error?.ocrEspanol) throw error
    throw errorEspanol(mensajeDeError(error), error)
  } finally {
    await ocr.terminar()
  }
}

/** Un único worker de Tesseract por documento, creado al necesitarlo y liberado al acabar. */
function crearOcr(entorno, avisar) {
  let worker = null
  let tarea = { pagina: 1, paginas: 1, indice: 0, total: 1, desde: 0 }
  const logger = (mensaje) => {
    if (mensaje?.status === 'recognizing text') {
      avisar({
        etapa: 'reconociendo',
        pagina: tarea.pagina,
        paginas: tarea.paginas,
        porcentaje: enTramo(tarea.desde, porcentajeTotal(tarea.indice, tarea.total, mensaje.progress)),
        mensaje: `Reconociendo el texto de la página ${tarea.pagina} de ${tarea.paginas}…`,
      })
    }
  }
  return {
    async reconocer(imagen, datosTarea, ppp) {
      tarea = datosTarea
      if (!worker) {
        avisar({
          etapa: 'cargando_ocr',
          pagina: tarea.pagina,
          paginas: tarea.paginas,
          porcentaje: enTramo(tarea.desde, porcentajeTotal(tarea.indice, tarea.total)),
          mensaje: 'Preparando el lector de texto (la primera vez descarga el idioma español)…',
        })
        try {
          worker = await entorno.crearWorker(logger)
        } catch (error) {
          throw errorEspanol(
            'No se pudo cargar el lector de texto. Revisa tu conexión a internet: la primera vez ' +
              'descarga el motor y el idioma español desde cdn.jsdelivr.net.',
            error,
          )
        }
      }
      // La resolución real ayuda a Tesseract a calcular el tamaño de letra esperado.
      if (ppp) await worker.setParameters({ user_defined_dpi: String(Math.round(ppp)) })
      const { data } = await worker.recognize(imagen)
      return data?.text || ''
    },
    async terminar() {
      if (worker) {
        const actual = worker
        worker = null
        await actual.terminate().catch(() => {})
      }
    },
  }
}

/** Dibuja `fuente` en un canvas escalado, lo pasa a grises con contraste y lo devuelve. */
function canvasPreparado(entorno, ancho, alto, dibujar) {
  const canvas = entorno.crearCanvas(Math.max(1, Math.round(ancho)), Math.max(1, Math.round(alto)))
  const contexto = canvas.getContext('2d', { willReadFrequently: true })
  // Fondo blanco: un PNG con transparencia saldría negro al pasarlo a grises.
  contexto.fillStyle = '#ffffff'
  contexto.fillRect(0, 0, canvas.width, canvas.height)
  return Promise.resolve(dibujar(contexto, canvas)).then(() => {
    const pixeles = contexto.getImageData(0, 0, canvas.width, canvas.height)
    prepararPixeles(pixeles.data)
    contexto.putImageData(pixeles, 0, 0)
    return canvas
  })
}

async function textoDeImagen(archivo, entorno, ocr, avisar) {
  avisar({ etapa: 'preparando', pagina: 1, paginas: 1, porcentaje: 0, mensaje: 'Abriendo la imagen…' })
  let abierta
  try {
    abierta = await entorno.abrirImagen(archivo)
  } catch (error) {
    const heic = /\.heic$/i.test(archivo.name || '') || /heic|heif/i.test(archivo.type || '')
    throw errorEspanol(
      heic
        ? 'Este navegador no abre fotos HEIC (las del iPhone). Expórtala como JPG o haz una captura de pantalla y súbela.'
        : 'No se pudo abrir la imagen. Prueba con una foto en JPG o PNG.',
      error,
    )
  }
  let canvas
  try {
    const escala = escalaParaImagen(abierta.ancho, abierta.alto)
    canvas = await canvasPreparado(entorno, abierta.ancho * escala, abierta.alto * escala, (contexto, lienzo) => {
      contexto.drawImage(abierta.imagen, 0, 0, lienzo.width, lienzo.height)
    })
  } finally {
    abierta.cerrar?.()
  }
  try {
    const texto = await ocr.reconocer(canvas, { pagina: 1, paginas: 1, indice: 0, total: 1, desde: 0 })
    return terminar([texto], 1, true, avisar)
  } finally {
    entorno.liberarCanvas?.(canvas)
  }
}

async function textoDePdf(archivo, entorno, ocr, avisar) {
  avisar({ etapa: 'preparando', pagina: 0, paginas: 0, porcentaje: 0, mensaje: 'Abriendo el PDF…' })
  const pdfjs = await entorno.cargarPdfjs()
  const datos = new Uint8Array(await archivo.arrayBuffer())
  const documento = await pdfjs.getDocument({ data: datos, isEvalSupported: false }).promise
  try {
    const paginas = documento.numPages
    if (paginas > MAX_PAGINAS_PDF) {
      throw errorEspanol(`El PDF tiene ${paginas} páginas; se leen como máximo ${MAX_PAGINAS_PDF}.`)
    }
    // 1) El texto que ya trae cada página: barato, y en un PDF digital es todo lo que hace falta.
    const textos = []
    for (let numero = 1; numero <= paginas; numero += 1) {
      avisar({
        etapa: 'leyendo',
        pagina: numero,
        paginas,
        porcentaje: Math.round((LECTURA_PDF * (numero - 1)) / paginas),
        mensaje: `Leyendo la página ${numero} de ${paginas}…`,
      })
      const pagina = await documento.getPage(numero)
      const contenido = await pagina.getTextContent()
      textos.push(lineasDeItems(contenido.items).join('\n'))
      pagina.cleanup()
    }
    // 2) OCR solo de las páginas que no traen texto (un PDF puede mezclar las dos cosas).
    const pendientes = paginasParaOcr(textos)
    if (!pendientes.length) return terminar(textos, paginas, false, avisar)
    if (pendientes.length > MAX_PAGINAS_OCR) {
      throw errorEspanol(
        `El PDF tiene ${pendientes.length} páginas escaneadas; se reconocen como máximo ` +
          `${MAX_PAGINAS_OCR}. Sube solo las páginas que necesitas.`,
      )
    }
    for (const [indice, cero] of pendientes.entries()) {
      const numero = cero + 1
      const pagina = await documento.getPage(numero)
      const base = pagina.getViewport({ scale: 1 })
      const escala = escalaParaPagina(base.width, base.height)
      const vista = pagina.getViewport({ scale: escala })
      avisar({
        etapa: 'reconociendo',
        pagina: numero,
        paginas,
        porcentaje: enTramo(LECTURA_PDF, porcentajeTotal(indice, pendientes.length)),
        mensaje: `Preparando la página ${numero} de ${paginas}…`,
      })
      const canvas = await canvasPreparado(entorno, vista.width, vista.height, (contexto) =>
        pagina.render({ canvasContext: contexto, viewport: vista, background: '#ffffff' }).promise,
      )
      try {
        const texto = await ocr.reconocer(
          canvas,
          { pagina: numero, paginas, indice, total: pendientes.length, desde: LECTURA_PDF },
          escala * 72,
        )
        // Si la página traía un pie suelto, gana el OCR, que también lo lee.
        textos[cero] = texto
      } finally {
        entorno.liberarCanvas?.(canvas)
        pagina.cleanup()
      }
    }
    return terminar(textos, paginas, true, avisar)
  } finally {
    await documento.destroy()
  }
}

function terminar(textos, paginas, usoOcr, avisar) {
  const texto = armarTexto(textos)
  if (caracteresUtiles(texto) < 10) {
    throw errorEspanol(
      usoOcr
        ? 'No se encontró texto legible. Prueba con una foto más nítida, de frente, con buena luz y sin sombras.'
        : 'El documento no trae texto.',
    )
  }
  avisar({ etapa: 'listo', pagina: paginas, paginas, porcentaje: 100, mensaje: 'Listo.' })
  return { texto, paginas, uso_ocr: usoOcr }
}
