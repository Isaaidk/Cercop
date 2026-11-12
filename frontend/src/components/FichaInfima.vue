<script setup>
/**
 * Ficha completa de una ínfima cuantía: todo lo que hace falta para decidir y para empezar a
 * llenar el TDR, en un solo bloque.
 *
 * El orden de arriba abajo sigue la decisión de quien la mira:
 *
 * 1. **Barra de acciones** — lo que se hace con la ínfima: llenar el TDR y la proforma (principal),
 *    bajar el TDR, abrir en el portal y copiar el código. Siempre en el mismo sitio y orden.
 * 2. **Plazo** — cuánto queda, en una línea de tiempo de publicación a cierre: es lo que más pesa.
 * 3. **Qué piden y quién** — el objeto completo y los datos de la entidad y del contacto.
 * 4. **Ítems con CPC** — la tabla de la ficha, o «leyendo CPC…» si el worker aún no la leyó.
 * 5. **Documentos del TDR** y, plegado, el resto de datos crudos que publica la fuente.
 *
 * No cambia ninguna funcionalidad: usa las mismas acciones que antes estaban repartidas por la fila.
 *
 * Rediseño 2026-11: base neutra. El plazo ya no pinta un borde de color ni una barra roja o ámbar;
 * se dice con texto, una insignia pequeña y una barra gris de avance. Los bloques se separan con
 * espacio y un título corto, no con fondos de color.
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '@/api/endpoints'
import VisorTdr from '@/components/VisorTdr.vue'
import { itemsDe } from '@/utils/cpc'
import { fechaCorta, horaCorta, sinEtiquetas } from '@/utils/formato'
import { diasParaProforma, insigniaDePlazo, textoDePlazo } from '@/utils/plazo'
import { copiarAlPortapapeles } from '@/utils/portapapeles'
import { descargarTdr } from '@/utils/tdr'

// Fuera del componente: compartida por todas las fichas abiertas en la sesión.
const memoriaMercado = new Map()

const props = defineProps({
  fila: { type: Object, required: true },
})
const emit = defineEmits(['preparar', 'filtrar-provincia'])

const v = (clave) => {
  const crudo = props.fila[clave]
  return crudo === null || crudo === undefined ? '' : sinEtiquetas(String(crudo)).trim()
}

const items = computed(() => itemsDe(props.fila))
const tieneTdr = computed(() => Boolean(props.fila.documentos?.length))
const leyendoCpc = computed(() => props.fila.items_leidos === false && !items.value.length)

// ------------------------------------------------------------------------------- plazo

const dias = computed(() => diasParaProforma(props.fila.fecha_limite_proformas))
const insignia = computed(() => insigniaDePlazo(dias.value))

const linea = computed(() => {
  const inicio = Date.parse(props.fila.fecha_publicacion)
  const fin = Date.parse(props.fila.fecha_limite_proformas)
  if (Number.isNaN(inicio) || Number.isNaN(fin) || fin <= inicio) return null
  const avance = Math.min(1, Math.max(0, (Date.now() - inicio) / (fin - inicio)))
  return { avance: Math.round(avance * 100) }
})

const textoCierre = computed(() => {
  if (dias.value === null) return 'Sin fecha límite publicada'
  if (dias.value < 0) return 'El plazo de proformas ya cerró'
  if (dias.value === 0) return `Cierra hoy a las ${horaCorta(props.fila.fecha_limite_proformas)}`
  return `Quedan ${textoDePlazo(dias.value)} para enviar la proforma`
})

// ------------------------------------------------------------------------------- datos

const rucEntidad = computed(() => (v('codigo').match(/-(\d{13})-/) || [])[1] || '')

const ubicacion = computed(() =>
  [v('canton'), v('provincia').replace(/\s+-\s+.*$/, '')].filter(Boolean).join(', '),
)

const hechos = computed(() =>
  [
    { etiqueta: 'Entidad contratante', valor: v('entidad'), ancho: true },
    { etiqueta: 'RUC de la entidad', valor: rucEntidad.value, numeros: true },
    { etiqueta: 'Tipo de compra', valor: v('tipo_necesidad') },
    // El estado salió de las columnas de la tabla al simplificarla: aquí sigue a la vista.
    { etiqueta: 'Estado', valor: v('estado') },
    { etiqueta: 'Ubicación', valor: ubicacion.value, accion: 'provincia' },
    { etiqueta: 'Dirección de entrega', valor: v('direccion_entrega'), ancho: true },
    { etiqueta: 'Responsable', valor: v('funcionario') },
    { etiqueta: 'Contacto', valor: v('contacto') },
    { etiqueta: 'Correo', valor: v('email'), enlace: v('email') ? `mailto:${v('email')}` : '' },
    { etiqueta: 'Teléfono', valor: v('telefono'), enlace: v('telefono') ? `tel:${v('telefono').replace(/\s/g, '')}` : '' },
    { etiqueta: 'Publicada', valor: v('fecha_publicacion') ? `${fechaCorta(props.fila.fecha_publicacion)} · ${horaCorta(props.fila.fecha_publicacion)}` : '' },
    { etiqueta: 'Límite de proformas', valor: v('fecha_limite_proformas') ? `${fechaCorta(props.fila.fecha_limite_proformas)} · ${horaCorta(props.fila.fecha_limite_proformas)}` : '' },
  ].filter((h) => h.valor),
)

const MOSTRADOS = new Set([
  'id', 'datos', 'enlace', 'enlace_publico', 'items', 'cpc_codigos', 'documentos', 'items_leidos',
  'codigo', 'objeto_compra', 'entidad', 'tipo_necesidad', 'canton', 'provincia', 'direccion_entrega',
  'funcionario', 'contacto', 'email', 'telefono', 'fecha_publicacion', 'fecha_limite_proformas', 'estado',
])

/** Lo que la fuente publica y no está arriba: plegado, para quien quiera verlo todo. */
const resto = computed(() =>
  Object.entries(props.fila)
    .filter(([clave, valor]) => !MOSTRADOS.has(clave) && valor !== null && valor !== undefined && String(valor).trim() !== '')
    .filter(([, valor]) => typeof valor !== 'object')
    .map(([clave, valor]) => ({ clave: clave.replaceAll('_', ' '), valor: sinEtiquetas(String(valor)) })),
)

// ------------------------------------------------------------------------------- mercado del CPC

/**
 * Precio de referencia y competidores del CPC principal de la ínfima, con lo que ya se adjudicó.
 * Se pide al abrir la ficha y se recuerda por CPC durante la sesión: abrir diez fichas del mismo
 * CPC cuesta una consulta.
 */
const cpcPrincipal = computed(() => {
  const veces = new Map()
  for (const item of items.value) {
    const raiz = String(item.codigo || '').replace(/\D/g, '').slice(0, 5)
    if (raiz.length === 5) veces.set(raiz, (veces.get(raiz) || 0) + 1)
  }
  return [...veces.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || ''
})

const mercado = reactive({ cargando: false, precio: null, proveedores: [], motivo: '' })

async function cargarMercado() {
  const cpc = cpcPrincipal.value
  if (!cpc) return
  if (!memoriaMercado.has(cpc)) {
    memoriaMercado.set(
      cpc,
      Promise.all([api.preciosMercado({ cpc }), api.proveedoresMercado({ cpc })]).catch((fallo) => {
        memoriaMercado.delete(cpc)
        throw fallo
      }),
    )
  }
  mercado.cargando = true
  try {
    const [precios, proveedores] = await memoriaMercado.get(cpc)
    const grupo = (precios.grupos || []).find((g) => g.mismo_cpc) || precios.grupos?.[0]
    mercado.precio = grupo?.resumen || null
    mercado.proveedores = (proveedores.filas || []).slice(0, 5)
    mercado.motivo = precios.motivo || proveedores.motivo || ''
  } catch (fallo) {
    mercado.motivo = fallo.message
  } finally {
    mercado.cargando = false
  }
}

const usd = (valor) =>
  valor == null
    ? '—'
    : new Intl.NumberFormat('es-EC', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(valor)

onMounted(cargarMercado)

// ------------------------------------------------------------------------------- acciones

const bajando = ref(false)
const errorTdr = ref('')
const copiado = ref(false)

async function bajarTdr() {
  bajando.value = true
  errorTdr.value = ''
  try {
    await descargarTdr(String(props.fila.id))
  } catch (fallo) {
    errorTdr.value = fallo.message
  } finally {
    bajando.value = false
  }
}

async function copiarCodigo() {
  if (await copiarAlPortapapeles(v('codigo'))) {
    copiado.value = true
    setTimeout(() => (copiado.value = false), 1600)
  }
}
</script>

<template>
  <article class="ficha" :aria-label="`Ínfima ${v('codigo')}`">
    <!-- 1. Acciones -->
    <div class="ficha__acciones">
      <button type="button" class="boton boton--principal" :disabled="!v('codigo')" @click="emit('preparar', fila)">
        <span aria-hidden="true">✎</span>
        Llenar TDR y proforma
      </button>
      <button
        v-if="tieneTdr"
        type="button"
        class="boton boton--secundario"
        :disabled="bajando"
        title="Bajar el TDR, los pliegos y el acta más reciente del proceso"
        @click="bajarTdr"
      >
        <span aria-hidden="true">⤓</span>
        {{ bajando ? 'Preparando…' : 'Bajar TDR' }}
      </button>
      <a
        v-if="fila.enlace_publico"
        class="boton boton--secundario"
        :href="fila.enlace_publico"
        target="_blank"
        rel="noopener noreferrer"
      >
        <span aria-hidden="true">↗</span>
        Ver en el portal
      </a>
      <button v-if="v('codigo')" type="button" class="boton boton--fantasma" @click="copiarCodigo">
        <span aria-hidden="true">{{ copiado ? '✓' : '⧉' }}</span>
        {{ copiado ? 'Copiado' : 'Copiar código' }}
      </button>
    </div>
    <p v-if="errorTdr" class="ficha__error" role="alert">{{ errorTdr }}</p>

    <div class="ficha__cuerpo">
      <div class="ficha__principal">
        <!-- 2. Plazo -->
        <section class="plazo-linea" aria-label="Plazo de proformas">
          <div class="plazo-linea__texto">
            <strong>{{ textoCierre }}</strong>
            <span class="etiqueta" :class="insignia.clase">{{ insignia.texto }}</span>
          </div>
          <div v-if="linea" class="plazo-linea__barra" role="img" :aria-label="`Transcurrido el ${linea.avance}% del plazo`">
            <span class="plazo-linea__relleno" :style="{ width: `${linea.avance}%` }" />
          </div>
          <div v-if="linea" class="plazo-linea__extremos">
            <span>Publicada {{ fechaCorta(fila.fecha_publicacion) }}</span>
            <span>Cierra {{ fechaCorta(fila.fecha_limite_proformas) }}</span>
          </div>
        </section>

        <!-- 3. Qué y quién -->
        <section class="bloque-ficha">
          <h4 class="bloque-ficha__titulo">Objeto de compra</h4>
          <p class="ficha__objeto">{{ v('objeto_compra') || 'La fuente no publicó la descripción.' }}</p>
        </section>

        <!-- 4. Ítems -->
        <section class="bloque-ficha">
          <h4 class="bloque-ficha__titulo">
            Ítems y CPC
            <span v-if="items.length" class="bloque-ficha__cuenta">{{ items.length }}</span>
          </h4>
          <p v-if="leyendoCpc" class="ficha__leyendo">
            <span class="ficha__pulso" aria-hidden="true" />
            Leyendo los ítems y CPC de la ficha del portal. Aparecen en pocos minutos.
          </p>
          <p v-else-if="!items.length" class="ficha__nota">La ficha no publica detalle de ítems.</p>
          <div v-else class="items__marco">
            <table class="items">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">CPC</th>
                  <th scope="col">Descripción del producto</th>
                  <th scope="col">Unidad</th>
                  <th scope="col" class="items__num">Cantidad</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, indice) in items" :key="`${indice}-${item.codigo}`">
                  <td class="numeros">{{ item.numero ?? indice + 1 }}</td>
                  <td class="items__cpc">
                    <span class="codigo numeros">{{ item.codigo }}</span>
                    <span class="items__nombre">{{ item.descripcion_cpc }}</span>
                  </td>
                  <td>{{ item.descripcion }}</td>
                  <td>{{ item.unidad }}</td>
                  <td class="numeros items__num">{{ item.cantidad }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <!-- Mercado del CPC -->
        <section v-if="cpcPrincipal" class="bloque-ficha">
          <h4 class="bloque-ficha__titulo">
            Precio de referencia y competidores
            <span class="bloque-ficha__sub">CPC {{ cpcPrincipal }}</span>
          </h4>
          <p v-if="mercado.cargando" class="ficha__nota">Buscando lo que ya se adjudicó con este CPC…</p>
          <p v-else-if="!mercado.precio && !mercado.proveedores.length" class="ficha__nota">
            {{ mercado.motivo || 'Aún no hay adjudicaciones con este CPC para comparar.' }}
          </p>
          <div v-else class="mercado-cpc">
            <div v-if="mercado.precio" class="mercado-cpc__precios">
              <div class="mercado-cpc__cifra mercado-cpc__cifra--principal">
                <small>Mediana adjudicada</small>
                <strong class="numeros">{{ usd(mercado.precio.mediana) }}</strong>
              </div>
              <div class="mercado-cpc__cifra">
                <small>Rango</small>
                <strong class="numeros">{{ usd(mercado.precio.minimo) }} – {{ usd(mercado.precio.maximo) }}</strong>
              </div>
              <div class="mercado-cpc__cifra">
                <small>Procesos</small>
                <strong class="numeros">{{ mercado.precio.n }}</strong>
              </div>
            </div>
            <ol v-if="mercado.proveedores.length" class="mercado-cpc__rivales">
              <li v-for="rival in mercado.proveedores" :key="rival.nombre">
                <span>{{ rival.nombre }}</span>
                <small class="numeros">{{ rival.adjudicaciones || rival.procesos }} ganados · {{ usd(rival.monto) }}</small>
              </li>
            </ol>
            <p class="ficha__nota">
              Montos totales de procesos adjudicados con el mismo CPC, no precio por unidad: compáralos
              con la cantidad que piden aquí.
            </p>
          </div>
        </section>

        <!-- 5. Documentos -->
        <section v-if="tieneTdr" class="bloque-ficha">
          <h4 class="bloque-ficha__titulo">Documentos del proceso</h4>
          <VisorTdr :registro-id="String(fila.id)" :documentos="fila.documentos" />
        </section>
      </div>

      <aside class="ficha__lateral">
        <h4 class="bloque-ficha__titulo">Entidad y contacto</h4>
        <dl class="hechos">
          <div v-for="hecho in hechos" :key="hecho.etiqueta" class="hechos__par">
            <dt>{{ hecho.etiqueta }}</dt>
            <dd :class="{ numeros: hecho.numeros }">
              <a v-if="hecho.enlace" :href="hecho.enlace">{{ hecho.valor }}</a>
              <button
                v-else-if="hecho.accion === 'provincia'"
                type="button"
                class="hechos__filtro"
                title="Ver solo esta provincia"
                @click="emit('filtrar-provincia', fila.provincia)"
              >
                {{ hecho.valor }}
              </button>
              <template v-else>{{ hecho.valor }}</template>
            </dd>
          </div>
        </dl>
        <details v-if="resto.length" class="ficha__resto">
          <summary>Más datos de la fuente ({{ resto.length }})</summary>
          <dl class="hechos">
            <div v-for="dato in resto" :key="dato.clave" class="hechos__par">
              <dt>{{ dato.clave }}</dt>
              <dd>{{ dato.valor }}</dd>
            </div>
          </dl>
        </details>
      </aside>
    </div>
  </article>
</template>

<style scoped>
.ficha {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-5) var(--e-5);
  animation: aparecer var(--normal) var(--curva-entrada) both;
}

.ficha__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.ficha__acciones .boton {
  gap: var(--e-2);
}

.ficha__error {
  font-size: var(--t-sm);
  color: var(--error);
}

.ficha__cuerpo {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(15rem, 1fr);
  gap: var(--e-5);
  align-items: start;
}

.ficha__principal {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
  min-width: 0;
}

.bloque-ficha {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.bloque-ficha__titulo {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-sm);
  font-weight: 650;
  color: var(--texto);
}

.bloque-ficha__cuenta {
  padding: 0 7px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  color: var(--texto-suave);
  font-size: 0.7rem;
}

.bloque-ficha__sub {
  font-family: var(--fuente-numeros);
  font-size: var(--t-xs);
  font-weight: 550;
  color: var(--texto-tenue);
}

.ficha__objeto {
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--texto);
  white-space: pre-line;
}

.ficha__nota {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

.ficha__leyendo {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  border: 1px dashed var(--borde-fuerte);
  color: var(--texto-suave);
  font-size: var(--t-sm);
}

.ficha__pulso {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--acento);
  animation: pulso 1.2s ease-in-out infinite;
}

@keyframes pulso {
  50% {
    opacity: 0.25;
  }
}

/* Mercado del CPC */
.mercado-cpc {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.mercado-cpc__precios {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
  gap: var(--e-2);
}

.mercado-cpc__cifra {
  display: flex;
  flex-direction: column;
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
  background: var(--superficie);
}

.mercado-cpc__cifra small {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

/* La mediana es la cifra que se usa para poner precio: destaca por tamaño, no por color. */
.mercado-cpc__cifra--principal strong {
  font-size: var(--t-lg);
}

.mercado-cpc__rivales {
  margin: 0;
  padding-left: var(--e-5);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--t-sm);
}

.mercado-cpc__rivales li span {
  font-weight: 550;
}

.mercado-cpc__rivales small {
  margin-left: var(--e-2);
  color: var(--texto-tenue);
}

/* Plazo: texto, insignia pequeña y una barra gris de avance. Sin bordes ni rellenos de color. */
.plazo-linea {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  background: var(--superficie);
  border: 1px solid var(--borde);
}

.plazo-linea__texto {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: var(--e-2) var(--e-3);
  font-size: var(--t-sm);
}

.plazo-linea__texto strong {
  font-weight: 600;
}

.plazo-linea__barra {
  height: 4px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  overflow: hidden;
}

.plazo-linea__relleno {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--texto-tenue);
  transition: width var(--normal) var(--curva);
}

.plazo-linea__extremos {
  display: flex;
  justify-content: space-between;
  gap: var(--e-3);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

/* Lateral */
.ficha__lateral {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border-radius: var(--r-2);
  background: var(--superficie);
  border: 1px solid var(--borde);
}

.hechos {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  margin: 0;
}

.hechos__par dt {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  margin-bottom: 1px;
}

.hechos__par dd {
  margin: 0;
  font-size: var(--t-sm);
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.hechos__par a {
  color: var(--acento);
}

.hechos__filtro {
  border: 0;
  padding: 0;
  background: none;
  color: var(--acento);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.hechos__filtro:hover {
  text-decoration: underline;
}

.ficha__resto summary {
  cursor: pointer;
  font-size: var(--t-xs);
  font-weight: 650;
  color: var(--acento-fuerte);
  margin-bottom: var(--e-2);
}

/* Ítems */
.items__marco {
  overflow-x: auto;
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
}

.items {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.items th,
.items td {
  text-align: left;
  padding: var(--e-2) var(--e-3);
  border-bottom: 1px solid var(--borde);
  vertical-align: top;
}

.items th {
  font-size: var(--t-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-tenue);
  white-space: nowrap;
  background: var(--superficie-2);
}

.items tbody tr:last-child td {
  border-bottom: none;
}

.items tbody tr:hover {
  background: var(--superficie-2);
}

.items__cpc {
  min-width: 12rem;
}

.items__cpc .codigo {
  display: inline-block;
  margin-right: var(--e-1);
  padding: 1px 6px;
  border-radius: var(--r-1);
  background: var(--superficie-3);
  color: var(--texto);
  font-family: var(--fuente-numeros);
  font-size: var(--t-xs);
  font-weight: 650;
}

.items__nombre {
  color: var(--texto-suave);
}

.items__num {
  text-align: right;
}

@media (max-width: 1023px) {
  .ficha {
    padding: var(--e-3) 0 var(--e-4);
  }

  .ficha__cuerpo {
    grid-template-columns: minmax(0, 1fr);
  }

  .ficha__acciones .boton--principal {
    flex: 1 1 100%;
    justify-content: center;
  }
}

@media (max-width: 639px) {
  .ficha__acciones .boton {
    flex: 1 1 auto;
    justify-content: center;
  }

  .ficha__lateral {
    padding: var(--e-3);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ficha,
  .ficha__pulso {
    animation: none;
  }
}
</style>
