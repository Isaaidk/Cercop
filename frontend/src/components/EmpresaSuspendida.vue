<script setup>
/**
 * Lo único que ve una empresa suspendida.
 *
 * No es un aviso dentro del panel: es una pantalla completa que sustituye al aplicativo entero,
 * porque el acceso está cortado de verdad —el servidor responde `empresa_suspendida` a todas las
 * peticiones— y enseñar el panel con un cartel encima daría a entender que hay algo detrás.
 *
 * El texto **no se escribe aquí**: llega del servidor y se enseña tal cual. El aviso incluye el
 * correo del administrador de la plataforma, y tenerlo en dos sitios sería la forma más segura de
 * que un día digan cosas distintas. Si el mensaje trae una dirección, se convierte en un enlace para
 * que reclamar sea un clic y no copiar y pegar.
 */
import { computed } from 'vue'

import { sesion } from '@/stores/sesion'

const CORREO = /[\w.+-]+@[\w-]+\.[\w.-]+/

const mensaje = computed(
  () => sesion.estado.motivoSuspension || 'Tu cuenta fue suspendida. Contáctate con el administrador.',
)

/** El mensaje partido en texto y dirección, para poder ofrecer el enlace de contacto. */
const partes = computed(() => {
  const encontrado = mensaje.value.match(CORREO)
  if (!encontrado) return { texto: mensaje.value, correo: '' }
  const [correo] = encontrado
  return {
    texto: mensaje.value.replace(correo, '').replace(/\s{2,}/g, ' ').trim(),
    correo: correo.replace(/[.,;]$/, ''),
  }
})
</script>

<template>
  <div class="suspendida">
    <div class="suspendida__fondo" aria-hidden="true" />

    <main class="suspendida__caja aparece">
      <p class="suspendida__icono" aria-hidden="true">⊘</p>

      <h1 class="suspendida__titulo">Tu cuenta está suspendida</h1>

      <p class="suspendida__aviso" role="alert">{{ partes.texto }}</p>

      <a v-if="partes.correo" class="suspendida__correo" :href="`mailto:${partes.correo}`">
        {{ partes.correo }}
      </a>

      <p class="suspendida__nota">
        Mientras la suspensión esté activa no se puede consultar ni ver nada del aplicativo. Tus datos
        y los de tu empresa siguen guardados: cuando se levante la suspensión, todo vuelve a estar
        donde estaba.
      </p>

      <button type="button" class="boton boton--secundario" @click="sesion.salir()">
        Cerrar sesión
      </button>
    </main>
  </div>
</template>

<style scoped>
.suspendida {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--e-5);
  position: relative;
  overflow: hidden;
}

.suspendida__fondo {
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 30% 20%, var(--error-suave), transparent 60%);
  pointer-events: none;
}

.suspendida__caja {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--e-4);
  width: min(560px, 100%);
  padding: var(--e-7);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  background: var(--superficie);
  text-align: center;
}

.suspendida__icono {
  font-size: 2.75rem;
  line-height: 1;
  color: var(--error);
}

.suspendida__titulo {
  font-size: var(--t-xl, 1.375rem);
  font-weight: 700;
}

.suspendida__aviso {
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--texto-suave);
}

.suspendida__correo {
  font-weight: 700;
  font-size: var(--t-md);
  color: var(--acento);
  text-decoration: underline;
}

.suspendida__nota {
  font-size: var(--t-sm);
  line-height: 1.6;
  color: var(--texto-tenue);
}
</style>
