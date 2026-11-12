<script setup>
/**
 * Inicio del panel: el acceso a «Propuestas para ti», el resumen del día en cuatro tarjetas y tres
 * accesos directos.
 *
 * Responde a «¿qué tengo hoy?» sin obligar a recorrer cinco pantallas. Todo lo que muestra ya existe
 * en otras partes —el total de ínfimas, las ofertas del CRM, los avisos de las alertas—; aquí solo
 * se junta y se enlaza a la pantalla donde se trabaja cada cosa.
 *
 * Cada tarjeta se defiende sola: si una llamada falla, esa tarjeta enseña un vacío amable y las
 * demás siguen. Un inicio que se queda en blanco porque el CRM no respondió sería peor que no tener
 * inicio. Por eso las peticiones van con `allSettled` y no con `all`.
 *
 * No pide nada al montarse el panel: solo cuando alguien abre esta pantalla (el montaje es perezoso,
 * como el del resto de pestañas) y otra vez cada vez que se vuelve a ella, para que los cierres y los
 * avisos no se queden de la mañana.
 */
import { computed, onMounted, reactive, watch } from 'vue'

import IconoPanel from '@/components/IconoPanel.vue'
import { api } from '@/api/endpoints'
import { datos } from '@/stores/datos'
import { sesion } from '@/stores/sesion'
import { numero } from '@/utils/formato'
import { diasParaProforma, insigniaDePlazo } from '@/utils/plazo'

const props = defineProps({
  /** Si la pantalla está a la vista: al volver a ella se refrescan los datos. */
  activa: { type: Boolean, default: false },
})

const emit = defineEmits(['ir'])

const ofertas = reactive({ cargando: true, fallo: false, lista: [], resumen: null })
const avisos = reactive({ cargando: true, fallo: false, sinLeer: 0 })
// Solo el total: la lista completa se pide al abrir «Propuestas para ti». `oculta` cuando la cuenta
// no puede ver ínfimas (el servidor responde 403) o falla: el acceso se quita en lugar de enseñar un
// cero que no es verdad.
const propuestas = reactive({ cargando: true, oculta: false, total: 0, sinPerfil: false })

async function cargar() {
  const [resultadoOfertas, resultadoAvisos, resultadoPropuestas] = await Promise.allSettled([
    api.misOfertas(),
    api.listarAvisos(),
    api.verPropuestas({ tamano: 1 }),
  ])

  if (resultadoPropuestas.status === 'fulfilled') {
    const respuesta = resultadoPropuestas.value || {}
    propuestas.total = Number(respuesta.total || 0)
    propuestas.sinPerfil = Boolean(respuesta.motivo) && !respuesta.criterios?.total_cpc && !respuesta.criterios?.total_palabras
    propuestas.oculta = false
  } else {
    propuestas.oculta = true
  }
  propuestas.cargando = false

  if (resultadoOfertas.status === 'fulfilled') {
    ofertas.lista = resultadoOfertas.value?.ofertas || []
    ofertas.resumen = resultadoOfertas.value?.resumen || null
    ofertas.fallo = false
  } else {
    ofertas.fallo = true
  }
  ofertas.cargando = false

  if (resultadoAvisos.status === 'fulfilled') {
    const lista = resultadoAvisos.value?.avisos || []
    avisos.sinLeer = lista.filter((item) => !item.leido_en).length
    avisos.fallo = false
  } else {
    avisos.fallo = true
  }
  avisos.cargando = false
}

onMounted(cargar)
watch(
  () => props.activa,
  (ahora, antes) => {
    if (ahora && antes === false) cargar()
  },
)

/** Saludo según la hora de quien mira, no la del servidor. */
const saludo = computed(() => {
  const hora = new Date().getHours()
  const base = hora < 12 ? 'Buenos días' : hora < 19 ? 'Buenas tardes' : 'Buenas noches'
  const nombre = String(sesion.estado.nombre || '').trim().split(/\s+/)[0]
  return nombre ? `${base}, ${nombre}` : base
})

/** Las mismas reglas que el CRM: borradores y enviadas que cierran en los próximos siete días. */
const cierres = computed(() =>
  ofertas.lista
    .map((oferta) => ({ oferta, dias: diasParaProforma(oferta.plazo) }))
    .filter(({ oferta, dias }) => ['borrador', 'enviada'].includes(oferta.etapa) && dias !== null && dias >= 0 && dias <= 7)
    .sort((a, b) => a.dias - b.dias),
)

const totalInfimas = computed(() => datos.estado.totalesPorCategoria?.infimas ?? null)

const tasa = computed(() => ofertas.resumen?.tasa_exito ?? null)
</script>

<template>
  <section class="inicio">
    <header class="inicio__saludo">
      <h2>{{ saludo }}</h2>
      <p>Esto es lo que tienes hoy. Elige por dónde empezar.</p>
    </header>

    <!-- El asistente: preguntar en palabras propias, sin buscar la pantalla. -->
    <button type="button" class="inicio__asistente" @click="emit('ir', 'asistente')">
      <span class="inicio__asistente-icono" aria-hidden="true"><IconoPanel nombre="asistente" :tamano="26" /></span>
      <span class="inicio__asistente-texto">
        <strong>Pregúntale al asistente</strong>
        <span>Escribe o dicta lo que necesitas: ínfimas para ti, un proceso, una alerta o tu proforma.</span>
      </span>
      <IconoPanel nombre="flecha" :tamano="20" />
    </button>

    <!-- Lo primero que se ve: a qué puede aplicar la empresa hoy. Una sola acción, abrir la lista. -->
    <section v-if="!propuestas.oculta" class="tarjeta inicio__propuestas" aria-label="Propuestas para ti">
      <div class="inicio__propuestas-texto">
        <p class="inicio__etiqueta"><IconoPanel nombre="propuestas" :tamano="16" /> Propuestas para ti</p>
        <p v-if="propuestas.cargando" class="esqueleto inicio__cifra-esqueleto" />
        <p v-else-if="propuestas.sinPerfil" class="inicio__propuestas-frase">
          Sube tu RUP o agrega tus CPC y te mostramos las ínfimas que puedes ofertar.
        </p>
        <p v-else-if="propuestas.total" class="inicio__propuestas-frase">
          <strong class="numeros">{{ numero(propuestas.total) }}</strong>
          {{ propuestas.total === 1 ? 'ínfima abierta que puedes ofertar' : 'ínfimas abiertas que puedes ofertar' }}
        </p>
        <p v-else class="inicio__propuestas-frase">Hoy no hay ínfimas abiertas para tu perfil. Revisa mañana.</p>
      </div>
      <button type="button" class="boton boton--principal" @click="emit('ir', 'propuestas')">
        Ver mis propuestas <IconoPanel nombre="flecha" :tamano="14" />
      </button>
    </section>

    <div class="inicio__tarjetas">
      <!-- Ínfimas -->
      <article class="tarjeta tarjeta--interactiva inicio__tarjeta">
        <p class="inicio__etiqueta"><IconoPanel nombre="infimas" :tamano="16" /> Ínfimas cuantías</p>
        <p v-if="datos.estado.cargando && totalInfimas === null" class="esqueleto inicio__cifra-esqueleto" />
        <template v-else-if="totalInfimas !== null">
          <p class="inicio__cifra numeros">{{ numero(totalInfimas) }}</p>
          <p class="inicio__pista">con los filtros que tienes puestos</p>
        </template>
        <p v-else class="inicio__vacio">Aún no hay datos cargados. Ábrelas para buscar.</p>
        <button type="button" class="boton boton--fantasma boton--pequeno inicio__ir" @click="emit('ir', 'infimas')">
          Ver ínfimas <IconoPanel nombre="flecha" :tamano="14" />
        </button>
      </article>

      <!-- Cierres próximos -->
      <article class="tarjeta tarjeta--interactiva inicio__tarjeta">
        <p class="inicio__etiqueta"><IconoPanel nombre="reloj" :tamano="16" /> Cierres próximos</p>
        <p v-if="ofertas.cargando" class="esqueleto inicio__cifra-esqueleto" />
        <p v-else-if="ofertas.fallo" class="inicio__vacio">No pudimos leer tus ofertas ahora. Prueba en un rato.</p>
        <template v-else-if="cierres.length">
          <p class="inicio__cifra numeros">{{ cierres.length }}</p>
          <ul class="inicio__lista">
            <li v-for="{ oferta, dias } in cierres.slice(0, 3)" :key="oferta.id">
              <span class="inicio__lista-texto">{{ oferta.objeto || oferta.titulo || oferta.codigo }}</span>
              <span class="etiqueta" :class="insigniaDePlazo(dias).clase">{{ insigniaDePlazo(dias).texto }}</span>
            </li>
          </ul>
        </template>
        <p v-else class="inicio__vacio">Ninguna de tus ofertas cierra esta semana.</p>
        <button type="button" class="boton boton--fantasma boton--pequeno inicio__ir" @click="emit('ir', 'misofertas')">
          Ver mis ofertas <IconoPanel nombre="flecha" :tamano="14" />
        </button>
      </article>

      <!-- Tasa de éxito -->
      <article class="tarjeta tarjeta--interactiva inicio__tarjeta">
        <p class="inicio__etiqueta"><IconoPanel nombre="trofeo" :tamano="16" /> Tasa de éxito</p>
        <p v-if="ofertas.cargando" class="esqueleto inicio__cifra-esqueleto" />
        <p v-else-if="ofertas.fallo" class="inicio__vacio">Sin datos por ahora.</p>
        <template v-else-if="tasa !== null">
          <p class="inicio__cifra numeros">{{ tasa }}%</p>
          <p class="inicio__pista">sobre {{ ofertas.resumen?.resueltas }} ofertas resueltas</p>
        </template>
        <p v-else class="inicio__vacio">Cuando marques ofertas como ganadas o perdidas, verás aquí tu tasa.</p>
        <button type="button" class="boton boton--fantasma boton--pequeno inicio__ir" @click="emit('ir', 'misofertas')">
          Ver seguimiento <IconoPanel nombre="flecha" :tamano="14" />
        </button>
      </article>

      <!-- Avisos -->
      <article class="tarjeta tarjeta--interactiva inicio__tarjeta">
        <p class="inicio__etiqueta"><IconoPanel nombre="campana" :tamano="16" /> Avisos sin leer</p>
        <p v-if="avisos.cargando" class="esqueleto inicio__cifra-esqueleto" />
        <p v-else-if="avisos.fallo" class="inicio__vacio">No pudimos leer tus avisos ahora.</p>
        <template v-else-if="avisos.sinLeer">
          <p class="inicio__cifra numeros">{{ avisos.sinLeer }}</p>
          <p class="inicio__pista">procesos nuevos que cumplen tus alertas</p>
        </template>
        <p v-else class="inicio__vacio">Estás al día. Crea una alerta y te avisamos cuando salga algo tuyo.</p>
        <button type="button" class="boton boton--fantasma boton--pequeno inicio__ir" @click="emit('ir', 'radar')">
          Mis alertas <IconoPanel nombre="flecha" :tamano="14" />
        </button>
      </article>
    </div>

    <section class="tarjeta inicio__atajos" aria-label="Accesos directos">
      <div>
        <p class="tarjeta__titulo">¿Qué quieres hacer?</p>
        <p class="tarjeta__pista">Los tres caminos de todos los días.</p>
      </div>
      <div class="inicio__botones">
        <button type="button" class="boton boton--principal" @click="emit('ir', 'infimas')">
          <IconoPanel nombre="infimas" :tamano="16" /> Ver ínfimas
        </button>
        <button type="button" class="boton boton--secundario" @click="emit('ir', 'radar')">
          <IconoPanel nombre="campana" :tamano="16" /> Mis alertas
        </button>
        <button type="button" class="boton boton--secundario" @click="emit('ir', 'documentos')">
          <IconoPanel nombre="documentos" :tamano="16" /> Preparar oferta
        </button>
      </div>
    </section>
  </section>
</template>

<style scoped>
.inicio {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
}

.inicio__saludo h2 {
  font-size: var(--t-xl);
}

.inicio__saludo p {
  margin-top: var(--e-1);
  color: var(--texto-suave);
}

.inicio__asistente {
  display: flex;
  align-items: center;
  gap: var(--e-4);
  width: 100%;
  min-height: 72px;
  padding: var(--e-4) var(--e-5);
  border: 1px solid var(--acento);
  border-radius: var(--r-3);
  background: var(--superficie);
  color: var(--texto);
  text-align: left;
  cursor: pointer;
  transition:
    box-shadow var(--normal) var(--curva),
    background-color var(--normal) var(--curva);
}

.inicio__asistente:hover {
  background: var(--acento-tenue);
  box-shadow: var(--sombra-2);
}

.inicio__asistente-icono {
  display: grid;
  place-items: center;
  flex: none;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--acento-suave);
  color: var(--acento-fuerte);
}

.inicio__asistente-texto {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.inicio__asistente-texto strong {
  font-size: var(--t-lg);
}

.inicio__asistente-texto span {
  font-size: 1rem;
  color: var(--texto-suave);
}

.inicio__propuestas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-5);
  box-shadow: none;
  border-color: var(--acento-suave);
  background: var(--acento-tenue);
}

.inicio__propuestas-texto {
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  min-width: 0;
}

.inicio__propuestas-frase {
  font-size: var(--t-lg);
  color: var(--texto);
}

.inicio__propuestas-frase strong {
  font-size: var(--t-xl);
}

.inicio__tarjetas {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--e-4);
}

.inicio__tarjeta {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4) var(--e-5);
  box-shadow: none;
}

.inicio__etiqueta {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--texto-suave);
}

.inicio__cifra {
  font-size: var(--t-2xl);
  font-weight: 700;
  line-height: 1.1;
  color: var(--texto);
}

.inicio__cifra-esqueleto {
  height: 2rem;
  width: 5rem;
}

.inicio__pista,
.inicio__vacio {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  line-height: 1.45;
}

.inicio__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
  font-size: var(--t-sm);
}

.inicio__lista li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
}

.inicio__lista-texto {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--texto-suave);
}

/* El enlace de cada tarjeta va abajo del todo, alineado, aunque las tarjetas tengan alturas distintas. */
.inicio__ir {
  margin-top: auto;
  align-self: flex-start;
  margin-left: calc(var(--e-2) * -1);
  color: var(--acento);
}

.inicio__atajos {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-5);
  box-shadow: none;
}

.inicio__botones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

@media (max-width: 639px) {
  .inicio__tarjetas {
    grid-template-columns: minmax(0, 1fr);
  }

  .inicio__propuestas .boton,
  .inicio__botones,
  .inicio__botones .boton {
    width: 100%;
  }
}
</style>
