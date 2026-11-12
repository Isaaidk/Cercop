<script setup>
/**
 * «Mis ofertas»: el CRM de las proformas ya hechas.
 *
 * - **Tablero** por etapa (borrador → enviada → adjudicada / perdida). Las tarjetas se arrastran de
 *   una columna a otra, o se mueven con el selector de la tarjeta (teclado y móvil).
 * - **Calendario** de cierres de los procesos con proforma en borrador o enviada. El worker deja un
 *   aviso el día antes del cierre si la proforma sigue en borrador.
 * - **Lista** compacta para buscar.
 *
 * La base solo guarda la etapa, el monto adjudicado y una nota corta; la tasa de éxito y los montos
 * se calculan al leer.
 *
 * Cada proforma queda guardada: desde el detalle se vuelve a ver y a descargar tal como se hizo. El
 * PDF lo arma este navegador con los datos guardados (`armarProformaPdf`), igual que en «Preparar
 * oferta», así verla otra vez no gasta CPU del servidor.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { guardarArchivo } from '@/utils/descargas'
import { diasParaProforma, nivelDePlazo, textoDePlazo } from '@/utils/plazo'
import { armarProformaPdf } from '@/utils/proformaPdf'

const emit = defineEmits(['preparar'])

const ETAPAS = [
  { id: 'borrador', titulo: 'Borrador', pista: 'Armada, sin enviar' },
  { id: 'enviada', titulo: 'Enviada', pista: 'Esperando resultado' },
  { id: 'adjudicada', titulo: 'Adjudicada', pista: 'Ganada' },
  { id: 'perdida', titulo: 'Perdida', pista: 'No adjudicada' },
]
const TODAS = [...ETAPAS, { id: 'descartada', titulo: 'Descartada', pista: 'No se presentó' }]

const ofertas = ref([])
const resumen = ref(null)
const cargando = ref(true)
const error = ref('')
const vista = ref('tablero')
const busqueda = ref('')
const verDescartadas = ref(false)
const abierta = ref(null)
const arrastrada = ref(null)
const sobre = ref('')
const guardando = reactive({})

async function cargar() {
  error.value = ''
  try {
    const datos = await api.misOfertas()
    ofertas.value = datos.ofertas || []
    resumen.value = datos.resumen
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

onMounted(cargar)

// ------------------------------------------------------------------------------- filtros

const filtradas = computed(() => {
  const texto = busqueda.value.trim().toLowerCase()
  if (!texto) return ofertas.value
  return ofertas.value.filter((o) =>
    [o.objeto, o.entidad, o.titulo, o.codigo, o.nota].some((v) => String(v || '').toLowerCase().includes(texto)),
  )
})

const porEtapa = computed(() => {
  const grupos = Object.fromEntries(TODAS.map((e) => [e.id, []]))
  for (const oferta of filtradas.value) (grupos[oferta.etapa] || grupos.borrador).push(oferta)
  return grupos
})

// ------------------------------------------------------------------------------- cifras

const usd = (valor) =>
  valor == null || valor === ''
    ? '—'
    : new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(valor)

const cierranPronto = computed(() =>
  ofertas.value.filter((o) => {
    const dias = diasParaProforma(o.plazo)
    return ['borrador', 'enviada'].includes(o.etapa) && dias !== null && dias >= 0 && dias <= 7
  }),
)

function sumaDe(lista) {
  return lista.reduce((suma, o) => suma + Number(o.total || 0), 0)
}

// ------------------------------------------------------------------------------- mover

async function mover(oferta, campos) {
  const antes = { ...oferta }
  Object.assign(oferta, campos)
  guardando[oferta.id] = true
  error.value = ''
  try {
    await api.moverOferta(oferta.id, campos)
    const datos = await api.misOfertas()
    resumen.value = datos.resumen
  } catch (fallo) {
    Object.assign(oferta, antes)
    error.value = fallo.message
  } finally {
    guardando[oferta.id] = false
  }
}

function alSoltar(etapa) {
  const oferta = ofertas.value.find((o) => o.id === arrastrada.value)
  sobre.value = ''
  arrastrada.value = null
  if (oferta && oferta.etapa !== etapa) mover(oferta, { etapa })
}

function guardarNota(oferta, texto) {
  if ((oferta.nota || '') !== texto) mover(oferta, { nota: texto.slice(0, 500) })
}

function guardarMonto(oferta, valor) {
  const numero = valor === '' ? null : Number(valor)
  if (numero !== null && (Number.isNaN(numero) || numero < 0)) return
  if (numero !== (oferta.monto_adjudicado == null ? null : Number(oferta.monto_adjudicado))) {
    mover(oferta, { monto_adjudicado: numero })
  }
}

const detalle = computed(() => ofertas.value.find((o) => o.id === abierta.value) || null)

// ------------------------------------------------------------------------------- proforma guardada

// La ficha técnica se maqueta en el servidor: en el navegador no hay PDF que armar.
const conPdf = (oferta) => Boolean(oferta) && oferta.tipo !== 'ficha'

const visor = reactive({ id: null, blob: null, url: '', abierto: false, cargando: '', error: '' })

/** Suelta el PDF armado. La URL del objeto retiene el archivo en memoria hasta que se revoca. */
function cerrarVisor() {
  if (visor.url) URL.revokeObjectURL(visor.url)
  Object.assign(visor, { id: null, blob: null, url: '', abierto: false, cargando: '', error: '' })
}

/** Arma el PDF una sola vez por proforma: ver y descargar reutilizan el mismo archivo. */
async function pdfDe(oferta, accion) {
  if (visor.id === oferta.id && visor.blob) return visor.blob
  cerrarVisor()
  visor.id = oferta.id
  visor.cargando = accion
  try {
    const guardado = await api.verDocumento(oferta.id)
    const { blob } = await armarProformaPdf(guardado)
    // Si mientras tanto se abrió otra oferta, este PDF ya no es el que se mira.
    if (visor.id !== oferta.id) return null
    visor.blob = blob
    return blob
  } catch (fallo) {
    if (visor.id === oferta.id) visor.error = fallo.message || 'No se pudo armar el PDF de esta proforma.'
    return null
  } finally {
    if (visor.id === oferta.id) visor.cargando = ''
  }
}

function nombrePdf(oferta) {
  const base = String(oferta.codigo || oferta.titulo || 'proforma').replace(/[^\w.-]+/g, '-')
  return `${(oferta.tipo || 'proforma').toLowerCase()}-${base}.pdf`
}

async function verProforma(oferta) {
  const blob = await pdfDe(oferta, 'ver')
  if (!blob) return
  if (!visor.url) visor.url = URL.createObjectURL(blob)
  visor.abierto = true
}

async function descargarProforma(oferta) {
  const blob = await pdfDe(oferta, 'bajar')
  if (blob) guardarArchivo(blob, nombrePdf(oferta))
}

/** Cierra la vista y libera su URL; el PDF armado se conserva por si se vuelve a abrir. */
function cerrarVista() {
  if (visor.url) URL.revokeObjectURL(visor.url)
  visor.url = ''
  visor.abierto = false
}

function alTeclear(evento) {
  if (evento.key === 'Escape' && visor.abierto) cerrarVista()
}

watch(abierta, cerrarVisor)
onMounted(() => window.addEventListener('keydown', alTeclear))
onBeforeUnmount(() => {
  window.removeEventListener('keydown', alTeclear)
  cerrarVisor()
})

// ------------------------------------------------------------------------------- calendario

const mesVisto = ref(new Date(new Date().getFullYear(), new Date().getMonth(), 1))

const diasDelMes = computed(() => {
  const inicio = mesVisto.value
  const primero = (inicio.getDay() + 6) % 7 // lunes primero
  const total = new Date(inicio.getFullYear(), inicio.getMonth() + 1, 0).getDate()
  const celdas = Array.from({ length: primero }, () => null)
  for (let dia = 1; dia <= total; dia += 1) {
    const fecha = new Date(inicio.getFullYear(), inicio.getMonth(), dia)
    const clave = fecha.toDateString()
    celdas.push({
      dia,
      hoy: clave === new Date().toDateString(),
      ofertas: ofertas.value.filter(
        (o) => o.plazo && ['borrador', 'enviada'].includes(o.etapa) && new Date(o.plazo).toDateString() === clave,
      ),
    })
  }
  return celdas
})

const tituloMes = computed(() =>
  mesVisto.value.toLocaleDateString('es-EC', { month: 'long', year: 'numeric' }),
)

function cambiarMes(salto) {
  const actual = mesVisto.value
  mesVisto.value = new Date(actual.getFullYear(), actual.getMonth() + salto, 1)
}

const proximos = computed(() =>
  ofertas.value
    .filter((o) => o.plazo && ['borrador', 'enviada'].includes(o.etapa) && diasParaProforma(o.plazo) >= 0)
    .sort((a, b) => new Date(a.plazo) - new Date(b.plazo))
    .slice(0, 12),
)

function fechaHora(valor) {
  return valor
    ? new Date(valor).toLocaleString('es-EC', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    : ''
}
</script>

<template>
  <div class="crm">
    <header class="crm__cabecera">
      <div>
        <h2>Mis ofertas</h2>
        <p>Las proformas que armaste, por etapa. Arrastra cada una a donde corresponda cuando la envíes o sepas el resultado.</p>
      </div>
      <div class="crm__herramientas">
        <input v-model="busqueda" class="entrada entrada--compacta" type="search" placeholder="Buscar por objeto, entidad o código" />
        <div class="segmentado" role="tablist" aria-label="Vista">
          <button
            v-for="opcion in [['tablero', 'Tablero'], ['calendario', 'Calendario'], ['lista', 'Lista']]"
            :key="opcion[0]"
            type="button"
            role="tab"
            :aria-selected="vista === opcion[0]"
            :class="{ 'segmentado__opcion--activa': vista === opcion[0] }"
            class="segmentado__opcion"
            @click="vista = opcion[0]"
          >
            {{ opcion[1] }}
          </button>
        </div>
      </div>
    </header>

    <p v-if="error" class="crm__error" role="alert">{{ error }}</p>

    <!-- Indicadores -->
    <section v-if="resumen" class="kpis" aria-label="Resumen">
      <div class="kpi kpi--principal">
        <small>Tasa de éxito</small>
        <strong class="numeros">{{ resumen.tasa_exito == null ? '—' : `${resumen.tasa_exito}%` }}</strong>
        <span>{{ resumen.resueltas ? `sobre ${resumen.resueltas} resueltas` : 'Aún sin resultados' }}</span>
      </div>
      <div class="kpi">
        <small>Adjudicado</small>
        <strong class="numeros">{{ usd(resumen.adjudicado) }}</strong>
        <span>{{ resumen.por_etapa.adjudicada.cantidad }} ganadas</span>
      </div>
      <div class="kpi">
        <small>En juego</small>
        <strong class="numeros">{{ usd(resumen.en_juego) }}</strong>
        <span>{{ resumen.por_etapa.borrador.cantidad + resumen.por_etapa.enviada.cantidad }} abiertas</span>
      </div>
      <div class="kpi" :class="{ 'kpi--alerta': cierranPronto.length }">
        <small>Cierran en 7 días</small>
        <strong class="numeros">{{ cierranPronto.length }}</strong>
        <button v-if="cierranPronto.length" type="button" class="kpi__enlace" @click="vista = 'calendario'">Ver calendario</button>
        <span v-else>Nada urgente</span>
      </div>
    </section>

    <div v-if="cargando" class="crm__cargando">
      <span v-for="n in 4" :key="n" class="esqueleto" />
    </div>

    <div v-else-if="!ofertas.length" class="crm__vacio">
      <p><strong>Aún no tienes proformas.</strong></p>
      <p>Abre una ínfima, pulsa «Llenar TDR» y genera la proforma: aparecerá aquí para darle seguimiento.</p>
    </div>

    <!-- Tablero -->
    <div v-else-if="vista === 'tablero'" class="tablero">
      <section
        v-for="etapa in ETAPAS"
        :key="etapa.id"
        class="columna"
        :class="[`columna--${etapa.id}`, { 'columna--sobre': sobre === etapa.id }]"
        @dragover.prevent="sobre = etapa.id"
        @dragleave="sobre = sobre === etapa.id ? '' : sobre"
        @drop.prevent="alSoltar(etapa.id)"
      >
        <header class="columna__cabecera">
          <span class="columna__punto" aria-hidden="true" />
          <h3>{{ etapa.titulo }}</h3>
          <span class="columna__cuenta">{{ porEtapa[etapa.id].length }}</span>
          <small class="numeros">{{ usd(sumaDe(porEtapa[etapa.id])) }}</small>
        </header>
        <p v-if="!porEtapa[etapa.id].length" class="columna__vacia">{{ etapa.pista }}</p>
        <article
          v-for="oferta in porEtapa[etapa.id]"
          :key="oferta.id"
          class="tarjeta-oferta"
          :class="{ 'tarjeta-oferta--guardando': guardando[oferta.id], 'tarjeta-oferta--abierta': abierta === oferta.id }"
          draggable="true"
          @dragstart="arrastrada = oferta.id"
          @dragend="arrastrada = null; sobre = ''"
          @click="abierta = abierta === oferta.id ? null : oferta.id"
        >
          <p class="tarjeta-oferta__codigo numeros">{{ oferta.codigo || oferta.titulo }}</p>
          <p class="tarjeta-oferta__objeto">{{ oferta.objeto || oferta.titulo }}</p>
          <p class="tarjeta-oferta__entidad">{{ oferta.entidad }}</p>
          <div class="tarjeta-oferta__pie">
            <strong class="numeros">{{ usd(oferta.total) }}</strong>
            <span v-if="oferta.plazo && ['borrador', 'enviada'].includes(oferta.etapa)" class="plazo" :class="nivelDePlazo(diasParaProforma(oferta.plazo))">
              {{ textoDePlazo(diasParaProforma(oferta.plazo)) }}
            </span>
            <span v-if="oferta.nota" class="tarjeta-oferta__nota" title="Tiene nota">✎</span>
          </div>
          <select
            class="tarjeta-oferta__mover"
            :value="oferta.etapa"
            :aria-label="`Mover ${oferta.objeto || oferta.titulo}`"
            @click.stop
            @change="mover(oferta, { etapa: $event.target.value })"
          >
            <option v-for="e in TODAS" :key="e.id" :value="e.id">{{ e.titulo }}</option>
          </select>
        </article>
      </section>
    </div>

    <!-- Calendario -->
    <div v-else-if="vista === 'calendario'" class="calendario">
      <section class="calendario__mes">
        <header class="calendario__cabecera">
          <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Mes anterior" @click="cambiarMes(-1)">‹</button>
          <h3>{{ tituloMes }}</h3>
          <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Mes siguiente" @click="cambiarMes(1)">›</button>
        </header>
        <div class="calendario__rejilla">
          <span v-for="d in ['L', 'M', 'X', 'J', 'V', 'S', 'D']" :key="d" class="calendario__dia-semana">{{ d }}</span>
          <div
            v-for="(celda, n) in diasDelMes"
            :key="n"
            class="calendario__celda"
            :class="{ 'calendario__celda--hoy': celda?.hoy, 'calendario__celda--con': celda?.ofertas.length }"
          >
            <template v-if="celda">
              <span class="calendario__numero">{{ celda.dia }}</span>
              <button
                v-for="oferta in celda.ofertas.slice(0, 3)"
                :key="oferta.id"
                type="button"
                class="calendario__evento"
                :class="`calendario__evento--${oferta.etapa}`"
                :title="oferta.objeto"
                @click="abierta = oferta.id"
              >
                {{ (oferta.objeto || oferta.titulo).slice(0, 22) }}
              </button>
              <small v-if="celda.ofertas.length > 3">+{{ celda.ofertas.length - 3 }}</small>
            </template>
          </div>
        </div>
      </section>
      <aside class="calendario__proximos">
        <h3>Próximos cierres</h3>
        <p class="crm__nota">Si una proforma sigue en borrador el día antes del cierre, te llega un aviso en «Radar → Avisos».</p>
        <ul>
          <li v-for="oferta in proximos" :key="oferta.id" @click="abierta = oferta.id">
            <span class="plazo" :class="nivelDePlazo(diasParaProforma(oferta.plazo))">{{ textoDePlazo(diasParaProforma(oferta.plazo)) }}</span>
            <span class="calendario__texto">
              <strong>{{ oferta.objeto || oferta.titulo }}</strong>
              <small>{{ fechaHora(oferta.plazo) }} · {{ TODAS.find((e) => e.id === oferta.etapa)?.titulo }}</small>
            </span>
          </li>
          <li v-if="!proximos.length" class="crm__nota">No hay cierres próximos.</li>
        </ul>
      </aside>
    </div>

    <!-- Lista -->
    <div v-else class="lista-ofertas">
      <table class="lista-ofertas__tabla">
        <thead>
          <tr>
            <th scope="col">Objeto</th>
            <th scope="col">Entidad</th>
            <th scope="col">Total</th>
            <th scope="col">Cierre</th>
            <th scope="col">Etapa</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="oferta in filtradas" :key="oferta.id" @click="abierta = oferta.id">
            <td><strong>{{ oferta.objeto || oferta.titulo }}</strong><small class="numeros">{{ oferta.codigo }}</small></td>
            <td>{{ oferta.entidad }}</td>
            <td class="numeros">{{ usd(oferta.total) }}</td>
            <td class="numeros">{{ oferta.plazo ? new Date(oferta.plazo).toLocaleDateString('es-EC') : '—' }}</td>
            <td>
              <select :value="oferta.etapa" @click.stop @change="mover(oferta, { etapa: $event.target.value })">
                <option v-for="e in TODAS" :key="e.id" :value="e.id">{{ e.titulo }}</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <details v-if="!cargando && porEtapa.descartada.length" class="crm__descartadas" :open="verDescartadas">
      <summary @click.prevent="verDescartadas = !verDescartadas">Descartadas ({{ porEtapa.descartada.length }})</summary>
      <ul>
        <li v-for="oferta in porEtapa.descartada" :key="oferta.id">
          {{ oferta.objeto || oferta.titulo }}
          <button type="button" class="boton boton--fantasma boton--pequeno" @click="mover(oferta, { etapa: 'borrador' })">Recuperar</button>
        </li>
      </ul>
    </details>

    <!-- Detalle -->
    <Transition name="lateral">
      <aside v-if="detalle" class="detalle-oferta" aria-label="Detalle de la oferta">
        <header class="detalle-oferta__cabecera">
          <div>
            <p class="numeros detalle-oferta__codigo">{{ detalle.codigo || detalle.titulo }}</p>
            <h3>{{ detalle.objeto || detalle.titulo }}</h3>
            <p class="crm__nota">{{ detalle.entidad }}</p>
            <span class="insignia-etapa" :class="`insignia-etapa--${detalle.etapa}`">
              {{ TODAS.find((e) => e.id === detalle.etapa)?.titulo || detalle.etapa }}
            </span>
          </div>
          <button type="button" class="boton boton--fantasma boton--icono" aria-label="Cerrar" @click="abierta = null">×</button>
        </header>
        <section v-if="conPdf(detalle)" class="detalle-oferta__proforma" aria-label="Proforma guardada">
          <p class="crm__nota">La proforma queda guardada tal como la generaste.</p>
          <div class="detalle-oferta__acciones">
            <button
              type="button"
              class="boton boton--secundario boton--pequeno"
              :disabled="Boolean(visor.cargando)"
              @click="verProforma(detalle)"
            >
              {{ visor.cargando === 'ver' ? 'Armando el PDF…' : 'Ver proforma' }}
            </button>
            <button
              type="button"
              class="boton boton--fantasma boton--pequeno"
              :disabled="Boolean(visor.cargando)"
              @click="descargarProforma(detalle)"
            >
              {{ visor.cargando === 'bajar' ? 'Preparando…' : 'Descargar PDF' }}
            </button>
          </div>
          <p v-if="visor.error" class="crm__error" role="alert">{{ visor.error }}</p>
        </section>
        <dl class="detalle-oferta__datos">
          <div><dt>Total ofertado</dt><dd class="numeros">{{ usd(detalle.total) }}</dd></div>
          <div><dt>Ítems</dt><dd class="numeros">{{ detalle.lineas }}</dd></div>
          <div><dt>Creada</dt><dd>{{ fechaHora(detalle.creado_en) }}</dd></div>
          <div v-if="detalle.plazo"><dt>Cierre del proceso</dt><dd>{{ fechaHora(detalle.plazo) }}</dd></div>
          <div v-if="detalle.etapa_en"><dt>Última etapa</dt><dd>{{ fechaHora(detalle.etapa_en) }}</dd></div>
        </dl>
        <div class="detalle-oferta__etapas" role="radiogroup" aria-label="Etapa">
          <button
            v-for="e in TODAS"
            :key="e.id"
            type="button"
            role="radio"
            :aria-checked="detalle.etapa === e.id"
            :class="['etapa-boton', `etapa-boton--${e.id}`, { 'etapa-boton--activa': detalle.etapa === e.id }]"
            @click="mover(detalle, { etapa: e.id })"
          >
            {{ e.titulo }}
          </button>
        </div>
        <label v-if="detalle.etapa === 'adjudicada'" class="campo">
          <span class="campo__etiqueta">Monto adjudicado (USD)</span>
          <input
            class="entrada numeros"
            type="number"
            min="0"
            step="0.01"
            :value="detalle.monto_adjudicado ?? ''"
            :placeholder="String(detalle.total || '')"
            @change="guardarMonto(detalle, $event.target.value)"
          />
        </label>
        <label class="campo">
          <span class="campo__etiqueta">Nota</span>
          <textarea
            class="entrada"
            rows="4"
            maxlength="500"
            placeholder="Ej. Enviada por correo al responsable el lunes; pidieron plazo de entrega de 15 días."
            :value="detalle.nota"
            @blur="guardarNota(detalle, $event.target.value)"
          />
        </label>
        <button
          v-if="detalle.codigo"
          type="button"
          class="boton boton--principal"
          @click="emit('preparar', { codigo: detalle.codigo })"
        >
          Abrir el proceso y su proforma
        </button>
      </aside>
    </Transition>

    <!-- Visor de la proforma guardada -->
    <div
      v-if="visor.abierto && visor.url && detalle"
      class="visor-proforma"
      role="dialog"
      aria-modal="true"
      aria-labelledby="visor-proforma-titulo"
      @click.self="cerrarVista"
    >
      <div class="visor-proforma__caja">
        <header class="visor-proforma__cabecera">
          <h3 id="visor-proforma-titulo">{{ detalle.objeto || detalle.titulo }}</h3>
          <button type="button" class="boton boton--principal boton--pequeno" @click="descargarProforma(detalle)">
            Descargar PDF
          </button>
          <button type="button" class="boton boton--fantasma boton--icono" aria-label="Cerrar la vista" @click="cerrarVista">×</button>
        </header>
        <iframe class="visor-proforma__marco" :src="visor.url" title="Proforma guardada" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.crm {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.crm__cabecera {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--e-3);
  align-items: flex-end;
}

.crm__cabecera h2 {
  font-size: var(--t-xl);
  font-weight: 700;
}

.crm__cabecera p,
.crm__nota {
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.crm__herramientas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

.crm__error {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.segmentado {
  display: inline-flex;
  padding: 3px;
  border-radius: var(--r-2);
  background: var(--superficie-3);
}

.segmentado__opcion {
  padding: 5px 12px;
  border: 0;
  border-radius: var(--r-1);
  background: transparent;
  color: var(--texto-suave);
  font-size: var(--t-sm);
  font-weight: 600;
  cursor: pointer;
}

.segmentado__opcion--activa {
  background: var(--superficie);
  color: var(--texto);
  box-shadow: var(--sombra-1);
}

/* KPIs */
.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: var(--e-3);
}

.kpi {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--e-3) var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.kpi small {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 650;
}

.kpi strong {
  font-size: var(--t-xl);
}

.kpi span,
.kpi__enlace {
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

.kpi--principal {
  border-color: var(--acento-suave);
  background: var(--acento-tenue);
}

.kpi--principal strong {
  color: var(--acento-fuerte);
}

/* Solo el número avisa: el bloque sigue neutro, como pide la guía. */
.kpi--alerta strong {
  color: var(--aviso);
}

.kpi__enlace {
  align-self: flex-start;
  border: 0;
  padding: 0;
  background: none;
  color: var(--acento-fuerte);
  text-decoration: underline;
  cursor: pointer;
}

.crm__cargando {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--e-3);
}

.crm__cargando .esqueleto {
  height: 14rem;
  border-radius: var(--r-3);
}

.crm__vacio {
  padding: var(--e-6);
  border: 1px dashed var(--borde-fuerte);
  border-radius: var(--r-3);
  text-align: center;
  color: var(--texto-suave);
}

/* Tablero */
.tablero {
  display: grid;
  grid-template-columns: repeat(4, minmax(14rem, 1fr));
  gap: var(--e-3);
  overflow-x: auto;
  padding-bottom: var(--e-2);
}

.columna {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  min-height: 12rem;
  padding: var(--e-3);
  border-radius: var(--r-3);
  background: var(--superficie-2);
  border: 2px solid transparent;
  transition: border-color var(--rapido), background var(--rapido);
}

.columna--sobre {
  border-color: var(--acento);
  background: var(--acento-tenue);
}

.columna__cabecera {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding-bottom: var(--e-2);
}

.columna__cabecera h3 {
  font-size: var(--t-sm);
  font-weight: 700;
}

.columna__cabecera small {
  margin-left: auto;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.columna__punto {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--texto-tenue);
}

/* Un punto pequeño basta para distinguir la columna; el color de estado no pasa de ahí. */
.columna--enviada .columna__punto {
  background: var(--info);
}

.columna--adjudicada .columna__punto {
  background: var(--ok);
}

.columna--perdida .columna__punto {
  background: var(--error);
}

.columna__cuenta {
  padding: 0 7px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  font-size: var(--t-xs);
  font-weight: 700;
}

.columna__vacia {
  padding: var(--e-4) var(--e-2);
  border: 1px dashed var(--borde-fuerte);
  border-radius: var(--r-2);
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  text-align: center;
}

.tarjeta-oferta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--e-3);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
  cursor: grab;
  transition: box-shadow var(--rapido), border-color var(--rapido), opacity var(--rapido);
}

.tarjeta-oferta:hover {
  box-shadow: var(--sombra-2);
  border-color: var(--acento-suave);
}

.tarjeta-oferta--abierta {
  border-color: var(--acento);
}

.tarjeta-oferta--guardando {
  opacity: 0.6;
}

.tarjeta-oferta__codigo {
  font-size: 0.7rem;
  color: var(--texto-tenue);
}

.tarjeta-oferta__objeto {
  font-size: var(--t-sm);
  font-weight: 600;
  line-height: 1.35;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tarjeta-oferta__entidad {
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

.tarjeta-oferta__pie {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin-top: 2px;
  font-size: var(--t-sm);
}

.tarjeta-oferta__nota {
  margin-left: auto;
  color: var(--texto-tenue);
}

.tarjeta-oferta__mover {
  margin-top: 4px;
  padding: 2px 4px;
  border: 1px solid var(--borde);
  border-radius: var(--r-1);
  background: var(--superficie-2);
  font-size: var(--t-xs);
}

/* Calendario */
.calendario {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(16rem, 1fr);
  gap: var(--e-4);
}

.calendario__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--e-2);
}

.calendario__cabecera h3 {
  text-transform: capitalize;
  font-size: var(--t-md);
}

.calendario__rejilla {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 4px;
}

.calendario__dia-semana {
  text-align: center;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  font-weight: 650;
}

.calendario__celda {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 5.5rem;
  padding: 4px;
  border: 1px solid var(--borde);
  border-radius: var(--r-1);
  background: var(--superficie);
}

.calendario__celda--hoy {
  border-color: var(--acento);
  box-shadow: inset 0 0 0 1px var(--acento);
}

.calendario__numero {
  font-size: var(--t-xs);
  color: var(--texto-suave);
  font-weight: 650;
}

.calendario__evento {
  padding: 1px 4px;
  border: 0;
  border-radius: 4px;
  background: var(--superficie-3);
  font-size: 0.68rem;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.calendario__evento--borrador {
  background: var(--superficie-3);
  color: var(--texto);
}

.calendario__evento--enviada {
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
}

.calendario__proximos {
  padding: var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.calendario__proximos h3 {
  font-size: var(--t-md);
  margin-bottom: var(--e-1);
}

.calendario__proximos ul {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin: var(--e-3) 0 0;
  padding: 0;
  list-style: none;
}

.calendario__proximos li {
  display: flex;
  gap: var(--e-2);
  align-items: flex-start;
  cursor: pointer;
}

.calendario__texto {
  display: flex;
  flex-direction: column;
  min-width: 0;
  font-size: var(--t-sm);
}

.calendario__texto small {
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

/* Lista */
.lista-ofertas {
  overflow-x: auto;
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
}

.lista-ofertas__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.lista-ofertas__tabla th,
.lista-ofertas__tabla td {
  padding: var(--e-2) var(--e-3);
  border-bottom: 1px solid var(--borde);
  text-align: left;
  vertical-align: top;
}

.lista-ofertas__tabla th {
  font-size: var(--t-xs);
  text-transform: uppercase;
  color: var(--texto-tenue);
  background: var(--superficie-2);
}

.lista-ofertas__tabla tbody tr {
  cursor: pointer;
}

.lista-ofertas__tabla tbody tr:hover {
  background: var(--acento-tenue);
}

.lista-ofertas__tabla small {
  display: block;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.crm__descartadas summary {
  cursor: pointer;
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.crm__descartadas ul {
  margin: var(--e-2) 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--t-sm);
}

/* Detalle */
.detalle-oferta {
  position: fixed;
  top: 0;
  right: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  width: min(26rem, 100vw);
  height: 100vh;
  padding: var(--e-5);
  overflow-y: auto;
  background: var(--superficie);
  border-left: 1px solid var(--borde);
  box-shadow: var(--sombra-3);
}

.detalle-oferta__cabecera {
  display: flex;
  justify-content: space-between;
  gap: var(--e-3);
}

.detalle-oferta__cabecera h3 {
  font-size: var(--t-md);
  line-height: 1.35;
}

.detalle-oferta__codigo {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.detalle-oferta__datos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-3);
  margin: 0;
}

.detalle-oferta__datos dt {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.detalle-oferta__datos dd {
  margin: 0;
  font-size: var(--t-sm);
  font-weight: 600;
}

.detalle-oferta__etapas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1);
}

.etapa-boton {
  padding: 5px 10px;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  font-size: var(--t-xs);
  font-weight: 650;
  cursor: pointer;
}

.etapa-boton:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
}

/* La etapa elegida se marca con el acento, sin bloques de color: el estado ya lo dice la insignia. */
.etapa-boton--activa {
  border-color: var(--acento);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
}

/* Insignia de la etapa: texto y fondo suave, como el resto de estados del panel. */
.insignia-etapa {
  display: inline-block;
  margin-top: var(--e-2);
  padding: 1px 0.6rem;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto-suave);
  font-size: var(--t-xs);
  font-weight: 650;
}

.insignia-etapa--enviada {
  background: var(--info-suave);
  color: var(--info);
}

.insignia-etapa--adjudicada {
  background: var(--ok-suave);
  color: var(--ok);
}

.insignia-etapa--perdida {
  background: var(--error-suave);
  color: var(--error);
}

.detalle-oferta__proforma {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-3) var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie-2);
}

.detalle-oferta__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

/* Visor de la proforma: una caja casi a pantalla completa sobre un velo. */
.visor-proforma {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  place-items: center;
  padding: var(--e-4);
  background: color-mix(in srgb, var(--texto) 45%, transparent);
}

.visor-proforma__caja {
  display: flex;
  flex-direction: column;
  width: min(60rem, 100%);
  height: min(92vh, 60rem);
  overflow: hidden;
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  box-shadow: var(--sombra-3);
}

.visor-proforma__cabecera {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: var(--e-3) var(--e-4);
  border-bottom: 1px solid var(--borde);
}

.visor-proforma__cabecera h3 {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  font-size: var(--t-md);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.visor-proforma__marco {
  flex: 1;
  width: 100%;
  border: 0;
  background: var(--superficie-2);
}

.lateral-enter-active,
.lateral-leave-active {
  transition: transform 0.22s var(--curva);
}

.lateral-enter-from,
.lateral-leave-to {
  transform: translateX(100%);
}

@media (max-width: 900px) {
  .tablero {
    grid-template-columns: repeat(4, minmax(15rem, 80vw));
    scroll-snap-type: x mandatory;
  }

  .columna {
    scroll-snap-align: start;
  }

  .calendario {
    grid-template-columns: minmax(0, 1fr);
  }

  .calendario__celda {
    min-height: 3.5rem;
  }

  .calendario__evento {
    font-size: 0;
    height: 6px;
    padding: 0;
  }
}

@media (max-width: 640px) {
  .crm__herramientas {
    width: 100%;
  }

  .crm__herramientas .entrada {
    flex: 1 1 100%;
  }

  .kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .crm__cargando {
    grid-template-columns: 1fr;
  }

  .detalle-oferta {
    width: 100vw;
    padding: var(--e-4);
  }

  .detalle-oferta__acciones .boton {
    flex: 1 1 auto;
  }

  .visor-proforma {
    padding: 0;
  }

  .visor-proforma__caja {
    width: 100%;
    height: 100%;
    border-radius: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .lateral-enter-active,
  .lateral-leave-active {
    transition: none;
  }
}
</style>
