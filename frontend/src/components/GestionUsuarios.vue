<script setup>
/**
 * Gestión de las cuentas de la empresa: crear, dar de baja, reactivar, borrar y cambiar contraseñas.
 *
 * Las decisiones que hacen que esto no sea un peligro
 * -------------------------------------------------
 * **«Desactivar» y «Eliminar» son dos botones distintos, con avisos distintos.** No es duplicar
 * acciones: son consecuencias que no se parecen. Desactivar cierra las sesiones y deja de dejar entrar,
 * pero conserva la fila y con ella el registro de que esa persona aceptó los términos; se puede
 * deshacer. Eliminar **destruye ese registro** —la tabla de consentimientos se borra en cascada— y no
 * hay forma de recuperarlo. Tenerlos en el mismo botón con etiquetas parecidas sería la manera de que
 * alguien perdiera evidencia legal por pulsar el que estaba al lado.
 *
 * **El borrado exige escribir el correo de la cuenta.** La confirmación no es un «¿seguro?»: hay que
 * teclear a quién se está borrando. Un diálogo que se acepta con un clic y sin leer no frena nada.
 *
 * **El botón de crear desaparece cuando no caben más cuentas**, y en su lugar se explica por qué. Un
 * botón deshabilitado sin explicación obliga a adivinar; aquí el límite se ve antes de intentarlo.
 *
 * **Nadie puede darse de baja a sí mismo**, y el botón ni se muestra en la fila propia. El servidor lo
 * rechaza igualmente, pero ofrecer una acción que va a fallar es una forma de que la gente desconfíe de
 * la interfaz.
 */
import { computed, onMounted, ref } from 'vue'

import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'
import { ETIQUETAS_ROL } from '@/utils/roles'
import { fechaCorta, haceCuanto } from '@/utils/formato'

const estado = ref({
  usuarios: [],
  limite_usuarios: 0,
  usuarios_activos: 0,
  administradores_activos: 0,
  plazas_libres: 0,
  roles: [],
})

const cargando = ref(true)
const error = ref('')
const avisos = ref([])

/**
 * ¿Ya sabemos de verdad cuántas plazas hay?
 *
 * Sin esta bandera la cabecera pinta el estado inicial —ceros y lista vacía— como si fueran datos
 * del servidor, y durante un instante le dice al administrador que su plan permite 0 cuentas y que
 * tiene que dar de baja a alguien. Es un mensaje alarmante y falso: distinguir «todavía no lo sé» de
 * «no cabe nadie» evita confundir una carga en curso con un problema de plan.
 */
const listo = ref(false)

// Formulario de alta
const creando = ref(false)
const nuevo = ref({ email: '', nombre: '', rol: 'consultor', contrasena: '' })
const enviando = ref(false)
const errorAlta = ref('')

// Acciones sobre una fila
const ocupado = ref(null)
const restableciendo = ref(null)
const contrasenaNueva = ref('')
const borrando = ref(null)
const confirmacion = ref('')

const sinPlazas = computed(() => listo.value && estado.value.plazas_libres <= 0)

const puedeCrear = computed(
  () =>
    nuevo.value.email.includes('@') &&
    nuevo.value.contrasena.length >= 8 &&
    !enviando.value &&
    !sinPlazas.value,
)

async function cargar() {
  cargando.value = true
  error.value = ''
  try {
    estado.value = await api.listarUsuarios(true)
    listo.value = true
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

onMounted(cargar)

function anotar(resultado) {
  avisos.value = [...(resultado?.avisos || []), ...avisos.value].slice(0, 4)
}

async function crear() {
  if (!puedeCrear.value) return
  enviando.value = true
  errorAlta.value = ''
  try {
    const resultado = await api.crearUsuario({
      email: nuevo.value.email.trim(),
      nombre: nuevo.value.nombre.trim() || null,
      rol: nuevo.value.rol,
      contrasena: nuevo.value.contrasena,
    })
    anotar(resultado)
    nuevo.value = { email: '', nombre: '', rol: 'consultor', contrasena: '' }
    creando.value = false
    await cargar()
  } catch (fallo) {
    errorAlta.value = fallo.message
  } finally {
    enviando.value = false
  }
}

async function darDeBaja(usuario) {
  ocupado.value = usuario.usuario_id
  try {
    anotar(await api.darDeBajaUsuario(usuario.usuario_id))
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = null
  }
}

async function reactivar(usuario) {
  ocupado.value = usuario.usuario_id
  try {
    await api.reactivarUsuario(usuario.usuario_id)
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = null
  }
}

async function restablecer(usuario) {
  if (contrasenaNueva.value.length < 8) return
  ocupado.value = usuario.usuario_id
  try {
    anotar(await api.fijarContrasenaDeUsuario(usuario.usuario_id, contrasenaNueva.value))
    restableciendo.value = null
    contrasenaNueva.value = ''
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = null
  }
}

async function eliminar(usuario) {
  ocupado.value = usuario.usuario_id
  try {
    anotar(await api.eliminarUsuario(usuario.usuario_id, confirmacion.value.trim()))
    borrando.value = null
    confirmacion.value = ''
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = null
  }
}

function etiquetaRol(codigo) {
  return ETIQUETAS_ROL[codigo] || codigo
}
</script>

<template>
  <div class="gestion">
    <header class="gestion__cabecera">
      <div>
        <h2 class="gestion__titulo">Cuentas de la empresa</h2>
        <p v-if="listo" class="gestion__resumen">
          <span class="numeros">{{ estado.usuarios_activos }}</span> de
          <span class="numeros">{{ estado.limite_usuarios }}</span> plazas del plan ·
          <span class="numeros">{{ estado.plazas_libres }}</span> libres
        </p>
        <p v-else class="gestion__resumen gestion__resumen--pendiente">
          Comprobando las plazas de tu plan…
        </p>
      </div>

      <button
        v-if="listo && !creando && !sinPlazas"
        type="button"
        class="boton boton--principal"
        @click="creando = true"
      >
        <span aria-hidden="true">＋</span> Crear usuario
      </button>
    </header>

    <!-- Cuando no caben más se explica en lugar de dejar un botón muerto. -->
    <p v-if="sinPlazas" class="gestion__limite" role="status">
      El plan de tu empresa permite <strong>{{ estado.limite_usuarios }} cuentas</strong> y están todas
      ocupadas. Da de baja alguna o pide una ampliación para crear otra.
    </p>

    <!-- Alta -->
    <form v-if="creando" class="alta aparece" @submit.prevent="crear">
      <p class="alta__titulo">Nueva cuenta</p>
      <p class="alta__nota">
        La contraseña la eliges tú y se la comunicas a la persona por un canal privado. Podrá cambiarla
        cuando entre, y al entrar por primera vez tendrá que aceptar los términos y condiciones.
      </p>

      <div class="rejilla-dos">
        <label class="campo">
          <span class="campo__etiqueta">Correo electrónico</span>
          <input v-model="nuevo.email" class="entrada" type="email" maxlength="254" placeholder="persona@empresa.ec" />
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Nombre</span>
          <input v-model="nuevo.nombre" class="entrada" type="text" maxlength="120" placeholder="Ana Pérez" />
        </label>
      </div>

      <div class="rejilla-dos">
        <label class="campo">
          <span class="campo__etiqueta">Rol</span>
          <select v-model="nuevo.rol" class="seleccion">
            <option v-for="rol in estado.roles" :key="rol.codigo" :value="rol.codigo">
              {{ rol.etiqueta }}
            </option>
          </select>
          <span v-if="nuevo.rol" class="campo__ayuda">
            {{ (estado.roles.find((r) => r.codigo === nuevo.rol) || {}).descripcion }}
          </span>
        </label>

        <label class="campo">
          <span class="campo__etiqueta">Contraseña inicial</span>
          <input v-model="nuevo.contrasena" class="entrada" type="text" maxlength="128" autocomplete="off" />
          <span class="campo__ayuda">Mínimo 12 caracteres, con 4 distintos.</span>
        </label>
      </div>

      <p v-if="errorAlta" class="gestion__error" role="alert">{{ errorAlta }}</p>

      <div class="alta__acciones">
        <button type="submit" class="boton boton--principal" :disabled="!puedeCrear">
          <span v-if="enviando" class="girador" aria-hidden="true" />
          {{ enviando ? 'Creando…' : 'Crear la cuenta' }}
        </button>
        <button type="button" class="boton boton--fantasma" @click="creando = false; errorAlta = ''">
          Cancelar
        </button>
      </div>
    </form>

    <!-- Avisos de la última acción: qué se cerró, qué hay que comunicar. -->
    <ul v-if="avisos.length" class="avisos" role="status">
      <li v-for="(texto, indice) in avisos" :key="indice" class="avisos__item">{{ texto }}</li>
    </ul>

    <p v-if="error" class="gestion__error" role="alert">{{ error }}</p>

    <div v-if="cargando" class="gestion__cargando">
      <span v-for="fila in 3" :key="fila" class="esqueleto gestion__esqueleto" />
    </div>

    <ul v-else class="lista">
      <li
        v-for="usuario in estado.usuarios"
        :key="usuario.usuario_id"
        class="cuenta"
        :class="{ 'cuenta--inactiva': !usuario.activo }"
      >
        <div class="cuenta__identidad">
          <span class="cuenta__avatar" aria-hidden="true">{{ (usuario.nombre || usuario.email)[0].toUpperCase() }}</span>
          <div class="cuenta__datos">
            <p class="cuenta__nombre">
              {{ usuario.nombre || usuario.email }}
              <span v-if="usuario.usuario_id === sesion.estado.usuario" class="etiqueta etiqueta--acento">Tú</span>
            </p>
            <p class="cuenta__correo">{{ usuario.email }}</p>
          </div>
        </div>

        <div class="cuenta__meta">
          <span class="etiqueta">{{ etiquetaRol(usuario.rol) }}</span>
          <span class="etiqueta" :class="usuario.activo ? 'etiqueta--ok' : 'etiqueta--error'">
            {{ usuario.activo ? 'Activa' : 'Dada de baja' }}
          </span>
          <span class="cuenta__uso" :title="fechaCorta(usuario.ultimo_acceso)">
            {{ usuario.ultimo_acceso ? `Último acceso ${haceCuanto(usuario.ultimo_acceso)}` : 'Nunca ha entrado' }}
          </span>
        </div>

        <div class="cuenta__acciones">
          <button
            type="button"
            class="boton boton--secundario boton--pequeno"
            @click="restableciendo = restableciendo === usuario.usuario_id ? null : usuario.usuario_id"
          >
            Contraseña
          </button>

          <button
            v-if="usuario.activo"
            type="button"
            class="boton boton--secundario boton--pequeno"
            :disabled="usuario.usuario_id === sesion.estado.usuario || ocupado === usuario.usuario_id"
            :title="usuario.usuario_id === sesion.estado.usuario ? 'No puedes darte de baja a ti mismo' : undefined"
            @click="darDeBaja(usuario)"
          >
            Desactivar
          </button>

          <button
            v-else
            type="button"
            class="boton boton--secundario boton--pequeno"
            :disabled="ocupado === usuario.usuario_id"
            @click="reactivar(usuario)"
          >
            Reactivar
          </button>

          <button
            type="button"
            class="boton boton--peligro boton--pequeno"
            :disabled="usuario.usuario_id === sesion.estado.usuario"
            :title="usuario.usuario_id === sesion.estado.usuario ? 'No puedes borrar tu propia cuenta' : undefined"
            @click="borrando = borrando === usuario.usuario_id ? null : usuario.usuario_id; confirmacion = ''"
          >
            Eliminar
          </button>
        </div>

        <!-- Restablecer contraseña: panel en línea, sin diálogo, para no perder de vista la lista. -->
        <div v-if="restableciendo === usuario.usuario_id" class="panel-accion aparece">
          <label class="campo">
            <span class="campo__etiqueta">Contraseña nueva para esta cuenta</span>
            <input v-model="contrasenaNueva" class="entrada" type="text" maxlength="128" autocomplete="off" />
            <span class="campo__ayuda">
              Se cerrarán todas sus sesiones, incluidas las que tenga abiertas ahora.
            </span>
          </label>
          <div class="panel-accion__botones">
            <button
              type="button"
              class="boton boton--principal boton--pequeno"
              :disabled="contrasenaNueva.length < 8 || ocupado === usuario.usuario_id"
              @click="restablecer(usuario)"
            >
              Guardar la contraseña
            </button>
            <button
              type="button"
              class="boton boton--fantasma boton--pequeno"
              @click="restableciendo = null; contrasenaNueva = ''"
            >
              Cancelar
            </button>
          </div>
        </div>

        <!-- Borrado: exige escribir el correo. -->
        <div v-if="borrando === usuario.usuario_id" class="panel-accion panel-accion--peligro aparece">
          <p class="panel-accion__aviso">
            Vas a <strong>borrar la cuenta definitivamente</strong>. Se pierde su registro de aceptación
            de los términos y condiciones, y no se puede deshacer. Si solo quieres que deje de entrar,
            usa <strong>Desactivar</strong>: es reversible y no pierde nada.
          </p>
          <label class="campo">
            <span class="campo__etiqueta">
              Escribe <code>{{ usuario.email }}</code> para confirmar
            </span>
            <input v-model="confirmacion" class="entrada" type="text" autocomplete="off" />
          </label>
          <div class="panel-accion__botones">
            <button
              type="button"
              class="boton boton--peligro boton--pequeno"
              :disabled="confirmacion.trim().toLowerCase() !== usuario.email.toLowerCase() || ocupado === usuario.usuario_id"
              @click="eliminar(usuario)"
            >
              Eliminar definitivamente
            </button>
            <button
              type="button"
              class="boton boton--fantasma boton--pequeno"
              @click="borrando = null; confirmacion = ''"
            >
              Cancelar
            </button>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.gestion {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.gestion__cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--e-4);
  flex-wrap: wrap;
}

.gestion__titulo {
  font-size: var(--t-lg);
  font-weight: 700;
}

.gestion__resumen {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

/* Mientras se comprueban las plazas se dice con palabras, no con ceros: la cursiva marca que
   todavía no es un dato. */
.gestion__resumen--pendiente {
  font-style: italic;
}

.gestion__limite {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--aviso);
  background: var(--aviso-suave);
  color: var(--aviso);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.gestion__error {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.avisos {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.avisos__item {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  border-left: 3px solid var(--info);
  background: var(--info-suave);
  color: var(--info);
  font-size: var(--t-xs);
  line-height: 1.5;
}

.alta {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border-radius: var(--r-2);
  border: 1px dashed var(--acento);
  background: var(--acento-tenue);
}

.alta__titulo {
  font-weight: 700;
  font-size: var(--t-md);
}

.alta__nota {
  font-size: var(--t-xs);
  color: var(--texto-suave);
  line-height: 1.5;
}

.alta__acciones,
.panel-accion__botones {
  display: flex;
  gap: var(--e-2);
}

.rejilla-dos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-3);
}

.lista {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.cuenta {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--e-4);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
  background: var(--superficie);
  transition: border-color var(--rapido) var(--curva);
}

.cuenta--inactiva {
  opacity: 0.62;
  border-style: dashed;
}

.cuenta__identidad {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  min-width: 0;
}

.cuenta__avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex: none;
  border-radius: 50%;
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  font-weight: 700;
}

.cuenta__datos {
  min-width: 0;
}

.cuenta__nombre {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-weight: 600;
  font-size: var(--t-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cuenta__correo {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  overflow-wrap: anywhere;
}

.cuenta__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-xs);
}

.cuenta__uso {
  color: var(--texto-tenue);
}

.cuenta__acciones {
  display: flex;
  gap: var(--e-2);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.panel-accion {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-3);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

.panel-accion--peligro {
  border-left: 3px solid var(--error);
  background: var(--error-suave);
}

.panel-accion__aviso {
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--texto-suave);
}

.panel-accion__aviso code {
  padding: 0 0.3rem;
  border-radius: var(--r-1);
  background: var(--superficie-3);
  font-family: var(--fuente-numeros);
}

.gestion__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.gestion__esqueleto {
  display: block;
  height: 58px;
  border-radius: var(--r-2);
}

.campo__obligatorio {
  color: var(--acento);
}

.girador {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

@media (max-width: 767px) {
  .cuenta,
  .rejilla-dos {
    grid-template-columns: 1fr;
  }

  .cuenta__acciones {
    justify-content: flex-start;
  }
}
</style>
