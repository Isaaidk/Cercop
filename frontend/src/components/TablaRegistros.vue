<script setup>
/**
 * Tabla de contrataciones.
 *
 * Dos cosas que se hacen mal con frecuencia y aquí están resueltas:
 *
 * - **En móvil, la tabla se convierte en fichas.** Una tabla de nueve columnas desplazándose en
 *   horizontal es inutilizable: se pierde la referencia de qué columna se está mirando. En pantalla
 *   estrecha cada registro pasa a ser un bloque con sus datos etiquetados.
 * - **Las celdas largas se recortan con `title`.** El objeto de compra puede ocupar tres líneas y
 *   descuadrar todas las filas. Se recorta a dos líneas y el texto completo queda en el título del
 *   elemento y en el detalle desplegable.
 *
 * Rediseño 2026-11: el cliente pidió quitar «esos colores feísimos». La tabla va ahora en base
 * neutra —sin borde de color por urgencia en las filas ni píldoras de colores en el resumen— y la
 * urgencia del plazo es solo una insignia pequeña con texto (`insigniaDePlazo`). Se ven seis
 * columnas, las que sirven para decidir si abrir una ínfima; el resto vive en la ficha.
 */
import { computed, ref } from 'vue'

import { fechaCorta, numero, recortar, sinEtiquetas } from '@/utils/formato'
import FichaInfima from '@/components/FichaInfima.vue'
import { resumenCpc } from '@/utils/cpc'
import { diasParaProforma, insigniaDePlazo } from '@/utils/plazo'
import IconoPanel from '@/components/IconoPanel.vue'
import { separarProvincia, codigoDeProvincia } from '@/utils/provincias'
import { guardarArchivo } from '@/utils/descargas'
import { descargarTdr } from '@/utils/tdr'
import { diaDeHoy } from '@/utils/fecha'
import {
  MESES_EXPORTABLES,
  descargaEnVentana,
  inicioExportable,
  limiteLegible,
} from '@/utils/exportacion'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { sesion } from '@/stores/sesion'

/**
 * La tabla es la misma en dos sitios —la pestaña de ínfimas cuantías y el mapa— y en cada uno se
 * titula según lo que muestra. El título llega de fuera en lugar de deducirse aquí porque quien
 * sabe qué familia está mirando es quien fija el filtro, y esta pieza no debería tener dos formas
 * de averiguarlo.
 */
const props = defineProps({
  titulo: { type: String, default: 'Contrataciones' },
})

const emit = defineEmits(['preparar'])

const desplegado = ref(null)

/**
 * Con esto puesto, el detalle de **todas** las filas está a la vista.
 *
 * Es un interruptor aparte y no una lista de claves abiertas, y la diferencia importa: con una lista,
 * abrir uno a uno veinticinco detalles para luego pulsar «desplegar todo» tendría que añadir las
 * veinticinco que faltan y el botón dejaría de significar lo mismo. Con un interruptor, «todo» es todo
 * —incluidas las filas que lleguen al pasar de página— y desmarcarlo devuelve la tabla a la forma
 * abreviada de siempre, que es exactamente lo que se pidió.
 */
const todosDesplegados = ref(false)

/**
 * ¿Se ve el detalle de esta fila?
 *
 * Una sola condición para el `v-if` y para el `aria-expanded` del botón de la fila. Calculado en dos
 * sitios distintos, el lector de pantalla podría anunciar un detalle como cerrado mientras está abierto.
 */
function estaDesplegada(fila) {
  return todosDesplegados.value || desplegado.value === (valor(fila, 'codigo') || fila.id)
}

function alternarTodo() {
  todosDesplegados.value = !todosDesplegados.value
  // Al contraer se olvida también la fila suelta que estuviera abierta: si no, quedaría una abierta y
  // el botón diría que no hay nada desplegado.
  desplegado.value = null
}

const registros = computed(() => datos.estado.registros)

const exportando = ref(null)
const errorExportacion = ref('')
const avisoExportacion = ref('')

/**
 * Las formas de descargar el histórico.
 *
 * **La principal descarga lo que se está viendo**: la familia de la pestaña —o la del selector del
 * mapa— con los filtros de la pantalla. Es lo que se espera de un botón que está encima de la tabla:
 * si la pantalla muestra ínfimas cuantías, el archivo trae ínfimas cuantías. Antes había un botón
 * «Todo» como principal y el resultado era el contrario: se pulsaba desde la pestaña de ínfimas y
 * llegaba un archivo con las dos familias dentro, que es lo que el usuario describió como «me
 * descarga todo».
 *
 * La segunda trae **las dos familias a propósito**, cada una en su hoja, y solo aparece cuando hace
 * algo distinto: con la vista en «Ambas» las dos harían exactamente lo mismo, y dos botones que
 * hacen lo mismo solo dan motivos para dudar.
 */
const OPCIONES_EXPORTACION = computed(() => {
  const familia = filtros.estado.categoria
  const principal = {
    clave: 'vista',
    categoria: familia,
    etiqueta: 'Descargar Excel',
    principal: true,
    pista: `Descarga ${descripcionDeLaVista.value} con los filtros de la pantalla`,
  }
  if (!familia) return [principal]
  return [
    principal,
    {
      clave: 'todo',
      categoria: null,
      etiqueta: 'Excel con todo',
      pista: 'Un solo archivo con las ínfimas cuantías y las ofertas, cada una en su hoja',
    },
  ]
})

/** Cómo se nombra en el botón lo que se va a descargar. */
const descripcionDeLaVista = computed(() =>
  filtros.estado.categoria ? `solo ${ETIQUETA_CATEGORIA[filtros.estado.categoria]}` : 'las dos familias',
)

/** El nombre de cada categoría, tal como se lee en una frase. */
const ETIQUETA_CATEGORIA = {
  infimas: 'las ínfimas cuantías',
  ofertas: 'las ofertas',
}

/** El servidor vuelve a comprobarlo; aquí solo se evita ofrecer un botón condenado a un rechazo. */
const puedeExportar = computed(() => sesion.puedeExportar.value)
const hayResultados = computed(() => datos.estado.total > 0)

/**
 * Descarga el Excel con **todo** lo que cumplen los filtros, no la página que se está viendo.
 *
 * El archivo lo arma el servidor con los mismos criterios que la tabla, así que lo que llega al
 * disco y lo que hay en pantalla no pueden discrepar. Aquí solo se le pone nombre y se guarda.
 *
 * `categoria` decide qué se lleva: sin él, el libro trae todo con **una hoja por categoría** —las
 * ínfimas cuantías y las ofertas no se leen igual ni se trabajan igual, así que quien recibe el
 * archivo las encuentra ya separadas—; con `'infimas'` u `'ofertas'`, una sola hoja con esa.
 *
 * `exportando` guarda **cuál** se está generando y no un simple sí o no: con tres botones, un
 * booleano dejaría girando los tres a la vez y no se sabría cuál se pulsó.
 */
async function exportar(opcion) {
  if (exportando.value) return

  exportando.value = opcion.clave
  errorExportacion.value = ''
  avisoExportacion.value = ''
  try {
    const resultado = await datos.exportar(opcion.categoria)
    guardarArchivo(resultado.contenido, resultado.nombre)
    const que = opcion.categoria ? ` de ${ETIQUETA_CATEGORIA[opcion.categoria]}` : ''
    avisoExportacion.value = resultado.filas
      ? `Se descargaron ${numero(resultado.filas)} contrataciones${que} en ${resultado.nombre}.`
      : 'El archivo salió vacío: no hay contrataciones con estos filtros.'
  } catch (fallo) {
    errorExportacion.value = fallo.message
  } finally {
    exportando.value = null
  }
}

/**
 * La fecha inicial **en vigor**, que es la que viaja en la descarga.
 *
 * Se lee de los parámetros y no del borrador a propósito: la descarga usa los criterios aplicados,
 * así que mirar el borrador diría que la descarga cabe cuando todavía no se ha pulsado «Aplicar».
 */
const desdeAplicado = computed(() => filtros.parametros.value.desde || '')

/**
 * ¿La descarga se sale de la ventana de tres meses?
 *
 * El servidor lo comprueba igual y rechaza la petición con el motivo; aquí se evita ofrecer un botón
 * condenado a un rechazo, que es lo que se lee como que el panel está roto.
 */
const descargaFueraDeVentana = computed(() => !descargaEnVentana(desdeAplicado.value))

const limiteDeLaVentana = computed(() => limiteLegible(inicioExportable()))

/**
 * Pone el periodo descargable y descarga, en un solo gesto.
 *
 * Es la excepción deliberada a la regla de que la descarga lleva **exactamente** los filtros de la
 * pantalla: aquí el botón no se limita a descargar, también fija el rango. Y se fija en los dos
 * sentidos —desde el límite hasta hoy— porque dejar el `hasta` anterior podría dejarlo por debajo
 * del nuevo `desde`, y entonces la petición se rechazaría por dos fechas que se contradicen.
 *
 * Después de aplicar, la tabla muestra el mismo periodo que el archivo: la descarga sigue siendo
 * fiel a la vista, que es la propiedad que no se puede perder.
 */
async function descargarElPeriodoExportable() {
  filtros.actualizar({ desde: inicioExportable(), hasta: diaDeHoy() })
  filtros.aplicar()
  await exportar(OPCIONES_EXPORTACION.value[0])
}

/**
 * Las columnas, con las claves **canónicas** que publica la API.
 *
 * Los nombres no son los de la fuente oficial: el mapeo de ingesta traduce `objeto_contratacion` a
 * `objeto_compra`, `razon_social` a `entidad` y `codigo_contratacion` a `codigo` para que las dos
 * fuentes —NCO y OCDS— hablen igual. Escribir aquí el nombre de la fuente dejaría la tabla vacía en
 * la mitad de las filas sin ningún error de por medio.
 *
 * **Solo seis a la vista**, en el orden en que se decide: qué es (código y objeto), quién lo compra,
 * dónde, cuándo cierra y con qué CPC. El tipo de compra, el responsable, el estado y la fecha de
 * publicación siguen ahí, en la ficha que se abre al pulsar la fila: con once columnas la tabla
 * obligaba a desplazarse de lado y nadie leía las del final.
 *
 * El juego sigue la ficha de ínfimas cuantías del SERCOP, pero **solo con los campos que la fuente
 * publica de verdad**: no trae Nro. de factura, ni justificativo, ni importes utilizables, así que no
 * se pintan columnas para datos que nadie tiene.
 */
const COLUMNAS = [
  { clave: 'codigo', etiqueta: 'Código', tipo: 'codigo' },
  { clave: 'objeto_compra', etiqueta: 'Objeto', tipo: 'objeto' },
  { clave: 'entidad', etiqueta: 'Entidad', tipo: 'largo' },
  { clave: 'provincia', etiqueta: 'Ubicación', tipo: 'ubicacion' },
  { clave: 'fecha_limite_proformas', etiqueta: 'Cierre', tipo: 'cierre' },
  { clave: 'cpc', etiqueta: 'CPC', tipo: 'cpc' },
]

function valor(registro, clave) {
  // El CPC no viene como campo suelto: la API devuelve los ítems de la ficha y el resumen se arma
  // aquí. Se resuelve dentro de `valor` para que el resto de la tabla —columnas, celda, ficha del
  // móvil— siga leyendo una clave como cualquier otra, sin ramas repartidas por la plantilla.
  if (clave === 'cpc') return resumenCpc(registro)
  const crudo = registro[clave]
  return crudo === null || crudo === undefined ? '' : String(crudo)
}

/*
 * Aquí hubo columnas de Cantidad, Costo U. y Valor, con el total calculado como cantidad × valor
 * unitario. Se quitaron al comprobar contra el origen que el listado NCO publica **siempre** cero en
 * los dos campos: 1.352 de 1.352 filas traen `cantidad = "0.00"` y `valor_unitario = "0.00000"`, y
 * probar otros valores del parámetro `lot` devuelve lo mismo. No es un fallo de la ingesta: es lo que
 * publica la fuente. Si algún día se rellenan, las columnas vuelven y el total se calcula igual.
 */

/**
 * Días que quedan para la proforma de una fila.
 *
 * El cálculo vive en `@/utils/plazo` porque lo comparten la ficha, el inicio y el CRM: la misma
 * ínfima no puede decir «2 días» en una pantalla y «3 días» en otra.
 */
function plazo(fila) {
  return diasParaProforma(valor(fila, 'fecha_limite_proformas'))
}

function insignia(fila) {
  return insigniaDePlazo(plazo(fila))
}

function alternar(fila) {
  const clave = valor(fila, 'codigo') || valor(fila, 'id')
  desplegado.value = desplegado.value === clave ? null : clave
}

/** Filas cuyo TDR se está bajando desde el botón de la tabla, para mostrar el estado. */
const bajandoTdr = ref(null)
const errorTdr = ref({})

async function bajarTdrDeFila(fila) {
  bajandoTdr.value = fila.id
  errorTdr.value = { ...errorTdr.value, [fila.id]: '' }
  try {
    await descargarTdr(String(fila.id))
  } catch (fallo) {
    errorTdr.value = { ...errorTdr.value, [fila.id]: fallo.message }
  } finally {
    bajandoTdr.value = null
  }
}

function filtrarPorProvincia(valorCrudo) {
  const { provincia } = separarProvincia(valorCrudo)
  const codigo = codigoDeProvincia(provincia)
  // Desde la tabla el gesto es «ver esta provincia»: reemplaza la selección en lugar de sumarse a
  // ella. Pulsar la celda de una fila esperando ver *esa* provincia y encontrarse cuatro más sería
  // desconcertante; para comparar ya está el doble clic sobre el mapa.
  if (codigo) filtros.elegirProvincia(codigo)
}

/** ¿La ficha de CPC de esta fila todavía no se ha leído? Se dice en vez de dejar la celda vacía. */
function leyendoCpc(fila) {
  return fila.items_leidos === false && !resumenCpc(fila)
}

/**
 * Lo que hay en esta página, de un vistazo: cuántas cierran pronto, cuántas traen TDR y cuántas
 * esperan aún su CPC. Es un resumen de la página, no un filtro: los filtros siguen en el lateral.
 * Se pinta como una línea de texto gris, no como píldoras de colores: es contexto, no una alarma.
 */
const resumenPagina = computed(() => {
  const filas = registros.value
  const urgentes = filas.filter((fila) => {
    const dias = plazo(fila)
    return dias !== null && dias >= 0 && dias < 3
  }).length
  const conTdr = filas.filter((fila) => fila.documentos?.length).length
  const leyendo = filas.filter(leyendoCpc).length
  return { urgentes, conTdr, leyendo }
})
</script>

<template>
  <section class="tarjeta tabla-tarjeta aparece">
    <header class="tabla__cabecera">
      <div class="tabla__cabecera-texto">
        <p class="tarjeta__titulo">{{ props.titulo }}</p>
        <p class="tarjeta__pista">
          <template v-if="datos.estado.total">
            <span class="numeros">{{ numero(datos.estado.total) }}</span> resultados
            <template v-if="datos.estado.paginas > 1">
              · página {{ filtros.estado.pagina }} de {{ datos.estado.paginas }}
            </template>
            <template v-if="datos.estado.desdeCache"> · servido desde la memoria intermedia</template>
          </template>
          <template v-else>Sin resultados con los filtros actuales</template>
        </p>
      </div>

      <!-- La exportación lleva **todos** los resultados de los filtros, no esta página. El rótulo lo
           dice para que nadie tenga que adivinarlo después de abrir el archivo. Las acciones de la
           cabecera son secundarias: la principal de esta pantalla es «Llenar TDR», en cada fila. -->
      <div class="tabla__acciones-cabecera">
        <button
          type="button"
          class="boton boton--fantasma boton--pequeno"
          :aria-pressed="todosDesplegados"
          :disabled="!registros.length"
          :title="
            todosDesplegados
              ? 'Volver a la forma abreviada, con el detalle cerrado'
              : 'Abrir el detalle completo de todas las contrataciones de esta página'
          "
          @click="alternarTodo"
        >
          <span aria-hidden="true">{{ todosDesplegados ? '⌃' : '⌄' }}</span>
          {{ todosDesplegados ? 'Contraer todo' : 'Desplegar todo' }}
        </button>

        <!-- El envoltorio `<template>` no crea ningún elemento: los botones quedan como hijos
             directos de la barra de acciones, que es la que reparte el espacio. Con `v-for` y `v-if`
             en el mismo botón, Vue evalúa antes el `v-if` y avisa de que la variable del recorrido
             todavía no existe. -->
        <template v-if="puedeExportar && descargaFueraDeVentana">
          <button
            type="button"
            class="boton boton--secundario boton--pequeno"
            :disabled="Boolean(exportando) || !hayResultados"
            :title="`Pone el periodo del ${limiteDeLaVentana} a hoy y descarga lo que cumpla los demás filtros`"
            @click="descargarElPeriodoExportable"
          >
            <span v-if="exportando" class="girador" aria-hidden="true" />
            <IconoPanel v-else nombre="descargar" :tamano="14" />
            {{ exportando ? 'Generando…' : `Excel de los últimos ${MESES_EXPORTABLES} meses` }}
          </button>
        </template>

        <template v-else-if="puedeExportar">
          <button
            v-for="opcion in OPCIONES_EXPORTACION"
            :key="opcion.clave"
            type="button"
            class="boton boton--pequeno"
            :class="opcion.principal ? 'boton--secundario' : 'boton--fantasma'"
            :disabled="Boolean(exportando) || !hayResultados"
            :title="
              hayResultados ? opcion.pista : 'Sin resultados que exportar con los filtros actuales'
            "
            @click="exportar(opcion)"
          >
            <span v-if="exportando === opcion.clave" class="girador" aria-hidden="true" />
            <IconoPanel v-else-if="opcion.principal" nombre="descargar" :tamano="14" />
            {{ exportando === opcion.clave ? 'Generando…' : opcion.etiqueta }}
          </button>
        </template>
      </div>
    </header>

    <!--
      Por qué la descarga no lleva el histórico entero, dicho donde se pulsa y no solo cuando
      falla: es una limitación del sistema y el usuario merece saberla antes de intentarlo. La
      consulta en pantalla no tiene ese tope —se pagina— así que se dice también eso.
    -->
    <details v-if="puedeExportar && descargaFueraDeVentana && hayResultados" class="ayuda tabla__pista-descarga">
      <summary>¿Qué cubre la descarga a Excel?</summary>
      <p>
        Cubre como mucho los últimos {{ MESES_EXPORTABLES }} meses, para no cargar el servidor con el
        histórico entero. El botón pone ese periodo en los filtros y lo descarga; para el histórico
        anterior, acota por palabra clave, CPC o provincia, o consúltalo aquí, que la tabla sí llega
        a todo.
      </p>
    </details>

    <!-- El resumen de la página, en una línea de texto gris: contexto, no una alarma. -->
    <p v-if="registros.length && !datos.estado.cargando" class="resumen-pagina" aria-label="Resumen de esta página">
      <span v-if="resumenPagina.urgentes">
        <strong class="numeros">{{ resumenPagina.urgentes }}</strong> cierran en menos de 3 días
      </span>
      <span>
        <strong class="numeros">{{ resumenPagina.conTdr }}</strong> con TDR para bajar
      </span>
      <span v-if="resumenPagina.leyendo" class="tabla__leyendo">
        <strong class="numeros">{{ resumenPagina.leyendo }}</strong> leyendo CPC…
      </span>
      <span class="resumen-pagina__pista">Pulsa una fila para ver la ficha completa.</span>
    </p>

    <p v-if="errorExportacion" class="tabla__error" role="alert">{{ errorExportacion }}</p>
    <p v-else-if="avisoExportacion" class="tabla__exportacion" role="status">
      {{ avisoExportacion }}
    </p>

    <!-- Esqueletos con la forma real de las filas: un bloque gris genérico no anticipa lo que va a
         llegar y hace que la espera se note más, no menos. -->
    <div v-if="datos.estado.cargando" class="tabla__cargando">
      <span v-for="fila in 6" :key="fila" class="esqueleto tabla__fila-esqueleto" />
    </div>

    <p v-else-if="datos.estado.error" class="tabla__error" role="alert">
      {{ datos.estado.error }}
    </p>

    <div v-else-if="!registros.length" class="tabla__vacio">
      <p class="tabla__vacio-titulo">No hay contrataciones que mostrar</p>
      <p class="tabla__vacio-texto">
        Prueba a quitar algún filtro o a elegir «Cualquiera» en vez de «Todas» en las palabras clave:
        con «Todas» se exige que la contratación mencione todas las palabras a la vez.
      </p>
      <button v-if="filtros.hayFiltros.value" type="button" class="boton boton--secundario" @click="filtros.limpiarTodo()">
        Limpiar los filtros
      </button>
    </div>

    <template v-else>
      <!-- Tabla para pantallas anchas -->
      <div class="tabla__contenedor">
        <table class="tabla">
          <caption class="solo-lectores">
            Contrataciones que cumplen los filtros activos
          </caption>
          <thead>
            <tr>
              <th v-for="columna in COLUMNAS" :key="columna.clave" scope="col" :class="`tabla__th--${columna.tipo}`">
                {{ columna.etiqueta }}
              </th>
              <th scope="col" class="tabla__th--acciones"><span class="solo-lectores">Acciones</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="fila in registros" :key="valor(fila, 'codigo') || fila.id">
              <tr
                class="tabla__fila"
                :class="{ 'tabla__fila--abierta': estaDesplegada(fila) }"
                @click="alternar(fila)"
              >
                <td
                  v-for="columna in COLUMNAS"
                  :key="columna.clave"
                  :data-etiqueta="columna.etiqueta"
                  :class="`tabla__td--${columna.tipo}`"
                >
                  <a
                    v-if="columna.tipo === 'codigo' && fila.enlace_publico"
                    class="codigo numeros codigo--enlace"
                    :href="fila.enlace_publico"
                    target="_blank"
                    rel="noopener noreferrer"
                    :title="`Abrir ${valor(fila, columna.clave)} en el portal de la fuente`"
                    @click.stop
                  >
                    {{ recortar(valor(fila, columna.clave), 26) || '—' }}
                    <span class="codigo__fuera" aria-hidden="true">↗</span>
                  </a>

                  <span v-else-if="columna.tipo === 'codigo'" class="codigo numeros">
                    {{ recortar(valor(fila, columna.clave), 26) || '—' }}
                  </span>

                  <span
                    v-else-if="columna.tipo === 'objeto'"
                    class="tabla__objeto"
                    :title="sinEtiquetas(valor(fila, columna.clave))"
                  >
                    {{ recortar(sinEtiquetas(valor(fila, columna.clave)), 160) || '—' }}
                  </span>

                  <button
                    v-else-if="columna.tipo === 'ubicacion'"
                    type="button"
                    class="tabla__ubicacion"
                    :title="`Ver solo ${sinEtiquetas(valor(fila, columna.clave)) || 'esta provincia'}`"
                    @click.stop="filtrarPorProvincia(valor(fila, columna.clave))"
                  >
                    {{ recortar(sinEtiquetas(valor(fila, columna.clave)), 30) || '—' }}
                  </button>

                  <!-- El cierre: la fecha en texto y, debajo, una insignia pequeña con lo que falta.
                       El color va solo en la insignia, y rojo solo si cierra hoy o mañana. -->
                  <span v-else-if="columna.tipo === 'cierre'" class="tabla__cierre">
                    <span class="numeros">{{ fechaCorta(valor(fila, columna.clave)) || '—' }}</span>
                    <span class="etiqueta" :class="insignia(fila).clase">{{ insignia(fila).texto }}</span>
                  </span>

                  <span v-else-if="columna.tipo === 'cpc' && leyendoCpc(fila)" class="tabla__leyendo">
                    Leyendo CPC…
                  </span>

                  <span
                    v-else-if="columna.tipo === 'cpc'"
                    class="tabla__cpc"
                    :title="valor(fila, columna.clave)"
                  >
                    {{ recortar(valor(fila, columna.clave), 60) || '—' }}
                  </span>

                  <span v-else class="tabla__largo" :title="sinEtiquetas(valor(fila, columna.clave))">
                    {{ recortar(sinEtiquetas(valor(fila, columna.clave)), 90) || '—' }}
                  </span>
                </td>
                <td class="tabla__acciones">
                  <div class="tabla__acciones-fila">
                    <button
                      v-if="valor(fila, 'codigo')"
                      type="button"
                      class="boton boton--principal boton--pequeno"
                      title="Abrir el TDR, los requisitos y la proforma de esta ínfima"
                      @click.stop="emit('preparar', fila)"
                    >
                      Llenar TDR
                    </button>
                    <button
                      v-if="fila.documentos && fila.documentos.length"
                      type="button"
                      class="boton boton--fantasma boton--icono"
                      :disabled="bajandoTdr === fila.id"
                      :aria-label="bajandoTdr === fila.id ? 'Preparando el TDR…' : 'Bajar el TDR'"
                      :title="errorTdr[fila.id] || 'Bajar los términos de referencia (TDR) en PDF o Word'"
                      @click.stop="bajarTdrDeFila(fila)"
                    >
                      <span v-if="bajandoTdr === fila.id" class="girador" aria-hidden="true" />
                      <IconoPanel v-else nombre="descargar" :tamano="16" />
                    </button>
                    <button
                      type="button"
                      class="boton boton--fantasma boton--icono"
                      :aria-expanded="estaDesplegada(fila)"
                      :aria-label="`Ver el detalle de ${valor(fila, 'codigo') || 'esta contratación'}`"
                      @click.stop="alternar(fila)"
                    >
                      <span aria-hidden="true" class="tabla__chevron">▾</span>
                    </button>
                  </div>
                  <span v-if="errorTdr[fila.id]" class="tabla__error-tdr" role="alert">
                    {{ errorTdr[fila.id] }}
                  </span>
                </td>
              </tr>

              <tr v-if="estaDesplegada(fila)" class="tabla__detalle-fila">
                <td :colspan="COLUMNAS.length + 1">
                  <FichaInfima
                    :fila="fila"
                    @preparar="emit('preparar', $event)"
                    @filtrar-provincia="filtrarPorProvincia"
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Fichas para pantallas estrechas -->
      <ul class="fichas">
        <li
          v-for="fila in registros"
          :key="`f-${valor(fila, 'codigo') || fila.id}`"
          class="ficha-registro"
        >
          <div class="ficha-registro__cabecera">
            <span class="codigo numeros">{{ recortar(valor(fila, 'codigo'), 30) || '—' }}</span>
            <span class="etiqueta" :class="insignia(fila).clase">{{ insignia(fila).texto }}</span>
          </div>
          <p class="ficha-registro__titulo">{{ sinEtiquetas(valor(fila, 'objeto_compra')) || '—' }}</p>
          <p class="ficha-registro__objeto">{{ sinEtiquetas(valor(fila, 'entidad')) || 'Sin razón social' }}</p>
          <p v-if="resumenCpc(fila)" class="ficha-registro__cpc">CPC {{ recortar(resumenCpc(fila), 60) }}</p>
          <p v-else-if="leyendoCpc(fila)" class="ficha-registro__cpc tabla__leyendo">Leyendo CPC…</p>
          <div class="ficha-registro__pie">
            <button type="button" class="tabla__ubicacion" @click="filtrarPorProvincia(valor(fila, 'provincia'))">
              {{ recortar(sinEtiquetas(valor(fila, 'provincia')), 28) || 'Sin provincia' }}
            </button>
            <span v-if="valor(fila, 'fecha_limite_proformas')" class="numeros">
              Cierra {{ fechaCorta(valor(fila, 'fecha_limite_proformas')) }}
            </span>
          </div>
          <div class="ficha-registro__acciones">
            <button
              v-if="valor(fila, 'codigo')"
              type="button"
              class="boton boton--principal boton--pequeno"
              @click="emit('preparar', fila)"
            >
              Llenar TDR
            </button>
            <button
              type="button"
              class="boton boton--secundario boton--pequeno"
              :aria-expanded="estaDesplegada(fila)"
              @click="alternar(fila)"
            >
              {{ estaDesplegada(fila) ? 'Ocultar ficha' : 'Ver ficha' }}
            </button>
          </div>
          <FichaInfima
            v-if="estaDesplegada(fila)"
            :fila="fila"
            @preparar="emit('preparar', $event)"
            @filtrar-provincia="filtrarPorProvincia"
          />
        </li>
      </ul>

      <slot name="paginacion" />
    </template>
  </section>
</template>

<style scoped>
/* Sombra solo al pasar el ratón, como el resto de tarjetas del rediseño. */
.tabla-tarjeta {
  box-shadow: none;
  overflow: hidden;
}

.tabla__cabecera {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-4) var(--e-5);
}

.tabla__cabecera-texto {
  min-width: 0;
}

.tabla__contenedor {
  overflow-x: auto;
  /* Sombras que avisan de que hay más columnas a un lado: la tabla no está «cortada», se desliza. */
  background:
    linear-gradient(to right, var(--superficie) 30%, transparent) left center / 24px 100% no-repeat local,
    linear-gradient(to left, var(--superficie) 30%, transparent) right center / 24px 100% no-repeat local,
    linear-gradient(to right, var(--borde-fuerte), transparent) left center / 6px 100% no-repeat scroll,
    linear-gradient(to left, var(--borde-fuerte), transparent) right center / 6px 100% no-repeat scroll;
}

.tabla__acciones-cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

.tabla__exportacion {
  margin: 0 var(--e-5) var(--e-3);
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

/*
 * La pista de la ventana de descarga: informa de un límite, no de un error, así que va en tono
 * neutro y no en el color de aviso. Con el color del error parecería que algo ha fallado.
 */
.tabla__pista-descarga {
  margin: 0 var(--e-5) var(--e-3);
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  line-height: 1.5;
}

/*
 * El código como enlace.
 *
 * Se subraya solo al pasar por encima: subrayados todos a la vez, una columna entera de enlaces
 * convierte la tabla en una masa de líneas. El color sí va siempre, porque es lo único que avisa de
 * que el código se puede pulsar sin tener que probarlo.
 */
.codigo--enlace {
  color: var(--acento);
  text-decoration: none;
}

.codigo--enlace:hover {
  text-decoration: underline;
}

.codigo__fuera {
  margin-left: 0.25em;
  font-size: 0.85em;
  opacity: 0.75;
}

.girador {
  width: 12px;
  height: 12px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: girar 0.7s linear infinite;
}

.tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.tabla th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: var(--e-2) var(--e-4);
  text-align: left;
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-tenue);
  background: var(--superficie-2);
  border-top: 1px solid var(--borde);
  border-bottom: 1px solid var(--borde);
  white-space: nowrap;
}

.tabla__fila {
  cursor: pointer;
  transition: background-color var(--rapido) var(--curva);
}

.tabla__fila:hover {
  background: var(--superficie-2);
}

/* La fila abierta se marca con el fondo más suave del acento: es «lo seleccionado», no una alerta. */
.tabla__fila--abierta,
.tabla__fila--abierta:hover {
  background: var(--acento-tenue);
}

.tabla__fila--abierta .tabla__chevron {
  transform: rotate(180deg);
}

/* «Leyendo CPC…»: gris con un punto que late. Es un estado de espera, no una alarma. */
.tabla__leyendo {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--texto-tenue);
  font-size: var(--t-xs);
  font-weight: 600;
}

.tabla__leyendo::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--acento);
  animation: pulso-tabla 1.2s ease-in-out infinite;
}

@keyframes pulso-tabla {
  50% {
    opacity: 0.25;
  }
}

.resumen-pagina {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--e-1) var(--e-4);
  margin: 0 var(--e-5) var(--e-3);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.resumen-pagina strong {
  color: var(--texto-suave);
}

.resumen-pagina__pista {
  margin-left: auto;
}

.tabla td {
  padding: var(--e-3) var(--e-4);
  border-bottom: 1px solid var(--borde);
  vertical-align: top;
}

.tabla__largo {
  display: block;
  max-width: 28ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--texto-suave);
}

/* El objeto es lo que más se lee: texto en color principal y hasta dos líneas. */
.tabla__objeto {
  display: -webkit-box;
  min-width: 18rem;
  max-width: 48ch;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--texto);
  font-weight: 550;
  line-height: 1.4;
}

.tabla__cpc {
  display: block;
  max-width: 22ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--t-xs);
  color: var(--texto-suave);
}

.tabla__cierre {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  white-space: nowrap;
}

.tabla__th--cierre,
.tabla__td--cierre {
  white-space: nowrap;
}

.codigo {
  font-family: var(--fuente-numeros);
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-suave);
  white-space: nowrap;
}

/* La ubicación filtra al pulsarla. Va en el color del texto para no llenar la tabla de azul; el
   subrayado al pasar el ratón y el `title` dicen que se puede pulsar. */
.tabla__ubicacion {
  border: 0;
  padding: 0;
  background: none;
  color: var(--texto-suave);
  text-align: left;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline dotted;
  text-decoration-color: var(--borde-fuerte);
  text-underline-offset: 3px;
  transition:
    color var(--rapido) var(--curva),
    text-decoration-color var(--rapido) var(--curva);
}

.tabla__ubicacion:hover {
  color: var(--acento);
  text-decoration-color: currentColor;
}

.tabla__acciones {
  width: 1%;
  text-align: right;
  white-space: nowrap;
}

.tabla__acciones-fila {
  display: inline-flex;
  align-items: center;
  gap: var(--e-1);
}

.tabla__error-tdr {
  display: block;
  max-width: 14rem;
  margin-top: 0.25rem;
  margin-left: auto;
  font-size: var(--t-xs);
  color: var(--error);
  white-space: normal;
  text-align: right;
}

.tabla__chevron {
  display: inline-block;
  transition: transform var(--normal) var(--curva);
}

.tabla__detalle-fila td {
  background: var(--superficie-2);
  padding: 0;
}

.tabla__cargando {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4);
}

.tabla__fila-esqueleto {
  display: block;
  height: 38px;
  border-radius: var(--r-1);
}

.tabla__error {
  margin: var(--e-3) var(--e-5);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px solid var(--borde);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

.tabla__vacio {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--e-2);
  padding: var(--e-7) var(--e-5);
  text-align: center;
}

.tabla__vacio-titulo {
  font-weight: 650;
  font-size: var(--t-md);
}

.tabla__vacio-texto {
  max-width: 48ch;
  color: var(--texto-tenue);
  font-size: var(--t-sm);
  margin-bottom: var(--e-2);
}

/* Las fichas solo se muestran en pantalla estrecha. */
.fichas {
  display: none;
  list-style: none;
  padding: 0;
  margin: 0;
  border-top: 1px solid var(--borde);
}

.ficha-registro {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
  padding: var(--e-4);
  border-bottom: 1px solid var(--borde);
}

.ficha-registro__cabecera,
.ficha-registro__pie {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
}

.ficha-registro__objeto {
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--texto-suave);
}

.ficha-registro__titulo {
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ficha-registro__cpc {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.ficha-registro__pie {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.ficha-registro__acciones {
  display: flex;
  gap: var(--e-2);
}

.ficha-registro__acciones .boton {
  flex: 1;
  justify-content: center;
}

@media (prefers-reduced-motion: reduce) {
  .tabla__leyendo::before {
    animation: none;
  }
}

@media (max-width: 1023px) {
  .tabla__contenedor {
    display: none;
  }

  .fichas {
    display: block;
  }
}

@media (max-width: 639px) {
  .tabla__cabecera {
    padding: var(--e-3) var(--e-4);
  }

  .resumen-pagina,
  .tabla__pista-descarga,
  .tabla__exportacion {
    margin-left: var(--e-4);
    margin-right: var(--e-4);
  }

  .resumen-pagina__pista {
    display: none;
  }

  .ficha-registro {
    padding: var(--e-3) var(--e-4);
  }
}
</style>
