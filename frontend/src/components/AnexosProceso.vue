<script setup>
/**
 * «Anexos para tu proforma» de un proceso con oferta (OCDS), dentro del cajón de detalle.
 *
 * Lo pidió el cliente: TDR, pliego y **solo la última acta**, y el monto del proceso a la vista. La
 * elección la hace el servidor (`dominio/anexos.elegir_anexos`), aquí solo se pinta.
 *
 * Lo normal hoy es que no haya archivos: los datos abiertos del SERCOP no los publican (comprobado
 * contra la fuente, ver `backend/.../fuentes/ocds_proceso.py`). Por eso el estado vacío no es un
 * hueco: dice por qué, da el código del proceso para copiarlo y el buscador del portal donde sí
 * están. El monto y las preguntas y respuestas sí vienen, y se enseñan igual.
 *
 * Se pide al abrir el cajón y no con la tabla: cuesta una petición a un servicio ajeno.
 */
import { computed, onMounted, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { decimal, fechaCorta } from '@/utils/formato'
import { copiarAlPortapapeles } from '@/utils/portapapeles'

const props = defineProps({
  registroId: { type: String, required: true },
  /** Si quien abre el cajón sabe preparar una oferta: sin eso no se pinta un botón que no hace nada. */
  puedePreparar: { type: Boolean, default: false },
})

const emit = defineEmits(['preparar'])

const cargando = ref(false)
const error = ref('')
const respuesta = ref(null)
const copiado = ref(false)

const anexos = computed(() => respuesta.value?.anexos || [])
const presupuesto = computed(() => respuesta.value?.presupuesto || null)
const adjudicado = computed(() => respuesta.value?.adjudicado || null)
const aclaraciones = computed(() => respuesta.value?.aclaraciones || [])

async function cargar() {
  cargando.value = true
  error.value = ''
  try {
    respuesta.value = await api.anexosDeProceso(props.registroId)
  } catch (fallo) {
    respuesta.value = null
    error.value = fallo?.message || 'No se pudieron traer los anexos de este proceso.'
  } finally {
    cargando.value = false
  }
}

function dinero(monto, moneda) {
  if (monto === null || monto === undefined) return ''
  return `${moneda && moneda !== 'USD' ? `${moneda} ` : '$ '}${decimal(monto)}`
}

/** El formato que declare la fuente, en corto: «application/pdf» → «PDF». */
function formatoDe(anexo) {
  const formato = String(anexo.formato || '').split('/').pop()
  return formato ? formato.toUpperCase().slice(0, 6) : ''
}

async function copiarCodigo() {
  const codigo = respuesta.value?.codigo
  if (!codigo) return
  copiado.value = await copiarAlPortapapeles(codigo)
  setTimeout(() => (copiado.value = false), 2000)
}

onMounted(cargar)
watch(() => props.registroId, cargar)
</script>

<template>
  <section class="anexos" aria-labelledby="titulo-anexos">
    <div class="anexos__cabecera">
      <h3 id="titulo-anexos" class="anexos__titulo">Anexos para tu proforma</h3>
      <button
        v-if="puedePreparar"
        type="button"
        class="boton boton--principal boton--pequeno"
        @click="emit('preparar')"
      >
        Preparar oferta
      </button>
    </div>
    <p class="anexos__ayuda">TDR, pliego y solo el acta más reciente, con el monto del proceso.</p>

    <p v-if="cargando" class="anexos__estado" role="status">Consultando el proceso en los datos abiertos…</p>

    <div v-else-if="error" class="anexos__estado" role="alert">
      <p>{{ error }}</p>
      <button type="button" class="boton boton--secundario boton--pequeno" @click="cargar()">
        Reintentar
      </button>
    </div>

    <template v-else-if="respuesta">
      <div v-if="presupuesto" class="monto">
        <p class="monto__etiqueta">{{ presupuesto.etiqueta_fuente || 'Monto del proceso' }}</p>
        <p class="monto__valor numeros">{{ dinero(presupuesto.monto, presupuesto.moneda) }}</p>
        <p v-if="adjudicado" class="monto__nota">
          Adjudicado: <span class="numeros">{{ dinero(adjudicado.monto, adjudicado.moneda) }}</span>
        </p>
      </div>
      <p v-else class="anexos__estado">La fuente no publica el monto de este proceso.</p>

      <ul v-if="anexos.length" class="lista">
        <li v-for="anexo in anexos" :key="anexo.enlace" class="lista__item">
          <div class="lista__texto">
            <span class="etiqueta">{{ anexo.etiqueta_tipo }}</span>
            <p class="lista__nombre">{{ anexo.nombre }}</p>
            <p class="lista__detalle">
              <span v-if="anexo.fecha">Publicado el {{ fechaCorta(anexo.fecha) }}</span>
              <span v-if="formatoDe(anexo)"> · {{ formatoDe(anexo) }}</span>
            </p>
          </div>
          <a
            class="boton boton--secundario boton--pequeno"
            :href="anexo.enlace"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="`Abrir ${anexo.nombre}`"
          >
            Abrir
          </a>
        </li>
      </ul>

      <div v-else class="vacio">
        <p>{{ respuesta.aviso || 'Este proceso no publica anexos.' }}</p>
        <div class="vacio__acciones">
          <button
            v-if="respuesta.codigo"
            type="button"
            class="boton boton--fantasma boton--pequeno numeros"
            @click="copiarCodigo()"
          >
            {{ copiado ? 'Código copiado' : `Copiar ${respuesta.codigo}` }}
          </button>
          <a
            v-if="respuesta.buscador_portal"
            class="boton boton--secundario boton--pequeno"
            :href="respuesta.buscador_portal"
            target="_blank"
            rel="noopener noreferrer"
          >
            <span aria-hidden="true">↗</span>
            Buscar en el portal
          </a>
        </div>
      </div>

      <details v-if="aclaraciones.length" class="aclaraciones">
        <summary>
          Preguntas y aclaraciones
          <span class="numeros">({{ aclaraciones.length }})</span>
        </summary>
        <ol class="aclaraciones__lista">
          <li v-for="(aclaracion, indice) in aclaraciones" :key="indice" class="aclaraciones__item">
            <p class="lista__detalle">
              {{ fechaCorta(aclaracion.fecha_respuesta || aclaracion.fecha) }}
            </p>
            <p><strong>Pregunta:</strong> {{ aclaracion.pregunta }}</p>
            <p v-if="aclaracion.respuesta"><strong>Respuesta:</strong> {{ aclaracion.respuesta }}</p>
          </li>
        </ol>
      </details>
    </template>
  </section>
</template>

<style scoped>
.anexos {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
}

.anexos__cabecera {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-2);
}

.anexos__titulo {
  font-size: var(--t-base);
  font-weight: 700;
}

.anexos__ayuda,
.anexos__estado,
.lista__detalle {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.anexos__estado {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.monto__etiqueta {
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-tenue);
}

.monto__valor {
  font-size: var(--t-xl);
  font-weight: 700;
}

.monto__nota {
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.lista,
.aclaraciones__lista {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.lista__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-2) 0;
}

.lista__item + .lista__item {
  border-top: 1px solid var(--borde);
}

.lista__texto {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
}

.lista__nombre {
  font-size: var(--t-sm);
  overflow-wrap: anywhere;
}

.vacio {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.vacio__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.aclaraciones summary {
  cursor: pointer;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--texto-suave);
}

.aclaraciones__lista {
  margin-top: var(--e-2);
}

.aclaraciones__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--t-sm);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

@media (width <= 640px) {
  .lista__item {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
