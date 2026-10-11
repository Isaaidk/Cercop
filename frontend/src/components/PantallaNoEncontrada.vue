<script setup>
/**
 * Lo que se ve cuando la dirección no corresponde a ninguna página.
 *
 * Importa que exista aunque el servidor no sepa distinguirla. Caddy entrega el mismo documento para
 * cualquier dirección desconocida —lo hace con `try_files`—, así que sin esta pantalla una dirección
 * inventada mostraría la portada con un 200, y para un buscador eso significa «esta dirección existe y
 * tiene este contenido». Lo que se puede arreglar desde el navegador se arregla: aquí se dice que la
 * dirección no existe y se dan los caminos que sí llevan a algo.
 */
import CabeceraPublica from '@/components/CabeceraPublica.vue'
import PiePublico from '@/components/PiePublico.vue'

defineProps({
  tema: { type: String, default: 'claro' },
})
const emit = defineEmits(['alternar-tema'])
</script>

<template>
  <div class="no-encontrada">
    <CabeceraPublica :tema="tema" @alternar-tema="emit('alternar-tema')" />

    <main class="no-encontrada__cuerpo">
      <p class="no-encontrada__codigo" aria-hidden="true">404</p>
      <h1>Esta dirección no existe</h1>
      <p class="no-encontrada__texto">
        La dirección que has escrito no corresponde a ninguna página de Cercop. Puede que se haya
        colado un carácter de más, o que el enlace que te trajo aquí esté mal escrito.
      </p>

      <p class="no-encontrada__texto">Desde aquí puedes seguir:</p>

      <ul class="no-encontrada__caminos">
        <li><a href="/">Ir a la portada</a></li>
        <li><a href="/contratacion-publica-ecuador">Contratación pública en Ecuador</a></li>
        <li><a href="/login">Ingresar con tu cuenta</a></li>
        <li><a href="/registro">Crear la cuenta de tu empresa</a></li>
      </ul>
    </main>

    <PiePublico />
  </div>
</template>

<style scoped>
.no-encontrada {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.no-encontrada__cuerpo {
  flex: 1;
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
  padding: var(--e-7) var(--e-6);
  text-align: center;
}

.no-encontrada__codigo {
  margin: 0;
  font-family: var(--fuente-numeros);
  font-size: var(--t-3xl);
  font-weight: 700;
  color: var(--acento);
  letter-spacing: 0.08em;
}

.no-encontrada h1 {
  margin: var(--e-3) 0 0;
  font-size: var(--t-2xl);
  line-height: 1.25;
}

.no-encontrada__texto {
  margin: var(--e-4) 0 0;
  color: var(--texto-suave);
  line-height: 1.7;
}

.no-encontrada__caminos {
  list-style: none;
  margin: var(--e-4) 0 0;
  padding: 0;
  display: grid;
  gap: var(--e-2);
}

.no-encontrada__caminos a {
  color: var(--acento);
  text-decoration: none;
  font-weight: 550;
}

.no-encontrada__caminos a:hover {
  text-decoration: underline;
}
</style>
