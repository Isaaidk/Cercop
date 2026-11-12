<script setup>
/**
 * Constructor interactivo de alertas.
 *
 * Tres ideas lo gobiernan:
 *
 * 1. **Ver antes de guardar.** Mientras se arma la alerta, una vista previa dice cuántos procesos
 *    vigentes la cumplirían hoy y enseña los mejores. Usa la misma regla que el worker
 *    (`POST /v1/alertas/vista-previa`), así que lo que se ve es lo que después llega como aviso.
 * 2. **Escribir lo menos posible.** Las palabras y los CPC son «chips» (Enter o coma para agregar),
 *    y las sugerencias salen del perfil de la empresa y de los CPC que ya vigila: un clic y entran.
 * 3. **Decir el resultado en una frase.** Arriba de la vista previa, la alerta se cuenta en lenguaje
 *    natural («Te avisaremos… cuando aparezca un proceso sobre…»). Es lo que el usuario necesita
 *    leer para saber si la alerta es la que quería; los campos son solo la manera de llegar ahí.
 *
 * Sobre el botón «Crear alerta»: no se deshabilita por faltar el nombre ni porque la palabra siga
 * escrita sin confirmar con Enter. Antes pasaba las dos cosas y el botón quedaba gris sin decir
 * por qué, que es exactamente «no funciona crear la alerta». Ahora el envío confirma lo escrito,
 * propone el nombre si falta y, si aun así algo no cuadra, lo dice con una frase.
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { perfilComercial, resumirAlerta } from '@/utils/oportunidades'
import { PROVINCIAS, nombreDeProvincia } from '@/utils/provincias'

const props = defineProps({
  /** Alerta de la que partir (para «duplicar y ajustar»). */
  semilla: { type: Object, default: null },
})
const emit = defineEmits(['creada', 'cancelar'])

const FRECUENCIAS = [
  { id: 'inmediata', titulo: 'Al instante', detalle: 'Cada pocos minutos' },
  { id: 'diaria', titulo: 'Diaria', detalle: 'Un resumen al día' },
  { id: 'semanal', titulo: 'Semanal', detalle: 'Un resumen a la semana' },
]

const RANGOS = [
  { etiqueta: 'Cualquiera', min: '', max: '' },
  { etiqueta: 'Hasta $7.000 (ínfima)', min: '', max: 7000 },
  { etiqueta: '$7.000 – $70.000', min: 7000, max: 70000 },
  { etiqueta: 'Más de $70.000', min: 70000, max: '' },
]

// El backend acepta hasta 80 caracteres; pasarse devolvía un 422 que el usuario no entendía.
const LARGO_NOMBRE = 80

const alerta = reactive({
  nombre: '',
  palabras: [],
  cpc: [],
  provincia: '',
  canton: '',
  presupuesto_min: '',
  presupuesto_max: '',
  frecuencia: 'diaria',
})
const borradorPalabra = ref('')
const borradorCpc = ref('')
const nombreTocado = ref(false)

const sugerencias = reactive({ palabras: [], cpc: [], provincias: [] })
const vista = reactive({ cargando: false, datos: null, error: '' })
const guardando = ref(false)
const error = ref('')

// ------------------------------------------------------------------------------- chips

function agregar(lista, texto) {
  for (const parte of String(texto || '').split(',')) {
    const limpio = parte.trim()
    if (limpio.length >= 2 && !lista.some((x) => x.toLowerCase() === limpio.toLowerCase())) {
      lista.push(limpio)
    }
  }
}

function alTeclear(evento, lista, borrador) {
  if (evento.key === 'Enter' || evento.key === ',') {
    evento.preventDefault()
    agregar(lista, borrador.value)
    borrador.value = ''
  } else if (evento.key === 'Backspace' && !borrador.value && lista.length) {
    lista.pop()
  }
}

function confirmarBorrador(lista, borrador) {
  if (borrador.value.trim()) {
    agregar(lista, borrador.value)
    borrador.value = ''
  }
}

function quitarDe(lista, valor) {
  const i = lista.indexOf(valor)
  if (i >= 0) lista.splice(i, 1)
}

const palabrasSugeridas = computed(() =>
  sugerencias.palabras
    .filter((p) => !alerta.palabras.some((x) => x.toLowerCase() === p.toLowerCase()))
    .slice(0, 8),
)
const cpcSugeridos = computed(() => sugerencias.cpc.filter((c) => !alerta.cpc.includes(c)).slice(0, 8))

// ------------------------------------------------------------------------------- lugar y rango

// Un cantón sin provincia no significa nada para el filtro: se borra con ella para no enviar un
// criterio oculto (el campo queda deshabilitado y el usuario ya no lo ve).
watch(
  () => alerta.provincia,
  (valor) => {
    if (!valor) alerta.canton = ''
  },
)

const rangoActivo = computed(() =>
  RANGOS.findIndex(
    (r) => String(r.min) === String(alerta.presupuesto_min) && String(r.max) === String(alerta.presupuesto_max),
  ),
)

function elegirRango(rango) {
  alerta.presupuesto_min = rango.min
  alerta.presupuesto_max = rango.max
}

// ------------------------------------------------------------------------------- nombre

const nombreSugerido = computed(() => {
  const que = alerta.palabras[0] || (alerta.cpc[0] ? `CPC ${alerta.cpc[0]}` : '')
  if (!que) return ''
  const donde = alerta.canton.trim() || (alerta.provincia ? nombreDeProvincia(alerta.provincia) : '')
  return (donde ? `${que} en ${donde}` : que).slice(0, LARGO_NOMBRE)
})

watch(nombreSugerido, (valor) => {
  if (!nombreTocado.value) alerta.nombre = valor
})

// ------------------------------------------------------------------------------- vista previa

const tieneInteres = computed(() => alerta.palabras.length > 0 || alerta.cpc.length > 0)
const hayBorrador = computed(() => Boolean(borradorPalabra.value.trim() || borradorCpc.value.trim()))

const cuerpo = computed(() => ({
  palabras: [...alerta.palabras],
  cpc: [...alerta.cpc],
  provincia: alerta.provincia,
  canton: alerta.canton.trim(),
  presupuesto_min: alerta.presupuesto_min === '' ? null : Number(alerta.presupuesto_min),
  presupuesto_max: alerta.presupuesto_max === '' ? null : Number(alerta.presupuesto_max),
}))

const resumen = computed(() => resumirAlerta({ ...cuerpo.value, frecuencia: alerta.frecuencia }))

let temporizador = null
let turno = 0

watch(
  cuerpo,
  () => {
    clearTimeout(temporizador)
    if (!tieneInteres.value) {
      turno += 1
      vista.datos = null
      vista.error = ''
      vista.cargando = false
      return
    }
    temporizador = setTimeout(previsualizar, 600)
  },
  { deep: true },
)

async function previsualizar() {
  const mio = ++turno
  vista.cargando = true
  vista.error = ''
  try {
    const datos = await api.previsualizarAlerta(cuerpo.value)
    if (mio === turno) vista.datos = datos
  } catch (fallo) {
    if (mio === turno) vista.error = `No se pudo calcular la vista previa: ${fallo.message}`
  } finally {
    if (mio === turno) vista.cargando = false
  }
}

const termometro = computed(() => {
  if (!vista.datos) return ''
  const total = vista.datos.total ?? 0
  if (total === 0) return 'Hoy nada la cumple. Puedes crearla igual o probar con más palabras.'
  if (total > 60) return 'Es muy amplia: recibirás muchos avisos. Acota la provincia o el presupuesto.'
  return 'Buen equilibrio: avisos relevantes sin saturarte.'
})

function dinero(valor) {
  if (valor == null) return ''
  return new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(
    valor,
  )
}

// ------------------------------------------------------------------------------- guardar

// Se puede pulsar en cuanto hay algo que buscar, aunque esté aún escrito sin confirmar.
const puedeGuardar = computed(() => (tieneInteres.value || hayBorrador.value) && !guardando.value)

function validar() {
  if (!tieneInteres.value) return 'Agrega al menos una palabra o un código CPC.'
  if (alerta.nombre.trim().length < 2) return 'Ponle un nombre a la alerta (dos letras como mínimo).'
  const { presupuesto_min: min, presupuesto_max: max } = cuerpo.value
  if (min != null && max != null && min > max) return 'El presupuesto «desde» es mayor que el «hasta».'
  return ''
}

async function guardar() {
  if (guardando.value) return
  confirmarBorrador(alerta.palabras, borradorPalabra)
  confirmarBorrador(alerta.cpc, borradorCpc)
  // El `watch` del nombre corre después de este turno; aquí se calcula a mano para no enviar vacío.
  if (alerta.nombre.trim().length < 2) {
    alerta.nombre = nombreSugerido.value
    nombreTocado.value = false
  }
  error.value = validar()
  if (error.value) return

  guardando.value = true
  try {
    const nombre = alerta.nombre.trim().slice(0, LARGO_NOMBRE)
    await api.crearAlerta({ ...cuerpo.value, nombre, frecuencia: alerta.frecuencia })
    emit('creada', nombre)
  } catch (fallo) {
    error.value = `No se pudo crear la alerta: ${fallo.message}`
  } finally {
    guardando.value = false
  }
}

// ------------------------------------------------------------------------------- arranque

async function cargarSugerencias() {
  const [perfil, vigilados] = await Promise.allSettled([api.verPerfil(), api.listarCpc()])
  const leido = perfilComercial(
    perfil.status === 'fulfilled' ? perfil.value : null,
    vigilados.status === 'fulfilled' ? vigilados.value?.claves : null,
  )
  sugerencias.palabras = [...leido.palabras, ...leido.productos]
  sugerencias.cpc = leido.cpc
  sugerencias.provincias = leido.provincias
}

function sembrar(semilla) {
  if (!semilla) return
  alerta.palabras = [...(semilla.palabras || [])]
  alerta.cpc = [...(semilla.cpc || [])]
  alerta.provincia = semilla.provincia || ''
  alerta.canton = semilla.canton || ''
  alerta.presupuesto_min = semilla.presupuesto_min ?? ''
  alerta.presupuesto_max = semilla.presupuesto_max ?? ''
  alerta.frecuencia = semilla.frecuencia || 'diaria'
  alerta.nombre = semilla.nombre ? `${semilla.nombre} (copia)`.slice(0, LARGO_NOMBRE) : ''
  nombreTocado.value = Boolean(semilla.nombre)
}

onMounted(() => {
  sembrar(props.semilla)
  cargarSugerencias()
})
onBeforeUnmount(() => clearTimeout(temporizador))
</script>

<template>
  <form class="constructor" novalidate @submit.prevent="guardar">
    <div class="constructor__campos">
      <!-- Qué -->
      <section class="bloque" aria-labelledby="alerta-que">
        <h4 id="alerta-que">¿Qué buscas?</h4>
        <p class="bloque__ayuda">Palabras del objeto de compra o códigos CPC. Basta con que coincida uno.</p>

        <label class="campo">
          <span class="campo__etiqueta">Palabras clave</span>
          <span class="chips">
            <span v-for="palabra in alerta.palabras" :key="palabra" class="chip">
              {{ palabra }}
              <button
                type="button"
                class="chip__quitar"
                :aria-label="`Quitar ${palabra}`"
                @click="quitarDe(alerta.palabras, palabra)"
              >
                ×
              </button>
            </span>
            <input
              v-model="borradorPalabra"
              class="chips__entrada"
              :placeholder="alerta.palabras.length ? 'Otra…' : 'Ej. mantenimiento, aire acondicionado'"
              @keydown="alTeclear($event, alerta.palabras, borradorPalabra)"
              @blur="confirmarBorrador(alerta.palabras, borradorPalabra)"
            />
          </span>
        </label>
        <div v-if="palabrasSugeridas.length" class="sugeridas">
          <span class="sugeridas__titulo">De tu perfil:</span>
          <button
            v-for="palabra in palabrasSugeridas"
            :key="palabra"
            type="button"
            class="sugerida"
            @click="agregar(alerta.palabras, palabra)"
          >
            + {{ palabra }}
          </button>
        </div>

        <label class="campo">
          <span class="campo__etiqueta">Códigos CPC</span>
          <span class="chips">
            <span v-for="codigo in alerta.cpc" :key="codigo" class="chip numeros">
              {{ codigo }}
              <button
                type="button"
                class="chip__quitar"
                :aria-label="`Quitar ${codigo}`"
                @click="quitarDe(alerta.cpc, codigo)"
              >
                ×
              </button>
            </span>
            <input
              v-model="borradorCpc"
              class="chips__entrada numeros"
              inputmode="numeric"
              :placeholder="alerta.cpc.length ? 'Otro…' : 'Ej. 87150 (sirve el inicio del código)'"
              @keydown="alTeclear($event, alerta.cpc, borradorCpc)"
              @blur="confirmarBorrador(alerta.cpc, borradorCpc)"
            />
          </span>
        </label>
        <div v-if="cpcSugeridos.length" class="sugeridas">
          <span class="sugeridas__titulo">De tu perfil:</span>
          <button
            v-for="codigo in cpcSugeridos"
            :key="codigo"
            type="button"
            class="sugerida numeros"
            @click="agregar(alerta.cpc, codigo)"
          >
            + {{ codigo }}
          </button>
        </div>
      </section>

      <!-- Dónde y cuánto -->
      <section class="bloque" aria-labelledby="alerta-donde">
        <h4 id="alerta-donde">¿Dónde y de cuánto? <span class="bloque__opcional">Opcional</span></h4>
        <div class="bloque__rejilla">
          <label class="campo">
            <span class="campo__etiqueta">Provincia</span>
            <select v-model="alerta.provincia" class="seleccion">
              <option value="">Todo el país</option>
              <optgroup v-if="sugerencias.provincias.length" label="Tu cobertura">
                <option v-for="codigo in sugerencias.provincias" :key="`c-${codigo}`" :value="codigo">
                  {{ nombreDeProvincia(codigo) }}
                </option>
              </optgroup>
              <optgroup label="Todas">
                <option v-for="p in PROVINCIAS" :key="p.codigo" :value="p.codigo">{{ p.nombre }}</option>
              </optgroup>
            </select>
          </label>
          <label class="campo">
            <span class="campo__etiqueta">Cantón</span>
            <input
              v-model="alerta.canton"
              class="entrada"
              :placeholder="alerta.provincia ? 'Cualquiera' : 'Elige antes la provincia'"
              :disabled="!alerta.provincia"
            />
          </label>
        </div>
        <div class="campo">
          <span class="campo__etiqueta" id="alerta-presupuesto">Presupuesto</span>
          <div class="segmentos" role="radiogroup" aria-labelledby="alerta-presupuesto">
            <button
              v-for="(rango, n) in RANGOS"
              :key="rango.etiqueta"
              type="button"
              role="radio"
              class="segmento"
              :class="{ 'segmento--activo': rangoActivo === n }"
              :aria-checked="rangoActivo === n"
              @click="elegirRango(rango)"
            >
              {{ rango.etiqueta }}
            </button>
          </div>
        </div>
        <details class="bloque__mas" :open="rangoActivo === -1">
          <summary>Poner un rango exacto</summary>
          <div class="bloque__rejilla">
            <label class="campo">
              <span class="campo__etiqueta">Desde (USD)</span>
              <input v-model="alerta.presupuesto_min" class="entrada numeros" type="number" min="0" placeholder="0" />
            </label>
            <label class="campo">
              <span class="campo__etiqueta">Hasta (USD)</span>
              <input
                v-model="alerta.presupuesto_max"
                class="entrada numeros"
                type="number"
                min="0"
                placeholder="Sin tope"
              />
            </label>
          </div>
        </details>
      </section>

      <!-- Cuándo -->
      <section class="bloque" aria-labelledby="alerta-cuando">
        <h4 id="alerta-cuando">¿Cada cuánto te avisamos?</h4>
        <p class="bloque__ayuda">El aviso llega a «Avisos», en esta misma pantalla.</p>
        <div class="segmentos" role="radiogroup" aria-labelledby="alerta-cuando">
          <button
            v-for="opcion in FRECUENCIAS"
            :key="opcion.id"
            type="button"
            role="radio"
            class="segmento segmento--doble"
            :class="{ 'segmento--activo': alerta.frecuencia === opcion.id }"
            :aria-checked="alerta.frecuencia === opcion.id"
            @click="alerta.frecuencia = opcion.id"
          >
            <strong>{{ opcion.titulo }}</strong>
            <small>{{ opcion.detalle }}</small>
          </button>
        </div>
        <label class="campo">
          <span class="campo__etiqueta">Nombre de la alerta</span>
          <input
            v-model="alerta.nombre"
            class="entrada"
            :maxlength="LARGO_NOMBRE"
            placeholder="Se propone solo a partir de lo que buscas"
            @input="nombreTocado = true"
          />
        </label>
      </section>
    </div>

    <!-- Resultado: la frase, la cifra de hoy y el botón -->
    <aside class="previa" aria-live="polite">
      <p class="previa__titulo">Así quedará tu alerta</p>

      <p v-if="resumen" class="previa__frase">{{ resumen }}</p>
      <p v-else class="previa__vacio">
        Escribe al menos una palabra o un CPC y aquí verás, en una frase, cuándo te avisaremos y cuántos
        procesos vigentes la cumplen hoy.
      </p>

      <template v-if="tieneInteres">
        <div class="previa__cifra" :class="{ 'previa__cifra--cargando': vista.cargando }">
          <strong class="numeros">{{ vista.datos ? vista.datos.total + (vista.datos.tope ? '+' : '') : '…' }}</strong>
          <span>procesos vigentes la cumplen hoy</span>
        </div>
        <p v-if="vista.datos?.por_fuente" class="previa__nota">
          <span v-if="vista.datos.por_fuente.NCO">{{ vista.datos.por_fuente.NCO }} ínfimas cuantías</span>
          <span v-if="vista.datos.por_fuente.NCO && vista.datos.por_fuente.OCDS"> · </span>
          <span v-if="vista.datos.por_fuente.OCDS">{{ vista.datos.por_fuente.OCDS }} otros procesos</span>
        </p>
        <p v-if="termometro" class="previa__nota">{{ termometro }}</p>
        <p v-if="vista.error" class="previa__nota">{{ vista.error }}</p>
        <ul v-if="vista.datos?.muestras?.length" class="previa__lista" aria-label="Ejemplos de hoy">
          <li v-for="fila in vista.datos.muestras" :key="fila.id" class="previa__fila">
            <strong>{{ fila.objeto || fila.codigo }}</strong>
            <small>{{ [fila.entidad, fila.provincia, dinero(fila.presupuesto)].filter(Boolean).join(' · ') }}</small>
          </li>
        </ul>
      </template>

      <p v-if="error" class="previa__error" role="alert">{{ error }}</p>
      <div class="previa__acciones">
        <button type="button" class="boton boton--fantasma" @click="emit('cancelar')">Cancelar</button>
        <button type="submit" class="boton boton--principal" :disabled="!puedeGuardar">
          {{ guardando ? 'Creando…' : 'Crear alerta' }}
        </button>
      </div>
    </aside>
  </form>
</template>

<style scoped>
.constructor {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(16rem, 1fr);
  gap: var(--e-6);
  align-items: start;
}

.constructor__campos {
  display: flex;
  flex-direction: column;
  gap: var(--e-6);
}

/* Sin cajas por bloque: se separan con espacio, que es lo que pide la guía para no agobiar. */
.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.bloque h4 {
  display: flex;
  align-items: baseline;
  gap: var(--e-2);
  font-size: var(--t-md);
  font-weight: 650;
}

.bloque__opcional {
  font-size: var(--t-xs);
  font-weight: 500;
  color: var(--texto-tenue);
}

.bloque__ayuda {
  margin-top: calc(var(--e-2) * -1);
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.bloque__rejilla {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-3);
}

.bloque__mas summary {
  cursor: pointer;
  font-size: var(--t-xs);
  color: var(--acento-fuerte);
  font-weight: 600;
  margin-bottom: var(--e-2);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1);
  min-height: 2.5rem;
  padding: 4px 8px;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  background: var(--superficie);
  cursor: text;
  transition:
    border-color var(--rapido),
    box-shadow var(--rapido);
}

.chips:focus-within {
  border-color: var(--acento);
  box-shadow: 0 0 0 3px var(--acento-suave);
}

/* Sin la caja de los campos globales: el borde lo pone el contenedor de chips. */
.chips__entrada {
  flex: 1;
  min-width: 8rem;
  min-height: 0;
  padding: 4px;
  border: 0;
  outline: 0;
  background: transparent;
  box-shadow: none;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 4px 2px 10px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto);
  font-size: var(--t-sm);
  font-weight: 550;
}

.chip__quitar {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--texto-suave);
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
}

.chip__quitar:hover {
  background: var(--borde);
  color: var(--texto);
}

.sugeridas {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1);
  margin-top: calc(var(--e-2) * -1);
}

.sugeridas__titulo {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.sugerida {
  padding: 2px 10px;
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  background: transparent;
  color: var(--texto-suave);
  font-size: var(--t-xs);
  cursor: pointer;
  transition:
    border-color var(--rapido),
    color var(--rapido);
}

.sugerida:hover {
  border-color: var(--acento);
  color: var(--acento-fuerte);
}

.segmentos {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.segmento {
  padding: 6px 12px;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-redondo);
  background: var(--superficie);
  color: var(--texto-suave);
  font-size: var(--t-sm);
  cursor: pointer;
  transition:
    border-color var(--rapido),
    color var(--rapido),
    background-color var(--rapido);
}

.segmento:hover {
  border-color: var(--acento);
  color: var(--texto);
}

.segmento--doble {
  flex: 1 1 8rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  text-align: left;
}

.segmento--doble strong {
  color: var(--texto);
  font-weight: 600;
}

.segmento--doble small {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.segmento--activo {
  border-color: var(--acento);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  box-shadow: inset 0 0 0 1px var(--acento);
}

.previa {
  position: sticky;
  top: var(--e-4);
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-5);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie-2);
}

.previa__titulo {
  font-size: var(--t-xs);
  font-weight: 650;
  color: var(--texto-tenue);
}

.previa__frase {
  font-size: var(--t-md);
  font-weight: 550;
  line-height: 1.5;
  color: var(--texto);
}

.previa__vacio {
  font-size: var(--t-sm);
  color: var(--texto-suave);
  line-height: 1.5;
}

.previa__cifra {
  display: flex;
  align-items: baseline;
  gap: var(--e-2);
  transition: opacity var(--rapido);
}

.previa__cifra strong {
  font-size: var(--t-2xl);
  line-height: 1;
  color: var(--texto);
}

.previa__cifra span,
.previa__nota {
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.previa__cifra--cargando {
  opacity: 0.5;
}

.previa__lista {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  margin: 0;
  padding: var(--e-3) 0 0;
  list-style: none;
  border-top: 1px solid var(--borde);
}

.previa__fila {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.previa__fila strong {
  font-size: var(--t-sm);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.previa__fila small {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.previa__error {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.previa__acciones {
  display: flex;
  justify-content: flex-end;
  gap: var(--e-2);
  flex-wrap: wrap;
}

@media (max-width: 900px) {
  .constructor {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--e-5);
  }

  .previa {
    position: static;
  }
}

@media (max-width: 640px) {
  .bloque__rejilla {
    grid-template-columns: 1fr;
  }

  .previa {
    padding: var(--e-4);
  }

  .previa__acciones .boton {
    flex: 1;
  }
}
</style>
