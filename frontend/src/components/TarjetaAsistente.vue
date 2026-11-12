<script setup>
/**
 * Una tarjeta dentro de una respuesta del asistente: ínfimas, la ficha de un proceso, una alerta
 * creada, listas cortas de datos o un botón de acción.
 *
 * Solo pinta y avisa:
 * - `preparar(registro)`: abrir «Preparar oferta» con ese registro (`{ id, codigo, … }`, la forma que
 *   espera `prepararOferta` del panel).
 * - `ir(pestana)`: abrir otra pantalla. Va el nombre que manda el servidor; el panel lo traduce.
 *
 * Un `tipo` que no se conoce no pinta nada: el servidor puede estrenar tarjetas antes que la web.
 * Todo se pinta con interpolación (`{{ }}`), nunca con `v-html`.
 */
import { computed } from 'vue'

import {
  cierreDe,
  enumerar,
  fechaCorta,
  lugarDe,
  nombreEtapa,
  registroDeTarjeta,
  usd,
} from '@/utils/asistente'

const props = defineProps({
  tarjeta: { type: Object, required: true },
})

const emit = defineEmits(['preparar', 'ir'])

const TIPOS = new Set(['infimas', 'proceso', 'alerta', 'alertas', 'ofertas', 'empresa', 'ruc', 'datos', 'accion', 'procesos_ruc'])
const conocida = computed(() => TIPOS.has(props.tarjeta?.tipo))
const t = computed(() => props.tarjeta || {})

const elementos = computed(() => (Array.isArray(t.value.elementos) ? t.value.elementos : []))
const campos = computed(() =>
  (Array.isArray(t.value.campos) ? t.value.campos : []).filter(
    (campo) => campo && campo.valor !== null && campo.valor !== undefined && campo.valor !== '',
  ),
)
const listaCpc = computed(() => (Array.isArray(t.value.cpc) ? t.value.cpc : []))

function dinero(valor) {
  const texto = usd(valor)
  return texto === '—' ? '' : texto
}

function preparar(fila) {
  const registro = registroDeTarjeta(fila)
  if (registro?.codigo || registro?.id) emit('preparar', registro)
}

const tituloInfimas = computed(() => {
  if (t.value.titulo) return t.value.titulo
  const total = Number(t.value.total) || elementos.value.length
  return total === 1 ? '1 ínfima' : `${total} ínfimas`
})

/** Las filas de la ficha del proceso, en el orden en que se leen. */
const fichaProceso = computed(() =>
  [
    { etiqueta: 'Código', valor: t.value.codigo },
    { etiqueta: 'Entidad', valor: t.value.entidad },
    { etiqueta: 'Estado', valor: t.value.estado },
    { etiqueta: 'Presupuesto', valor: dinero(t.value.presupuesto) },
    { etiqueta: 'Publicado', valor: fechaCorta(t.value.publicado) },
    { etiqueta: 'Cierre', valor: fechaCorta(t.value.cierre) },
  ].filter((fila) => fila.valor),
)

const alerta = computed(() => t.value.alerta || {})
const criteriosAlerta = computed(() =>
  [
    { etiqueta: 'Palabras', valor: enumerar(alerta.value.palabras) },
    { etiqueta: 'CPC', valor: enumerar(alerta.value.cpc) },
    { etiqueta: 'Provincias', valor: enumerar(alerta.value.provincias) },
    { etiqueta: 'Frecuencia', valor: alerta.value.frecuencia },
  ].filter((fila) => fila.valor),
)

function accionar() {
  const accion = t.value.accion || {}
  if (accion.tipo === 'preparar_oferta') preparar({ registro_id: accion.registro_id, codigo: accion.codigo })
  else if (accion.tipo === 'ir' && accion.pestana) emit('ir', accion.pestana)
}
</script>

<template>
  <section v-if="conocida" class="tarjeta-ia" :class="`tarjeta-ia--${t.tipo}`">
    <!-- Ínfimas -->
    <template v-if="t.tipo === 'infimas'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">{{ tituloInfimas }}</h3>
        <span v-if="t.total && t.titulo" class="etiqueta numeros">{{ t.total }}</span>
      </header>
      <ul v-if="elementos.length" class="tarjeta-ia__filas">
        <li v-for="(fila, indice) in elementos" :key="fila.registro_id || fila.codigo || indice" class="infima">
          <div class="infima__texto">
            <p class="infima__objeto">{{ fila.objeto || 'Sin objeto publicado' }}</p>
            <p v-if="fila.entidad" class="infima__meta">{{ fila.entidad }}</p>
            <p class="infima__datos">
              <span v-if="lugarDe(fila)">{{ lugarDe(fila) }}</span>
              <span v-if="dinero(fila.presupuesto)" class="numeros infima__monto">{{ dinero(fila.presupuesto) }}</span>
              <span v-if="cierreDe(fila.cierre).texto" class="etiqueta" :class="cierreDe(fila.cierre).clase">
                {{ cierreDe(fila.cierre).texto }}
              </span>
            </p>
            <ul v-if="fila.motivos?.length" class="infima__motivos" aria-label="Por qué te la sugerimos">
              <li v-for="motivo in fila.motivos" :key="motivo" class="etiqueta">✓ {{ motivo }}</li>
            </ul>
          </div>
          <button
            v-if="fila.codigo || fila.registro_id"
            type="button"
            class="boton boton--secundario tarjeta-ia__boton"
            :aria-label="`Preparar proforma de ${fila.objeto || fila.codigo}`"
            @click="preparar(fila)"
          >
            Preparar proforma
          </button>
        </li>
      </ul>
      <p v-else class="tarjeta-ia__vacio">No encontré ínfimas con eso.</p>
      <button
        v-if="t.ver_mas?.pestana"
        type="button"
        class="boton boton--fantasma tarjeta-ia__boton tarjeta-ia__enlace"
        @click="emit('ir', t.ver_mas.pestana)"
      >
        Ver todas →
      </button>
    </template>

    <!-- Ficha de un proceso -->
    <template v-else-if="t.tipo === 'proceso'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">{{ t.objeto || t.codigo || 'Proceso' }}</h3>
        <span v-if="cierreDe(t.cierre).texto" class="etiqueta" :class="cierreDe(t.cierre).clase">
          {{ cierreDe(t.cierre).texto }}
        </span>
      </header>
      <dl class="tarjeta-ia__lista-def">
        <div v-for="fila in fichaProceso" :key="fila.etiqueta">
          <dt>{{ fila.etiqueta }}</dt>
          <dd>{{ fila.valor }}</dd>
        </div>
        <div v-if="listaCpc.length">
          <dt>CPC</dt>
          <dd>
            <ul class="tarjeta-ia__cpc">
              <li v-for="cpc in listaCpc" :key="cpc.codigo">
                <span class="numeros">{{ cpc.codigo }}</span> {{ cpc.descripcion }}
              </li>
            </ul>
          </dd>
        </div>
        <div v-if="t.etapa_mi_oferta">
          <dt>Tu oferta</dt>
          <dd><span class="etiqueta etiqueta--acento">{{ nombreEtapa(t.etapa_mi_oferta) }}</span></dd>
        </div>
      </dl>
      <button
        v-if="t.codigo || t.registro_id"
        type="button"
        class="boton boton--principal tarjeta-ia__boton"
        @click="preparar(t)"
      >
        Preparar proforma
      </button>
    </template>

    <!-- Alerta recién creada -->
    <template v-else-if="t.tipo === 'alerta'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">
          <span class="tarjeta-ia__check" aria-hidden="true">✓</span> Alerta creada
        </h3>
      </header>
      <p v-if="alerta.nombre" class="tarjeta-ia__destacado">{{ alerta.nombre }}</p>
      <dl v-if="criteriosAlerta.length" class="tarjeta-ia__lista-def">
        <div v-for="fila in criteriosAlerta" :key="fila.etiqueta">
          <dt>{{ fila.etiqueta }}</dt>
          <dd>{{ fila.valor }}</dd>
        </div>
      </dl>
      <p v-if="t.coincidencias !== null && t.coincidencias !== undefined" class="tarjeta-ia__nota">
        <template v-if="Number(t.coincidencias) === 1">Hoy hay 1 proceso que la cumple.</template>
        <template v-else-if="Number(t.coincidencias) > 1">Hoy hay {{ t.coincidencias }} procesos que la cumplen.</template>
        <template v-else>Por ahora no hay procesos que la cumplan. Te avisaremos cuando salga uno.</template>
      </p>
      <button type="button" class="boton boton--secundario tarjeta-ia__boton" @click="emit('ir', 'alertas')">
        Ver mis alertas
      </button>
    </template>

    <!-- Lista de alertas -->
    <template v-else-if="t.tipo === 'alertas'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">Tus alertas</h3>
      </header>
      <ul v-if="elementos.length" class="tarjeta-ia__simple">
        <li v-for="fila in elementos" :key="fila.id || fila.nombre">
          <span class="tarjeta-ia__nombre">{{ fila.nombre }}</span>
          <span class="tarjeta-ia__lado">
            <span v-if="fila.frecuencia">{{ fila.frecuencia }}</span>
            <span class="etiqueta" :class="fila.activa === false ? '' : 'etiqueta--ok'">
              {{ fila.activa === false ? 'Pausada' : 'Activa' }}
            </span>
          </span>
        </li>
      </ul>
      <p v-else class="tarjeta-ia__vacio">Todavía no tienes alertas.</p>
      <button type="button" class="boton boton--fantasma tarjeta-ia__boton tarjeta-ia__enlace" @click="emit('ir', 'alertas')">
        Ver mis alertas →
      </button>
    </template>

    <!-- Ofertas del CRM -->
    <template v-else-if="t.tipo === 'ofertas'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">Tus ofertas</h3>
      </header>
      <ul v-if="elementos.length" class="tarjeta-ia__simple">
        <li v-for="fila in elementos" :key="fila.id || fila.titulo">
          <button type="button" class="tarjeta-ia__fila-boton" @click="emit('ir', 'mis-ofertas')">
            <span class="tarjeta-ia__nombre">{{ fila.titulo || 'Oferta' }}</span>
            <span class="tarjeta-ia__lado">
              <span v-if="dinero(fila.monto)" class="numeros">{{ dinero(fila.monto) }}</span>
              <span v-if="fila.etapa" class="etiqueta">{{ nombreEtapa(fila.etapa) }}</span>
              <span v-if="cierreDe(fila.cierre).texto" class="etiqueta" :class="cierreDe(fila.cierre).clase">
                {{ cierreDe(fila.cierre).texto }}
              </span>
            </span>
          </button>
        </li>
      </ul>
      <p v-else class="tarjeta-ia__vacio">Todavía no tienes ofertas.</p>
      <button type="button" class="boton boton--fantasma tarjeta-ia__boton tarjeta-ia__enlace" @click="emit('ir', 'mis-ofertas')">
        Ir a Mis ofertas →
      </button>
    </template>

    <!-- Historial de un RUC en compras públicas: procesos ganados -->
    <template v-else-if="t.tipo === 'procesos_ruc'">
      <header class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">Procesos de {{ t.razon_social || t.ruc }}</h3>
      </header>
      <dl class="tarjeta-ia__lista-def">
        <div><dt>RUC</dt><dd class="numeros">{{ t.ruc }}</dd></div>
        <div><dt>Procesos encontrados</dt><dd>{{ t.total ?? 0 }}</dd></div>
        <div><dt>Ganados</dt><dd>{{ t.ganados ?? 0 }}</dd></div>
        <div v-if="dinero(t.monto_total)"><dt>Monto adjudicado</dt><dd>{{ dinero(t.monto_total) }}</dd></div>
      </dl>
      <template v-if="elementos.length">
        <p class="tarjeta-ia__subtitulo">Últimos procesos ganados</p>
        <ul class="tarjeta-ia__simple">
          <li v-for="fila in elementos" :key="fila.codigo || fila.objeto">
            <span class="tarjeta-ia__nombre">
              {{ fila.objeto || fila.codigo }}
              <small class="tarjeta-ia__nota">
                {{ [fila.codigo, fila.entidad, fechaCorta(fila.fecha)].filter(Boolean).join(' · ') }}
              </small>
            </span>
            <span class="tarjeta-ia__lado">
              <span v-if="dinero(fila.monto)" class="numeros">{{ dinero(fila.monto) }}</span>
              <span v-if="fila.resultado" class="etiqueta">{{ fila.resultado }}</span>
            </span>
          </li>
        </ul>
      </template>
      <p class="tarjeta-ia__nota">
        Datos abiertos del SERCOP de los últimos 3 años. Solo publica a quien ganó; las ínfimas no
        están incluidas.
      </p>
    </template>

    <!-- Empresa, RUC y datos: lista de definiciones -->
    <template v-else-if="t.tipo === 'empresa' || t.tipo === 'ruc' || t.tipo === 'datos'">
      <header v-if="t.titulo || t.tipo === 'ruc'" class="tarjeta-ia__cabecera">
        <h3 class="tarjeta-ia__titulo">{{ t.titulo || 'Consulta de RUC' }}</h3>
      </header>
      <dl v-if="campos.length" class="tarjeta-ia__lista-def">
        <div v-for="(campo, indice) in campos" :key="`${campo.etiqueta}-${indice}`">
          <dt>{{ campo.etiqueta }}</dt>
          <dd>{{ campo.valor }}</dd>
        </div>
      </dl>
      <template v-if="t.tipo === 'empresa' && listaCpc.length">
        <p class="tarjeta-ia__subtitulo">Tus CPC</p>
        <ul class="tarjeta-ia__cpc">
          <li v-for="cpc in listaCpc" :key="cpc.codigo">
            <span class="numeros">{{ cpc.codigo }}</span> {{ cpc.descripcion }}
          </li>
        </ul>
      </template>
    </template>

    <!-- Una acción -->
    <template v-else-if="t.tipo === 'accion'">
      <button type="button" class="boton boton--principal tarjeta-ia__boton" @click="accionar">
        {{ t.etiqueta || 'Continuar' }}
      </button>
    </template>
  </section>
</template>

<style scoped>
.tarjeta-ia {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  min-width: 0;
  padding: var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  color: var(--texto);
  font-size: 1rem;
  line-height: 1.5;
}

/* La acción sola no necesita marco: es un botón dentro de la respuesta. */
.tarjeta-ia--accion {
  padding: 0;
  border: 0;
  background: transparent;
}

.tarjeta-ia__cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--e-3);
}

.tarjeta-ia__titulo {
  min-width: 0;
  font-size: 1.0625rem;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.tarjeta-ia__check {
  color: var(--ok);
}

.tarjeta-ia__destacado {
  font-weight: 650;
}

.tarjeta-ia__subtitulo {
  font-size: 0.9375rem;
  font-weight: 650;
  color: var(--texto-suave);
}

.tarjeta-ia__nota,
.tarjeta-ia__vacio {
  color: var(--texto-suave);
}

.tarjeta-ia__boton {
  align-self: flex-start;
  min-height: 44px;
  padding: 0.55rem 1rem;
  font-size: 1rem;
  white-space: normal;
  text-align: center;
}

.tarjeta-ia__enlace {
  color: var(--acento);
  margin-left: calc(var(--e-3) * -1);
}

/* Ínfimas: una fila por ínfima, texto a la izquierda y el botón a la derecha (abajo en móvil). */
.tarjeta-ia__filas {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.infima {
  display: flex;
  align-items: center;
  gap: var(--e-4);
  padding: var(--e-3) 0;
  border-top: 1px solid var(--borde);
}

.infima:first-child {
  border-top: 0;
  padding-top: 0;
}

.infima__texto {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.infima__objeto {
  font-weight: 650;
  overflow-wrap: anywhere;
}

.infima__meta {
  color: var(--texto-suave);
  overflow-wrap: anywhere;
}

.infima__datos {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1) var(--e-3);
  color: var(--texto-suave);
  font-size: 0.9375rem;
}

.infima__monto {
  font-weight: 650;
  color: var(--texto);
}

.infima__motivos {
  list-style: none;
  margin: var(--e-1) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-1);
}

.infima__motivos .etiqueta {
  white-space: normal;
  font-size: 0.8125rem;
}

.infima .tarjeta-ia__boton {
  flex: none;
  align-self: center;
}

/* Listas de definiciones: etiqueta en gris y el valor al lado (debajo en móvil). */
.tarjeta-ia__lista-def {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.tarjeta-ia__lista-def > div {
  display: grid;
  grid-template-columns: minmax(7rem, 30%) minmax(0, 1fr);
  gap: var(--e-3);
}

.tarjeta-ia__lista-def dt {
  color: var(--texto-suave);
}

.tarjeta-ia__lista-def dd {
  margin: 0;
  min-width: 0;
  overflow-wrap: anywhere;
}

.tarjeta-ia__cpc {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tarjeta-ia__simple {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.tarjeta-ia__simple > li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-2) 0;
  border-top: 1px solid var(--borde);
}

.tarjeta-ia__simple > li:first-child {
  border-top: 0;
}

.tarjeta-ia__nombre {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.tarjeta-ia__lado {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: var(--e-2);
  color: var(--texto-suave);
  font-size: 0.9375rem;
}

.tarjeta-ia__fila-boton {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  width: calc(100% + var(--e-2) * 2);
  min-height: 44px;
  padding: var(--e-1) var(--e-2);
  margin: 0 calc(var(--e-2) * -1);
  border: 0;
  border-radius: var(--r-2);
  background: transparent;
  color: inherit;
  font-size: 1rem;
  text-align: left;
  cursor: pointer;
}

.tarjeta-ia__fila-boton:hover {
  background: var(--superficie-3);
}

@media (max-width: 639px) {
  .infima {
    flex-direction: column;
    align-items: stretch;
    gap: var(--e-2);
  }

  .infima .tarjeta-ia__boton,
  .tarjeta-ia--accion .tarjeta-ia__boton {
    align-self: stretch;
  }

  .tarjeta-ia__lista-def > div {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }

  .tarjeta-ia__simple > li,
  .tarjeta-ia__fila-boton {
    flex-wrap: wrap;
  }
}
</style>
