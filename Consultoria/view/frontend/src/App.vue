<script setup>
import { ref } from 'vue'
import NecesidadesTab from './components/NecesidadesTab.vue'
import GraficasTab from './components/GraficasTab.vue'
import OfertasTab from './components/OfertasTab.vue'
import OcdsTab from './components/OcdsTab.vue'

const pestana = ref('necesidades')
</script>

<template>
  <div class="app">
    <header class="cabecera">
      <div class="marca">
        <span class="logo">SERCOP</span>
        <div>
          <h1>Consultoría de Contratación Pública</h1>
          <p>Necesidades de contratación y procesos publicados del Ecuador</p>
        </div>
      </div>

      <nav class="pestanas">
        <button :class="{ activa: pestana === 'necesidades' }" @click="pestana = 'necesidades'">
          Necesidades de Contratación
        </button>
        <button :class="{ activa: pestana === 'graficas' }" @click="pestana = 'graficas'">
          Gráficas
        </button>
        <button :class="{ activa: pestana === 'ofertas' }" @click="pestana = 'ofertas'">
          Ofertas / Procesos
        </button>
        <button :class="{ activa: pestana === 'ocds' }" @click="pestana = 'ocds'">
          Procesos publicados (OCDS)
        </button>
      </nav>
    </header>

    <main class="contenido">
      <NecesidadesTab v-if="pestana === 'necesidades'" />
      <GraficasTab v-else-if="pestana === 'graficas'" />
      <OfertasTab v-else-if="pestana === 'ofertas'" />
      <OcdsTab v-else />
    </main>

    <footer class="pie">
      <p>
        Fuente: Servicio Nacional de Contratación Pública (SERCOP) — portal de
        Necesidades de Contratación y API de Datos Abiertos (OCDS).
      </p>
      <p class="aviso">
        La información se muestra tal como la publica el SERCOP; verifique siempre los
        plazos en el portal oficial antes de presentar una proforma.
      </p>
    </footer>
  </div>
</template>

<style scoped>
.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.cabecera {
  background: linear-gradient(120deg, var(--azul-oscuro), var(--azul));
  color: #fff;
  padding: 26px 32px 0;
  box-shadow: var(--sombra);
}

.marca {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 62px;
  height: 62px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.3);
  font-weight: 800;
  letter-spacing: 0.5px;
  font-size: 0.78em;
}

.marca h1 {
  font-size: 1.5em;
  letter-spacing: 0.2px;
}

.marca p {
  margin: 4px 0 0;
  opacity: 0.85;
  font-size: 0.9em;
}

.pestanas {
  display: flex;
  gap: 6px;
  margin-top: 22px;
  flex-wrap: wrap;
}

.pestanas button {
  border: none;
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  padding: 11px 20px;
  border-radius: 12px 12px 0 0;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.92em;
  transition: 0.15s;
}

.pestanas button:hover {
  background: rgba(255, 255, 255, 0.22);
}

.pestanas button.activa {
  background: var(--gris-100);
  color: var(--azul-oscuro);
}

.contenido {
  flex: 1;
  padding: 24px 32px;
  max-width: 1800px;
  width: 100%;
  margin: 0 auto;
}

.pie {
  padding: 18px 32px 26px;
  text-align: center;
  color: var(--gris-400);
  font-size: 0.8em;
  line-height: 1.5;
}

.pie p {
  margin: 2px 0;
}

.aviso {
  opacity: 0.85;
}

@media (max-width: 720px) {
  .cabecera,
  .contenido,
  .pie {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
