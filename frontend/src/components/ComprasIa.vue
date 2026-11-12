<script setup>
/** Compras de créditos de IA por confirmar. Al confirmar el pago, los créditos se suman a la empresa. */
import { onMounted, reactive, ref } from 'vue'

import { api } from '@/api/endpoints'
import { decimal } from '@/utils/formato'

const compras = ref([])
const error = ref('')
const ocupado = ref(false)
const empresas = ref([])
const aviso = ref('')
const regalo = reactive({ negocioId: '', cantidad: 50, motivo: '' })

async function otorgar() {
  ocupado.value = true
  error.value = ''
  aviso.value = ''
  try {
    const r = await api.otorgarCreditosIa(regalo.negocioId, Number(regalo.cantidad), regalo.motivo)
    const nombre = empresas.value.find((e) => e.negocio_id === regalo.negocioId)?.nombre || 'la empresa'
    aviso.value = `Listo: ${r.otorgados} créditos para ${nombre}. Ahora tiene ${r.disponibles}.`
    regalo.motivo = ''
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = false
  }
}

async function cargar() {
  error.value = ''
  try {
    compras.value = (await api.comprasPendientesIa()).compras || []
  } catch (fallo) {
    error.value = fallo.message
  }
}

async function resolver(compra, pagada) {
  ocupado.value = true
  error.value = ''
  try {
    await api.resolverCompraIa(compra.negocio_id, compra.id, pagada)
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = false
  }
}

onMounted(async () => {
  cargar()
  try {
    empresas.value = (await api.listarEmpresas()).empresas || []
  } catch (fallo) {
    error.value = fallo.message
  }
})
</script>

<template>
  <section class="compras">
    <div class="compras__cabecera"><h3>Dar créditos de IA a una empresa</h3></div>
    <form class="compras__regalo" @submit.prevent="otorgar">
      <select v-model="regalo.negocioId" required aria-label="Empresa">
        <option value="" disabled>Elige la empresa…</option>
        <option v-for="e in empresas" :key="e.negocio_id" :value="e.negocio_id">{{ e.nombre }}</option>
      </select>
      <input v-model.number="regalo.cantidad" type="number" min="1" max="100000" required aria-label="Créditos" />
      <input v-model="regalo.motivo" type="text" maxlength="120" placeholder="Motivo (opcional)" aria-label="Motivo" />
      <button type="submit" class="boton boton--principal boton--pequeno" :disabled="ocupado || !regalo.negocioId">
        Dar créditos
      </button>
    </form>
    <p v-if="aviso" class="compras__ok" role="status">{{ aviso }}</p>
    <div class="compras__cabecera">
      <h3>Créditos de IA por confirmar</h3>
      <button type="button" class="boton boton--fantasma boton--pequeno" @click="cargar">Actualizar</button>
    </div>
    <p v-if="error" class="compras__error" role="alert">{{ error }}</p>
    <p v-if="!compras.length" class="compras__vacio">No hay compras pendientes.</p>
    <ul v-else class="compras__lista">
      <li v-for="compra in compras" :key="compra.id" class="compras__fila">
        <div>
          <strong>{{ compra.negocio }}</strong>
          <small>{{ compra.paquete }} · {{ compra.creditos }} créditos · $ {{ decimal(compra.precio_usd) }}</small>
        </div>
        <div class="compras__acciones">
          <button type="button" class="boton boton--principal boton--pequeno" :disabled="ocupado" @click="resolver(compra, true)">
            Confirmar pago
          </button>
          <button type="button" class="boton boton--secundario boton--pequeno" :disabled="ocupado" @click="resolver(compra, false)">
            Anular
          </button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.compras { display: flex; flex-direction: column; gap: var(--e-3); margin-top: var(--e-5); padding: var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-3); background: var(--superficie-2); }
.compras__cabecera { display: flex; align-items: center; justify-content: space-between; gap: var(--e-3); }
.compras__regalo { display: flex; flex-wrap: wrap; gap: var(--e-2); }
.compras__regalo select, .compras__regalo input { padding: var(--e-2) var(--e-3); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); color: var(--texto); font: inherit; }
.compras__regalo input[type='number'] { width: 7rem; }
.compras__ok { color: var(--exito, #15803d); font-size: var(--t-sm); }
.compras__error { color: var(--error); font-size: var(--t-sm); }
.compras__vacio { color: var(--texto-tenue); font-size: var(--t-sm); }
.compras__lista { display: flex; flex-direction: column; gap: var(--e-2); margin: 0; padding: 0; list-style: none; }
.compras__fila { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--e-3); padding: var(--e-3) var(--e-4); border: 1px solid var(--borde); border-radius: var(--r-2); background: var(--superficie); }
.compras__fila small { display: block; color: var(--texto-suave); font-size: var(--t-xs); }
.compras__acciones { display: flex; gap: var(--e-2); }
</style>
