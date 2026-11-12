<script setup>
/**
 * «Propuestas para ti»: todas las ínfimas abiertas que la empresa puede ofertar, según su perfil.
 *
 * Lo pidió el cliente con estas palabras: «que sean todas las ínfimas a las que la empresa pueda
 * aplicar, y sea fácil para ellos». Por eso la pantalla es deliberadamente corta: una frase que dice
 * qué es, la línea «Te sugerimos según…» para que se entienda de dónde sale la lista, un orden y
 * tarjetas grandes con **una** acción principal, «Preparar proforma».
 *
 * Se diferencia de «Recomendadas» (el radar) en la promesa: aquí no hay tope oculto ni mezcla con
 * otros procesos. Son solo ínfimas con el plazo de proformas abierto, todas, paginadas con «Ver más».
 *
 * Eventos:
 * - `preparar(fila)`: abrir «Preparar oferta» con la ínfima (la fila trae `codigo`).
 * - `ir-perfil` (opcional): llevar al perfil para ajustar CPC, cobertura o presupuesto. Si el padre
 *   no lo escucha, en lugar del botón se dice en texto dónde está el perfil.
 */
import { computed, getCurrentInstance, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import { usd } from '@/utils/oportunidades'
import { diasParaProforma, insigniaDePlazo } from '@/utils/plazo'

const emit = defineEmits(['preparar', 'ir-perfil'])

// Si el padre escucha `ir-perfil`, Vue deja el manejador en las props del vnode como `onIrPerfil`.
const escuchanPerfil = Boolean(getCurrentInstance()?.vnode.props?.onIrPerfil)

const TAMANO = 20
const ORDENES = [
  { id: 'coincidencia', texto: 'Mejor coincidencia' },
  { id: 'cierre', texto: 'Cierra antes' },
  { id: 'presupuesto', texto: 'Mayor presupuesto' },
]

const orden = ref('coincidencia')
const propuestas = ref([])
const total = ref(0)
const pagina = ref(1)
const criterios = ref(null)
const motivo = ref('')
const aviso = ref('')
const cargando = ref(true)
const cargandoMas = ref(false)
const error = ref('')

const hayMas = computed(() => propuestas.value.length < total.value)
// Sin CPC ni productos el servidor responde un motivo y ningún criterio con qué comparar.
const perfilVacio = computed(
  () => Boolean(motivo.value) && !criterios.value?.total_cpc && !criterios.value?.total_palabras,
)

async function cargar({ mas = false } = {}) {
  const siguiente = mas ? pagina.value + 1 : 1
  if (mas) cargandoMas.value = true
  else cargando.value = true
  error.value = ''
  try {
    const respuesta = await api.verPropuestas({ pagina: siguiente, tamano: TAMANO, orden: orden.value })
    const filas = respuesta?.propuestas || []
    propuestas.value = mas ? [...propuestas.value, ...filas] : filas
    total.value = Number(respuesta?.total || 0)
    pagina.value = siguiente
    criterios.value = respuesta?.criterios || null
    motivo.value = respuesta?.motivo || ''
    aviso.value = respuesta?.aviso || ''
  } catch (fallo) {
    error.value = fallo?.message || 'No pudimos cargar tus propuestas. Prueba en un momento.'
  } finally {
    cargando.value = false
    cargandoMas.value = false
  }
}

function cambiarOrden(id) {
  if (orden.value === id) return
  orden.value = id
  cargar()
}

onMounted(() => cargar())

// Las ínfimas publican provincia y cantón en mayúsculas: se leen mejor como nombre propio.
const MINUSCULAS = new Set(['de', 'del', 'la', 'las', 'los', 'y', 'el'])
function nombrePropio(texto) {
  return String(texto || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .map((palabra, indice) =>
      indice > 0 && MINUSCULAS.has(palabra) ? palabra : palabra.charAt(0).toUpperCase() + palabra.slice(1),
    )
    .join(' ')
}

function lugar(fila) {
  return [fila.canton, fila.provincia].filter(Boolean).map(nombrePropio).join(', ')
}

/** «Cierra hoy», «Cierra mañana», «Cierra en 4 días»: la insignia sobria del plazo. */
function plazo(fila) {
  const dias = diasParaProforma(fila.plazo)
  const insignia = insigniaDePlazo(dias)
  if (dias === null) return { texto: 'Sin fecha de cierre', clase: '' }
  if (dias >= 2) return { texto: `Cierra en ${dias} días`, clase: insignia.clase }
  return insignia
}
</script>

<template>
  <div class="propuestas">
    <header class="propuestas__cabecera">
      <h2>Propuestas para ti</h2>
      <p>Ínfimas abiertas que tu empresa puede ofertar, según tus CPC, tu ubicación y tu presupuesto.</p>
    </header>

    <p v-if="criterios?.texto && !perfilVacio" class="propuestas__segun">
      <span>Te sugerimos según: <strong>{{ criterios.texto }}</strong></span>
      <button v-if="escuchanPerfil" type="button" class="propuestas__enlace" @click="emit('ir-perfil')">
        Ajustar mis datos
      </button>
    </p>

    <p v-if="error" class="propuestas__mensaje" role="alert">
      {{ error }}
      <button type="button" class="boton boton--secundario boton--pequeno" @click="cargar()">Reintentar</button>
    </p>

    <!-- Cargando -->
    <div v-if="cargando" class="propuestas__lista" aria-busy="true" aria-label="Cargando propuestas">
      <div v-for="n in 3" :key="n" class="esqueleto propuestas__esqueleto" />
    </div>

    <!-- Perfil sin CPC ni productos: no hay con qué sugerir. Se dice qué falta y dónde ponerlo. -->
    <section v-else-if="perfilVacio" class="propuestas__vacio">
      <h3>Sube tu RUP o agrega tus CPC para recibir propuestas</h3>
      <p>Con tus CPC sabemos qué ínfimas puedes ofertar y te las mostramos aquí cada día.</p>
      <button v-if="escuchanPerfil" type="button" class="boton boton--principal" @click="emit('ir-perfil')">
        Ir a mi perfil
      </button>
      <p v-else class="propuestas__nota">Lo encuentras en «Mi empresa › Perfil y RUP».</p>
    </section>

    <template v-else-if="!error">
      <div class="propuestas__barra">
        <p class="propuestas__total" role="status">
          <template v-if="total === 1">1 ínfima abierta que puedes ofertar</template>
          <template v-else-if="total">{{ total }} ínfimas abiertas que puedes ofertar</template>
        </p>
        <div v-if="total > 1" class="propuestas__orden" role="group" aria-label="Ordenar propuestas">
          <span class="propuestas__orden-etiqueta">Ordenar:</span>
          <button
            v-for="opcion in ORDENES"
            :key="opcion.id"
            type="button"
            class="propuestas__orden-boton"
            :class="{ 'propuestas__orden-boton--activo': orden === opcion.id }"
            :aria-pressed="orden === opcion.id"
            @click="cambiarOrden(opcion.id)"
          >
            {{ opcion.texto }}
          </button>
        </div>
      </div>

      <ul v-if="propuestas.length" class="propuestas__lista">
        <li v-for="fila in propuestas" :key="fila.id" class="propuesta">
          <div class="propuesta__arriba">
            <span class="etiqueta" :class="plazo(fila).clase">{{ plazo(fila).texto }}</span>
            <span v-if="usd(fila.presupuesto) !== '—'" class="propuesta__monto numeros">
              {{ usd(fila.presupuesto) }}
            </span>
          </div>
          <h3 class="propuesta__objeto">{{ fila.objeto || 'Sin objeto publicado' }}</h3>
          <p class="propuesta__meta">
            <span v-if="fila.entidad">{{ fila.entidad }}</span>
            <span v-if="lugar(fila)">{{ lugar(fila) }}</span>
          </p>
          <ul v-if="fila.motivos?.length" class="propuesta__motivos" aria-label="Por qué te la sugerimos">
            <li v-for="texto in fila.motivos" :key="texto">
              <span class="propuesta__check" aria-hidden="true">✓</span>{{ texto }}
            </li>
          </ul>
          <div class="propuesta__pie">
            <span class="propuesta__codigo numeros">{{ fila.codigo }}</span>
            <button type="button" class="boton boton--principal" @click="emit('preparar', fila)">
              Preparar proforma
            </button>
          </div>
        </li>
      </ul>

      <section v-else class="propuestas__vacio">
        <h3>Hoy no hay ínfimas abiertas para tu empresa</h3>
        <p>
          {{ motivo || 'Revisa mañana: salen ínfimas nuevas cada día.' }}
          Si vendes algo más, agrégalo a tu perfil para recibir más propuestas.
        </p>
        <button v-if="escuchanPerfil" type="button" class="boton boton--secundario" @click="emit('ir-perfil')">
          Ajustar mis datos
        </button>
      </section>

      <div v-if="hayMas" class="propuestas__mas">
        <button type="button" class="boton boton--secundario" :disabled="cargandoMas" @click="cargar({ mas: true })">
          {{ cargandoMas ? 'Cargando…' : `Ver más (${total - propuestas.length} más)` }}
        </button>
      </div>

      <p v-if="aviso && propuestas.length" class="propuestas__nota">{{ aviso }}</p>
    </template>
  </div>
</template>

<style scoped>
.propuestas {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.propuestas__cabecera h2 {
  font-size: var(--t-xl);
}

.propuestas__cabecera p {
  margin-top: var(--e-1);
  color: var(--texto-suave);
  font-size: var(--t-base);
}

.propuestas__segun {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--e-2) var(--e-3);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.propuestas__segun strong {
  color: var(--texto);
  font-weight: 600;
}

.propuestas__enlace {
  border: 0;
  background: none;
  padding: 0;
  color: var(--acento);
  font: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.propuestas__enlace:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
  border-radius: var(--r-1);
}

.propuestas__mensaje {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-3);
  color: var(--texto);
}

.propuestas__barra {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
}

.propuestas__total {
  font-weight: 600;
  color: var(--texto);
}

.propuestas__orden {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1);
}

.propuestas__orden-etiqueta {
  font-size: var(--t-sm);
  color: var(--texto-suave);
  margin-right: var(--e-1);
}

.propuestas__orden-boton {
  border: 1px solid var(--borde);
  background: var(--superficie);
  color: var(--texto-suave);
  border-radius: var(--r-redondo);
  padding: var(--e-1) var(--e-3);
  font: inherit;
  font-size: var(--t-sm);
  min-height: 36px;
  cursor: pointer;
}

.propuestas__orden-boton--activo {
  border-color: var(--acento);
  background: var(--acento-tenue);
  color: var(--acento);
  font-weight: 600;
}

.propuestas__orden-boton:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
}

.propuestas__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.propuestas__esqueleto {
  height: 9rem;
  border-radius: var(--r-3);
}

.propuesta {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4) var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  transition: box-shadow 0.15s ease;
}

.propuesta:hover {
  box-shadow: var(--sombra-2);
}

.propuesta__arriba {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
}

.propuesta__monto {
  font-weight: 700;
  color: var(--texto);
  font-size: var(--t-lg);
}

.propuesta__objeto {
  font-size: var(--t-lg);
  line-height: 1.35;
  color: var(--texto);
  overflow-wrap: anywhere;
}

.propuesta__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1) var(--e-3);
  color: var(--texto-suave);
  font-size: var(--t-base);
}

.propuesta__motivos {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1) var(--e-4);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.propuesta__check {
  color: var(--acento);
  font-weight: 700;
  margin-right: var(--e-1);
}

.propuesta__pie {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  margin-top: var(--e-1);
}

.propuesta__codigo {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  overflow-wrap: anywhere;
}

.propuestas__vacio {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--e-3);
  padding: var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie-2);
}

.propuestas__vacio h3 {
  font-size: var(--t-lg);
}

.propuestas__vacio p {
  color: var(--texto-suave);
  line-height: 1.5;
}

.propuestas__mas {
  display: flex;
  justify-content: center;
}

.propuestas__nota {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

@media (max-width: 639px) {
  .propuesta {
    padding: var(--e-4);
  }

  .propuesta__pie .boton,
  .propuestas__mas .boton,
  .propuestas__vacio .boton {
    width: 100%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .propuesta {
    transition: none;
  }
}
</style>
