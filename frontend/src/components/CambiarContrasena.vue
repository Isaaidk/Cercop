<script setup>
/**
 * Diálogo para cambiar la contraseña propia.
 *
 * Tres decisiones que hacen que este diálogo no estorbe:
 *
 * - **Pide la contraseña actual.** No es papeleo: sin ella, cualquiera que encuentre un equipo
 *   desatendido un minuto podría quedarse con la cuenta para siempre. El servidor también la exige, y
 *   aquí se explica por qué se pide antes de que alguien se pregunte si era necesario.
 * - **Avisa de que se cerrarán las otras sesiones.** Es la consecuencia real de la operación, y quien
 *   la hace debe saberla antes, no descubrirla al verse fuera en otro dispositivo.
 * - **Comprueba la contraseña nueva contra la política del servidor mientras se escribe.** La misma
 *   lista que en el registro, por el mismo motivo.
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'
import { contrasenaAceptable, obtenerRequisitos, revisarContrasena } from '@/utils/politica'

const emit = defineEmits(['cerrar', 'cambiada'])

const actual = ref('')
const nueva = ref('')
const repetida = ref('')
const requisitos = ref(null)
const enviando = ref(false)
const error = ref('')

onMounted(async () => {
  requisitos.value = await obtenerRequisitos()
})

const comprobaciones = computed(() =>
  revisarContrasena(nueva.value, requisitos.value, sesion.estado.email),
)

const coinciden = computed(() => nueva.value.length > 0 && nueva.value === repetida.value)
const distintos = computed(() => nueva.value.length > 0 && nueva.value !== actual.value)

const puedeEnviar = computed(
  () =>
    actual.value.length > 0 &&
    contrasenaAceptable(nueva.value, requisitos.value, sesion.estado.email) &&
    coinciden.value &&
    distintos.value &&
    !enviando.value,
)

async function guardar() {
  if (!puedeEnviar.value) return
  enviando.value = true
  error.value = ''

  try {
    // Se envía el identificador de la sesión actual para que el servidor **no** la cierre: expulsar a
    // quien acaba de hacer lo correcto sería la peor respuesta posible.
    const resultado = await api.cambiarMiContrasena(actual.value, nueva.value, sesion.estado.sesionId)
    emit('cambiada', resultado)
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <div class="velo" @click.self="emit('cerrar')">
    <div class="dialogo aparece" role="dialog" aria-modal="true" aria-labelledby="titulo-clave">
      <header class="dialogo__cabecera">
        <h2 id="titulo-clave" class="dialogo__titulo">Cambiar tu contraseña</h2>
        <button
          type="button"
          class="boton boton--fantasma boton--icono"
          aria-label="Cerrar"
          @click="emit('cerrar')"
        >
          ✕
        </button>
      </header>

      <form class="dialogo__cuerpo" @submit.prevent="guardar">
        <label class="campo">
          <span class="campo__etiqueta">Contraseña actual</span>
          <input
            v-model="actual"
            class="entrada"
            type="password"
            autocomplete="current-password"
            autofocus
          />
          <span class="campo__ayuda">
            Se pide para que nadie con una sesión abierta pueda quedarse con tu cuenta.
          </span>
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Contraseña nueva</span>
          <input v-model="nueva" class="entrada" type="password" autocomplete="new-password" />
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Repite la contraseña nueva</span>
          <input v-model="repetida" class="entrada" type="password" autocomplete="new-password" />
        </label>

        <ul class="requisitos">
          <li
            v-for="fila in comprobaciones"
            :key="fila.clave"
            class="requisitos__fila"
            :class="{ 'requisitos__fila--bien': fila.cumple }"
          >
            <span aria-hidden="true">{{ fila.cumple ? '✓' : '·' }}</span>
            {{ fila.etiqueta }}
          </li>
          <li class="requisitos__fila" :class="{ 'requisitos__fila--bien': coinciden }">
            <span aria-hidden="true">{{ coinciden ? '✓' : '·' }}</span>
            Las dos coinciden
          </li>
          <li class="requisitos__fila" :class="{ 'requisitos__fila--bien': distintos }">
            <span aria-hidden="true">{{ distintos ? '✓' : '·' }}</span>
            Distinta de la actual
          </li>
        </ul>

        <p class="dialogo__aviso">
          Al guardar se cerrarán tus <strong>otras sesiones</strong>. Esta seguirá abierta.
        </p>

        <p v-if="error" class="dialogo__error" role="alert">{{ error }}</p>

        <div class="dialogo__acciones">
          <button type="submit" class="boton boton--principal" :disabled="!puedeEnviar">
            <span v-if="enviando" class="girador" aria-hidden="true" />
            {{ enviando ? 'Guardando…' : 'Cambiar la contraseña' }}
          </button>
          <button type="button" class="boton boton--fantasma" @click="emit('cerrar')">Cancelar</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.velo {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: var(--e-4);
  background: rgb(0 0 0 / 40%);
  animation: aparecer var(--rapido) var(--curva) both;
  overflow-y: auto;
}

.dialogo {
  width: min(480px, 100%);
  border-radius: var(--r-3);
  background: var(--superficie);
  border: 1px solid var(--borde);
  box-shadow: var(--sombra-3);
}

.dialogo__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--e-4) var(--e-5);
  border-bottom: 1px solid var(--borde);
}

.dialogo__titulo {
  font-size: var(--t-lg);
  font-weight: 700;
}

.dialogo__cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-5);
}

.requisitos {
  list-style: none;
  padding: var(--e-3);
  margin: 0;
  border-radius: var(--r-2);
  background: var(--superficie-2);
  display: flex;
  flex-direction: column;
  gap: var(--e-1);
}

.requisitos__fila {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.requisitos__fila--bien {
  color: var(--ok);
  font-weight: 600;
}

.dialogo__aviso {
  font-size: var(--t-xs);
  line-height: 1.5;
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  background: var(--info-suave);
  color: var(--info);
}

.dialogo__error {
  padding: var(--e-3);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.dialogo__acciones {
  display: flex;
  gap: var(--e-2);
}

.girador {
  width: 13px;
  height: 13px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}
</style>
