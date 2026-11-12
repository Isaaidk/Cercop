/**
 * Consultas a servicios públicos que se hacen **desde el navegador** de quien las pide.
 *
 * El SRI (consulta de RUC) y los datos abiertos del SERCOP (contratos por proveedor) permiten
 * consultas directas desde cualquier página (CORS abierto). Hacerlas aquí tiene tres ventajas: el
 * servidor no gasta CPU, memoria ni conexiones en ellas; las peticiones salen de la red de la
 * persona, no de una sola IP compartida que un servicio ajeno acabaría limitando; y una consulta
 * lenta no ocupa un proceso de la API.
 *
 * El portal de compras (TDR e ítems) **no** permite consultas desde el navegador, y esas siguen en
 * el worker. Todo lo de aquí repite, en JavaScript, las reglas de `dominio/consulta_ruc.py` y
 * `dominio/historial.py`; si una cambia, la otra también. El servidor conserva esas rutas como
 * respaldo para cuando el navegador no pueda llegar al servicio.
 */

const SRI = 'https://srienlinea.sri.gob.ec/sri-catastro-sujeto-servicio-internet/rest'
const OCDS = 'https://datosabiertos.compraspublicas.gob.ec/PLATAFORMA/api'

const PROVINCIAS = [
  'Azuay', 'Bolívar', 'Cañar', 'Carchi', 'Chimborazo', 'Cotopaxi', 'El Oro', 'Esmeraldas',
  'Galápagos', 'Guayas', 'Imbabura', 'Loja', 'Los Ríos', 'Manabí', 'Morona Santiago', 'Napo',
  'Orellana', 'Pastaza', 'Pichincha', 'Santa Elena', 'Santo Domingo de los Tsáchilas',
  'Sucumbíos', 'Tungurahua', 'Zamora Chinchipe',
]
const MINUSCULAS = new Set(['de', 'del', 'la', 'las', 'los', 'y', 'e', 'el'])
const FORMAS = new Set(['sa', 's', 'a', 'cia', 'ltda', 'limitada', 'compania', 'sas', 'ca', 'cl', 'eirl'])

const plano = (texto) =>
  String(texto || '').normalize('NFD').replace(/[̀-ͯ]/g, '').trim().toLowerCase()
const OFICIAL = new Map(PROVINCIAS.map((nombre) => [plano(nombre), nombre]))

function titulo(texto) {
  return String(texto || '')
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((palabra, i) =>
      i && MINUSCULAS.has(palabra) ? palabra : palabra.charAt(0).toUpperCase() + palabra.slice(1),
    )
    .join(' ')
}

const provincia = (texto) => OFICIAL.get(plano(texto)) || titulo(texto)

async function pedirJson(url, params = {}) {
  const consulta = new URLSearchParams(params).toString()
  const respuesta = await fetch(consulta ? `${url}?${consulta}` : url, {
    headers: { Accept: 'application/json' },
  })
  if (!respuesta.ok) throw new Error(`HTTP ${respuesta.status}`)
  return respuesta.json()
}

/** Corre las tareas con a lo más `limite` a la vez: no se martilla un servicio ajeno. */
async function conLimite(tareas, limite) {
  const resultados = new Array(tareas.length)
  let siguiente = 0
  async function trabajador() {
    while (siguiente < tareas.length) {
      const i = siguiente
      siguiente += 1
      resultados[i] = await tareas[i]()
    }
  }
  await Promise.all(Array.from({ length: Math.min(limite, tareas.length) }, trabajador))
  return resultados
}

// ------------------------------------------------------------------------------------- SRI

function partesDireccion(completa) {
  const partes = String(completa || '').split('/').map((p) => p.trim())
  while (partes.length < 4) partes.push('')
  return { provincia: partes[0], canton: partes[1], calle: partes.slice(3).filter(Boolean).join(' / ') }
}

function tipoPersona(contribuyente) {
  const tipo = String(contribuyente.tipoContribuyente || '').toUpperCase()
  if (tipo.includes('SOCIEDAD') || tipo.includes('JURID')) return 'juridica'
  if (tipo.includes('NATURAL')) return 'natural'
  const tercero = String(contribuyente.numeroRuc || '')[2]
  return tercero && /\d/.test(tercero) ? (Number(tercero) < 6 ? 'natural' : 'juridica') : null
}

function regimen(contribuyente) {
  let nombre = titulo(contribuyente.regimen)
  const categoria = titulo(contribuyente.categoria)
  if (nombre.toLowerCase() === 'rimpe') nombre = 'RIMPE'
  return nombre && categoria ? `${nombre} · ${categoria}` : nombre
}

export function propuestaDesdeSri(contribuyente, establecimientos) {
  const abiertos = establecimientos.filter((e) => String(e.estado || '').toUpperCase() === 'ABIERTO')
  const matriz =
    abiertos.find((e) => String(e.matriz || '').toUpperCase() === 'SI') ||
    abiertos[0] ||
    establecimientos[0] ||
    {}
  const { canton, calle } = partesDireccion(matriz.direccionCompleta)
  const fantasia = [matriz, ...abiertos]
    .map((e) => String(e.nombreFantasiaComercial || '').trim())
    .find(Boolean)
  const fechas = contribuyente.informacionFechasContribuyente || {}
  const inicio = String(fechas.fechaInicioActividades || '').match(/^\d{4}-\d{2}-\d{2}/)

  const identidad = {
    razon_social: String(contribuyente.razonSocial || '').trim(),
    nombre_comercial: fantasia ? titulo(fantasia) : '',
    tipo_persona: tipoPersona(contribuyente),
    regimen_tributario: regimen(contribuyente),
    obligado_contabilidad: String(contribuyente.obligadoLlevarContabilidad || '').toUpperCase() === 'SI',
    fecha_inicio_actividades: inicio ? inicio[0] : null,
    direccion: calle ? titulo(calle) : '',
    ciudad: titulo(canton),
  }
  for (const clave of Object.keys(identidad)) {
    if (identidad[clave] === '' || identidad[clave] === null) delete identidad[clave]
  }

  const legal = (contribuyente.representantesLegales || []).find((r) => r && String(r.nombre || '').trim())
  const representante = legal
    ? {
        tipo: 'representante_legal',
        nombre: titulo(legal.nombre),
        cedula: String(legal.identificacion || '').trim(),
        cargo: 'Representante legal',
        principal: true,
      }
    : null

  const vistas = new Set()
  const cobertura = []
  for (const e of abiertos) {
    const p = partesDireccion(e.direccionCompleta)
    const clave = [provincia(p.provincia), titulo(p.canton)]
    if (clave[0] && !vistas.has(clave.join('|'))) {
      vistas.add(clave.join('|'))
      cobertura.push({ provincia: clave[0], canton: clave[1] })
    }
  }

  const estado = String(contribuyente.estadoContribuyenteRuc || '').trim().toUpperCase()
  const avisos = []
  if (estado && estado !== 'ACTIVO') avisos.push(`El SRI registra este RUC como ${estado.toLowerCase()}.`)
  if (String(contribuyente.contribuyenteFantasma || '').toUpperCase() === 'SI') avisos.push('El SRI lo marca como contribuyente fantasma.')
  if (String(contribuyente.transaccionesInexistente || '').toUpperCase() === 'SI') avisos.push('El SRI lo marca con transacciones inexistentes.')

  return {
    ruc: String(contribuyente.numeroRuc || '').trim(),
    estado_sri: estado,
    identidad,
    representante,
    cobertura: cobertura.slice(0, 24),
    actividad: String(contribuyente.actividadEconomicaPrincipal || '').trim(),
    avisos,
    no_publica: ['Correo', 'Teléfono', 'Código CIIU', 'Estado en el RUP'],
  }
}

/**
 * Forma del RUC ecuatoriano, igual que `ruc_valido` en `dominio/verificacion.py`: 13 dígitos,
 * provincia 01-24 o 30, tercer dígito distinto de 7 y 8, y establecimiento distinto de 000.
 */
export function rucConForma(ruc) {
  const limpio = String(ruc || '')
  if (!/^\d{13}$/.test(limpio)) return false
  const provincia = Number(limpio.slice(0, 2))
  if (!((provincia >= 1 && provincia <= 24) || provincia === 30)) return false
  if (limpio[2] === '7' || limpio[2] === '8') return false
  return limpio.slice(10) !== '000'
}

/** La propuesta de perfil para un RUC, consultando al SRI desde el navegador. */
export async function consultarRucEnNavegador(ruc) {
  const [contribuyentes, establecimientos] = await Promise.all([
    pedirJson(`${SRI}/ConsolidadoContribuyente/obtenerPorNumerosRuc`, { ruc }),
    pedirJson(`${SRI}/Establecimiento/consultarPorNumeroRuc`, { numeroRuc: ruc }),
  ])
  if (!Array.isArray(contribuyentes) || !contribuyentes.length) {
    const error = new Error('El SRI no tiene un contribuyente con ese RUC.')
    error.definitivo = true
    throw error
  }
  return propuestaDesdeSri(contribuyentes[0], Array.isArray(establecimientos) ? establecimientos : [])
}

// ----------------------------------------------------------------------------- contratos (OCDS)

export function terminoDeBusqueda(razonSocial) {
  const cabeza = String(razonSocial || '').toUpperCase().split(/["“”(,]/)[0]
  const palabras = cabeza.split(/\s+/).filter(Boolean)
  while (palabras.length && FORMAS.has(palabras[palabras.length - 1].replace(/\W/g, '').toLowerCase())) {
    palabras.pop()
  }
  return palabras.join(' ').slice(0, 80).replace(/^[\s.]+|[\s.]+$/g, '')
}

const CATEGORIAS = { goods: 'bienes', services: 'servicios', works: 'obras' }

export function contratoDe(carga, ruc) {
  const releases = [
    ...(carga?.releases || []),
    ...(carga?.records || []).flatMap((registro) => registro?.releases || []),
  ].filter((r) => r && typeof r === 'object')
  for (const release of releases) {
    const propios = (release.parties || []).some(
      (parte) =>
        (parte.roles || []).includes('supplier') &&
        String(parte.id || parte.identifier?.id || '').includes(ruc),
    )
    const adjudicados = (release.awards || []).filter((a) =>
      (a.suppliers || []).some((s) => String(s.id || '').includes(ruc)),
    )
    if (!propios && !adjudicados.length) continue
    const cpc = {}
    const productos = []
    let monto = 0
    for (const adjudicacion of adjudicados.length ? adjudicados : release.awards || []) {
      const valor = adjudicacion.value?.amount
      if (typeof valor === 'number') monto += valor
      for (const item of adjudicacion.items || []) {
        const nombre = String(item.description || '').replace(/\s+/g, ' ').trim()
        if (nombre && !productos.includes(nombre)) productos.push(nombre)
        const clasificacion = item.classification || {}
        if (String(clasificacion.scheme || '').toUpperCase() === 'CPC' && clasificacion.id) {
          cpc[String(clasificacion.id)] = String(clasificacion.description || '')
        }
      }
    }
    const tender = release.tender || {}
    return {
      ocid: release.ocid,
      entidad: String(release.buyer?.name || '').trim(),
      titulo: String(tender.title || '').trim(),
      descripcion: String(tender.description || '').replace(/\s+/g, ' ').trim(),
      fecha: String(release.date || '').slice(0, 10),
      monto: monto || tender.value?.amount || 0,
      cpc,
      productos,
      categoria: String(tender.mainProcurementCategory || ''),
    }
  }
  return null
}

export function resumirHistorial(ruc, contratos, { total, revisados, termino }) {
  const veces = new Map()
  const nombres = new Map()
  for (const contrato of contratos) {
    for (const [codigo, descripcion] of Object.entries(contrato.cpc)) {
      veces.set(codigo, (veces.get(codigo) || 0) + 1)
      if (!nombres.has(codigo)) nombres.set(codigo, descripcion)
    }
  }
  const experiencia = [...contratos]
    .sort((a, b) => b.fecha.localeCompare(a.fecha))
    .slice(0, 8)
    .map((contrato) => {
      const generico = /^(orden de compra|compra de)/i.test(contrato.descripcion)
      const objeto =
        contrato.productos.length && (generico || !contrato.descripcion)
          ? contrato.productos.slice(0, 3).join('; ')
          : contrato.descripcion || contrato.titulo
      const codigos = Object.keys(contrato.cpc)
      return {
        entidad: contrato.entidad,
        objeto: objeto.slice(0, 240),
        monto: contrato.monto,
        anio: /^\d{4}/.test(contrato.fecha) ? Number(contrato.fecha.slice(0, 4)) : null,
        cpc: codigos[0] || '',
        tipo_contratacion: CATEGORIAS[contrato.categoria] || null,
      }
    })
  return {
    ruc,
    termino,
    contratos_total: total,
    revisados,
    verificados: contratos.length,
    monto_revisado: Math.round(contratos.reduce((suma, c) => suma + Number(c.monto || 0), 0) * 100) / 100,
    cpc: [...veces.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
      .map(([codigo, cantidad]) => ({ codigo, descripcion: nombres.get(codigo), veces: cantidad })),
    experiencia,
    aviso:
      'Es lo que figura como adjudicado a tu RUC en los datos abiertos de los últimos años. ' +
      'No es tu habilitación en el RUP: ese registro no tiene consulta pública.',
  }
}

const ANIOS = 3
const MAX_PROCESOS = 12
const recordados = new Map()

/** CPC y contratos que los datos abiertos atribuyen a ese RUC, consultados desde el navegador. */
export async function consultarContratosEnNavegador(ruc, razonSocial) {
  const termino = terminoDeBusqueda(razonSocial)
  if (termino.length < 3) throw new Error('La razón social es muy corta para buscar contratos.')
  const guardado = recordados.get(ruc)
  if (guardado && Date.now() - guardado.cuando < 30 * 60 * 1000) return guardado.datos

  const anioActual = new Date().getFullYear()
  const listados = await Promise.all(
    Array.from({ length: ANIOS }, (_, n) =>
      pedirJson(`${OCDS}/search_ocds`, {
        year: String(anioActual - n),
        search: '',
        supplier: termino,
        page: '1',
      }),
    ),
  )
  const total = listados.reduce((suma, l) => suma + Number(l.total || 0), 0)
  const filas = listados
    .flatMap((l) => l.data || [])
    .filter((fila) => fila && fila.ocid)
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
    .slice(0, MAX_PROCESOS)
  const procesos = await conLimite(
    filas.map((fila) => async () => {
      try {
        return contratoDe(await pedirJson(`${OCDS}/record`, { ocid: fila.ocid }), ruc)
      } catch {
        return null // un proceso que no responde no tumba el resto
      }
    }),
    4,
  )
  const datos = resumirHistorial(ruc, procesos.filter(Boolean), {
    total,
    revisados: filas.length,
    termino,
  })
  recordados.set(ruc, { cuando: Date.now(), datos })
  return datos
}
