<script setup>
/**
 * Barra de tiempo del plazo de proformas: cuánto del tiempo entre la publicación y el cierre ya
 * pasó, con el color de la urgencia y lo que queda dicho en palabras.
 *
 * La cuenta vive en `utils/plazo.js` (`avanceDelPlazo`), probada aparte; aquí solo se pinta. El
 * color nunca va solo: el texto («Quedan 2 días y 3 horas», «Transcurrido el 60 %») dice lo mismo,
 * y el lector de pantalla recibe la barra como `progressbar` con su valor y una frase completa.
 *
 * Las horas son de Ecuador (America/Guayaquil): el portal las publica sin zona.
 *
 * Se refresca sola cada minuto mientras está a la vista, para que «Quedan 20 minutos» no se quede
 * congelado si la ficha sigue abierta.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { avanceDelPlazo } from '@/utils/plazo'

const props = defineProps({
  publicacion: { type: [String, Date], default: '' },
  limite: { type: [String, Date], default: '' },
  /** Si la barra dice además lo que queda. Se apaga donde ese texto ya va al lado (la ficha). */
  mostrarRestante: { type: Boolean, default: true },
})

const ahora = ref(Date.now())
let reloj = 0
onMounted(() => {
  reloj = window.setInterval(() => (ahora.value = Date.now()), 60_000)
})
onBeforeUnmount(() => window.clearInterval(reloj))

const FECHA = new Intl.DateTimeFormat('es-EC', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'America/Guayaquil',
})
const HORA = new Intl.DateTimeFormat('es-EC', {
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'America/Guayaquil',
})
const fecha = (instante) => (instante === null ? '' : FECHA.format(instante).replace('.', ''))
const hora = (instante) => (instante === null ? '' : HORA.format(instante))

const plazo = computed(() => avanceDelPlazo(props.publicacion, props.limite, ahora.value))

const descripcion = computed(() => {
  const p = plazo.value
  if (!p) return ''
  const partes = []
  if (p.porcentaje !== null) partes.push(`Transcurrido el ${p.porcentaje} % del plazo.`)
  partes.push(p.cerrado ? 'El plazo de proformas ya cerró.' : `${p.texto}.`)
  partes.push(`${p.cerrado ? 'Cerró' : 'Cierra'} el ${fecha(p.fin)} a las ${hora(p.fin)}.`)
  return partes.join(' ')
})
</script>

<template>
  <div v-if="plazo" class="barra-plazo" :class="`barra-plazo--${plazo.nivel}`">
    <div class="barra-plazo__resumen">
      <span v-if="mostrarRestante" class="barra-plazo__restante">{{ plazo.texto }}</span>
      <span v-if="plazo.porcentaje !== null" class="barra-plazo__porcentaje numeros" aria-hidden="true">
        {{ plazo.porcentaje }} % del plazo transcurrido
      </span>
    </div>
    <div
      v-if="plazo.porcentaje !== null"
      class="barra-plazo__pista"
      role="progressbar"
      aria-label="Tiempo transcurrido del plazo de proformas"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-valuenow="plazo.porcentaje"
      :aria-valuetext="descripcion"
    >
      <span class="barra-plazo__relleno" :style="{ width: `${Math.max(plazo.porcentaje, 2)}%` }" />
    </div>
    <p v-else class="solo-lectores">{{ descripcion }}</p>
    <div class="barra-plazo__extremos">
      <span v-if="plazo.inicio !== null">
        Publicado el <span class="numeros">{{ fecha(plazo.inicio) }} · {{ hora(plazo.inicio) }}</span>
      </span>
      <span class="barra-plazo__cierre">
        {{ plazo.cerrado ? 'Cerró' : 'Cierra' }} el
        <span class="numeros">{{ fecha(plazo.fin) }} · {{ hora(plazo.fin) }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.barra-plazo {
  --barra-color: var(--ok);
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
}

.barra-plazo--atencion {
  --barra-color: var(--aviso);
}

.barra-plazo--urgente {
  --barra-color: var(--error);
}

.barra-plazo--cerrado {
  --barra-color: var(--texto-tenue);
}

.barra-plazo__resumen {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--e-1) var(--e-3);
  font-size: var(--t-sm);
}

.barra-plazo__restante {
  font-weight: 650;
  color: var(--barra-color);
}

.barra-plazo--cerrado .barra-plazo__restante {
  color: var(--texto-suave);
}

.barra-plazo__porcentaje {
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

/* Pista neutra y relleno del color del nivel. 8 px: se ve en el móvil sin ocupar el bloque. */
.barra-plazo__pista {
  height: 8px;
  border-radius: var(--r-redondo);
  background: var(--superficie-3);
  box-shadow: inset 0 0 0 1px var(--borde);
  overflow: hidden;
}

.barra-plazo__relleno {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--barra-color);
  transition: width var(--normal) var(--curva);
}

.barra-plazo__extremos {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--e-1) var(--e-3);
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

.barra-plazo__cierre {
  margin-left: auto;
  text-align: right;
}

@media (prefers-reduced-motion: reduce) {
  .barra-plazo__relleno {
    transition: none;
  }
}
</style>
