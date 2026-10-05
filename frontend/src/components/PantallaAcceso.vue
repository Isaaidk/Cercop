<script setup>
/**
 * Pantalla de acceso.
 *
 * Dos detalles que parecen menores y no lo son:
 *
 * - **El mensaje de error es el mismo para un correo que no existe y una contraseña equivocada**, y
 *   así lo dice el servidor. No es un descuido: distinguirlos permitiría averiguar qué correos están
 *   registrados probando uno detrás de otro.
 * - **El botón se deshabilita mientras se envía.** Sin eso, pulsar dos veces seguidas enviaría dos
 *   inicios de sesión y el segundo podría expulsar la primera sesión por el límite de sesiones
 *   simultáneas, con lo que el usuario acabaría fuera justo al entrar.
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import CampoContrasena from '@/components/CampoContrasena.vue'
import { sesion } from '@/stores/sesion'

const props = defineProps({
  tema: { type: String, default: 'claro' },
  correoInicial: { type: String, default: '' },
  mensaje: { type: String, default: '' },
})
const emit = defineEmits(['alternar-tema', 'ir-a-registro'])

const email = ref(props.correoInicial || '')
const contrasena = ref('')
const mostrarContrasena = ref(false)
const enfocado = ref('')
const servicioListo = ref(null)

const puedeEnviar = computed(
  () => email.value.trim().length > 3 && contrasena.value.length > 0 && !sesion.estado.cargando,
)

onMounted(async () => {
  // Se comprueba si la API responde antes de que alguien escriba su contraseña. Si está caída, es
  // mucho mejor decirlo aquí que dejar que lo descubra al pulsar el botón.
  try {
    const respuesta = await fetch(`${import.meta.env.VITE_API_BASE || ''}/salud`)
    servicioListo.value = respuesta.ok
  } catch {
    servicioListo.value = false
  }
})

async function entrar() {
  if (!puedeEnviar.value) return
  await sesion.entrar(email.value, contrasena.value)
}
</script>

<template>
  <div class="acceso">
    <header class="acceso__cabecera">
      <div class="marca">
        <span class="marca__icono" aria-hidden="true">CP</span>
        <span class="marca__texto">Contratación pública</span>
      </div>
      <button
        type="button"
        class="boton boton--fantasma boton--icono"
        :aria-label="tema === 'oscuro' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'"
        @click="emit('alternar-tema')"
      >
        <span aria-hidden="true">{{ tema === 'oscuro' ? '☀' : '☾' }}</span>
      </button>
    </header>

    <main class="acceso__cuerpo">
      <section class="acceso__presentacion aparece">
        <h1>Sigue las contrataciones que te importan</h1>
        <p>
          Configura tus palabras clave y el panel reúne las publicaciones de las fuentes oficiales,
          las ordena por provincia y te avisa cuando aparece algo nuevo.
        </p>
        <ul class="acceso__lista">
          <li><span aria-hidden="true">◆</span> Búsqueda por varias palabras clave a la vez</li>
          <li><span aria-hidden="true">◆</span> Mapa del Ecuador con las 24 provincias</li>
          <li><span aria-hidden="true">◆</span> Gráficas que filtran al pulsarlas</li>
        </ul>
      </section>

      <section class="acceso__tarjeta aparece retardo-1">
        <h2>Entrar</h2>
        <p class="acceso__ayuda">Usa las credenciales que te entregó el administrador.</p>

        <!--
          Confirmación de la vuelta desde el registro. Sin esto, quien acaba de crear su empresa
          aterriza en el acceso con el correo escrito y sin ninguna explicación de qué ha pasado ni
          de qué hacer ahora, que es justo donde se pierde la gente.
        -->
        <p v-if="props.mensaje" class="acceso__mensaje" role="status">
          {{ props.mensaje }}
        </p>

        <form class="acceso__formulario" @submit.prevent="entrar">
          <div class="campo">
            <label class="campo__etiqueta" for="email">Correo electrónico</label>
            <input
              id="email"
              v-model="email"
              class="entrada"
              type="email"
              autocomplete="username"
              required
              placeholder="nombre@empresa.ec"
              @focus="enfocado = 'email'"
              @blur="enfocado = ''"
            />
          </div>

          <CampoContrasena
            id="contrasena"
            v-model="contrasena"
            v-model:visible="mostrarContrasena"
            etiqueta="Contraseña"
            ajuste="current-password"
          />

          <p v-if="sesion.estado.error" class="acceso__error" role="alert">
            {{ sesion.estado.error }}
          </p>

          <button type="submit" class="boton boton--principal acceso__enviar" :disabled="!puedeEnviar">
            <span v-if="sesion.estado.cargando" class="girador" aria-hidden="true" />
            {{ sesion.estado.cargando ? 'Entrando…' : 'Entrar' }}
          </button>
        </form>

        <div class="acceso__separador" aria-hidden="true"><span>¿No tienes cuenta?</span></div>

        <button
          type="button"
          class="boton boton--secundario acceso__registro"
          @click="emit('ir-a-registro')"
        >
          Crear la cuenta de mi empresa
        </button>
        <p class="acceso__registro-nota">
          El registro da acceso al panel durante 30 días, con todas las vistas y sin coste.
        </p>

        <p
          v-if="servicioListo === false"
          class="acceso__servicio acceso__servicio--error"
          role="status"
        >
          <span aria-hidden="true">●</span>
          La API no responde. Comprueba que el servidor está en marcha.
        </p>
        <p v-else-if="servicioListo === true" class="acceso__servicio">
          <span aria-hidden="true">●</span>
          Servicio disponible
        </p>
      </section>
    </main>
  </div>
</template>

<style scoped>
.acceso {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.acceso__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-4);
  padding: var(--e-4) var(--e-6);
}

.marca {
  display: flex;
  align-items: center;
  gap: var(--e-3);
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

.acceso__cuerpo {
  flex: 1;
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  align-items: center;
  gap: var(--e-7);
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--e-5) var(--e-6) var(--e-7);
}

.acceso__presentacion h1 {
  font-size: var(--t-3xl);
  letter-spacing: -0.02em;
  margin-bottom: var(--e-4);
  background: linear-gradient(120deg, var(--texto), var(--acento));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.acceso__presentacion > p {
  color: var(--texto-suave);
  font-size: var(--t-md);
  max-width: 46ch;
}

.acceso__lista {
  list-style: none;
  padding: 0;
  margin-top: var(--e-5);
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  color: var(--texto-suave);
}

.acceso__lista li {
  display: flex;
  align-items: center;
  gap: var(--e-3);
}

.acceso__lista span {
  color: var(--acento);
  font-size: 0.65em;
}

.acceso__tarjeta {
  padding: var(--e-6);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-4);
  box-shadow: var(--sombra-3);
}

.acceso__tarjeta h2 {
  font-size: var(--t-xl);
  margin-bottom: var(--e-1);
}

.acceso__ayuda {
  color: var(--texto-tenue);
  font-size: var(--t-sm);
  margin-bottom: var(--e-5);
}

.acceso__formulario {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.acceso__mensaje {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--ok);
  background: var(--ok-suave);
  color: var(--ok);
  font-size: var(--t-sm);
  line-height: 1.55;
}

/* Separador con el texto en medio: separa el acceso del registro sin partir la tarjeta en dos. */
.acceso__separador {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  margin: var(--e-1) 0;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.acceso__separador::before,
.acceso__separador::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--borde);
}

.acceso__registro {
  width: 100%;
}

.acceso__registro-nota {
  margin-top: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  text-align: center;
  line-height: 1.5;
}

.acceso__error {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.acceso__enviar {
  width: 100%;
  padding: 0.65rem 1rem;
}

.acceso__servicio {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin-top: var(--e-4);
  font-size: var(--t-xs);
  color: var(--ok);
}

.acceso__servicio--error {
  color: var(--error);
}

.girador {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

@media (max-width: 1023px) {
  .acceso__cuerpo {
    grid-template-columns: 1fr;
    gap: var(--e-6);
    max-width: 560px;
    padding-top: var(--e-4);
  }

  .acceso__presentacion h1 {
    font-size: var(--t-2xl);
  }

  .acceso__lista {
    display: none;
  }
}

@media (max-width: 639px) {
  .acceso__cuerpo {
    padding: var(--e-4) var(--e-4) var(--e-6);
  }

  .acceso__tarjeta {
    padding: var(--e-5) var(--e-4);
    border-radius: var(--r-3);
  }
}
</style>
