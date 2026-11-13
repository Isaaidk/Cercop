<script setup>
/**
 * Registro de una empresa, empezando por el RUC.
 *
 * Cómo está pensado
 * -----------------
 * **El RUC va primero.** Con 13 dígitos bien formados se consulta solo al SRI (desde el navegador y,
 * si no llega, por el servidor) y se llena lo que el SRI publica: razón social, nombre comercial,
 * dirección, ciudad, representante legal, establecimientos y actividad. Así la persona escribe lo
 * mínimo —correo, teléfono y su cuenta— y la empresa nace con el perfil casi completo, que es lo
 * que después rellena los TDR.
 *
 * **Revelado progresivo, sin perder lo escrito.** Los bloques 2 y 3 aparecen cuando el RUC está
 * resuelto (o la persona elige llenar a mano), y desde ahí todo queda a la vista: no es un asistente
 * de pantallas que esconde lo anterior.
 *
 * **Lo del SRI se marca y se puede corregir.** Cada campo traído lleva la marca «del SRI»; si la
 * persona lo cambia, la marca desaparece. Nada se fija sin que lo vea.
 *
 * **La política de contraseñas se pide al servidor** y se muestra como una lista que se completa
 * mientras se escribe.
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'

import { api } from '@/api/endpoints'
import CampoContrasena from '@/components/CampoContrasena.vue'
import PiePublico from '@/components/PiePublico.vue'
import {
  consultarContratosEnNavegador,
  consultarRucEnNavegador,
  rucConForma,
} from '@/utils/consultasPublicas'
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

// --------------------------------------------------------------------------------- RUC y SRI

const ruc = ref({ estado: 'vacio', propuesta: null, error: '', manual: false })
// Lo que el SRI llenó, para marcarlo y para saber si la persona lo cambió después.
const delSri = ref({})
const bloqueEmpresa = ref(null)
let consultaVigente = 0

// CPC y experiencia que los datos abiertos del SERCOP atribuyen al RUC. El RUP no tiene consulta
// pública (su lista de CPC exige entrar al SOCE), así que esto es lo más cercano sin credenciales.
const hist = ref({ estado: 'vacio', datos: null })
const cpcElegidos = ref({})

async function buscarHistorial(rucBuscado, razonSocial) {
  hist.value = { estado: 'cargando', datos: null }
  try {
    const datos = await consultarContratosEnNavegador(rucBuscado, razonSocial)
    if (rucLimpio.value !== rucBuscado) return
    cpcElegidos.value = Object.fromEntries((datos.cpc || []).map((fila) => [fila.codigo, true]))
    hist.value = { estado: datos.cpc?.length ? 'listo' : 'sin-datos', datos }
  } catch {
    if (rucLimpio.value === rucBuscado) hist.value = { estado: 'error', datos: null }
  }
}

const cpcSeleccionados = computed(() =>
  (hist.value.datos?.cpc || []).filter((fila) => cpcElegidos.value[fila.codigo]).map((fila) => fila.codigo),
)

const rucLimpio = computed(() => empresa.value.ruc.replace(/\D/g, ''))
const rucBienFormado = computed(() => rucConForma(rucLimpio.value))
const rucResuelto = computed(() => ruc.value.estado === 'encontrado' || ruc.value.manual)

const pasoActual = computed(() => {
  if (!rucResuelto.value) return 1
  if (!datosEmpresaBien.value) return 2
  return 3
})

watch(rucLimpio, (valor) => {
  if (valor.length < 13) {
    if (ruc.value.estado !== 'vacio') ruc.value = { ...ruc.value, estado: 'vacio', error: '' }
    return
  }
  if (!rucBienFormado.value) {
    ruc.value = { ...ruc.value, estado: 'invalido', error: '' }
    return
  }
  if (ruc.value.propuesta?.ruc !== valor) consultarRuc(valor)
})

async function consultarRuc(valor) {
  const turno = ++consultaVigente
  ruc.value = { ...ruc.value, estado: 'consultando', error: '' }
  try {
    let propuesta
    try {
      propuesta = await consultarRucEnNavegador(valor)
    } catch (fallo) {
      if (fallo.definitivo) throw fallo
      propuesta = await api.consultarRucPublico(valor)
    }
    if (turno !== consultaVigente) return
    aplicarPropuesta(propuesta)
    ruc.value = { estado: 'encontrado', propuesta, error: '', manual: false }
    // Sin esperar: tarda unos segundos y la persona puede seguir llenando mientras tanto.
    if (propuesta.identidad?.razon_social) buscarHistorial(valor, propuesta.identidad.razon_social)
    await nextTick()
    bloqueEmpresa.value?.querySelector('input:not([readonly])[data-falta]')?.focus()
  } catch (fallo) {
    if (turno !== consultaVigente) return
    ruc.value = {
      ...ruc.value,
      estado: 'error',
      propuesta: null,
      error: fallo.definitivo
        ? 'El SRI no tiene un contribuyente con ese RUC. Revísalo o continúa llenando a mano.'
        : 'No pudimos consultar al SRI en este momento. Puedes reintentar o llenar los datos a mano.',
    }
  }
}

function aplicarPropuesta(propuesta) {
  const identidad = propuesta.identidad || {}
  const llenado = {}
  const poner = (campo, valor) => {
    if (!valor) return
    empresa.value[campo] = valor
    llenado[campo] = valor
  }
  poner('nombre', identidad.razon_social)
  poner('direccion', identidad.direccion)
  poner('ciudad', identidad.ciudad)
  // El nombre de la persona solo se sugiere si no lo escribió: es la cuenta de quien se registra,
  // y el representante legal no siempre es quien administra.
  if (!admin.value.nombre && propuesta.representante?.nombre) {
    admin.value.nombre = propuesta.representante.nombre
    llenado.admin_nombre = propuesta.representante.nombre
  }
  delSri.value = llenado
}

function esDelSri(campo, valor) {
  return Boolean(delSri.value[campo]) && delSri.value[campo] === valor
}

function llenarAMano() {
  ruc.value = { ...ruc.value, manual: true, error: '' }
  nextTick(() => bloqueEmpresa.value?.querySelector('input')?.focus())
}

function reintentar() {
  if (rucBienFormado.value) consultarRuc(rucLimpio.value)
}

function soloDigitos(evento) {
  empresa.value.ruc = evento.target.value.replace(/\D/g, '').slice(0, 13)
}

const resumenSri = computed(() => {
  const propuesta = ruc.value.propuesta
  if (!propuesta) return []
  const identidad = propuesta.identidad || {}
  const persona = { natural: 'Persona natural', juridica: 'Sociedad' }[identidad.tipo_persona]
  return [
    ['Nombre comercial', identidad.nombre_comercial],
    ['Tipo', persona],
    ['Régimen', identidad.regimen_tributario],
    ['Contabilidad', identidad.obligado_contabilidad ? 'Obligado a llevar' : 'No obligado'],
    ['Inicio de actividades', identidad.fecha_inicio_actividades],
    ['Representante legal', propuesta.representante?.nombre],
    ['Actividad principal', propuesta.actividad],
    [
      'Establecimientos abiertos',
      propuesta.cobertura?.length
        ? propuesta.cobertura.map((fila) => [fila.canton, fila.provincia].filter(Boolean).join(', ')).join(' · ')
        : '',
    ],
  ].filter(([, valor]) => valor)
})

const estadoSri = computed(() => {
  const estado = ruc.value.propuesta?.estado_sri || ''
  return { texto: estado ? estado.toLowerCase() : 'sin estado', activo: estado === 'ACTIVO' }
})

// --------------------------------------------------------------------------------- validación

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

const formaCorreo = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const nombreEmpresaBien = computed(() => empresa.value.nombre.trim().length >= 3)
const correoBien = computed(() => formaCorreo.test(admin.value.email.trim()))
const correoContactoBien = computed(
  () => !empresa.value.email_contacto.trim() || formaCorreo.test(empresa.value.email_contacto.trim()),
)
const datosEmpresaBien = computed(
  () => nombreEmpresaBien.value && (rucBienFormado.value || ruc.value.manual) && correoContactoBien.value,
)

const faltan = computed(() => {
  const lista = []
  if (!rucResuelto.value) lista.push('el RUC')
  else if (!nombreEmpresaBien.value) lista.push('la razón social')
  if (!correoBien.value) lista.push('tu correo')
  if (!contrasenaBien.value) lista.push('una contraseña válida')
  else if (!coinciden.value) lista.push('repetir la contraseña')
  return lista
})

const puedeEnviar = computed(
  () =>
    rucResuelto.value &&
    datosEmpresaBien.value &&
    correoBien.value &&
    contrasenaBien.value &&
    coinciden.value &&
    !enviando.value,
)

async function registrar() {
  if (!puedeEnviar.value) return
  enviando.value = true
  error.value = ''

  const propuesta = ruc.value.propuesta
  try {
    await api.registrarEmpresa({
      nombre: empresa.value.nombre.trim(),
      admin_email: admin.value.email.trim(),
      contrasena: admin.value.contrasena,
      admin_nombre: admin.value.nombre.trim() || null,
      // Los campos vacíos se envían como nulos y no como cadena vacía: el servidor interpreta la
      // cadena vacía como «lo escribió y lo dejó en blanco», y para el RUC eso es un error de formato.
      ruc: rucLimpio.value || null,
      email_contacto: empresa.value.email_contacto.trim() || null,
      telefono: empresa.value.telefono.trim() || null,
      direccion: empresa.value.direccion.trim() || null,
      ciudad: empresa.value.ciudad.trim() || null,
      // Lo que el SRI publica deja listo el perfil con el que después se rellenan los TDR.
      perfil:
        propuesta && propuesta.ruc === rucLimpio.value
          ? {
              identidad: {
                ...propuesta.identidad,
                razon_social: empresa.value.nombre.trim(),
                direccion: empresa.value.direccion.trim() || undefined,
                ciudad: empresa.value.ciudad.trim() || undefined,
              },
              representante: propuesta.representante || undefined,
              cobertura: propuesta.cobertura || [],
              actividad: propuesta.actividad || undefined,
              cpc: cpcSeleccionados.value,
              experiencia: hist.value.datos?.experiencia || [],
            }
          : null,
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
        <span class="marca__icono">
          <img src="/logo-cercoapp.png" alt="" width="36" height="36" />
        </span>
        <span class="marca__texto">CercoApp</span>
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
      <aside class="registro__intro aparece">
        <h1>Crea la cuenta de tu empresa en un minuto</h1>
        <p>
          Escribe tu <strong>RUC</strong> y traemos del SRI tu razón social, dirección,
          establecimientos y representante legal. Tú solo completas el contacto y tu contraseña.
        </p>

        <ol class="pasos" aria-label="Pasos del registro">
          <li
            v-for="(titulo, n) in ['Tu RUC', 'Datos de la empresa', 'Tu cuenta']"
            :key="titulo"
            class="pasos__paso"
            :class="{
              'pasos__paso--hecho': pasoActual > n + 1,
              'pasos__paso--actual': pasoActual === n + 1,
            }"
            :aria-current="pasoActual === n + 1 ? 'step' : undefined"
          >
            <span class="pasos__marca" aria-hidden="true">{{ pasoActual > n + 1 ? '✓' : n + 1 }}</span>
            {{ titulo }}
          </li>
        </ol>

        <p class="registro__aviso-prueba">
          Tu empresa empieza con <strong>7 días de acceso a todas las vistas</strong> y
          <strong>100 créditos de IA de bienvenida</strong>, para que compruebes si el producto te
          sirve antes de decidir nada.
        </p>
        <ul class="registro__incluye" aria-label="Qué tendrás al entrar">
          <li>Ínfimas cuantías y necesidades de contratación del SERCOP, al día.</li>
          <li>Propuestas para ti y alertas por tus códigos CPC o palabras clave.</li>
          <li>Un asistente con IA al que le preguntas con tus palabras.</li>
          <li>Tu proforma en 4 pasos, en PDF o Word, y el seguimiento de tus ofertas.</li>
        </ul>
        <p class="registro__nota">
          Después, en «Perfil de empresa», puedes subir tu RUP en PDF —aunque esté escaneado— y
          leemos tus códigos CPC para afinar las propuestas.
        </p>
        <p class="registro__nota">
          Quien se registra queda como <strong>administrador de la empresa</strong> y podrá crear las
          cuentas de su equipo.
        </p>
      </aside>

      <form class="registro__formulario aparece retardo-1" novalidate @submit.prevent="registrar">
        <!-- Bloque 1: RUC -->
        <fieldset class="bloque">
          <legend class="bloque__titulo">
            <span class="bloque__numero" aria-hidden="true">1</span>
            Empieza con tu RUC
          </legend>

          <div class="campo">
            <label class="campo__etiqueta" for="registro-ruc">
              RUC de la empresa <span class="campo__obligatorio">obligatorio</span>
            </label>
            <div class="ruc" :class="`ruc--${ruc.estado}`">
              <input
                id="registro-ruc"
                :value="empresa.ruc"
                class="entrada ruc__entrada numeros"
                type="text"
                inputmode="numeric"
                autocomplete="off"
                maxlength="13"
                placeholder="1790012344001"
                autofocus
                :aria-invalid="ruc.estado === 'invalido'"
                aria-describedby="registro-ruc-ayuda"
                @input="soloDigitos"
              />
              <span class="ruc__contador numeros" aria-hidden="true">{{ rucLimpio.length }}/13</span>
              <span v-if="ruc.estado === 'consultando'" class="ruc__girador" aria-hidden="true" />
              <span v-else-if="ruc.estado === 'encontrado'" class="ruc__ok" aria-hidden="true">✓</span>
            </div>
            <span id="registro-ruc-ayuda" class="campo__ayuda" aria-live="polite">
              <template v-if="ruc.estado === 'consultando'">Consultando al SRI…</template>
              <template v-else-if="ruc.estado === 'invalido'">
                <span class="campo__error">Ese RUC no tiene una forma válida. Revisa los dígitos.</span>
              </template>
              <template v-else-if="ruc.estado === 'encontrado'">Datos traídos del SRI. Revísalos abajo.</template>
              <template v-else>Al escribir los 13 dígitos consultamos al SRI automáticamente.</template>
            </span>
          </div>

          <div v-if="ruc.estado === 'consultando'" class="sri sri--cargando" aria-hidden="true">
            <span class="esqueleto" style="width: 70%; height: 18px" />
            <span class="esqueleto" style="width: 45%; height: 12px" />
            <span class="esqueleto" style="width: 90%; height: 12px" />
          </div>

          <div v-else-if="ruc.estado === 'encontrado' && ruc.propuesta" class="sri aparece">
            <div class="sri__cabecera">
              <div>
                <p class="sri__razon">{{ ruc.propuesta.identidad?.razon_social || empresa.nombre }}</p>
                <p class="sri__ruc numeros">RUC {{ ruc.propuesta.ruc }}</p>
              </div>
              <span class="etiqueta" :class="estadoSri.activo ? 'etiqueta--ok' : 'etiqueta--aviso'">
                {{ estadoSri.texto }}
              </span>
            </div>
            <dl class="sri__datos">
              <div v-for="[nombre, valor] in resumenSri" :key="nombre" class="sri__dato">
                <dt>{{ nombre }}</dt>
                <dd>{{ valor }}</dd>
              </div>
            </dl>
            <ul v-if="ruc.propuesta.avisos?.length" class="sri__avisos">
              <li v-for="aviso in ruc.propuesta.avisos" :key="aviso">{{ aviso }}</li>
            </ul>
            <p class="sri__pie">
              Todo esto queda guardado en el perfil de tu empresa y se usa para rellenar tus
              proformas. El SRI no publica correo ni teléfono: complétalos abajo.
            </p>
          </div>

          <div v-if="ruc.estado === 'encontrado' && hist.estado !== 'vacio'" class="historial aparece" aria-live="polite">
            <p class="historial__titulo">CPC con los que ya vendiste al Estado</p>
            <template v-if="hist.estado === 'cargando'">
              <p class="historial__nota">
                <span class="ruc__girador historial__girador" aria-hidden="true" />
                Buscando tus contratos en los datos abiertos del SERCOP… puedes seguir llenando.
              </p>
            </template>
            <template v-else-if="hist.estado === 'listo'">
              <p class="historial__nota">
                {{ hist.datos.verificados }} contratos verificados con tu RUC. Elige los CPC que quieres
                vigilar: el radar y las alertas te avisarán de ínfimas con esos códigos.
              </p>
              <div class="historial__chips">
                <button
                  v-for="fila in hist.datos.cpc"
                  :key="fila.codigo"
                  type="button"
                  class="historial__chip"
                  :class="{ 'historial__chip--activo': cpcElegidos[fila.codigo] }"
                  :aria-pressed="Boolean(cpcElegidos[fila.codigo])"
                  :title="fila.descripcion"
                  @click="cpcElegidos[fila.codigo] = !cpcElegidos[fila.codigo]"
                >
                  <span class="numeros">{{ fila.codigo }}</span>
                  <small>{{ (fila.descripcion || '').slice(0, 40) }}</small>
                </button>
              </div>
              <p v-if="hist.datos.experiencia?.length" class="historial__nota">
                También se guardarán {{ hist.datos.experiencia.length }} contratos como experiencia en tu perfil.
              </p>
            </template>
            <p v-else class="historial__nota">
              No encontramos contratos adjudicados a tu RUC en los últimos años. Podrás agregar tus CPC
              desde «Perfil de empresa».
            </p>
          </div>

          <div v-else-if="ruc.estado === 'error'" class="registro__alerta" role="alert">
            <p>{{ ruc.error }}</p>
            <div class="registro__alerta-acciones">
              <button type="button" class="boton boton--secundario boton--pequeno" @click="reintentar">
                Reintentar
              </button>
              <button type="button" class="boton boton--fantasma boton--pequeno" @click="llenarAMano">
                Llenar a mano
              </button>
            </div>
          </div>

          <button
            v-if="!rucResuelto && ruc.estado !== 'error' && ruc.estado !== 'consultando'"
            type="button"
            class="enlace-discreto"
            @click="llenarAMano"
          >
            No tengo el RUC a mano: llenar los datos manualmente
          </button>
        </fieldset>

        <!-- Bloque 2: empresa -->
        <Transition name="desplegar">
          <fieldset v-if="rucResuelto" ref="bloqueEmpresa" class="bloque">
            <legend class="bloque__titulo">
              <span class="bloque__numero" aria-hidden="true">2</span>
              Datos de la empresa
            </legend>

            <label class="campo">
              <span class="campo__etiqueta">
                Razón social <span class="campo__obligatorio">obligatorio</span>
                <span v-if="esDelSri('nombre', empresa.nombre)" class="marca-sri">del SRI</span>
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
                <span class="campo__etiqueta">
                  Ciudad
                  <span v-if="esDelSri('ciudad', empresa.ciudad)" class="marca-sri">del SRI</span>
                </span>
                <input v-model="empresa.ciudad" class="entrada" type="text" maxlength="80" placeholder="Quito" />
              </label>
              <label class="campo">
                <span class="campo__etiqueta">Teléfono <span class="campo__pendiente">complétalo</span></span>
                <input
                  v-model="empresa.telefono"
                  class="entrada"
                  type="tel"
                  maxlength="20"
                  placeholder="+593 99 123 4567"
                  autocomplete="tel"
                  data-falta
                />
              </label>
            </div>

            <label class="campo">
              <span class="campo__etiqueta">
                Dirección
                <span v-if="esDelSri('direccion', empresa.direccion)" class="marca-sri">del SRI</span>
              </span>
              <input
                v-model="empresa.direccion"
                class="entrada"
                type="text"
                maxlength="200"
                placeholder="Av. Amazonas 1234 y Colón"
              />
            </label>

            <label class="campo">
              <span class="campo__etiqueta">Correo de contacto <span class="campo__pendiente">complétalo</span></span>
              <input
                v-model="empresa.email_contacto"
                class="entrada"
                type="email"
                maxlength="254"
                placeholder="contacto@empresa.ec"
                :aria-invalid="!correoContactoBien"
              />
              <span v-if="!correoContactoBien" class="campo__error">Ese correo no tiene forma de correo.</span>
              <span v-else class="campo__ayuda">Aparece en tus proformas como correo de la empresa.</span>
            </label>
          </fieldset>
        </Transition>

        <!-- Bloque 3: cuenta -->
        <Transition name="desplegar">
          <fieldset v-if="rucResuelto" class="bloque">
            <legend class="bloque__titulo">
              <span class="bloque__numero" aria-hidden="true">3</span>
              Tu cuenta de administrador
            </legend>

            <div class="rejilla-dos">
              <label class="campo">
                <span class="campo__etiqueta">
                  Tu nombre
                  <span v-if="esDelSri('admin_nombre', admin.nombre)" class="marca-sri">representante legal</span>
                </span>
                <input
                  v-model="admin.nombre"
                  class="entrada"
                  type="text"
                  maxlength="120"
                  placeholder="Ana Pérez"
                  autocomplete="name"
                />
              </label>

              <label class="campo">
                <span class="campo__etiqueta">
                  Correo para entrar <span class="campo__obligatorio">obligatorio</span>
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
              </label>
            </div>

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
                Las dos contraseñas coinciden
              </li>
            </ul>
          </fieldset>
        </Transition>

        <p v-if="error" class="registro__error" role="alert">{{ error }}</p>

        <div class="registro__acciones">
          <button type="submit" class="boton boton--principal" :disabled="!puedeEnviar">
            <span v-if="enviando" class="girador" aria-hidden="true" />
            {{ enviando ? 'Creando la cuenta…' : 'Crear la empresa' }}
          </button>
          <span v-if="!puedeEnviar && !enviando && faltan.length" class="registro__faltan">
            Falta {{ faltan.join(', ') }}.
          </span>
        </div>
      </form>
    </main>

    <PiePublico />
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

/* Mismo dibujo de marca que en la aceptación de términos: es la cabecera del mismo tipo de
   pantalla —una sola tarea, sin panel alrededor—, así que el icono se ve igual en las dos. */
.marca {
  display: flex;
  align-items: center;
  gap: var(--e-3);
}

.marca__icono {
  display: grid;
  place-items: center;
  flex: none;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  overflow: hidden;
}

.marca__icono img {
  display: block;
  width: 100%;
  height: 100%;
}

html[data-tema='oscuro'] .marca__icono {
  box-shadow: 0 0 0 1px rgb(255 255 255 / 16%);
}

.marca__texto {
  font-weight: 650;
  letter-spacing: -0.01em;
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

/* Lo que trae la cuenta, para quien duda antes de escribir el RUC. En pantallas estrechas se oculta
   (más abajo): ahí la introducción va encima del formulario y no debe empujarlo fuera de la vista. */
.registro__incluye {
  list-style: none;
  margin: 0 0 var(--e-3);
  padding: 0;
  display: grid;
  gap: var(--e-2);
  color: var(--texto-suave);
  font-size: var(--t-sm);
  line-height: 1.55;
}

.registro__incluye li {
  position: relative;
  padding-left: var(--e-5);
}

.registro__incluye li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: var(--acento);
  font-weight: 700;
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

.campo__obligatorio {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--acento);
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

/* --- Historial de CPC --------------------------------------------------- */
.historial {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4);
  border-radius: var(--r-2);
  border: 1px dashed var(--borde-fuerte);
}

.historial__titulo {
  font-weight: 650;
  font-size: var(--t-sm);
}

.historial__nota {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-suave);
  line-height: 1.5;
}

.historial__girador {
  position: static;
  flex: none;
  width: 14px;
  height: 14px;
}

.historial__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
}

.historial__chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 4px 10px;
  border: 1px solid var(--borde-fuerte);
  border-radius: var(--r-2);
  background: var(--superficie);
  cursor: pointer;
  text-align: left;
  transition: all var(--rapido);
}

.historial__chip small {
  font-size: 0.68rem;
  color: var(--texto-tenue);
}

.historial__chip--activo {
  border-color: var(--info);
  background: var(--info-suave);
  color: var(--info);
}

/* --- Pasos ------------------------------------------------------------- */
.pasos {
  list-style: none;
  padding: 0;
  margin: var(--e-5) 0;
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.pasos__paso {
  display: flex;
  align-items: center;
  gap: var(--e-3);
  color: var(--texto-tenue);
  font-size: var(--t-sm);
  font-weight: 550;
  transition: color var(--rapido) var(--curva);
}

.pasos__marca {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 2px solid var(--borde-fuerte);
  font-size: var(--t-xs);
  font-weight: 700;
  transition: all var(--rapido) var(--curva);
}

.pasos__paso--actual {
  color: var(--texto);
}

.pasos__paso--actual .pasos__marca {
  border-color: var(--acento);
  color: var(--acento);
  box-shadow: 0 0 0 4px var(--acento-suave);
}

.pasos__paso--hecho {
  color: var(--ok);
}

.pasos__paso--hecho .pasos__marca {
  border-color: var(--ok);
  background: var(--ok);
  color: #fff;
}

.registro__nota {
  font-size: var(--t-sm);
}

/* --- RUC --------------------------------------------------------------- */
.ruc {
  position: relative;
  display: flex;
  align-items: center;
}

.ruc__entrada {
  font-size: var(--t-lg, 1.125rem);
  letter-spacing: 0.08em;
  padding-right: 88px;
  height: 52px;
}

.ruc--encontrado .ruc__entrada {
  border-color: var(--ok);
}

.ruc--invalido .ruc__entrada,
.ruc--error .ruc__entrada {
  border-color: var(--error);
}

.ruc__contador {
  position: absolute;
  right: 44px;
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  pointer-events: none;
}

.ruc__ok,
.ruc__girador {
  position: absolute;
  right: 14px;
  width: 20px;
  height: 20px;
}

.ruc__ok {
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--ok);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.ruc__girador {
  border: 2px solid var(--acento-suave);
  border-top-color: var(--acento);
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

.sri {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-4);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
  background: var(--superficie-2);
}

.sri--cargando {
  gap: var(--e-2);
}

.sri__cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--e-3);
}

.sri__razon {
  font-weight: 700;
  line-height: 1.3;
}

.sri__ruc {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.sri__datos {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--e-2) var(--e-4);
  margin: 0;
}

.sri__dato dt {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.sri__dato dd {
  margin: 0;
  font-size: var(--t-sm);
  line-height: 1.4;
}

.sri__avisos {
  margin: 0;
  padding: var(--e-2) var(--e-3) var(--e-2) var(--e-5);
  border-radius: var(--r-1);
  background: var(--aviso-suave);
  color: var(--aviso);
  font-size: var(--t-sm);
}

.sri__pie {
  font-size: var(--t-xs);
  color: var(--texto-suave);
  line-height: 1.5;
}

.marca-sri {
  margin-left: var(--e-1);
  padding: 1px 6px;
  border-radius: var(--r-redondo);
  background: var(--ok-suave);
  color: var(--ok);
  font-size: 0.66rem;
  font-weight: 650;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.campo__pendiente {
  font-size: 0.68rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--aviso);
}

.registro__alerta {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--aviso);
  background: var(--aviso-suave);
  font-size: var(--t-sm);
}

.registro__alerta-acciones {
  display: flex;
  gap: var(--e-2);
  flex-wrap: wrap;
}

.enlace-discreto {
  align-self: flex-start;
  border: 0;
  background: none;
  padding: 0;
  color: var(--acento);
  font-size: var(--t-sm);
  cursor: pointer;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.registro__faltan {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  align-self: center;
}

.desplegar-enter-active {
  transition:
    opacity 0.3s var(--curva),
    transform 0.3s var(--curva);
}

.desplegar-enter-from {
  opacity: 0;
  transform: translateY(-6px);
}

@media (prefers-reduced-motion: reduce) {
  .desplegar-enter-active {
    transition: none;
  }
}

@media (max-width: 1023px) {
  .registro__cuerpo {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--e-5);
  }

  .registro__intro h1 {
    font-size: var(--t-2xl);
  }

  .registro__incluye {
    display: none;
  }
}

@media (max-width: 639px) {
  .rejilla-dos,
  .requisitos,
  .sri__datos {
    grid-template-columns: 1fr;
  }
}
</style>
