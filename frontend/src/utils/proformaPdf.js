/**
 * Arma el PDF de la proforma **en el navegador** de quien la prepara.
 *
 * Maquetar un PDF de decenas de renglones es trabajo de CPU. Hecho en el servidor, cada persona que
 * descarga o previsualiza su proforma ocupa el mismo proceso que atiende a todas las demás; hecho
 * aquí, el servidor solo guarda los datos. La librería (jsPDF) se carga recién al descargar, así que
 * no pesa en la carga del panel.
 *
 * El diseño sigue el formulario de proformas de ínfima cuantía del SOCE: datos del proveedor,
 * detalle del objeto de compra con CPC, unidad, cantidad, valor unitario ofertado y total, vigencia
 * de la proforma y documentos anexos. Después van las secciones propias de la oferta (condiciones,
 * cumplimiento del TDR con un recuadro de firma por requisito, declaración, firma y el Formulario de
 * Perfil de Integridad).
 *
 * Devuelve también los **recuadros de firma** (página y rectángulo en puntos PDF): el servidor
 * estampa ahí la firma electrónica sin volver a maquetar nada.
 */

const MM_A_PUNTOS = 72 / 25.4
const ALTO_PAGINA = 297
const LIMITE = 272
const ANCHO = 190

const AZUL_OSCURO = [30, 58, 138]
const TINTA = [19, 28, 51]
const GRIS = [71, 85, 105]
const LINEA = [203, 213, 225]
const FILA = [241, 245, 249]

// Helvetica del PDF solo trae Latin-1: lo que no tiene equivalente se cambia o se omite.
const EQUIVALENTES = {
  '‘': "'", '’': "'", '‚': "'", '“': '"', '”': '"', '„': '"',
  '«': '"', '»': '"', '–': '-', '—': '-', '―': '-', '…': '...',
  '•': '-', ' ': ' ', ' ': ' ',
}
// El portal a veces entrega UTF-8 leído como Latin-1: un guion largo llega como «â€“». Se repara.
const MOJIBAKE = { '“': '-', '”': '-', '™': "'", 'œ': '"', '\u009d': '"', '˜': "'" }

function limpio(valor) {
  return String(valor ?? '')
    .replace(/â€[“”™œ˜\u009d]?/g, (c) => MOJIBAKE[c.slice(2)] ?? '-')
    .replace(/[‘’‚“”„«»–—―…•  ]/g, (c) => EQUIVALENTES[c])
    .replace(/[^\u0000-ÿ]/g, '')
}

const precio5 = (valor) => (Number.isFinite(Number(valor)) ? Number(valor).toFixed(5) : '')
const cantidad2 = (valor) => (Number.isFinite(Number(valor)) ? Number(valor).toFixed(2) : '')
const entero = (valor) => (Number.isInteger(Number(valor)) ? String(Number(valor)) : String(Number(valor)))

const ETIQUETA = 45
const ANCHOS = [10, 20, 26, 58, 16, 18, 20, 22]
const CABECERAS = ['Ítem', 'CPC', 'Producto', 'Descripción de servicios requeridos', 'Cantidad', 'Unidad de medida', 'Valor unitario', 'Valor Total']

const NEGRO = [0, 0, 0]
const VERDE = [169, 209, 142]
const AZUL_BLOQUE = [132, 151, 176]
const AZUL_CABECERA = [132, 151, 176]
const GRIS_CLARO = [217, 217, 217]

/** «45 días calendario» → «45 DÍAS»; lo que no empieza con un número se deja en mayúsculas. */
function diasEnMayuscula(valor) {
  const texto = String(valor ?? '').trim()
  if (!texto) return ''
  const dias = texto.match(/^\s*(\d+)\s*(d[ií]as?)?/i)
  return dias && dias[2] ? `${dias[1]} DÍAS` : texto.toUpperCase().slice(0, 90)
}

function fechaCorta(valor) {
  const iso = String(valor || '').match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return `${iso[3]}/${iso[2]}/${iso[1]}`
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(String(valor || ''))) return String(valor)
  const d = new Date()
  const dos = (n) => String(n).padStart(2, '0')
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)}/${d.getFullYear()}`
}

/** El CPC de 9 dígitos se escribe «4733105 12», como en el formulario. */
function cpcConEspacio(valor) {
  const c = String(valor ?? '').replace(/\s+/g, '')
  return /^\d{9,}$/.test(c) ? `${c.slice(0, 7)} ${c.slice(7)}` : c
}

/** Cifra sin ceros sobrantes: 3020, 2.5, 0.12345. */
function numero(valor) {
  const n = Number(valor)
  return Number.isFinite(n) && valor !== '' && valor != null ? String(Number(n.toFixed(5))) : ''
}

const coma = (valor) => (Number.isFinite(Number(valor)) ? Number(valor).toFixed(2).replace('.', ',') : '')

const UNIDADES = ['', 'UN', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE', 'DIEZ', 'ONCE', 'DOCE', 'TRECE', 'CATORCE', 'QUINCE', 'DIECISÉIS', 'DIECISIETE', 'DIECIOCHO', 'DIECINUEVE', 'VEINTE', 'VEINTIÚN', 'VEINTIDÓS', 'VEINTITRÉS', 'VEINTICUATRO', 'VEINTICINCO', 'VEINTISÉIS', 'VEINTISIETE', 'VEINTIOCHO', 'VEINTINUEVE']
const DECENAS = ['', '', '', 'TREINTA', 'CUARENTA', 'CINCUENTA', 'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
const CENTENAS = ['', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 'QUINIENTOS', 'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS']

function menorDeMil(n) {
  if (n === 100) return 'CIEN'
  const c = Math.floor(n / 100)
  const r = n % 100
  const partes = []
  if (c) partes.push(CENTENAS[c])
  if (r < 30) {
    if (r) partes.push(UNIDADES[r])
  } else {
    const d = Math.floor(r / 10)
    const u = r % 10
    partes.push(u ? `${DECENAS[d]} Y ${UNIDADES[u]}` : DECENAS[d])
  }
  return partes.join(' ')
}

function enLetras(n) {
  if (n === 0) return 'CERO'
  const miles = Math.floor(n / 1000)
  const resto = n % 1000
  const partes = []
  if (miles) {
    const millones = Math.floor(miles / 1000)
    const m = miles % 1000
    if (millones) partes.push(millones === 1 ? 'UN MILLÓN' : `${enLetras(millones)} MILLONES`)
    if (m) partes.push(m === 1 ? 'MIL' : `${menorDeMil(m)} MIL`)
  }
  if (resto) partes.push(menorDeMil(resto))
  return partes.join(' ')
}

/** 83607 → «OCHENTA Y TRES MIL SEISCIENTOS SIETE DÓLARES»; con centavos, «… CON 05/100». */
export function dolaresEnLetras(valor) {
  const n = Math.round(Number(valor || 0) * 100)
  const enteros = Math.floor(n / 100)
  const centavos = n % 100
  const base = `${enLetras(enteros)} ${enteros === 1 ? 'DÓLAR' : 'DÓLARES'}`
  return centavos ? `${base} CON ${String(centavos).padStart(2, '0')}/100` : base
}

const TIPOS = {
  proforma: ['PROFORMA', 'Documento con los efectos de oferta, conforme la normativa de ínfima cuantía del SERCOP', 'esta proforma'],
  cotizacion: ['COTIZACIÓN', 'Cotización para el estudio de mercado y la determinación del presupuesto referencial de la entidad, conforme la normativa del SERCOP', 'esta cotización'],
}

/** El título que va arriba del documento: el que puso la persona, o «PROFORMA»/«COTIZACIÓN». */
export function tituloDelDocumento(documento = {}) {
  const [generico] = TIPOS[documento.tipo] || TIPOS.proforma
  const propio = String(documento.titulo || '').replace(/\s+/g, ' ').trim()
  return propio ? propio.toUpperCase() : generico
}

const INTEGRIDAD = [
  '1. Conozco formalmente el contenido, alcance y principios de la Política Nacional de Integridad Pública (PNIP). Garantizo que mi actuación en este procedimiento se ceñirá estrictamente a los valores de honestidad, legalidad, integridad, probidad y prevención de conflictos de interés, así como a las directrices e instrumentos que emita la Secretaría General de Integridad Pública, para promover la integridad y fortalecer la lucha contra la corrupción.',
  '2. En mi calidad de proveedor del Estado, no he ofrecido, entregado, prometido ni facilitado dinero, bienes, dádivas, favores ni ventajas indebidas de orden material o inmaterial a ningún servidor público, trabajador de la entidad contratante o persona del sector privado, con el objeto de influir, viciar u obtener un trato favorable en este o cualquier otro procedimiento de contratación en el que haya participado.',
  '3. No me encuentro incurso en ningún conflicto de intereses con los miembros de la Comisión Técnica y/o el delegado de la fase precontractual, ni con los servidores públicos que intervengan en la sustanciación de las fases y etapas de este procedimiento de contratación de {entidad}, garantizando que mi participación está libre de conductas que configuren tráfico de influencias, colusión o cualquier otro delito contra la administración pública.',
  '4. Toda la información y documentación consignada en este formulario y en mi oferta es veraz, exacta, completa y actualizada. Acepto que, si la entidad contratante, el Servicio Nacional de Contratación Pública o cualquier organismo de control constata falsedad o alteración en estos datos, o si se determinan motivadamente riesgos sustanciales para la seguridad integral del Estado conforme al Decreto Ejecutivo Nro. 328 del 12 de marzo de 2026, esto constituirá una falta de idoneidad en materia de integridad pública. En consecuencia, acepto que dicha condición se calificará como incumplimiento de un requisito mínimo, dando lugar a la descalificación inmediata de la oferta en la etapa precontractual, o a la declaratoria de adjudicatario fallido o contratista incumplido, según corresponda, sin perjuicio de las acciones administrativas, civiles y penales pertinentes.',
]
const COMPROMISO =
  'Así también me comprometo a poner en conocimiento y denunciar de manera inmediata ante la Fiscalía General del Estado, la Secretaría General de Integridad Pública, la máxima autoridad de la entidad contratante o cualquier otra autoridad competente, todo presunto delito contra la administración pública o acto de corrupción del cual llegue a tener conocimiento, a fin de que se adopten las acciones y medidas legales en contra de los presuntos infractores.'

class Maquetador {
  constructor(doc, documento) {
    this.doc = doc
    this.documento = documento
    this.extras = documento.extras || {}
    this.empresa = this.extras.empresa || {}
    this.nombre = limpio(this.empresa.razon_social || documento.titulo || 'Proforma')
    this.cajas = []
    this.y = 0
    doc.setLineHeightFactor(1.3)
  }

  get pagina() {
    return this.doc.getCurrentPageInfo().pageNumber
  }

  /** Alto de un renglón de texto, en milímetros. */
  alto(size) {
    return size * 0.3528 * 1.3
  }

  fuente(size, estilo = 'normal', color = TINTA) {
    this.doc.setFont('helvetica', estilo)
    this.doc.setFontSize(size)
    this.doc.setTextColor(...color)
  }

  partir(texto, ancho, size, estilo = 'normal') {
    this.fuente(size, estilo)
    return this.doc.splitTextToSize(limpio(texto), ancho)
  }

  nuevaPagina() {
    this.doc.addPage()
    this.fuente(8, 'italic', GRIS)
    this.doc.text(`${this.nombre}  ·  ${this.tipoTexto}`, 10, 11, { baseline: 'top' })
    this.y = 22
  }

  asegurar(alto) {
    if (this.y + alto > LIMITE) this.nuevaPagina()
  }

  registrarCaja(x, y, ancho, alto) {
    const k = MM_A_PUNTOS
    this.cajas.push({
      pagina: this.pagina - 1,
      caja: [
        Math.round(x * k * 10) / 10,
        Math.round((ALTO_PAGINA - y - alto) * k * 10) / 10,
        Math.round((x + ancho) * k * 10) / 10,
        Math.round((ALTO_PAGINA - y) * k * 10) / 10,
      ],
    })
  }

  // ----------------------------------------------------------------------- bloques generales

  titulo(texto, subtitulo) {
    const { doc } = this
    this.fuente(16, 'bold', AZUL_OSCURO)
    doc.text(texto, 105, this.y, { align: 'center', baseline: 'top' })
    this.y += 8
    this.fuente(8, 'normal', GRIS)
    for (const linea of this.partir(subtitulo, ANCHO - 20, 8)) {
      doc.text(linea, 105, this.y, { align: 'center', baseline: 'top' })
      this.y += this.alto(8)
    }
    this.y += 2
  }

  seccion(texto) {
    if (this.y > 258) this.nuevaPagina()
    this.y += 4
    this.doc.setFillColor(...AZUL_OSCURO)
    this.doc.rect(10, this.y - 0.3, 1.8, 5.6, 'F')
    this.fuente(10, 'bold')
    this.doc.text(limpio(texto), 14, this.y, { baseline: 'top' })
    this.y += 7.5
  }

  dato(etiqueta, valor) {
    const texto = String(valor ?? '').trim()
    if (!texto) return
    const lineas = this.partir(texto, ANCHO - 46, 8.5)
    this.asegurar(lineas.length * this.alto(8.5) + 1)
    this.fuente(8.5, 'bold')
    this.doc.text(limpio(etiqueta), 10, this.y, { baseline: 'top' })
    this.fuente(8.5)
    this.doc.text(lineas, 56, this.y, { baseline: 'top' })
    this.y += lineas.length * this.alto(8.5) + 0.8
  }

  parrafo(texto, size = 9, ancho = ANCHO, x = 10, despues = 1.5, estilo = 'normal', color = TINTA) {
    const lineas = this.partir(texto, ancho, size, estilo)
    this.fuente(size, estilo, color)
    for (const linea of lineas) {
      this.asegurar(this.alto(size))
      this.doc.text(linea, x, this.y, { baseline: 'top' })
      this.y += this.alto(size)
    }
    this.y += despues
  }

  // ----------------------------------------------------------------------- modelo del SOCE

  /** Celda con borde. `lineas` ya viene partida; se centra o alinea a la izquierda. */
  celda(x, y, ancho, alto, lineas, { alinear = 'center', size = 7.5, estilo = 'normal', relleno = null, color = TINTA } = {}) {
    const { doc } = this
    doc.setDrawColor(...NEGRO)
    doc.setLineWidth(0.15)
    if (relleno) {
      doc.setFillColor(...relleno)
      doc.rect(x, y, ancho, alto, 'FD')
    } else {
      doc.rect(x, y, ancho, alto)
    }
    if (!lineas.length) return
    this.fuente(size, estilo, color)
    const alto_texto = lineas.length * this.alto(size)
    const ay = y + Math.max(0.8, (alto - alto_texto) / 2)
    const ax = alinear === 'center' ? x + ancho / 2 : x + 1.5
    this.doc.text(lineas, ax, ay, { align: alinear, baseline: 'top' })
  }

  /** Barra de color a todo el ancho con un título (VERDE para la proforma, AZUL para cada bloque). */
  barra(texto, relleno, size = 8.5, alto = 6) {
    this.asegurar(alto + 2)
    this.celda(10, this.y, ANCHO, alto, texto ? [limpio(texto)] : [], { size, estilo: 'bold', relleno })
    this.y += alto
  }

  /** Fila «etiqueta | valor»: etiqueta en negrita centrada, valor a la izquierda. */
  fila(etiqueta, valor, { negrita = false, minimo = 4.8 } = {}) {
    const texto = String(valor ?? '').trim()
    const lineas = texto ? this.partir(texto, ANCHO - ETIQUETA - 3, 7.5, negrita ? 'bold' : 'normal') : []
    const rotulo = this.partir(etiqueta, ETIQUETA - 2, 7.5, 'bold')
    const alto = Math.max(minimo, lineas.length * this.alto(7.5) + 1.6, rotulo.length * this.alto(7.5) + 1.6)
    this.asegurar(alto)
    this.celda(10, this.y, ETIQUETA, alto, rotulo, { estilo: 'bold' })
    this.celda(10 + ETIQUETA, this.y, ANCHO - ETIQUETA, alto, lineas, { alinear: 'left', estilo: negrita ? 'bold' : 'normal' })
    this.y += alto
  }

  numeroDeProforma() {
    const { extras, documento } = this
    // La barra verde lleva el título que escribió la persona (referente a la ínfima) en lugar del
    // genérico «PROFORMA»; sin título propio, queda el genérico.
    const titulo = tituloDelDocumento(documento)
    const numero = String(extras.numero || '').trim()
    const texto = numero ? `${titulo} Nro.${numero}` : titulo
    const size = texto.length > 90 ? 9.5 : 11
    const lineas = this.partir(limpio(texto), ANCHO - 6, size, 'bold')
    const alto = Math.max(9, lineas.length * this.alto(size) + 3)
    this.asegurar(alto + 2)
    this.celda(10, this.y, ANCHO, alto, lineas, { size, estilo: 'bold', relleno: VERDE })
    this.y += alto + 1.2
  }

  bloqueEntidad() {
    const { documento, extras } = this
    const e = extras.entidad || {}
    this.barra('Entidad', AZUL_BLOQUE)
    this.fila('Entidad', String(documento.entidad || '').toUpperCase())
    this.fila('RUC', e.ruc, { negrita: true })
    this.fila('Dirección', e.direccion)
    this.fila('Teléfono', e.telefono)
  }

  bloqueInformacion() {
    const { extras } = this
    const c = extras.condiciones || {}
    this.barra('INFORMACIÓN PROFORMA', AZUL_BLOQUE)
    this.fila('Tiempo de vigencia', diasEnMayuscula(c.validez))
    this.fila('Plazo de ejecución', diasEnMayuscula(c.plazo_ejecucion || c.plazo_entrega))
    this.fila('Garantías', c.garantia)
    this.fila('Forma de pago', c.forma_pago)
    this.fila('Código Necesidad de Contratación', extras.necesidad || extras.codigo)
    this.y += 1.2
  }

  bloqueOferente() {
    const e = this.empresa
    this.barra('DATOS DEL OFERENTE', AZUL_BLOQUE)
    this.fila('Razón social', e.razon_social, { minimo: 5.5 })
    this.fila('RUC', e.ruc, { negrita: true })
    const direccion = [e.direccion, [e.canton || e.ciudad, e.provincia].filter(Boolean).join(', ')].filter(Boolean).join(' - ')
    this.fila('Dirección', direccion, { minimo: 9 })
    this.fila('Teléfono', e.telefono)
    this.fila('Correo electrónico', e.email)
  }

  /** Recuadro de la firma electrónica del oferente y datos de la emisión, como en el modelo. */
  bloqueFirmaYFecha() {
    const { extras } = this
    const e = this.empresa
    this.asegurar(62)
    const alto = 30
    this.celda(10, this.y, ANCHO, alto, [])
    // El sello de la firma queda en el centro de este recuadro.
    const ancho = 70
    const x = 10 + (ANCHO - ancho) / 2
    this.doc.setDrawColor(...GRIS)
    this.doc.setLineWidth(0.2)
    this.doc.rect(x, this.y + 2.5, ancho, alto - 5)
    this.registrarCaja(x, this.y + 2.5, ancho, alto - 5)
    this.fuente(6, 'normal', GRIS)
    this.doc.text('Firma electrónica del oferente', x + ancho / 2, this.y + alto - 2.2, { align: 'center', baseline: 'top' })
    this.y += alto
    this.barra('', AZUL_BLOQUE, 8, 2.5)
    const codigo = extras.necesidad || extras.codigo || ''
    this.celda(10, this.y, ANCHO, 5.5, codigo ? [limpio(codigo)] : [], { estilo: 'bold' })
    this.y += 5.5
    this.celda(10, this.y, ANCHO, 5.5, [limpio(e.razon_social || this.nombre)], { estilo: 'bold' })
    this.y += 5.5
    this.celda(10, this.y, ANCHO, 8, [`Fecha ${fechaCorta(extras.fecha)}`], { estilo: 'bold' })
    this.y += 8
    const lugar = [e.ciudad || e.canton, e.pais || 'Ecuador'].filter(Boolean).join(' - ')
    this.celda(10, this.y, ANCHO, 6, [limpio(lugar)], { estilo: 'bold' })
    this.y += 6
  }

  bloqueObjeto() {
    const { documento } = this
    this.barra('OBJETO', AZUL_BLOQUE)
    const lineas = this.partir(documento.objeto || '', ANCHO - 4, 7)
    const alto = Math.max(6, lineas.length * this.alto(7) + 2)
    this.celda(10, this.y, ANCHO, alto, lineas, { size: 7 })
    this.y += alto
  }

  cabeceraTerminos() {
    let x = 10
    CABECERAS.forEach((texto, i) => {
      this.celda(x, this.y, ANCHOS[i], 6.5, this.partir(texto, ANCHOS[i] - 1.5, 6.5, 'bold'), { size: 6.5, estilo: 'bold', relleno: i === 7 ? GRIS_CLARO : AZUL_CABECERA })
      x += ANCHOS[i]
    })
    this.y += 6.5
  }

  detalleDeCompra() {
    const { documento } = this
    const lineas = documento.lineas || []
    this.asegurar(30)
    this.celda(10, this.y, ANCHO, 8, ['Términos de Referencia conforme el requerimiento - Detallado'], { size: 8.5, estilo: 'bold', relleno: AZUL_CABECERA })
    this.y += 8
    this.cabeceraTerminos()
    lineas.forEach((linea, n) => {
      const celdas = [
        String(n + 1),
        cpcConEspacio(linea.cpc),
        String(linea.cpc_nombre || '').toUpperCase(),
        String(linea.descripcion || ''),
        entero(linea.cantidad),
        String(linea.unidad || '').slice(0, 3) || 'U',
        numero(linea.precio_unitario),
        numero(linea.subtotal),
      ]
      const partidas = celdas.map((t, i) => (t ? this.partir(t, ANCHOS[i] - 3, 6.5) : []))
      const alto = Math.max(9, ...partidas.map((l) => l.length * this.alto(6.5) + 2))
      if (this.y + alto > LIMITE) {
        this.nuevaPagina()
        this.cabeceraTerminos()
      }
      let x = 10
      partidas.forEach((lineasCelda, i) => {
        this.celda(x, this.y, ANCHOS[i], alto, lineasCelda, { alinear: i === 3 ? 'left' : 'center', size: 6.5 })
        x += ANCHOS[i]
      })
      this.y += alto
    })
    const cifras = documento.cifras || {}
    if (!Object.keys(cifras).length) return
    this.asegurar(30)
    const izq = 10 + ANCHO - ANCHOS[6] - ANCHOS[7]
    const porcentaje = Number(cifras.impuesto_porcentaje || 0)
    const totales = [
      ['Subtotal', cifras.subtotal],
      [`IVA ${entero(porcentaje)}%`, cifras.impuesto],
      ['Total', cifras.total],
    ]
    this.celda(10, this.y, ANCHO, 0.1, [])
    for (const [etiqueta, valor] of totales) {
      this.celda(izq, this.y, ANCHOS[6], 4.2, [etiqueta], { alinear: 'left', size: 6.5 })
      this.celda(izq + ANCHOS[6], this.y, ANCHOS[7], 4.2, [coma(valor)], { size: 6.5, estilo: 'bold' })
      this.y += 4.2
    }
    this.y += 1.5
    const letras = dolaresEnLetras(cifras.subtotal)
    const texto = `TOTAL: ${letras} de los Estados Unidos de Norteamérica, más IVA.`
    const partidas = this.partir(texto, ANCHO - 3, 6.5)
    const alto = Math.max(5, partidas.length * this.alto(6.5) + 1.6)
    this.celda(10, this.y, ANCHO, alto, partidas, { alinear: 'left', size: 6.5 })
    this.y += alto
    this.barra('', AZUL_BLOQUE, 8, 6)
  }

  // ----------------------------------------------------------------------- secciones de la oferta

  presentacion() {
    if (!this.extras.carta) return
    this.seccion('PRESENTACIÓN')
    for (const parrafo of String(this.extras.carta).split('\n')) {
      if (parrafo.trim()) this.parrafo(parrafo.trim(), 9.5, ANCHO, 10, 1.4)
    }
  }

  condiciones() {
    const c = this.extras.condiciones || {}
    const filas = [
      ['Plazo de entrega:', c.plazo_entrega],
      ['Lugar de entrega:', c.lugar_entrega],
    ].filter(([, v]) => String(v || '').trim())
    if (!filas.length) return
    this.seccion('CONDICIONES DE LA OFERTA')
    for (const [etiqueta, valor] of filas) this.dato(etiqueta, valor)
  }

  listas() {
    for (const [titulo, clave] of [['EXPERIENCIA DEL OFERENTE', 'experiencia'], ['PERSONAL TÉCNICO', 'personal'], ['EQUIPO DISPONIBLE', 'equipo']]) {
      const filas = (this.extras[clave] || []).map(String).filter((f) => f.trim())
      if (!filas.length) continue
      this.seccion(titulo)
      for (const fila of filas) this.parrafo(`-  ${fila}`, 9, ANCHO - 2, 12, 0.8)
    }
  }

  cumplimiento() {
    const filas = (this.extras.cumplimiento || []).filter((f) => f && String(f.requisito || '').trim())
    if (!filas.length) return
    this.seccion('CUMPLIMIENTO DE LOS TÉRMINOS DE REFERENCIA')
    const anchos = [10, 56, 70, 54]
    const cabecera = () => {
      let x = 10
      ;['N.º', 'Requisito del TDR', 'Cómo cumple el oferente', 'Firma electrónica'].forEach((t, i) => {
        this.doc.setFillColor(...AZUL_OSCURO)
        this.doc.rect(x, this.y, anchos[i], 6.5, 'F')
        this.fuente(8, 'bold', [255, 255, 255])
        this.doc.text(t, x + anchos[i] / 2, this.y + 1.6, { align: 'center', baseline: 'top' })
        x += anchos[i]
      })
      this.y += 6.5
    }
    this.asegurar(30)
    cabecera()
    const firmante = limpio(this.empresa.representante || this.nombre)
    filas.forEach((fila, n) => {
      const textos = [`R${n + 1}`, String(fila.requisito).trim(), String(fila.como_cumple || '').trim() || 'Sin respuesta']
      const partidas = textos.map((t, i) => this.partir(t, anchos[i] - 2, 8.5, i < 2 ? 'bold' : 'normal'))
      const alto = Math.max(20, ...partidas.map((l) => l.length * this.alto(8.5) + 2.8))
      if (this.y + alto > LIMITE) {
        this.nuevaPagina()
        cabecera()
      }
      if ((n + 1) % 2 === 0) {
        this.doc.setFillColor(...FILA)
        this.doc.rect(10, this.y, ANCHO, alto, 'F')
      }
      let x = 10
      partidas.forEach((lineas, i) => {
        this.fuente(8.5, i < 2 ? 'bold' : 'normal')
        this.doc.text(lineas, i === 0 ? x + anchos[0] / 2 : x + 1, this.y + 1, { align: i === 0 ? 'center' : 'left', baseline: 'top' })
        x += anchos[i]
      })
      // Recuadro de firma de la fila: el sello de la firma electrónica queda exactamente aquí.
      const fx = x + 1.5
      this.doc.setDrawColor(...LINEA)
      this.doc.setLineWidth(0.2)
      this.doc.rect(fx, this.y + 1.2, anchos[3] - 3, alto - 8.5)
      this.registrarCaja(fx, this.y + 1.2, anchos[3] - 3, alto - 8.5)
      this.fuente(6, 'normal', GRIS)
      this.doc.text(this.partir(firmante, anchos[3] - 2, 6).slice(0, 2), x + anchos[3] / 2, this.y + alto - 6.8, { align: 'center', baseline: 'top' })
      this.y += alto
    })
    this.doc.setDrawColor(...LINEA)
    this.doc.line(10, this.y, 200, this.y)
  }

  declaracion() {
    const este = (TIPOS[this.documento.tipo] || TIPOS.proforma)[2]
    this.seccion('DECLARACIÓN DEL OFERENTE')
    this.parrafo(
      `${this.nombre} declara que no se encuentra incursa en ninguna de las inhabilidades ni prohibiciones para contratar con el Estado previstas en la Ley Orgánica del Sistema Nacional de Contratación Pública, que conoce y acepta las condiciones establecidas por la entidad contratante, y que los precios de ${este} incluyen todos los costos, impuestos y obligaciones tributarias. La vigencia indicada se cuenta desde la fecha de emisión.`,
      8.5, ANCHO, 10, 1,
    )
  }

  /** Firma de responsabilidad, con el recuadro a la derecha a la altura del bloque. */
  firma() {
    const e = this.empresa
    const nota =
      'Firma de responsabilidad. En la ínfima cuantía la firma electrónica es exigible en la orden de compra o la factura; en la proforma es opcional. Si se firma, se hace con FirmaEC o con un certificado de una entidad acreditada, y cada recuadro lleva su sello.'
    this.asegurar(42)
    this.y += 4
    const y0 = this.y
    const { doc } = this
    doc.setDrawColor(...AZUL_OSCURO)
    doc.setLineWidth(0.4)
    doc.line(10, y0, 95, y0)
    this.y += 2
    if (e.representante) {
      this.fuente(10, 'bold')
      doc.text(limpio(e.representante), 10, this.y, { baseline: 'top' })
      this.y += 4.8
    }
    for (const fila of [e.cargo, e.cedula ? `C.I. ${e.cedula}` : '', this.nombre]) {
      if (!fila) continue
      this.fuente(9, 'normal', GRIS)
      doc.text(limpio(fila), 10, this.y, { baseline: 'top' })
      this.y += 4.4
    }
    this.fuente(7, 'italic', GRIS)
    const lineas = this.partir(nota, 105, 7, 'italic')
    doc.text(lineas, 10, this.y + 1, { baseline: 'top' })
    this.y += lineas.length * this.alto(7) + 2
    // El recuadro de firma, a la derecha y a la altura del bloque.
    doc.setDrawColor(...AZUL_OSCURO)
    doc.setLineWidth(0.3)
    doc.rect(120, y0, 80, 30)
    this.registrarCaja(120, y0, 80, 30)
    this.fuente(7, 'normal', GRIS)
    doc.text('Firma electrónica', 120, y0 - 3.6, { baseline: 'top' })
    this.y = Math.max(this.y, y0 + 31)
  }

  integridad() {
    const e = this.empresa
    this.nuevaPagina()
    this.titulo(
      'FORMULARIO DE PERFIL DE INTEGRIDAD DEL PROVEEDOR',
      'Anexo I de la Resolución Nro. R.E-SERCOP-2026-0005, que se presenta junto con la oferta',
    )
    const entidad = this.documento.entidad || 'la entidad contratante'
    const razon = e.razon_social || ''
    const firmante = e.representante || razon
    const ruc = e.ruc || ''
    const porRazon = razon && firmante !== razon ? `, por la razón social ${razon}` : ''
    this.parrafo(
      `Yo, ${firmante || '[nombre completo]'}${porRazon}, portador del RUC No. ${ruc || '[RUC]'}, en atención a la convocatoria realizada por ${entidad} para la ejecución de «${this.documento.objeto || '[objeto]'}», dentro del procedimiento de contratación pública con el código ${this.extras.codigo || '[código del proceso]'}, al presentar mi oferta suscribo el presente Formulario de Perfil de Integridad del Proveedor, y declaro que:`,
      9, ANCHO, 10, 2,
    )
    for (const texto of INTEGRIDAD) this.parrafo(texto.replace('{entidad}', entidad), 8.6, ANCHO, 10, 1.6)
    this.parrafo(COMPROMISO, 8.6, ANCHO, 10, 4)
    this.asegurar(40)
    this.y += 4
    const y0 = this.y
    this.doc.setDrawColor(...AZUL_OSCURO)
    this.doc.setLineWidth(0.3)
    this.doc.rect(10, y0, 80, 30)
    this.fuente(7, 'normal', GRIS)
    this.doc.text('Firma manuscrita o la del recuadro de la primera página', 10, y0 - 3.6, { baseline: 'top' })
    this.fuente(9)
    const lugarFecha = [e.ciudad, this.extras.fecha].filter(Boolean).join(', ')
    let y = y0 + 2
    for (const [etiqueta, valor] of [['Nombre:', firmante], ['C.C. / RUC:', ruc || e.cedula || ''], ['Lugar y fecha:', lugarFecha]]) {
      this.doc.text(limpio(`${etiqueta} ${valor}`), 100, y, { baseline: 'top' })
      y += 5.5
    }
    this.y = y0 + 31
  }

  pies() {
    const total = this.doc.getNumberOfPages()
    for (let i = 1; i <= total; i += 1) {
      this.doc.setPage(i)
      this.doc.setDrawColor(...LINEA)
      this.doc.setLineWidth(0.2)
      this.doc.line(10, 283, 200, 283)
      this.fuente(7.5, 'normal', GRIS)
      const ruc = this.empresa.ruc ? `  ·  RUC ${this.empresa.ruc}` : ''
      this.doc.text(limpio(`${this.nombre}${ruc}`), 10, 285.5, { baseline: 'top' })
      this.doc.text(`Página ${i} de ${total}`, 200, 285.5, { align: 'right', baseline: 'top' })
    }
  }
}

/**
 * @param {object} documento la proforma o cotización guardada (`GET /v1/documentos/proformas/{id}`)
 * @returns {Promise<{ blob: Blob, cajas: Array<{pagina: number, caja: number[]}> }>}
 */
export async function armarProformaPdf(documento) {
  const { jsPDF } = await import('jspdf')
  const doc = new jsPDF({ unit: 'mm', format: 'a4', compress: true })
  const m = new Maquetador(doc, documento)
  const [titulo] = TIPOS[documento.tipo] || TIPOS.proforma
  m.tipoTexto = titulo.charAt(0) + titulo.slice(1).toLowerCase()

  m.numeroDeProforma()
  m.bloqueEntidad()
  m.bloqueInformacion()
  m.bloqueOferente()
  m.bloqueFirmaYFecha()
  m.bloqueObjeto()
  m.detalleDeCompra()
  const conIntegridad = documento.tipo !== 'cotizacion' && (documento.extras || {}).integridad !== false
  m.presentacion()
  m.condiciones()
  m.listas()
  m.declaracion()
  if (conIntegridad) m.integridad()
  m.pies()

  return { blob: doc.output('blob'), cajas: m.cajas }
}
