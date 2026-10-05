<script setup>
/**
 * Registro de una empresa.
 *
 * Cómo está pensado para que no sea confuso
 * ----------------------------------------
 * **Una sola página, con dos bloques separados y numerados**: primero la empresa, después la persona
 * que la va a administrar. Se podría haber hecho un asistente de varios pasos, y se descartó: obliga a
 * decidir cuánto cabe en cada pantalla, esconde lo que ya se escribió y hace que volver atrás pierda
 * datos. Con los dos bloques a la vista, quien lo rellena ve de un vistazo qué le falta y puede
 * corregir cualquier cosa antes de enviar.
 *
 * **Solo el nombre de la empresa, el correo y la contraseña son obligatorios.** El RUC, el teléfono y
 * la dirección se pueden dejar en blanco y rellenar después desde el panel. Exigirlos todos convertiría
 * el registro en un trámite, y quien no tenga el RUC a mano no podría entrar a ver si el producto le
 * sirve.
 *
 * **La política de contraseñas se pide al servidor y se muestra como una lista que se completa.** Es
 * la única forma de que el formulario no diga una cosa y el servidor exija otra. Y se ve lo que falta
 * mientras se escribe, en lugar de descubrirlo al pulsar el botón.
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import CampoContrasena from '@/components/CampoContrasena.vue'
import { contrasenaAceptable, obtenerRequisitos, revisarContrasena } from '@/utils/politica'

const emit = defineEmits(['alternar-tema', 'ir-a-acceso', 'registrada'])

const props = defineProps({
  tema: { type: String, default: 'claro' },
  correoInicial: { type: String, default: '' },
})

const empresa = ref({ nombre: '', ruc: '', email_contacto: '', telefono: '', direccion: '', ciudad: '' })
const admin = ref({ nombre: '', email: props.correoInicial || '', contrasena: '', repetida: '' })

const requisitos = ref(null)
const enviando = ref(false)
const error = ref('')

onMounted(async () => {
  requisitos.value = await obtenerRequisitos()
})

const comprobaciones = computed(() =>
  revisarContrasena(admin.value.contrasena, requisitos.value, admin.value.email),
)

const contrasenaBien = computed(() =>
  contrasenaAceptable(admin.value.contrasena, requisitos.value, admin.value.email),
)

const coinciden = computed(
  () => admin.value.contrasena.length > 0 && admin.value.contrasena === admin.value.repetida,
)

const nombreEmpresaBien = computed(() => empresa.value.nombre.trim().length >= 3)
const correoBien = computed(() => /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(admin.value.email.trim()))

const puedeEnviar = computed(
  () =>
    nombreEmpresaBien.value &&
    correoBien.value &&
    contrasenaBien.value &&
    coinciden.value &&
    !enviando.value,
)

async function registrar() {
  if (!puedeEnviar.value) return
  enviando.value = true
  error.value = ''

  try {
    await api.registrarEmpresa({
      nombre: empresa.value.nombre.trim(),
      admin_email: admin.value.email.trim(),
      contrasena: admin.value.contrasena,
      admin_nombre: admin.value.nombre.trim() || null,
      // Los campos vacíos se envían como nulos y no como cadena vacía: el servidor interpreta la
      // cadena vacía como «lo escribió y lo dejó en blanco», y para el RUC eso es un error de formato.
      ruc: empresa.value.ruc.trim() || null,
      email_contacto: empresa.value.email_contacto.trim() || null,
      telefono: empresa.value.telefono.trim() || null,
      direccion: empresa.value.direccion.trim() || null,
      ciudad: empresa.value.ciudad.trim() || null,
    })
    emit('registrada', admin.value.email.trim())
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <div class="registro">
    <header class="registro__cabecera">
      <div class="marca">
        <span class="marca__icono" aria-hidden="true">CP</span>
        <span class="marca__texto">Contratación pública</span>
      </div>
      <div class="registro__cabecera-acciones">
        <button type="button" class="boton boton--fantasma boton--pequeno" @click="emit('ir-a-acceso')">
          Ya tengo cuenta
        </button>
        <button
          type="button"
          class="boton boton--fantasma boton--icono"
          :aria-label="tema === 'oscuro' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'"
          @click="emit('alternar-tema')"
        >
          <span aria-hidden="true">{{ tema === 'oscuro' ? '☀' : '☾' }}</span>
        </button>
      </div>
    </header>

    <main class="registro__cuerpo">
      <div class="registro__intro aparece">
        <h1>Crea la cuenta de tu empresa</h1>
        <p>
          Quien se registra queda como <strong>administrador de su empresa</strong>: podrá crear las
          cuentas de su equipo, asignarles la contraseña y darlas de baja cuando haga falta.
        </p>
        <p class="registro__aviso-prueba">
          Tu empresa empieza con <strong>30 días de acceso a todas las vistas</strong>, para que puedas
          comprobar si el producto te sirve antes de decidir nada.
        </p>
      </div>

      <form class="registro__formulario aparece retardo-1" @submit.prevent="registrar">
        <!-- Bloque 1 -->
        <fieldset class="bloque">
          <legend class="bloque__titulo">
            <span class="bloque__numero" aria-hidden="true">1</span>
            Tu empresa
          </legend>

          <label class="campo">
            <span class="campo__etiqueta">
              Nombre o razón social <span class="campo__obligatorio">obligatorio</span>
            </span>
            <input
              v-model="empresa.nombre"
              class="entrada"
              type="text"
              maxlength="160"
              placeholder="Constructora del Pacífico Cía. Ltda."
              :aria-invalid="empresa.nombre.length > 0 && !nombreEmpresaBien"
            />
            <span v-if="empresa.nombre.length > 0 && !nombreEmpresaBien" class="campo__error">
              Escribe al menos 3 caracteres.
            </span>
          </label>

          <div class="rejilla-dos">
            <label class="campo">
              <span class="campo__etiqueta">RUC <span class="campo__opcional">opcional</span></span>
              <input v-model="empresa.ruc" class="entrada" type="text" maxlength="20" placeholder="1790012344001" />
              <span class="campo__ayuda">Se comprueba el dígito verificador.</span>
            </label>

            <label class="campo">
              <span class="campo__etiqueta">Ciudad <span class="campo__opcional">opcional</span></span>
              <input v-model="empresa.ciudad" class="entrada" type="text" maxlength="80" placeholder="Quito" />
            </label>
          </div>

          <div class="rejilla-dos">
            <label class="campo">
              <span class="campo__etiqueta">Teléfono <span class="campo__opcional">opcional</span></span>
              <input v-model="empresa.telefono" class="entrada" type="tel" maxlength="20" placeholder="+593 99 123 4567" />
            </label>

            <label class="campo">
              <span class="campo__etiqueta">Correo de contacto <span class="campo__opcional">opcional</span></span>
              <input v-model="empresa.email_contacto" class="entrada" type="email" maxlength="254" placeholder="contacto@empresa.ec" />
            </label>
          </div>

          <label class="campo">
            <span class="campo__etiqueta">Dirección <span class="campo__opcional">opcional</span></span>
            <input v-model="empresa.direccion" class="entrada" type="text" maxlength="200" placeholder="Av. Amazonas 1234 y Colón" />
          </label>
        </fieldset>

        <!-- Bloque 2 -->
        <fieldset class="bloque">
          <legend class="bloque__titulo">
            <span class="bloque__numero" aria-hidden="true">2</span>
            Tu cuenta de administrador
          </legend>

          <p class="bloque__nota">
            Con estos datos entrarás al panel, y serás quien gestione las cuentas del equipo.
          </p>

          <label class="campo">
            <span class="campo__etiqueta">Tu nombre <span class="campo__opcional">opcional</span></span>
            <input v-model="admin.nombre" class="entrada" type="text" maxlength="120" placeholder="Ana Pérez" />
          </label>

          <label class="campo">
            <span class="campo__etiqueta">
              Correo electrónico <span class="campo__obligatorio">obligatorio</span>
            </span>
            <input
              v-model="admin.email"
              class="entrada"
              type="email"
              maxlength="254"
              placeholder="gerencia@empresa.ec"
              autocomplete="username"
              :aria-invalid="admin.email.length > 0 && !correoBien"
            />
            <span v-if="admin.email.length > 0 && !correoBien" class="campo__error">
              Ese correo no tiene forma de dirección de correo.
            </span>
            <span v-else class="campo__ayuda">
              Un correo solo puede pertenecer a una empresa.
            </span>
          </label>

          <div class="rejilla-dos">
            <CampoContrasena
              id="registro-clave"
              v-model="admin.contrasena"
              etiqueta="Contraseña"
              ajuste="new-password"
              obligatorio
              :maxlength="128"
            />

            <CampoContrasena
              id="registro-clave-repetida"
              v-model="admin.repetida"
              etiqueta="Repite la contraseña"
              ajuste="new-password"
              obligatorio
              :maxlength="128"
            />
          </div>

          <!-- La lista se completa mientras se escribe: es lo que evita descubrir la política al
               pulsar el botón y tener que rehacer el formulario. -->
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
            <li
              class="requisitos__fila"
              :class="{ 'requisitos__fila--bien': coinciden }"
            >
              <span aria-hidden="true">{{ coinciden ? '✓' : '·' }}</span>
              Las dos contraseñas coinciden
            </li>
          </ul>
        </fieldset>

        <p v-if="error" class="registro__error" role="alert">{{ error }}</p>

        <div class="registro__acciones">
          <button type="submit" class="boton boton--principal" :disabled="!puedeEnviar">
            <span v-if="enviando" class="girador" aria-hidden="true" />
            {{ enviando ? 'Creando la cuenta…' : 'Crear la empresa' }}
          </button>
          <button type="button" class="boton boton--fantasma" @click="emit('ir-a-acceso')">
            Cancelar
          </button>
        </div>
      </form>
    </main>
  </div>
</template>

<style scoped>
.registro {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.registro__cabecera {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-4) var(--e-5);
}

.registro__cabecera-acciones {
  display: flex;
  align-items: center;
  gap: var(--e-2);
}

.registro__cuerpo {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr);
  gap: var(--e-7);
  align-items: start;
  max-width: 1180px;
  margin: 0 auto;
  padding: var(--e-5) var(--e-5) var(--e-7);
  width: 100%;
}

.registro__intro h1 {
  font-size: var(--t-3xl);
  letter-spacing: -0.02em;
  line-height: 1.15;
  margin-bottom: var(--e-3);
}

.registro__intro p {
  color: var(--texto-suave);
  line-height: 1.6;
  margin-bottom: var(--e-3);
}

.registro__aviso-prueba {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--ok);
  background: var(--ok-suave);
  color: var(--texto) !important;
  font-size: var(--t-sm);
}

.registro__formulario {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
  padding: var(--e-5);
  border-radius: var(--r-3);
  background: var(--superficie);
  border: 1px solid var(--borde);
  box-shadow: var(--sombra-2);
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  border: 0;
  padding: 0;
  margin: 0;
}

.bloque__titulo {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-md);
  font-weight: 700;
  padding: 0;
  margin-bottom: var(--e-2);
}

.bloque__numero {
  display: grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--acento);
  color: #fff;
  font-size: var(--t-xs);
  font-weight: 700;
}

.bloque__nota {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  line-height: 1.5;
}

.rejilla-dos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-3);
}

.campo__obligatorio,
.campo__opcional {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.campo__obligatorio {
  color: var(--acento);
}

.campo__opcional {
  color: var(--texto-tenue);
}

.campo__error {
  font-size: var(--t-xs);
  color: var(--error);
}

.requisitos {
  list-style: none;
  padding: var(--e-3);
  margin: 0;
  border-radius: var(--r-2);
  background: var(--superficie-2);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-1) var(--e-3);
}

.requisitos__fila {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  transition: color var(--rapido) var(--curva);
}

.requisitos__fila--bien {
  color: var(--ok);
  font-weight: 600;
}

.registro__error {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.registro__acciones {
  display: flex;
  gap: var(--e-3);
}

.girador {
  width: 13px;
  height: 13px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

@media (max-width: 1023px) {
  .registro__cuerpo {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--e-5);
  }

  .registro__intro h1 {
    font-size: var(--t-2xl);
  }
}

@media (max-width: 639px) {
  .rejilla-dos,
  .requisitos {
    grid-template-columns: 1fr;
  }
}
</style>
