<script setup>
/**
 * Campo de contraseña con el botón de ver y ocultar.
 *
 * Existe como componente porque el mismo campo aparece en cuatro formularios —entrar, registrarse,
 * cambiar la contraseña y gestionar usuarios— y tenerlo copiado cuatro veces garantiza que las
 * copias se separen: se arregla una y las otras tres se quedan como estaban. Aquí se escribe una
 * vez, y el detalle que de verdad importa —que el botón diga en voz alta qué hace y en qué estado
 * está, para que un lector de pantalla lo anuncie— se escribe también una sola vez.
 */

const valor = defineModel({ type: String, default: '', required: true })
const visible = defineModel('visible', { type: Boolean, default: false })

defineProps({
  id: { type: String, required: true },
  etiqueta: { type: String, required: true },
  ajuste: { type: String, default: 'off' },
  /** Ayuda corta bajo el campo. Vacía no ocupa sitio. */
  ayuda: { type: String, default: '' },
  /** Entrada inválida: se marca el borde y se anuncia el mensaje. */
  error: { type: String, default: '' },
  requerido: { type: Boolean, default: true },
  /** Muestra el distintivo «obligatorio» junto a la etiqueta, como el resto del formulario. */
  obligatorio: { type: Boolean, default: false },
  maxlength: { type: Number, default: null },
  autofocus: { type: Boolean, default: false },
})
</script>

<template>
  <div class="campo">
    <label class="campo__etiqueta" :for="id">
      {{ etiqueta }}
      <span v-if="obligatorio" class="campo__obligatorio">obligatorio</span>
    </label>
    <div class="contrasena">
      <input
        :id="id"
        v-model="valor"
        class="entrada"
        :class="{ 'entrada--error': error }"
        :type="visible ? 'text' : 'password'"
        :autocomplete="ajuste"
        :required="requerido"
        :maxlength="maxlength ?? undefined"
        :aria-invalid="error ? 'true' : undefined"
        :aria-describedby="error ? `${id}-error` : ayuda ? `${id}-ayuda` : undefined"
        :autofocus="autofocus"
      />
      <button
        type="button"
        class="contrasena__ojo"
        :aria-label="visible ? 'Ocultar la contraseña' : 'Mostrar la contraseña'"
        :aria-pressed="visible"
        @click="visible = !visible"
      >
        {{ visible ? 'Ocultar' : 'Ver' }}
      </button>
    </div>
    <p v-if="error" :id="`${id}-error`" class="campo__error" role="alert">{{ error }}</p>
    <p v-else-if="ayuda" :id="`${id}-ayuda`" class="campo__ayuda">{{ ayuda }}</p>
  </div>
</template>

<style scoped>
.contrasena {
  position: relative;
  display: flex;
  align-items: center;
}

/* Hueco reservado para el botón: sin él, el texto de la contraseña pasaría por debajo. */
.contrasena .entrada {
  padding-right: 4.2rem;
}

.contrasena__ojo {
  position: absolute;
  right: var(--e-2);
  padding: 4px 8px;
  border: 0;
  border-radius: var(--r-1);
  background: transparent;
  color: var(--texto-suave);
  font-size: var(--t-xs);
  font-weight: 600;
  cursor: pointer;
  transition: color var(--rapido) var(--curva), background-color var(--rapido) var(--curva);
}

.contrasena__ojo:hover {
  color: var(--acento);
  background: var(--acento-tenue);
}

.campo__error {
  margin-top: var(--e-1);
  font-size: var(--t-xs);
  color: var(--peligro, #b91c1c);
}

.campo__ayuda {
  margin-top: var(--e-1);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}
</style>
