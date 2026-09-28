/**
 * Conjunto de datos de ejemplo para poder revisar el diseño con el histórico vacío.
 *
 * Es determinista: la misma lista de palabras clave produce siempre los mismos números. Con valores
 * al azar, las gráficas cambiarían en cada repintado y sería imposible comprobar si una animación o
 * un color funcionan, además de que el usuario vería moverse cifras que nadie ha tocado.
 *
 * Se genera a partir de una semilla derivada de las palabras clave seleccionadas, así que al
 * cambiar el filtro los datos cambian de forma coherente y se puede comprobar que el filtrado tiene
 * efecto —que es justo lo que se quiere revisar—.
 *
 * Las cifras están elegidas para que las gráficas se vean, no para parecerse a la realidad: no hay
 * que sacar ninguna conclusión de ellas, y por eso el panel las anuncia como ejemplo mientras se
 * muestren.
 */

import { PROVINCIAS, agruparPorProvincia } from '@/utils/provincias'

/** Generador congruente lineal: predecible, sin dependencias y suficiente para esto. */
function crearAzar(semilla) {
  let estado = semilla >>> 0 || 1
  return () => {
    estado = (estado * 1664525 + 1013904223) >>> 0
    return estado / 4294967296
  }
}

function semillaDe(texto) {
  let valor = 2166136261
  for (let i = 0; i < texto.length; i += 1) {
    valor ^= texto.charCodeAt(i)
    valor = Math.imul(valor, 16777619)
  }
  return valor >>> 0
}

/**
 * Peso relativo de cada provincia.
 *
 * No es una estimación real de la contratación pública: es una distribución desigual a propósito,
 * porque con todas las provincias iguales las gráficas de barras y el sombreado del mapa se ven
 * planos y no se distingue si el color está funcionando.
 */
const PESOS = {
  Pichincha: 1.0,
  Guayas: 0.95,
  Azuay: 0.62,
  Manabi: 0.55,
  Tungurahua: 0.44,
  Loja: 0.4,
  'El Oro': 0.38,
  'Los Rios': 0.34,
  Chimborazo: 0.32,
  Cotopaxi: 0.28,
  Imbabura: 0.26,
  Esmeraldas: 0.22,
  'Santa Elena': 0.2,
  Carchi: 0.18,
  Canar: 0.16,
  Bolivar: 0.15,
  Sucumbios: 0.14,
  Orellana: 0.13,
  Napo: 0.12,
  Pastaza: 0.11,
  'Morona Santiago': 0.1,
  'Zamora Chinchipe': 0.09,
  'Santo Domingo de los Tsachilas': 0.17,
  Galapagos: 0.05,
}

const CANTONES_POR_PROVINCIA = {
  Pichincha: ['Quito', 'Rumiñahui', 'Mejía', 'Cayambe'],
  Guayas: ['Guayaquil', 'Durán', 'Samborondón', 'Milagro'],
  Azuay: ['Cuenca', 'Gualaceo', 'Paute'],
  Manabi: ['Portoviejo', 'Manta', 'Chone'],
  Tungurahua: ['Ambato', 'Baños', 'Pelileo'],
  Loja: ['Loja', 'Catamayo', 'Saraguro'],
  'El Oro': ['Machala', 'Pasaje', 'Santa Rosa'],
  'Los Rios': ['Babahoyo', 'Quevedo', 'Ventanas'],
  Chimborazo: ['Riobamba', 'Alausí'],
  Cotopaxi: ['Latacunga', 'Saquisilí'],
  Imbabura: ['Ibarra', 'Otavalo', 'Antonio Ante'],
  Esmeraldas: ['Esmeraldas', 'Atacames'],
  'Santa Elena': ['Santa Elena', 'Salinas', 'La Libertad'],
  Carchi: ['Tulcán', 'Montúfar'],
  Canar: ['Azogues', 'Cañar'],
  Bolivar: ['Guaranda', 'Chillanes'],
  Sucumbios: ['Nueva Loja', 'Putumayo'],
  Orellana: ['Francisco de Orellana', 'Aguarico'],
  Napo: ['Tena', 'Archidona'],
  Pastaza: ['Pastaza', 'Mera'],
  'Morona Santiago': ['Morona', 'Gualaquiza'],
  'Zamora Chinchipe': ['Zamora', 'Yantzaza'],
  'Santo Domingo de los Tsachilas': ['Santo Domingo', 'La Concordia'],
  Galapagos: ['Santa Cruz', 'San Cristóbal'],
}

const MESES = 12
const FUENTES = [
  { fuente: 'NCO', peso: 0.62 },
  { fuente: 'OCDS', peso: 0.38 },
]

export function datosDeEjemplo(palabrasClave = []) {
  const clave = [...palabrasClave].sort().join('|') || 'sin-filtro'
  const azar = crearAzar(semillaDe(clave))

  // Con más palabras clave se exige más, así que hay menos coincidencias. Es la misma relación que
  // tendría una búsqueda real en modo «todas», y hace que agregar un filtro se note en las gráficas.
  const factor = palabrasClave.length ? 1 / (1 + 0.45 * (palabrasClave.length - 1)) : 1
  const base = 2400 * factor

  const filasProvincia = []
  const porProvincia = []

  for (const { codigo, nombre } of PROVINCIAS) {
    const peso = PESOS[codigo] || 0.1
    const total = Math.max(0, Math.round(base * peso * (0.75 + azar() * 0.5)))
    if (!total) continue

    const cantones = CANTONES_POR_PROVINCIA[codigo] || [nombre]
    // Se reparte el total entre los cantones con pesos decrecientes: los dos primeros concentran la
    // mayor parte, como ocurre de verdad en casi todas las provincias.
    const cortes = [0.45, 0.3, 0.15, 0.1]
    let restante = total

    for (let i = 0; i < cantones.length; i += 1) {
      const cuantos = i === cantones.length - 1 ? restante : Math.round(total * (cortes[i] || 0.1))
      restante -= cuantos
      if (cuantos <= 0) continue

      const valor = `${nombre.toUpperCase()} - ${cantones[i].toUpperCase()}`
      filasProvincia.push({ provincia: valor, total: cuantos })
      porProvincia.push({ provincia: valor, total: cuantos })
    }
  }

  // Serie mensual: doce meses con una tendencia suave y un pico a mitad de año, que es cuando más
  // se publica. Se genera hacia atrás desde el mes actual para que las fechas tengan sentido.
  const serie = []
  const hoy = new Date()
  for (let i = MESES - 1; i >= 0; i -= 1) {
    const fecha = new Date(hoy.getFullYear(), hoy.getMonth() - i, 1)
    const estacional = 0.8 + 0.45 * Math.sin(((MESES - i) / MESES) * Math.PI * 2)
    serie.push({
      mes: fecha.toISOString(),
      total: Math.round(base * 0.42 * estacional * (0.85 + azar() * 0.3)),
    })
  }

  const totalSerie = serie.reduce((suma, mes) => suma + mes.total, 0)
  const porFuente = FUENTES.map(({ fuente, peso }) => ({
    fuente,
    total: Math.round(totalSerie * peso),
    ultima_publicacion: new Date().toISOString(),
  }))

  return {
    estadisticas: {
      fuente: null,
      por_fuente: porFuente,
      serie_mensual: serie,
      por_provincia: filasProvincia,
    },
    resumenProvincias: agruparPorProvincia(porProvincia),
  }
}
