<script setup>
const props = defineProps({
  pagina: { type: Number, required: true },
  totalPaginas: { type: Number, required: true },
  total: { type: Number, default: 0 },
  porPagina: { type: Number, default: 25 },
  opciones: { type: Array, default: () => [10, 25, 50, 100] },
})

const emit = defineEmits(['update:pagina', 'update:porPagina'])

/** Ventana de páginas visibles alrededor de la actual. */
const rangoPaginas = () => {
  const { pagina, totalPaginas } = props
  const inicio = Math.max(1, Math.min(pagina - 2, totalPaginas - 4))
  const fin = Math.min(totalPaginas, inicio + 4)
  const paginas = []
  for (let i = inicio; i <= fin; i += 1) paginas.push(i)
  return paginas
}

const ir = (pagina) => {
  if (pagina >= 1 && pagina <= props.totalPaginas && pagina !== props.pagina) {
    emit('update:pagina', pagina)
  }
}
</script>

<template>
  <div class="paginacion" v-if="totalPaginas > 1 || total > 0">
    <div class="registros">
      <span>
        Mostrando
        <strong>{{ total === 0 ? 0 : (pagina - 1) * porPagina + 1 }}</strong>
        -
        <strong>{{ Math.min(pagina * porPagina, total) }}</strong>
        de <strong>{{ total.toLocaleString('es-EC') }}</strong> registros
      </span>
      <label class="selector">
        Por página
        <select :value="porPagina" @change="emit('update:porPagina', Number($event.target.value))">
          <option v-for="opcion in opciones" :key="opcion" :value="opcion">{{ opcion }}</option>
        </select>
      </label>
    </div>

    <div class="botones" v-if="totalPaginas > 1">
      <button :disabled="pagina === 1" @click="ir(1)">« Primero</button>
      <button :disabled="pagina === 1" @click="ir(pagina - 1)">‹ Anterior</button>
      <button
        v-for="numero in rangoPaginas()"
        :key="numero"
        :class="{ activa: numero === pagina }"
        @click="ir(numero)"
      >
        {{ numero }}
      </button>
      <button :disabled="pagina === totalPaginas" @click="ir(pagina + 1)">Siguiente ›</button>
      <button :disabled="pagina === totalPaginas" @click="ir(totalPaginas)">Último »</button>
    </div>
  </div>
</template>

<style scoped>
.paginacion {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  border-top: 1px solid var(--gris-200);
  background: #fff;
}

.registros {
  display: flex;
  gap: 18px;
  align-items: center;
  font-size: 0.88em;
  color: var(--gris-700);
}

.selector select {
  margin-left: 6px;
  padding: 4px 8px;
  border: 1px solid var(--gris-200);
  border-radius: 6px;
}

.botones {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.botones button {
  min-width: 38px;
  padding: 7px 12px;
  border: 1px solid var(--gris-200);
  background: #fff;
  border-radius: 7px;
  cursor: pointer;
  font-size: 0.85em;
  transition: 0.15s;
}

.botones button:hover:not(:disabled) {
  border-color: var(--azul);
  color: var(--azul);
}

.botones button.activa {
  background: var(--azul);
  border-color: var(--azul);
  color: #fff;
  font-weight: 700;
}

.botones button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
</style>
