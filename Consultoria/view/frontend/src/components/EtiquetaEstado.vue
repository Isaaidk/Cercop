<script setup>
import { computed } from 'vue'

const props = defineProps({
  estado: { type: String, default: '' },
  dias: { type: Number, default: null },
})

const claseEstado = computed(() => {
  const estado = (props.estado || '').toLowerCase()
  if (estado.includes('curso') || estado.includes('active')) return 'curso'
  if (estado.includes('finaliz') || estado.includes('complete') || estado.includes('adjudic')) return 'finalizada'
  if (estado.includes('cancel')) return 'cancelada'
  if (estado.includes('desiert') || estado.includes('unsucc')) return 'desierta'
  return 'neutro'
})

const plazo = computed(() => {
  if (props.dias === null || props.dias === undefined || Number.isNaN(props.dias)) return null
  const dias = Number(props.dias)
  if (dias < 0) return { texto: 'Plazo vencido', clase: 'vencido' }
  if (dias < 1) {
    const horas = Math.max(1, Math.round(dias * 24))
    return { texto: `Vence en ${horas} h`, clase: 'urgente' }
  }
  if (dias < 3) return { texto: `Vence en ${Math.round(dias)} días`, clase: 'urgente' }
  if (dias <= 7) return { texto: `Vence en ${Math.round(dias)} días`, clase: 'proximo' }
  return { texto: `Vence en ${Math.round(dias)} días`, clase: 'holgado' }
})
</script>

<template>
  <div class="etiquetas">
    <span v-if="estado" class="badge" :class="claseEstado">{{ estado }}</span>
    <span v-if="plazo" class="badge plazo" :class="plazo.clase">{{ plazo.texto }}</span>
  </div>
</template>

<style scoped>
.etiquetas {
  display: flex;
  flex-direction: column;
  gap: 5px;
  align-items: flex-start;
}

.badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 0.78em;
  font-weight: 700;
  white-space: nowrap;
}

.curso {
  background: var(--azul-claro);
  color: var(--azul-oscuro);
}

.finalizada {
  background: var(--verde-claro);
  color: var(--verde);
}

.cancelada,
.desierta {
  background: var(--gris-200);
  color: var(--gris-700);
}

.neutro {
  background: var(--gris-200);
  color: var(--gris-700);
}

.plazo.holgado {
  background: #f1f5f9;
  color: var(--gris-700);
  font-weight: 600;
}

.plazo.proximo {
  background: var(--ambar-claro);
  color: var(--ambar);
}

.plazo.urgente {
  background: #ffedd5;
  color: #c2410c;
}

.plazo.vencido {
  background: var(--rojo-claro);
  color: var(--rojo);
}
</style>
