<script setup>
/**
 * Lectura pública de un texto legal: `/terminos` y `/privacidad`.
 *
 * Por qué existe
 * --------------
 * La Ley Orgánica de Protección de Datos Personales pide informar del tratamiento **en el momento de
 * recoger los datos** (art. 12), y la Ley de Comercio Electrónico pide que quien contrata por medios
 * electrónicos pueda conocer y conservar lo que acepta (arts. 48 a 50). Las dos cosas exigen que el
 * texto se pueda leer sin cuenta, antes de registrarse, y en cualquier momento después.
 *
 * El texto no está escrito aquí
 * -----------------------------
 * Se pide al servidor, igual que en la pantalla de aceptación, y por la misma razón: el texto que se
 * lee tiene que ser **el mismo** que se acepta, con su versión y su huella. Si viviera también en
 * este archivo, el día que uno cambiara la página pública diría una cosa y la aceptación guardaría
 * otra.
 *
 * El formato
 * ----------
 * Los textos se publican sin marcas de formato (ver la migración `0022`): títulos numerados en
 * mayúsculas, párrafos separados por una línea en blanco y listas con guiones. Aquí se reconoce esa
 * estructura para pintar títulos de verdad —que un lector de pantalla puede recorrer— sin
 * transformar ni una palabra del texto.
 */
import { computed, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import CabeceraPublica from '@/components/CabeceraPublica.vue'
import PiePublico from '@/components/PiePublico.vue'

const props = defineProps({
  /** `terminos_uso` o `tratamiento_datos`: los dos que el servidor publica sin cuenta. */
  tipo: { type: String, required: true },
  tema: { type: String, default: 'claro' },
})
const emit = defineEmits(['alternar-tema'])

const politica = ref(null)
const cargando = ref(true)
const error = ref('')

/** El otro texto, para enlazarlo al pie: quien lee uno casi siempre necesita el otro. */
const otro = computed(() =>
  props.tipo === 'terminos_uso'
    ? { href: '/privacidad', texto: 'Política de privacidad y tratamiento de datos personales' }
    : { href: '/terminos', texto: 'Términos y condiciones de uso' },
)

const vigenteDesde = computed(() => {
  if (!politica.value?.vigente_desde) return ''
  const fecha = new Date(politica.value.vigente_desde)
  if (Number.isNaN(fecha.getTime())) return ''
  return fecha.toLocaleDateString('es-EC', { day: 'numeric', month: 'long', year: 'numeric' })
})

/**
 * Bloques del texto: el título, los encabezados numerados y los párrafos.
 *
 * El primer bloque es la cabecera del documento —su título y la línea de versión—, que ya se pinta
 * arriba con los datos del servidor, así que no se repite. Un bloque de una sola línea que empieza
 * con un número y va en mayúsculas es un encabezado; todo lo demás se pinta tal cual, respetando los
 * saltos de línea de las listas.
 */
const ENCABEZADO = /^\d+\.\s+[^a-záéíóúñ]+$/

const bloques = computed(() => {
  const texto = politica.value?.texto || ''
  const partes = texto
    .replace(/\r\n?/g, '\n')
    .split(/\n\s*\n/)
    .map((parte) => parte.replace(/\s+$/g, ''))
    .filter((parte) => parte.trim())
  return partes.slice(1).map((parte, indice) => {
    const linea = parte.trim()
    const esEncabezado = !linea.includes('\n') && ENCABEZADO.test(linea)
    return { id: indice, tipo: esEncabezado ? 'encabezado' : 'parrafo', texto: esEncabezado ? linea : parte }
  })
})

async function cargar(tipo) {
  cargando.value = true
  error.value = ''
  politica.value = null
  try {
    politica.value = await api.textoPoliticaPublica(tipo)
  } catch (fallo) {
    error.value = fallo.esLimite
      ? 'Has pedido este texto demasiadas veces seguidas. Espera unos minutos y vuelve a intentarlo.'
      : fallo.message || 'No se pudo cargar el texto.'
  } finally {
    cargando.value = false
  }
}

watch(() => props.tipo, cargar, { immediate: true })

function imprimir() {
  window.print()
}
</script>

<template>
  <div class="politica">
    <CabeceraPublica :tema="tema" @alternar-tema="emit('alternar-tema')" />

    <main class="politica__cuerpo">
      <div v-if="cargando" class="politica__cargando" aria-live="polite">
        <span class="esqueleto esqueleto--titulo" />
        <span class="esqueleto esqueleto--linea" />
        <span class="esqueleto esqueleto--linea corta" />
      </div>

      <div v-else-if="error" class="aviso-error" role="alert">
        <strong>No se pudo mostrar el texto</strong>
        <span>{{ error }}</span>
        <button type="button" class="boton boton--fantasma" @click="cargar(tipo)">Reintentar</button>
      </div>

      <article v-else-if="politica" class="politica__documento aparece">
        <header class="politica__encabezado">
          <p class="politica__etiqueta">Documento legal</p>
          <h1>{{ politica.titulo }}</h1>
          <p class="politica__datos">
            Versión {{ politica.version }}
            <template v-if="vigenteDesde"> · vigente desde el {{ vigenteDesde }}</template>
          </p>
          <p class="politica__huella">
            Huella SHA-256 del texto:
            <span class="numeros">{{ politica.hash }}</span>
          </p>
          <div class="politica__acciones">
            <button type="button" class="boton boton--fantasma" @click="imprimir">
              Imprimir o guardar en PDF
            </button>
            <a class="enlace" :href="otro.href">{{ otro.texto }}</a>
          </div>
        </header>

        <template v-for="bloque in bloques" :key="bloque.id">
          <h2 v-if="bloque.tipo === 'encabezado'" class="politica__seccion">{{ bloque.texto }}</h2>
          <p v-else class="politica__parrafo">{{ bloque.texto }}</p>
        </template>
      </article>
    </main>

    <PiePublico />
  </div>
</template>

<style scoped>
.politica {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.politica__cuerpo {
  flex: 1;
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  padding: var(--e-7) var(--e-6);
}

.politica__cargando {
  display: grid;
  gap: var(--e-3);
}

.aviso-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--e-2);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
}

.enlace {
  color: var(--acento);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.enlace:hover {
  color: var(--acento-fuerte);
}

.politica__encabezado {
  padding-bottom: var(--e-5);
  margin-bottom: var(--e-5);
  border-bottom: 1px solid var(--borde);
}

.politica__etiqueta {
  margin: 0;
  color: var(--acento);
  font-weight: 600;
  font-size: var(--t-sm);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.politica h1 {
  margin: var(--e-2) 0 0;
  font-size: var(--t-2xl);
  line-height: 1.25;
}

.politica__datos {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
}

.politica__huella {
  margin: var(--e-2) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-sm);
  overflow-wrap: anywhere;
}

.politica__acciones {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-4);
  margin-top: var(--e-4);
}

.politica__seccion {
  margin: var(--e-6) 0 var(--e-3);
  font-size: var(--t-lg);
  line-height: 1.35;
}

.politica__parrafo {
  margin: 0 0 var(--e-4);
  line-height: 1.7;
  /* Respeta los saltos de las listas con guiones y de los bloques de datos del responsable. */
  white-space: pre-line;
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .politica__cuerpo {
    padding: var(--e-6) var(--e-4);
  }
}

@media print {
  .politica__acciones {
    display: none;
  }

  .politica__cuerpo {
    max-width: none;
    padding: 0;
  }
}
</style>
