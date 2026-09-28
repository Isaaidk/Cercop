<script setup>
/**
 * Pantalla de aceptación de los términos y condiciones.
 *
 * Está construida exactamente como se pidió: **una sola casilla** que dice «Acepto los términos y
 * condiciones» y, en pequeño, un **enlace azul** que agranda el recuadro y muestra el texto
 * completo. No hay dos pantallas ni un asistente por pasos: una casilla y un enlace.
 *
 * Las tres decisiones que hacen que esto valga para algo
 * -----------------------------------------------------
 * **El texto lo sirve el servidor, con su versión y su huella.** No está escrito en este archivo.
 * Podría estarlo —es más cómodo— y sería un error: la evidencia que se guarda tiene que corresponder
 * al texto que se mostró, y si el texto viviera en dos sitios (el panel y la base de datos) el día
 * que uno cambiara la aceptación guardaría la huella de un documento y la persona habría leído otro.
 *
 * **La puerta la decide el servidor.** Esta pantalla aparece porque `GET /v1/politicas` dijo que
 * falta algo, no porque el panel lo deduzca. Y aunque se saltara esta pantalla por completo, el
 * servidor negaría el paso a cualquier dato.
 *
 * **El botón se habilita al llegar al final, y eso es una comodidad, no una garantía.** Conviene
 * decirlo claro: ninguna página puede demostrar que alguien leyó. Lo que sí queda demostrado es
 * **qué texto exacto** estaba delante al pulsar, y de eso se encargan la versión y la huella que se
 * envían al aceptar. Además, la comprobación de «ha llegado al final» se salta sola cuando el texto
 * cabe entero en pantalla: obligar a desplazar un texto que ya se ve sería un obstáculo sin sentido.
 */
import { computed, nextTick, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'

const emit = defineEmits(['alternar-tema'])

defineProps({ tema: { type: String, default: 'claro' } })

const politica = ref(null)
const cargando = ref(false)
const error = ref('')
const expandido = ref(false)
const aceptada = ref(false)
const enviando = ref(false)
const leidoHastaElFinal = ref(false)
const zonaTexto = ref(null)

/** La política que el servidor dice que falta. Solo se atiende a la primera: se encadenan. */
const pendiente = computed(() => sesion.estado.pendientes[0] || null)

const puedeAceptar = computed(
  () => Boolean(politica.value) && leidoHastaElFinal.value && aceptada.value && !enviando.value,
)

/**
 * Carga el texto **cuando aparece la política pendiente**, no al montar el componente.
 *
 * Esto era un defecto real y de los difíciles de ver: al iniciar sesión, esta pantalla se monta en
 * cuanto el servidor confirma la identidad, y en ese instante la lista de pendientes todavía está
 * vacía —llega en la consulta de consentimiento, que es la petición siguiente—. Con la carga en
 * `onMounted`, el componente se montaba, no encontraba nada que pedir y se quedaba en blanco para
 * siempre: el encabezado se veía y el enlace «términos y condiciones» no aparecía nunca, sin ningún
 * error en la consola. La causa era que `onMounted` se ejecuta **una vez** y la lista llega después.
 *
 * Con el vigilante, la carga ocurre cuando ya hay algo que cargar, y también al encadenar el segundo
 * texto obligatorio después de aceptar el primero.
 */
watch(
  () => pendiente.value?.tipo || null,
  async (tipo) => {
    if (!tipo) return
    if (politica.value?.tipo === tipo) return
    if (cargando.value) return
    await cargarTexto()
  },
  { immediate: true },
)

async function cargarTexto() {
  if (!pendiente.value) return
  cargando.value = true
  error.value = ''
  try {
    politica.value = await api.textoPolitica(pendiente.value.tipo)
    // Al abrir el panel con el texto delante no se sabe si llegará a leerse. Se comprueba en cuanto
    // se pinta, porque un texto que cabe entero ya está «leído hasta el final».
    await nextTick()
    comprobarFinal()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

async function abrirTexto() {
  expandido.value = !expandido.value
  if (!expandido.value) return

  await nextTick()
  comprobarFinal()
  // Se lleva la vista al recuadro para que la persona vea que se ha abierto: si el texto empieza
  // justo debajo del pliegue, sin esto parecería que el enlace no hizo nada.
  zonaTexto.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

/**
 * ¿Ha llegado al final del texto?
 *
 * Se admite un margen de 24 píxeles porque los tamaños de línea de los distintos sistemas hacen que
 * el cálculo exacto del final no coincida nunca: sin margen, el botón no se habilitaría aunque la
 * persona hubiera llegado hasta el final, y eso es peor que habilitarlo un poco antes.
 */
function comprobarFinal() {
  const elemento = zonaTexto.value
  if (!elemento) return

  const cabe = elemento.scrollHeight <= elemento.clientHeight + 24
  const alFinal = elemento.scrollTop + elemento.clientHeight >= elemento.scrollHeight - 24
  leidoHastaElFinal.value = cabe || alFinal
}

async function aceptar() {
  if (!puedeAceptar.value) return

  enviando.value = true
  error.value = ''
  try {
    // Se envía **la versión y la huella que el servidor entregó**, no las que el panel calcule.
    // Si el texto cambió mientras se leía, no coincidirán y el servidor rechazará la aceptación:
    // es exactamente lo que se quiere, porque registrar la lectura de un texto que ya no es el
    // vigente sería guardar una prueba falsa.
    await sesion.aceptar(politica.value.tipo, politica.value.version, politica.value.hash)

    if (sesion.debeAceptar.value) {
      // Queda otro texto obligatorio: se carga el siguiente sin salir de la pantalla.
      politica.value = null
      expandido.value = false
      aceptada.value = false
      leidoHastaElFinal.value = false
      await cargarTexto()
    }
  } catch (fallo) {
    error.value = fallo.message
    // Si el texto cambió, hay que volver a traerlo: el que está en pantalla ya no es el vigente.
    if (fallo.estado === 409 || fallo.estado === 422) {
      expandido.value = true
      await cargarTexto()
    }
  } finally {
    enviando.value = false
  }
}
</script>

<template>
  <div class="terminos">
    <header class="terminos__cabecera aparece">
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

    <main class="terminos__cuerpo">
      <section class="terminos__tarjeta aparece retardo-1">
        <p class="terminos__paso">Un paso antes de empezar</p>
        <h1>Para usar el panel necesitamos tu consentimiento</h1>
        <p class="terminos__intro">
          {{ sesion.estado.nombre ? `${sesion.estado.nombre}, lee` : 'Lee' }} y acepta las condiciones
          de uso del aplicativo. Sin este paso el panel permanece bloqueado, y lo decide el servidor:
          no es una pantalla que se pueda saltar.
        </p>

        <div v-if="error" class="aviso-error" role="alert">
          <strong>No se pudo completar</strong>
          <span>{{ error }}</span>
        </div>

        <div v-if="cargando && !politica" class="terminos__cargando">
          <span class="esqueleto esqueleto--titulo" />
          <span class="esqueleto esqueleto--linea" />
          <span class="esqueleto esqueleto--linea corta" />
        </div>

        <template v-else-if="politica">
          <div class="terminos__ficha">
            <div>
              <p class="terminos__ficha-titulo">{{ politica.titulo }}</p>
              <p class="terminos__ficha-dato">
                Versión {{ politica.version }} ·
                <span class="numeros">{{ politica.hash.slice(0, 12) }}…</span>
              </p>
            </div>
            <span class="etiqueta etiqueta--acento">Obligatoria</span>
          </div>

          <button
            type="button"
            class="enlace"
            :aria-expanded="expandido"
            aria-controls="texto-terminos"
            @click="abrirTexto"
          >
            {{ expandido ? 'Ocultar los términos y condiciones' : 'términos y condiciones' }}
            <span class="enlace__flecha" :class="{ 'enlace__flecha--arriba': expandido }" aria-hidden="true">▾</span>
          </button>

          <!--
            El recuadro se despliega con una animación de altura. Se usa una transición y no
            `v-show` para que el crecimiento se vea: aparecer de golpe un bloque de texto largo
            desorienta, porque el resto de la página salta sin avisar.
          -->
          <Transition name="desplegar">
            <div v-if="expandido" id="texto-terminos" class="terminos__lector">
              <div
                ref="zonaTexto"
                class="terminos__texto"
                tabindex="0"
                role="region"
                aria-label="Texto completo de los términos y condiciones"
                @scroll="comprobarFinal"
              >
                <pre class="terminos__pre">{{ politica.texto }}</pre>
              </div>

              <p class="terminos__progreso" :class="{ 'terminos__progreso--listo': leidoHastaElFinal }">
                <span aria-hidden="true">{{ leidoHastaElFinal ? '✓' : '↓' }}</span>
                {{ leidoHastaElFinal ? 'Has llegado al final del documento' : 'Desplázate para leer todo el documento' }}
              </p>
            </div>
          </Transition>

          <label class="casilla" :class="{ 'casilla--bloqueada': !leidoHastaElFinal }">
            <input
              v-model="aceptada"
              type="checkbox"
              :disabled="!leidoHastaElFinal"
              class="casilla__control"
            />
            <span class="casilla__marca" aria-hidden="true" />
            <span class="casilla__texto">
              Acepto los términos y condiciones
              <small v-if="!leidoHastaElFinal">
                Primero abre el enlace y lee el documento completo.
              </small>
            </span>
          </label>

          <div class="terminos__acciones">
            <button
              type="button"
              class="boton boton--principal boton--ancho"
              :disabled="!puedeAceptar"
              @click="aceptar"
            >
              <span v-if="enviando" class="girador" aria-hidden="true" />
              {{ enviando ? 'Registrando tu aceptación…' : 'Aceptar y continuar' }}
            </button>

            <button type="button" class="boton boton--fantasma" @click="sesion.salir()">
              Cerrar sesión
            </button>
          </div>

          <p class="terminos__letra-pequena">
            Al aceptar se guarda la versión del texto y su huella digital junto a la fecha, para que
            puedas comprobar en cualquier momento qué aceptaste y cuándo.
          </p>
        </template>
      </section>
    </main>
  </div>
</template>

<style scoped>
.terminos {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.terminos__cabecera {
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
  letter-spacing: 0.02em;
}

.marca__texto {
  font-weight: 650;
  letter-spacing: -0.01em;
}

.terminos__cuerpo {
  flex: 1;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: var(--e-4) var(--e-5) var(--e-7);
}

.terminos__tarjeta {
  width: 100%;
  max-width: 720px;
  padding: var(--e-6);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-4);
  box-shadow: var(--sombra-3);
}

.terminos__paso {
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--acento);
  margin-bottom: var(--e-2);
}

.terminos__tarjeta h1 {
  font-size: var(--t-xl);
  margin-bottom: var(--e-3);
}

.terminos__intro {
  color: var(--texto-suave);
  margin-bottom: var(--e-5);
}

.aviso-error {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--e-3) var(--e-4);
  margin-bottom: var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.terminos__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4) 0;
}

.esqueleto--titulo {
  display: block;
  height: 18px;
  width: 45%;
}
.esqueleto--linea {
  display: block;
  height: 12px;
  width: 100%;
}
.esqueleto--linea.corta {
  width: 62%;
}

.terminos__ficha {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

.terminos__ficha-titulo {
  font-weight: 600;
  font-size: var(--t-base);
}

.terminos__ficha-dato {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

/* El enlace azul, en pequeño, tal y como se pidió. */
.enlace {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin: var(--e-3) 0;
  padding: 0;
  border: 0;
  background: none;
  color: var(--acento);
  font-size: var(--t-sm);
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  transition: color var(--rapido) var(--curva);
}

.enlace:hover {
  color: var(--acento-fuerte);
}

.enlace__flecha {
  display: inline-block;
  font-size: 0.7em;
  transition: transform var(--normal) var(--curva);
}

.enlace__flecha--arriba {
  transform: rotate(180deg);
}

.terminos__lector {
  margin-bottom: var(--e-4);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  overflow: hidden;
  background: var(--superficie-2);
}

.terminos__texto {
  max-height: 320px;
  overflow-y: auto;
  padding: var(--e-4) var(--e-5);
  /* La línea de desplazamiento se marca para que se vea que hay más texto debajo. */
  scrollbar-width: thin;
}

.terminos__texto:focus-visible {
  outline-offset: -2px;
}

.terminos__pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--fuente);
  font-size: var(--t-sm);
  line-height: 1.7;
  color: var(--texto-suave);
}

.terminos__progreso {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  padding: var(--e-2) var(--e-5);
  border-top: 1px solid var(--borde);
  background: var(--superficie-3);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  transition: color var(--normal) var(--curva), background-color var(--normal) var(--curva);
}

.terminos__progreso--listo {
  color: var(--ok);
  background: var(--ok-suave);
}

.casilla {
  display: flex;
  align-items: flex-start;
  gap: var(--e-3);
  padding: var(--e-4);
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  cursor: pointer;
  transition:
    border-color var(--normal) var(--curva),
    background-color var(--normal) var(--curva);
}

.casilla:hover:not(.casilla--bloqueada) {
  border-color: var(--acento);
  background: var(--acento-tenue);
}

.casilla--bloqueada {
  cursor: not-allowed;
  opacity: 0.7;
}

/* La casilla nativa se oculta pero sigue existiendo: es la que recibe el foco, participa en el
   formulario y la lee el lector de pantalla. La «marca» es solo su dibujo. */
.casilla__control {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.casilla__marca {
  flex: none;
  width: 20px;
  height: 20px;
  margin-top: 1px;
  border: 2px solid var(--borde-fuerte);
  border-radius: 5px;
  transition:
    background-color var(--rapido) var(--curva),
    border-color var(--rapido) var(--curva);
}

.casilla__control:checked + .casilla__marca {
  background: var(--acento);
  border-color: var(--acento);
  /* La palomita se dibuja con un borde girado; no hace falta ninguna imagen. */
  background-image: linear-gradient(45deg, transparent 45%, #fff 45%, #fff 55%, transparent 55%),
    linear-gradient(-45deg, transparent 45%, #fff 45%, #fff 55%, transparent 55%);
  background-size: 60% 60%;
  background-position: center;
  background-repeat: no-repeat;
  transform: rotate(0deg);
}

.casilla__control:focus-visible + .casilla__marca {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
}

.casilla__texto {
  font-weight: 550;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.casilla__texto small {
  font-weight: 400;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
}

.terminos__acciones {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  margin-top: var(--e-5);
}

.boton--ancho {
  flex: 1;
}

.terminos__letra-pequena {
  margin-top: var(--e-4);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.6;
}

.girador {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

/* Despliegue del recuadro de texto */
.desplegar-enter-active,
.desplegar-leave-active {
  transition: opacity var(--normal) var(--curva);
}

.desplegar-enter-from,
.desplegar-leave-to {
  opacity: 0;
}

@media (max-width: 639px) {
  .terminos__tarjeta {
    padding: var(--e-5) var(--e-4);
    border-radius: var(--r-3);
  }

  .terminos__acciones {
    flex-direction: column-reverse;
    align-items: stretch;
  }

  .terminos__texto {
    max-height: 260px;
    padding: var(--e-3) var(--e-4);
  }
}
</style>
