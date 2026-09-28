<script setup>
/**
 * Armazón del panel.
 *
 * Decide qué se ve, y esa decisión tiene tres estados que **no se pueden mezclar**:
 *
 * 1. **Sin sesión** → pantalla de acceso.
 * 2. **Con sesión pero sin aceptar los términos** → pantalla de aceptación. El aplicativo queda
 *    bloqueado aquí: es la puerta que exige la fase legal, y se aplica antes de cargar nada.
 * 3. **Con sesión y al día** → el panel.
 *
 * Quién decide en qué estado estamos es el **servidor**, siempre. Este componente solo obedece al
 * resultado de `sesion.recuperar()` y `sesion.refrescarConsentimiento()`. Si el panel dedujera por
 * su cuenta que ya está todo aceptado, bastaría con editar el navegador para saltarse la aceptación.
 */
import { computed, onMounted, ref } from 'vue'

import AceptacionTerminos from '@/components/AceptacionTerminos.vue'
import EmpresaSuspendida from '@/components/EmpresaSuspendida.vue'
import PantallaAcceso from '@/components/PantallaAcceso.vue'
import PantallaRegistro from '@/components/PantallaRegistro.vue'
import VistaPanel from '@/components/VistaPanel.vue'
import { sesion } from '@/stores/sesion'

const arrancando = ref(true)
const aviso = ref('')

/**
 * Qué pantalla pública se está viendo: el acceso o el registro.
 *
 * Es estado del armazón y no del registro porque el registro no tiene sesión: cuando termina, no se
 * «entra» desde aquí, se vuelve al acceso con el correo ya escrito para que la persona escriba su
 * contraseña. Fabricar una sesión al registrar abriría un segundo camino de autenticación, y es justo
 * lo que el servidor evita.
 */
const vistaPublica = ref('acceso')
const correoRegistrado = ref('')
const mensaje = ref('')

/** El tema se guarda para que la elección sobreviva a la recarga. */
const tema = ref(document.documentElement.dataset.tema || 'claro')

function alternarTema() {
  tema.value = tema.value === 'oscuro' ? 'claro' : 'oscuro'
  document.documentElement.dataset.tema = tema.value
  try {
    localStorage.setItem('tema', tema.value)
  } catch {
    /* sin almacenamiento, el tema dura lo que dure la pestaña */
  }
}

/**
 * Vuelta al acceso después de crear la empresa.
 *
 * Se deja el correo escrito y la contraseña **no**: el registro no crea sesión, así que lo que toca
 * ahora es entrar. Escribir el correo por la persona es un detalle pequeño que evita el error más
 * probable —una errata al teclearlo por segunda vez— y que la cuenta recién creada no encuentre su
 * contraseña.
 */
function alRegistrar(correo) {
  correoRegistrado.value = correo
  vistaPublica.value = 'acceso'
  mensaje.value =
    'Tu empresa ya está creada. Entra con ese correo y la contraseña que acabas de elegir: al entrar ' +
    'se te pedirá aceptar los términos y condiciones.'
}

const fase = computed(() => {
  if (arrancando.value) return 'cargando'
  // La suspensión se mira antes que todo lo demás, incluso antes de saber si hay sesión. Es la
  // única pantalla que **sustituye** al aplicativo: no se enseña el panel con un cartel encima,
  // porque el acceso está cortado de verdad y un panel de fondo daría a entender lo contrario.
  if (sesion.estado.suspendida) return 'suspendido'
  // Sin sesión, el armazón muestra la pantalla pública que toque. `vistaPublica` solo puede valer
  // 'acceso' o 'registro', así que la fase resultante es una de las dos sin más comprobaciones.
  if (!sesion.estaIdentificado.value) return vistaPublica.value
  // Mientras no se haya confirmado con el servidor que no falta nada, se asume que falta. Es la
  // postura segura: si se asumiera lo contrario, un fallo de red dejaría entrar sin aceptar.
  if (sesion.estado.alDia !== true) return 'terminos'
  return 'panel'
})

onMounted(async () => {
  try {
    const recuperada = await sesion.recuperar()
    if (!recuperada) aviso.value = ''
  } finally {
    arrancando.value = false
  }
})
</script>

<template>
  <div class="armazon">
    <!-- El fondo decorativo no aporta información: se oculta a quien usa un lector de pantalla. -->
    <div class="armazon__fondo" aria-hidden="true" />

    <p v-if="fase === 'cargando'" class="armazon__cargando aparece">
      <span class="girador" aria-hidden="true" />
      Comprobando tu sesión…
    </p>

    <template v-else-if="fase === 'suspendido'">
      <EmpresaSuspendida />
    </template>

    <template v-else-if="fase === 'acceso'">
      <PantallaAcceso
        :tema="tema"
        :correo-inicial="correoRegistrado"
        :mensaje="mensaje"
        @alternar-tema="alternarTema"
        @ir-a-registro="vistaPublica = 'registro'"
      />
    </template>

    <template v-else-if="fase === 'registro'">
      <PantallaRegistro
        :tema="tema"
        @alternar-tema="alternarTema"
        @ir-a-acceso="vistaPublica = 'acceso'"
        @registrada="alRegistrar"
      />
    </template>

    <template v-else-if="fase === 'terminos'">
      <AceptacionTerminos :tema="tema" @alternar-tema="alternarTema" />
    </template>

    <template v-else>
      <VistaPanel :tema="tema" @alternar-tema="alternarTema" @cerrar-sesion="sesion.salir()" />
    </template>

    <p v-if="aviso" class="solo-lectores" role="status">{{ aviso }}</p>
  </div>
</template>

<style scoped>
.armazon {
  position: relative;
  min-height: 100vh;
}

/* Dos manchas de color muy suaves tras el contenido. Dan profundidad sin competir con los datos, y
   se quedan fijas al desplazar para que el fondo no «arrastre». */
.armazon__fondo {
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
  background:
    radial-gradient(680px 420px at 8% 0%, color-mix(in srgb, var(--acento) 9%, transparent), transparent 70%),
    radial-gradient(560px 380px at 96% 12%, color-mix(in srgb, var(--serie-2) 8%, transparent), transparent 70%);
}

.armazon__cargando {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--e-3);
  min-height: 100vh;
  color: var(--texto-suave);
  font-size: var(--t-md);
}

.girador {
  width: 18px;
  height: 18px;
  border: 2px solid var(--borde-fuerte);
  border-top-color: var(--acento);
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}
</style>
