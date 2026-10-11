<script setup>
/**
 * Armazón del panel.
 *
 * Decide qué se ve, y en esa decisión hay dos cosas mezcladas que conviene no confundir:
 *
 * **Una: quién eres.** Sin sesión, con sesión pero sin aceptar los términos, o con sesión al día.
 * Quién decide en qué estado estamos es el **servidor**, siempre. Este componente solo obedece al
 * resultado de `sesion.recuperar()` y `sesion.refrescarConsentimiento()`. Si el panel dedujera por
 * su cuenta que ya está todo aceptado, bastaría con editar el navegador para saltarse la aceptación.
 *
 * **Otra: qué dirección has pedido.** La portada, la entrada, el registro o la página de contratación
 * pública. Eso lo resuelve `utils/enrutado.js`, que no sabe nada de sesiones.
 *
 * El orden entre las dos importa, y es la regla que sostiene todo esto: **si hay sesión, la dirección
 * no decide nada.** Quien está dentro ve el panel aunque escriba `/login`, porque su sesión no depende
 * de por dónde haya entrado. Si no hay sesión, se enseña la página que pide la dirección, y ninguna
 * de esas páginas lleva datos de nadie. Así la puerta sigue teniendo una sola llave —la que da el
 * servidor— en lugar de tener además una segunda que se pueda forzar desde la barra del navegador.
 */
import { computed, onMounted, ref, watch } from 'vue'

import AceptacionTerminos from '@/components/AceptacionTerminos.vue'
import EmpresaSuspendida from '@/components/EmpresaSuspendida.vue'
import PantallaAcceso from '@/components/PantallaAcceso.vue'
import PantallaContratacionPublica from '@/components/PantallaContratacionPublica.vue'
import PantallaInicio from '@/components/PantallaInicio.vue'
import PantallaNoEncontrada from '@/components/PantallaNoEncontrada.vue'
import PantallaRegistro from '@/components/PantallaRegistro.vue'
import VistaPanel from '@/components/VistaPanel.vue'
import { sesion } from '@/stores/sesion'
import { ir, paginaActual } from '@/utils/enrutado'
import { aplicarSeo } from '@/utils/seo'

const arrancando = ref(true)
const aviso = ref('')

/**
 * El correo con el que se acaba de crear la empresa.
 *
 * Cuando el registro termina, no se «entra» desde aquí: se vuelve al acceso con el correo ya escrito
 * para que la persona escriba su contraseña. Fabricar una sesión al registrar abriría un segundo
 * camino de autenticación, y es justo lo que el servidor evita.
 *
 * Qué pantalla pública se ve ya no se guarda aquí: lo dice la dirección del navegador.
 */
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
  // Se vuelve al acceso cambiando la dirección, y no una variable interna: así la barra del navegador
  // dice dónde está la persona, y recargar no la devuelve al registro con la cuenta ya creada.
  ir('login')
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
  // Sin sesión manda la dirección. Es lo que permite enlazar la portada, el acceso o el registro, y
  // que recargar en cualquiera de ellas devuelva a la misma.
  if (!sesion.estaIdentificado.value) return paginaActual.value
  // Con sesión, la dirección deja de mandar. Mientras no se haya confirmado con el servidor que no
  // falta nada, se asume que falta: es la postura segura, porque si se asumiera lo contrario un
  // fallo de red dejaría entrar sin aceptar los términos.
  if (sesion.estado.alDia !== true) return 'terminos'
  return 'panel'
})

/**
 * Con la sesión abierta, las direcciones públicas dejan de tener sentido.
 *
 * Si alguien entra y la barra del navegador se queda diciendo `/login`, acaban existiendo dos
 * direcciones sirviendo el mismo panel, y la que se ve no es la que se pidió. Se corrige a la raíz, y
 * con `reemplazar` para que el botón «atrás» no devuelva a la dirección que se acaba de corregir.
 */
watch(fase, (nueva) => {
  if ((nueva === 'panel' || nueva === 'terminos') && paginaActual.value !== 'inicio') {
    ir('inicio', { reemplazar: true })
  }
})

/**
 * El título de la pestaña y las descripciones, según la página que se esté viendo.
 *
 * Durante `cargando` no se toca nada —`aplicarSeo` ignora ese nombre—: todavía no se sabe qué se va a
 * ver, y el documento ya viene con el título de la portada escrito desde `index.html`.
 */
watch(fase, (nueva) => aplicarSeo(nueva), { immediate: true })

/**
 * Salir y volver al acceso.
 *
 * Se espera a que la sesión termine de cerrarse **antes** de moverse de dirección. Al revés, mientras
 * la dirección ya dijera `/login` la sesión seguiría abierta un instante, y el vigilante de arriba
 * vería «panel» en una dirección pública y devolvería a la persona a la portada en lugar del acceso.
 *
 * Se vuelve a `/login` y no a la portada a propósito: quien acaba de cerrar sesión va a entrar otra
 * vez, o a dejar el equipo, y mandarlo a la portada añade un clic a la acción más probable.
 */
async function cerrarSesion() {
  await sesion.salir()
  ir('login')
}

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

    <template v-else-if="fase === 'inicio'">
      <PantallaInicio :tema="tema" @alternar-tema="alternarTema" />
    </template>

    <template v-else-if="fase === 'contratacion'">
      <PantallaContratacionPublica :tema="tema" @alternar-tema="alternarTema" />
    </template>

    <template v-else-if="fase === 'login'">
      <PantallaAcceso
        :tema="tema"
        :correo-inicial="correoRegistrado"
        :mensaje="mensaje"
        @alternar-tema="alternarTema"
        @ir-a-registro="ir('registro')"
      />
    </template>

    <template v-else-if="fase === 'registro'">
      <PantallaRegistro
        :tema="tema"
        @alternar-tema="alternarTema"
        @ir-a-acceso="ir('login')"
        @registrada="alRegistrar"
      />
    </template>

    <template v-else-if="fase === 'no-encontrada'">
      <PantallaNoEncontrada :tema="tema" @alternar-tema="alternarTema" />
    </template>

    <template v-else-if="fase === 'terminos'">
      <AceptacionTerminos :tema="tema" @alternar-tema="alternarTema" />
    </template>

    <template v-else>
      <VistaPanel :tema="tema" @alternar-tema="alternarTema" @cerrar-sesion="cerrarSesion" />
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
