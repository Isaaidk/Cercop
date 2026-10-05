<script setup>
/**
 * El trabajo de los workers: qué ha hecho la ingesta y el botón para pedir un ciclo ahora.
 *
 * Vive en la pantalla de plataforma, y no instrumenta nada nuevo: cada ciclo del worker deja su fila
 * en `sincronizacion` —cuándo empezó, cuándo terminó, cuántos registros escribió, cuántas peticiones
 * gastó y qué avisó—, así que la gráfica solo dibuja lo que ya está escrito. Si esto enseñara una
 * medida que el worker no registra, sería una medida inventada.
 *
 * La barra de cada ciclo es lo que **escribió** —nuevos más actualizados—, y el color dice de qué
 * fuente es. Las dos fuentes tienen cadencias distintas, y eso es justo lo que se ve: las barras
 * apretadas del listado y las separadas de las fichas. Un ciclo que falló se marca con el borde en
 * rojo en lugar de desaparecer, y uno que aún no ha terminado se pinta translúcido: si un ciclo se
 * cayera de la gráfica, parecería que no ha corrido.
 *
 * El botón **no ingesta nada**. Deja pedido un ciclo donde el worker lo mira y contesta en cuanto
 * está escrito, porque ninguna petición de usuario puede originar tráfico hacia el SERCOP (R-01): el
 * único proceso que habla con la fuente es el worker. Por eso la pantalla se queda mirando hasta que
 * la petición desaparece —el worker la consumió— y entonces dice que el ciclo está en marcha.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import { colorDeToken, opcionesBase, paletaSeries, useGrafica } from '@/composables/useGrafica'
import { abreviado, haceCuanto, horaCorta, numero } from '@/utils/formato'

/** Cada cuánto se refresca sola la tarjeta cuando no hay nada pedido. */
const REFRESCO_SEG = 20

const tablero = ref(null)
const cargando = ref(true)
const error = ref('')
const aviso = ref('')
const pidiendo = ref(false)
let temporizador = null

const fuentes = computed(() => tablero.value?.fuentes || [])
const solicitud = computed(() => tablero.value?.solicitud || null)
/** Lo que el worker tarda como mucho en ver la petición. Lo manda el servidor, no se adivina aquí. */
const cadenciaMs = computed(() => (tablero.value?.cadencia_seg || 5) * 1000)

/**
 * Los ciclos de las dos fuentes en una sola línea de tiempo, del más viejo al más nuevo.
 *
 * Se mezclan a propósito. Dos gráficas separadas dirían «cada fuente va por su lado», que ya se sabe,
 * y taparían lo que interesa: que las dos se solapen y que el sistema está vivo o lleva una hora
 * callado. El orden es cronológico porque así se lee un eje de tiempo.
 */
const ciclos = computed(() => {
  const filas = []
  for (const [codigo, lista] of Object.entries(tablero.value?.historial || {})) {
    for (const ciclo of lista) filas.push({ ...ciclo, fuente: codigo })
  }
  return filas.sort((uno, otro) => new Date(uno.iniciada_en) - new Date(otro.iniciada_en))
})

/** El color de cada fuente, por orden alfabético, para que no cambie entre refrescos. */
const orden = computed(() => [...new Set(ciclos.value.map((ciclo) => ciclo.fuente))].sort())

/** Escribe lo mismo en el lienzo (color resuelto) y en la lista (token de CSS). */
function tonoDe(codigo) {
  const indice = Math.max(0, orden.value.indexOf(codigo))
  return { token: `var(--serie-${(indice % 6) + 1})`, indice }
}

function enCurso(ciclo) {
  // `en_curso` es el estado con el que el ciclo nace —la fila se escribe al empezar y se completa al
  // terminar—, así que un ciclo está abierto si lo dice su estado o si todavía no tiene final.
  return ciclo.estado === 'en_curso' || !ciclo.terminada_en
}

/**
 * El borde dice cómo acabó el ciclo: rojo si falló, ámbar si quedó a medias, sin borde si terminó.
 *
 * Se marca en el borde y no quitando la barra porque una barra que desaparece se lee como «no ha
 * corrido», y lo que hay que ver es justo lo contrario: que corrió y no le fue bien.
 */
function colorBorde(ciclo) {
  if (ciclo.estado === 'error' || (ciclo.errores || 0) > 0) return colorDeToken('--error')
  if (ciclo.estado === 'parcial') return colorDeToken('--aviso')
  return 'transparent'
}

/** Cómo va un ciclo, en una palabra y con la etiqueta que le toca. */
function estadoDeCiclo(ciclo) {
  if (!ciclo) return { texto: 'sin datos', clase: 'etiqueta' }
  if (enCurso(ciclo)) return { texto: 'en marcha', clase: 'etiqueta--aviso' }
  if (ciclo.estado === 'error') return { texto: 'falló', clase: 'etiqueta--error' }
  if (ciclo.estado === 'parcial') return { texto: 'a medias', clase: 'etiqueta--aviso' }
  return { texto: 'terminado', clase: 'etiqueta--ok' }
}

/**
 * Los avisos de un ciclo, como lista de texto.
 *
 * Vienen del servidor como una lista —un `jsonb`— y una lista **vacía es verdadera** en JavaScript:
 * un `v-if="avisos"` a secas pintaba un renglón con «[]» en todos los ciclos que no avisaron de
 * nada, que son casi todos. Se mira la longitud, no la verdad del valor.
 */
function avisosDe(fila) {
  const avisos = fila?.avisos
  if (!avisos) return []
  return (Array.isArray(avisos) ? avisos : [avisos]).filter(Boolean).map(String)
}

/** «1 ciclo» y no «1 ciclos»: en una pantalla que se lee de un vistazo, el plural mal duele. */
function cuenta(total, singular, plural = `${singular}s`) {
  const valor = numero(total)
  return `${valor} ${Number(total) === 1 ? singular : plural}`
}

/** «4 min 20 s»: una duración se lee mal en segundos cuando pasa del minuto. */
function duracion(ciclo) {
  if (!ciclo.terminada_en) return '—'
  const segundos = Math.round((new Date(ciclo.terminada_en) - new Date(ciclo.iniciada_en)) / 1000)
  if (segundos < 60) return `${segundos} s`
  const minutos = Math.floor(segundos / 60)
  return `${minutos} min ${segundos % 60} s`
}

const { lienzo } = useGrafica(
  () => {
    const series = paletaSeries()

    return {
      type: 'bar',
      data: {
        labels: ciclos.value.map((ciclo) => [horaCorta(ciclo.iniciada_en), ciclo.fuente]),
        datasets: [
          {
            data: ciclos.value.map((ciclo) => (ciclo.nuevos || 0) + (ciclo.actualizados || 0)),
            // El color dice la fuente y la opacidad si el ciclo sigue abierto: dos lecturas en la
            // misma marca, sin añadir una leyenda ni un eje.
            backgroundColor: ciclos.value.map((ciclo) => {
              const color = series[tonoDe(ciclo.fuente).indice % series.length]
              return enCurso(ciclo) ? `${color}59` : color
            }),
            borderColor: ciclos.value.map((ciclo) => colorBorde(ciclo)),
            borderWidth: ciclos.value.map((ciclo) => (colorBorde(ciclo) === 'transparent' ? 0 : 2)),
            borderRadius: 5,
            maxBarThickness: 26,
            // Un ciclo que no escribió nada —o que aún está corriendo— tiene altura cero. Sin este
            // mínimo desaparecería de la gráfica, y «no escribió nada» se leería como «no corrió».
            minBarLength: 3,
          },
        ],
      },
      options: {
        ...opcionesBase(),
        plugins: {
          ...opcionesBase().plugins,
          legend: { display: false },
          tooltip: {
            ...opcionesBase().plugins.tooltip,
            callbacks: {
              title: (elementos) => {
                const ciclo = ciclos.value[elementos[0]?.dataIndex]
                return ciclo ? `${ciclo.fuente} · ${horaCorta(ciclo.iniciada_en)}` : ''
              },
              label: (contexto) => {
                const ciclo = ciclos.value[contexto.dataIndex]
                if (!ciclo) return ''
                const lineas = [
                  `${cuenta(ciclo.nuevos, 'nuevo')} · ${cuenta(ciclo.actualizados, 'actualizado')}`,
                  `${estadoDeCiclo(ciclo).texto} en ${duracion(ciclo)} · ${cuenta(ciclo.peticiones, 'petición', 'peticiones')}`,
                ]
                const avisos = avisosDe(ciclo)
                if (avisos.length) lineas.push(avisos.join(' · '))
                return lineas
              },
            },
          },
        },
        scales: {
          ...opcionesBase().scales,
          // La escala se abrevia: «12.480» cinco veces en el eje ocupa más que la gráfica entera en
          // una pantalla estrecha. La cifra exacta está en el globo y en la lista de abajo.
          y: {
            ...opcionesBase().scales.y,
            ticks: { ...opcionesBase().scales.y.ticks, callback: (valor) => abreviado(valor) },
          },
        },
      },
    }
  },
  () => ciclos.value,
)

async function cargar({ silencioso = false } = {}) {
  if (!silencioso) cargando.value = true
  const habiaPeticion = Boolean(solicitud.value)
  try {
    tablero.value = await api.trabajoDeIngesta()
    error.value = ''
    // La petición desaparece cuando el worker la toma. Es la señal de que el ciclo arrancó, y sin
    // decirlo la pantalla parecería no haberse enterado.
    if (habiaPeticion && !solicitud.value) {
      aviso.value = 'El worker ya tomó el ciclo: está en marcha.'
    }
  } catch (fallo) {
    if (!silencioso) error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

/**
 * Una sola cadena de esperas, no un `setInterval`.
 *
 * Con un intervalo fijo, una respuesta que tarde más que el propio intervalo acumula peticiones
 * encima de peticiones, y con el navegador en segundo plano se sigue preguntando para nadie. Así cada
 * vuelta se programa cuando la anterior terminó, y si la pestaña no está a la vista se espera al
 * ciclo largo sin gastar nada.
 */
function programar(espera) {
  clearTimeout(temporizador)
  temporizador = setTimeout(async () => {
    if (document.visibilityState !== 'visible') {
      programar(REFRESCO_SEG * 1000)
      return
    }
    await cargar({ silencioso: true })
    programar(solicitud.value ? cadenciaMs.value : REFRESCO_SEG * 1000)
  }, espera)
}

async function pedirCiclo() {
  pidiendo.value = true
  error.value = ''
  aviso.value = ''
  try {
    const respuesta = await api.pedirCiclo()
    aviso.value = `Ciclo pedido a las ${horaCorta(respuesta.solicitud?.solicitado_en)}. El worker lo toma en cuanto acabe lo que tenga entre manos.`
    await cargar({ silencioso: true })
    // Con la petición pendiente se mira a la cadencia del worker: es lo que tarda como mucho en
    // tomarla, y lo que permite decir en pantalla si ya arrancó.
    programar(cadenciaMs.value)
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    pidiendo.value = false
  }
}

onMounted(async () => {
  await cargar()
  programar(solicitud.value ? cadenciaMs.value : REFRESCO_SEG * 1000)
})

onBeforeUnmount(() => clearTimeout(temporizador))
</script>

<template>
  <section class="trabajo aparece">
    <header class="trabajo__cabecera">
      <div>
        <p class="trabajo__titulo">Trabajo de la ingesta</p>
        <p class="trabajo__pista">
          Cada barra es una sincronización registrada —nuevos más actualizados—, y el color dice de
          qué fuente. Pasa el cursor por encima para ver el detalle. Pide una cuando quieras que
          revise las fuentes ya mismo, sin esperar a su turno.
        </p>
      </div>

      <button
        type="button"
        class="boton boton--principal"
        :disabled="pidiendo || Boolean(solicitud)"
        @click="pedirCiclo"
      >
        <span aria-hidden="true">{{ solicitud ? '◷' : '▶' }}</span>
        {{ solicitud ? 'Ciclo en cola' : 'Ejecutar ahora' }}
      </button>
    </header>

    <p v-if="error" class="trabajo__error" role="alert">{{ error }}</p>
    <p v-if="aviso" class="trabajo__aviso" role="status">{{ aviso }}</p>

    <p v-if="solicitud" class="trabajo__cola" role="status">
      Pedido {{ haceCuanto(solicitud.solicitado_en) }}. El worker mira cada
      {{ Math.round(cadenciaMs / 1000) }} s entre ciclos; en cuanto lo tome, el ciclo aparecerá aquí.
    </p>

    <div v-if="cargando" class="esqueleto trabajo__esqueleto" />

    <template v-else>
      <p v-if="!ciclos.length" class="trabajo__vacio">
        Todavía no hay ningún ciclo registrado. Pulsa «Ejecutar ahora» para lanzar el primero.
      </p>

      <div v-else class="trabajo__lienzo">
        <canvas
          ref="lienzo"
          role="img"
          aria-label="Gráfica de barras con los registros escritos por cada ciclo de ingesta"
        />
      </div>

      <ul class="trabajo__fuentes">
        <li v-for="fuente in fuentes" :key="fuente.codigo" class="trabajo__fuente">
          <span
            class="trabajo__punto"
            :style="{ background: tonoDe(fuente.codigo).token }"
            aria-hidden="true"
          />
          <div class="trabajo__fuente-cuerpo">
            <p class="trabajo__fuente-nombre">
              {{ fuente.codigo }}
              <span class="trabajo__fuente-cadencia">cada {{ fuente.intervalo_min }} min</span>
            </p>
            <p class="trabajo__fuente-detalle">
              <template v-if="fuente.iniciada_en">
                Último ciclo {{ haceCuanto(fuente.iniciada_en) }} ·
                {{ cuenta(fuente.nuevos, 'nuevo') }} ·
                {{ cuenta(fuente.actualizados, 'actualizado') }} ·
                {{ cuenta(fuente.peticiones, 'petición', 'peticiones') }}
              </template>
              <template v-else>Sin ningún ciclo todavía.</template>
            </p>
            <p v-if="avisosDe(fuente).length" class="trabajo__fuente-aviso">
              {{ avisosDe(fuente).join(' · ') }}
            </p>
          </div>
          <span
            class="etiqueta"
            :class="fuente.iniciada_en ? estadoDeCiclo(fuente).clase : 'etiqueta'"
          >
            {{ fuente.iniciada_en ? estadoDeCiclo(fuente).texto : 'sin datos' }}
          </span>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.trabajo {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  box-shadow: var(--sombra-1);
}

.trabajo__cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  align-items: flex-start;
  justify-content: space-between;
}

.trabajo__titulo {
  font-size: var(--t-lg);
  font-weight: 700;
}

.trabajo__pista,
.trabajo__fuente-detalle {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  line-height: 1.55;
}

.trabajo__error,
.trabajo__aviso,
.trabajo__cola {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.trabajo__aviso {
  border-left-color: var(--ok);
  background: var(--ok-suave);
  color: var(--ok);
}

.trabajo__cola {
  border-left-color: var(--aviso);
  background: var(--aviso-suave);
  color: var(--aviso);
}

.trabajo__esqueleto {
  height: 240px;
  border-radius: var(--r-2);
}

.trabajo__vacio {
  padding: var(--e-5) 0;
  text-align: center;
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

.trabajo__lienzo {
  position: relative;
  height: 240px;
}

.trabajo__fuentes {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.trabajo__fuente {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: var(--e-3);
  align-items: center;
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  background: var(--superficie-2);
}

.trabajo__punto {
  width: 10px;
  height: 10px;
  border-radius: var(--r-redondo);
}

.trabajo__fuente-nombre {
  font-size: var(--t-sm);
  font-weight: 700;
}

.trabajo__fuente-cadencia,
.trabajo__fuente-aviso {
  font-size: var(--t-xs);
  font-weight: 500;
  color: var(--texto-tenue);
}

.trabajo__fuente-aviso {
  color: var(--aviso);
}
</style>
