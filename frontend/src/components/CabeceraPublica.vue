<script setup>
/**
 * La cabecera de las páginas públicas.
 *
 * Está separada porque las cuatro pantallas públicas la llevan igual: la marca y el botón de tema. Si
 * cada una la escribiera por su cuenta, cambiar el nombre del producto o el icono serían cuatro
 * ediciones y la que se olvidara se notaría solo en esa página.
 *
 * La marca es un enlace a la portada y no un adorno. Es la forma que tiene cualquiera de volver al
 * principio, y además un buscador la sigue: desde la página de contratación pública hay un camino de
 * vuelta que no depende de que el JavaScript se ejecute.
 */
defineProps({
  tema: { type: String, default: 'claro' },
  /**
   * Añade los accesos de entrar y crear cuenta.
   *
   * Se piden desde fuera y no se muestran siempre porque en las propias pantallas de entrar y de
   * registro serían enlaces a donde ya se está.
   */
  conAcciones: { type: Boolean, default: false },
})
const emit = defineEmits(['alternar-tema'])
</script>

<template>
  <header class="cabecera">
    <a class="marca" href="/" aria-label="CercoApp: ir a la portada">
      <span class="marca__icono" aria-hidden="true">CA</span>
      <span class="marca__texto">CercoApp</span>
    </a>

    <nav v-if="conAcciones" class="cabecera__acciones" aria-label="Acceso a la cuenta">
      <a class="boton boton--fantasma" href="/contratacion-publica-ecuador">
        Contratación pública
      </a>
      <a class="boton boton--fantasma" href="/login">Ingresar</a>
      <a class="boton boton--principal" href="/registro">Crear cuenta</a>
    </nav>

    <button
      type="button"
      class="boton boton--fantasma boton--icono"
      :aria-label="tema === 'oscuro' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'"
      @click="emit('alternar-tema')"
    >
      <span aria-hidden="true">{{ tema === 'oscuro' ? '☀' : '☾' }}</span>
    </button>
  </header>
</template>

<style scoped>
.cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-6);
  max-width: 1180px;
  margin: 0 auto;
  width: 100%;
}

.marca {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  text-decoration: none;
  color: inherit;
}

.marca__icono {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--r-2);
  background: var(--acento);
  color: #fff;
  font-size: var(--t-xs);
  font-weight: 700;
}

.marca__texto {
  font-weight: 650;
}

.cabecera__acciones {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin-left: auto;
}

/* Los enlaces llevan subrayado por defecto en la hoja general, y aquí estos son botones: sin esto,
   «Ingresar» y «Crear cuenta» saldrían subrayados y no parecería lo que son. */
.cabecera__acciones a.boton {
  text-decoration: none;
}

/* En pantallas estrechas se retira el enlace intermedio, que es el prescindible: las dos acciones de
   cuenta siguen a la vista, y la marca y el botón de tema también. */
@media (max-width: 640px) {
  .cabecera {
    padding: var(--e-3) var(--e-4);
  }

  .cabecera__acciones a:first-child {
    display: none;
  }
}
</style>
