<script setup>
/**
 * Panel de la plataforma: las empresas, su estado y el acceso de su gente.
 *
 * Es la pantalla del dueño del sistema, y por eso enseña cosas que ninguna empresa ve de sí misma: el
 * censo completo, cuántas cuentas tiene cada una y el estado de cada cuenta. Lo que **no** enseña es
 * nada de lo que hay dentro de esas empresas —ni contrataciones, ni palabras clave, ni contenido de
 * sus datos—: administrar la plataforma es decidir quién entra y hasta cuándo, no mirar por dentro.
 *
 * Las vistas se conceden **por cuenta**, no por empresa. No es una limitación de la interfaz sino del
 * modelo: el permiso es de una persona para una vista y con un vencimiento concreto, así que el plazo
 * se elige por cuenta. Concederlo «a la empresa» obligaría a inventar qué significa eso cuando dentro
 * hay gente con permisos distintos.
 *
 * Arriba del todo va el trabajo de los workers, que es lo otro que se administra desde aquí: la
 * ingesta no la lanza un cliente ni el navegador, así que su estado y su botón viven en la pantalla
 * de quien responde por el sistema.
 *
 * Suspender y eliminar están juntos y no se parecen. **Suspender** corta el acceso y se deshace;
 * **eliminar** borra la empresa con sus cuentas y no hay vuelta atrás, así que exige escribir su
 * nombre. La traba está en el servidor —compara el texto y rechaza la petición—; el botón
 * deshabilitado de aquí solo evita mandar algo que se sabe que va a ser rechazado.
 */
import { computed, onMounted, ref } from 'vue'

import TrabajoWorkers from '@/components/TrabajoWorkers.vue'
import { api } from '@/api/endpoints'
import { sesion } from '@/stores/sesion'
import { fechaCorta } from '@/utils/formato'

const empresas = ref([])
const catalogo = ref({ vistas: [], plazos: [] })
const cargando = ref(true)
const error = ref('')
const aviso = ref('')

/** La empresa abierta, si hay alguna. Solo se carga su gente cuando se abre. */
const abierta = ref(null)
const usuarios = ref([])
const cargandoUsuarios = ref(false)
const ocupado = ref('')

/** El plazo elegido para cada cuenta. Arranca en el mínimo, que es el que menos compromete. */
const plazos = ref({})

/**
 * Qué borrado está pidiendo confirmación, y qué se ha escrito en la casilla.
 *
 * Hay un solo par de variables para las dos cosas —empresas y cuentas— porque dos confirmaciones a
 * la vez no significan nada, y tener dos estados distintos dejaría la puerta abierta a que las dos
 * casillas estuvieran vivas enseñando el mismo texto.
 */
const borrando = ref('')
const confirmacion = ref('')

function abrirBorrado(clave) {
  borrando.value = borrando.value === clave ? '' : clave
  confirmacion.value = ''
  error.value = ''
  aviso.value = ''
}

function cerrarBorrado() {
  borrando.value = ''
  confirmacion.value = ''
}

/**
 * ¿Lo escrito coincide con lo que hay que escribir?
 *
 * Se compara en minúsculas y sin espacios de sobra, igual que el servidor: es una traba contra el
 * descuido, no un examen de mecanografía. La comprobación de verdad es la del servidor, que la
 * repite por si alguien llama a la API sin pasar por esta pantalla.
 */
function confirmaCon(texto) {
  return confirmacion.value.trim().toLowerCase() === (texto || '').trim().toLowerCase()
}

const plazosDisponibles = computed(() => catalogo.value.plazos || [])
const vistas = computed(() => catalogo.value.vistas || [])

function plazoDe(usuarioId) {
  return plazos.value[usuarioId] || plazosDisponibles.value[0]?.codigo || '30d'
}

async function cargar() {
  cargando.value = true
  error.value = ''
  try {
    const [lista, cat] = await Promise.all([api.listarEmpresas(), api.catalogoDeAccesos()])
    empresas.value = lista.empresas || []
    catalogo.value = cat
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargando.value = false
  }
}

onMounted(cargar)

async function alternarEmpresa(empresa) {
  if (abierta.value === empresa.negocio_id) {
    abierta.value = null
    usuarios.value = []
    return
  }
  abierta.value = empresa.negocio_id
  usuarios.value = []
  cargandoUsuarios.value = true
  try {
    const datos = await api.usuariosDeNegocio(empresa.negocio_id)
    usuarios.value = datos.usuarios || []
    for (const usuario of usuarios.value) {
      if (!plazos.value[usuario.usuario_id]) {
        plazos.value[usuario.usuario_id] = plazosDisponibles.value[0]?.codigo || '30d'
      }
    }
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    cargandoUsuarios.value = false
  }
}

async function cambiarEstado(empresa) {
  ocupado.value = empresa.negocio_id
  error.value = ''
  aviso.value = ''
  try {
    const resultado = empresa.activa
      ? await api.suspenderEmpresa(empresa.negocio_id)
      : await api.reactivarEmpresa(empresa.negocio_id)
    aviso.value = resultado.aviso
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = ''
  }
}

/** Conceder y quitar son el mismo botón: se pulsa la vista y cambia de estado. */
async function alternarVista(usuario, estadoVista) {
  const negocioId = abierta.value
  const marca = `${usuario.usuario_id}:${estadoVista.vista}`
  ocupado.value = marca
  error.value = ''
  aviso.value = ''
  try {
    if (estadoVista.vigente) {
      await api.retirarVista(usuario.usuario_id, negocioId, estadoVista.vista)
      aviso.value = `Se retiró «${estadoVista.etiqueta || estadoVista.vista}» a ${usuario.email}.`
    } else {
      await api.concederVista(
        usuario.usuario_id,
        negocioId,
        estadoVista.vista,
        plazoDe(usuario.usuario_id),
      )
      aviso.value = `Se concedió «${estadoVista.etiqueta || estadoVista.vista}» a ${usuario.email}.`
    }
    const datos = await api.usuariosDeNegocio(negocioId)
    usuarios.value = datos.usuarios || []
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = ''
  }
}

function textoEstado(empresa) {
  if (empresa.estado === 'suspendido') return 'Suspendida'
  if (empresa.estado === 'activo') return 'Activa'
  if (empresa.estado === 'prueba') return 'En prueba'
  return empresa.estado
}

/**
 * Elimina una empresa con sus cuentas. **No se deshace**, y la confirmación viaja con la petición.
 *
 * Después se recarga la lista: la empresa ya no está, y dejarla pintada haría que el siguiente clic
 * sobre ella fallara con «esa empresa no existe», que parece un error del panel y es el resultado
 * correcto de lo que se acaba de hacer.
 */
async function eliminarEmpresa(empresa) {
  ocupado.value = empresa.negocio_id
  error.value = ''
  aviso.value = ''
  try {
    const resultado = await api.eliminarEmpresa(empresa.negocio_id, confirmacion.value.trim())
    aviso.value = `${resultado.nombre} se ha eliminado: ${resultado.cuentas_borradas} ${
      resultado.cuentas_borradas === 1 ? 'cuenta' : 'cuentas'
    } y ${resultado.sesiones_cerradas} ${
      resultado.sesiones_cerradas === 1 ? 'sesión cerrada' : 'sesiones cerradas'
    }.`
    cerrarBorrado()
    if (abierta.value === empresa.negocio_id) abierta.value = null
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = ''
  }
}

/** Elimina una cuenta concreta. Se confirma con su correo, que es lo que se enseña al pedirlo. */
async function eliminarUsuario(usuario) {
  const negocioId = abierta.value
  ocupado.value = usuario.usuario_id
  error.value = ''
  aviso.value = ''
  try {
    const resultado = await api.eliminarUsuarioDeEmpresa(
      negocioId,
      usuario.usuario_id,
      confirmacion.value.trim(),
    )
    aviso.value = `${resultado.nombre || usuario.email} ya no existe. Se cerraron ${
      resultado.sesiones_cerradas
    } ${resultado.sesiones_cerradas === 1 ? 'sesión' : 'sesiones'}.`
    cerrarBorrado()
    const datos = await api.usuariosDeNegocio(negocioId)
    usuarios.value = datos.usuarios || []
    // El recuento de cuentas de la cabecera acaba de cambiar; se refresca para no mentir.
    await cargar()
  } catch (fallo) {
    error.value = fallo.message
  } finally {
    ocupado.value = ''
  }
}
</script>

<template>
  <section class="plataforma">
    <TrabajoWorkers />

    <header class="plataforma__cabecera">
      <div>
        <h2 class="plataforma__titulo">Empresas de la plataforma</h2>
        <p class="plataforma__pista">
          <span class="numeros">{{ empresas.length }}</span>
          {{ empresas.length === 1 ? 'empresa registrada' : 'empresas registradas' }}. Suspende o
          devuelve el acceso, ajusta hasta cuándo puede ver cada persona, o elimina una empresa con
          sus cuentas.
        </p>
      </div>
    </header>

    <p v-if="error" class="plataforma__error" role="alert">{{ error }}</p>
    <p v-if="aviso" class="plataforma__aviso" role="status">{{ aviso }}</p>

    <div v-if="cargando" class="plataforma__cargando">
      <span v-for="fila in 4" :key="fila" class="esqueleto plataforma__esqueleto" />
    </div>

    <p v-else-if="!empresas.length" class="plataforma__vacio">
      No hay ninguna empresa registrada todavía.
    </p>

    <ul v-else class="plataforma__lista">
      <li v-for="empresa in empresas" :key="empresa.negocio_id" class="plataforma__empresa">
        <div class="plataforma__fila">
          <div class="plataforma__identidad">
            <p class="plataforma__nombre">{{ empresa.nombre }}</p>
            <p class="plataforma__detalle">
              <template v-if="empresa.ruc">RUC {{ empresa.ruc }} · </template>
              <template v-if="empresa.ciudad">{{ empresa.ciudad }} · </template>
              <span class="numeros">{{ empresa.cuentas_activas }}</span> de
              <span class="numeros">{{ empresa.limite_usuarios }}</span> cuentas ·
              desde {{ fechaCorta(empresa.creado_en) }}
            </p>
            <p v-if="empresa.email_contacto" class="plataforma__detalle">
              {{ empresa.email_contacto }}
            </p>
          </div>

          <div class="plataforma__acciones">
            <span
              class="etiqueta"
              :class="empresa.activa ? 'etiqueta--ok' : 'etiqueta--error'"
            >
              {{ textoEstado(empresa) }}
            </span>

            <button
              type="button"
              class="boton boton--secundario boton--pequeno"
              :aria-expanded="abierta === empresa.negocio_id"
              @click="alternarEmpresa(empresa)"
            >
              {{ abierta === empresa.negocio_id ? 'Ocultar accesos' : 'Ver accesos' }}
            </button>

            <button
              type="button"
              class="boton boton--pequeno"
              :class="empresa.activa ? 'boton--peligro' : 'boton--principal'"
              :disabled="ocupado === empresa.negocio_id"
              @click="cambiarEstado(empresa)"
            >
              {{ empresa.activa ? 'Suspender' : 'Reactivar' }}
            </button>

            <!-- Suspender y eliminar están juntos porque son la misma familia de decisiones, pero
                 no se parecen en nada: suspender se deshace y esto no. El estilo y la confirmación
                 son lo único que lo dice antes de pulsar. -->
            <button
              type="button"
              class="boton boton--fantasma boton--pequeno plataforma__eliminar"
              :aria-expanded="borrando === `empresa:${empresa.negocio_id}`"
              :disabled="ocupado === empresa.negocio_id"
              @click="abrirBorrado(`empresa:${empresa.negocio_id}`)"
            >
              Eliminar
            </button>
          </div>
        </div>

        <!-- Borrado de la empresa: exige escribir su nombre. -->
        <div
          v-if="borrando === `empresa:${empresa.negocio_id}`"
          class="plataforma__borrado aparece"
        >
          <p class="plataforma__borrado-aviso">
            Vas a <strong>eliminar «{{ empresa.nombre }}»</strong> con todas sus cuentas. Se pierde
            el registro de aceptación de los términos de su gente y no se puede deshacer. Si solo
            quieres que deje de entrar, usa <strong>Suspender</strong>: es reversible y no borra nada.
          </p>
          <label class="campo">
            <span class="campo__etiqueta">
              Escribe <code>{{ empresa.nombre }}</code> para confirmar
            </span>
            <input v-model="confirmacion" class="entrada" type="text" autocomplete="off" />
          </label>
          <div class="plataforma__borrado-botones">
            <button
              type="button"
              class="boton boton--peligro boton--pequeno"
              :disabled="!confirmaCon(empresa.nombre) || ocupado === empresa.negocio_id"
              @click="eliminarEmpresa(empresa)"
            >
              Eliminar la empresa definitivamente
            </button>
            <button
              type="button"
              class="boton boton--fantasma boton--pequeno"
              @click="cerrarBorrado"
            >
              Cancelar
            </button>
          </div>
        </div>

        <!-- Accesos de la empresa abierta -->
        <div v-if="abierta === empresa.negocio_id" class="plataforma__accesos aparece">
          <p v-if="cargandoUsuarios" class="plataforma__detalle">Cargando las cuentas…</p>

          <p v-else-if="!usuarios.length" class="plataforma__detalle">
            Esta empresa no tiene cuentas.
          </p>

          <template v-else>
            <p class="plataforma__nota">
              Pulsa una vista para concederla o quitarla. El plazo se aplica al conceder, y renovar
              nunca acorta lo que ya estaba concedido.
            </p>

            <div v-for="usuario in usuarios" :key="usuario.usuario_id" class="plataforma__cuenta">
              <div class="plataforma__cuenta-cabecera">
                <span class="plataforma__cuenta-nombre">{{ usuario.nombre || usuario.email }}</span>
                <span class="plataforma__detalle">{{ usuario.email }}</span>
                <span class="etiqueta" :class="usuario.estado === 'activo' ? 'etiqueta--ok' : 'etiqueta--error'">
                  {{ usuario.rol }}
                </span>

                <label class="plataforma__plazo">
                  <span>Plazo</span>
                  <select
                    class="seleccion"
                    :value="plazoDe(usuario.usuario_id)"
                    @change="plazos[usuario.usuario_id] = $event.target.value"
                  >
                    <option v-for="plazo in plazosDisponibles" :key="plazo.codigo" :value="plazo.codigo">
                      {{ plazo.etiqueta }}
                    </option>
                  </select>
                </label>

                <button
                  v-if="usuario.usuario_id !== sesion.estado.usuario"
                  type="button"
                  class="boton boton--fantasma boton--pequeno"
                  :aria-expanded="borrando === `usuario:${usuario.usuario_id}`"
                  :disabled="ocupado === usuario.usuario_id"
                  @click="abrirBorrado(`usuario:${usuario.usuario_id}`)"
                >
                  Eliminar
                </button>
              </div>

              <!-- Borrado de la cuenta: se confirma con su correo. -->
              <div
                v-if="borrando === `usuario:${usuario.usuario_id}`"
                class="plataforma__borrado aparece"
              >
                <p class="plataforma__borrado-aviso">
                  Vas a <strong>borrar la cuenta {{ usuario.email }}</strong> definitivamente. Se
                  pierde su registro de aceptación de los términos, y no se puede deshacer.
                </p>
                <label class="campo">
                  <span class="campo__etiqueta">
                    Escribe <code>{{ usuario.email }}</code> para confirmar
                  </span>
                  <input v-model="confirmacion" class="entrada" type="text" autocomplete="off" />
                </label>
                <div class="plataforma__borrado-botones">
                  <button
                    type="button"
                    class="boton boton--peligro boton--pequeno"
                    :disabled="!confirmaCon(usuario.email) || ocupado === usuario.usuario_id"
                    @click="eliminarUsuario(usuario)"
                  >
                    Eliminar la cuenta definitivamente
                  </button>
                  <button
                    type="button"
                    class="boton boton--fantasma boton--pequeno"
                    @click="cerrarBorrado"
                  >
                    Cancelar
                  </button>
                </div>
              </div>

              <div class="plataforma__vistas">
                <button
                  v-for="estadoVista in usuario.tablero"
                  :key="estadoVista.vista"
                  type="button"
                  class="boton boton--pequeno"
                  :class="estadoVista.vigente ? 'boton--principal' : 'boton--fantasma'"
                  :disabled="ocupado === `${usuario.usuario_id}:${estadoVista.vista}`"
                  :aria-pressed="estadoVista.vigente"
                  :title="
                    estadoVista.vigente
                      ? `Vence el ${fechaCorta(estadoVista.vence_en)}. Pulsa para quitarla.`
                      : 'Pulsa para concederla con el plazo elegido.'
                  "
                  @click="alternarVista(usuario, estadoVista)"
                >
                  <span aria-hidden="true">{{ estadoVista.vigente ? '◉' : '○' }}</span>
                  {{ estadoVista.etiqueta || estadoVista.vista }}
                  <span v-if="estadoVista.vigente && estadoVista.vence_en" class="plataforma__vence">
                    {{ fechaCorta(estadoVista.vence_en) }}
                  </span>
                </button>
              </div>
            </div>
          </template>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.plataforma {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.plataforma__cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  align-items: flex-start;
  justify-content: space-between;
}

.plataforma__titulo {
  font-size: var(--t-lg);
  font-weight: 700;
}

.plataforma__pista,
.plataforma__detalle,
.plataforma__nota {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  line-height: 1.55;
}

.plataforma__nota {
  margin-bottom: var(--e-2);
}

.plataforma__error,
.plataforma__aviso {
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.plataforma__aviso {
  border-left-color: var(--ok);
  background: var(--ok-suave);
  color: var(--ok);
}

.plataforma__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
}

.plataforma__esqueleto {
  height: 76px;
  border-radius: var(--r-2);
}

.plataforma__vacio {
  padding: var(--e-4);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  color: var(--texto-tenue);
  font-size: var(--t-sm);
}

.plataforma__lista {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.plataforma__empresa {
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
  overflow: hidden;
}

.plataforma__fila {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  align-items: flex-start;
  justify-content: space-between;
  padding: var(--e-4);
}

.plataforma__identidad {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.plataforma__nombre {
  font-weight: 700;
  font-size: var(--t-md);
}

.plataforma__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

.plataforma__accesos {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border-top: 1px solid var(--borde);
  background: var(--superficie-2);
}

.plataforma__cuenta {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-3);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie);
}

.plataforma__cuenta-cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

.plataforma__cuenta-nombre {
  font-weight: 600;
  font-size: var(--t-sm);
}

.plataforma__plazo {
  display: flex;
  gap: var(--e-2);
  align-items: center;
  margin-left: auto;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.plataforma__vistas {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.plataforma__vence {
  font-weight: 400;
  opacity: 0.85;
}

/*
 * La confirmación de un borrado, en línea y dentro de la fila.
 *
 * Se queda en el sitio en lugar de abrir un diálogo: lo que hay que leer es de qué empresa se trata,
 * y un diálogo tapa justo la ficha que permite comprobarlo. Misma elección que en la gestión de
 * cuentas, donde el panel en línea también sustituye al diálogo.
 */
.plataforma__borrado {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border-top: 1px solid var(--borde);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
}

.plataforma__borrado-aviso {
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--texto);
}

.plataforma__borrado-botones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

/* El botón de eliminar va apagado hasta que se pasa por encima: la acción destructiva no compite en
   peso visual con «Suspender», que es la que se usa casi siempre. */
.plataforma__eliminar {
  opacity: 0.75;
}

.plataforma__eliminar:hover {
  opacity: 1;
}
</style>
