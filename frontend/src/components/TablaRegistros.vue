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
 *   descuadrar todas las filas. Se recorta a una línea y el texto completo queda en el título del
 *   elemento y en el detalle desplegable.
 */
import { computed, ref } from 'vue'

import { fechaCorta, numero, recortar, sinEtiquetas } from '@/utils/formato'
import { itemsDe, resumenCpc } from '@/utils/cpc'
import { diasParaProforma, nivelDePlazo, textoDePlazo } from '@/utils/plazo'
import { separarProvincia, codigoDeProvincia } from '@/utils/provincias'
import { guardarArchivo } from '@/utils/descargas'
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
    etiqueta: 'Descargar',
    principal: true,
    pista: `Descarga ${descripcionDeLaVista.value} con los filtros de la pantalla`,
  }
  if (!familia) return [principal]
  return [
    principal,
    {
      clave: 'todo',
      categoria: null,
      etiqueta: 'Todo',
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
 * El juego de columnas sigue la ficha de ínfimas cuantías del SERCOP, pero **solo con los campos que
 * la fuente publica de verdad**. Comprobado contra el origen: el listado NCO trae veinte claves, todas
 * las filas son «Ínfimas Cuantías» y el objeto, la razón social, el responsable, la provincia, el
 * estado y las fechas vienen rellenos. No trae Nro. de factura, ni CPC, ni justificativo, ni importes
 * utilizables, así que no se pintan columnas para datos que nadie tiene: una columna a cero parece
 * información y no lo es.
 */
const COLUMNAS = [
  { clave: 'codigo', etiqueta: 'Código', tipo: 'codigo' },
  { clave: 'tipo_necesidad', etiqueta: 'Tipo de compra', tipo: 'texto' },
  { clave: 'entidad', etiqueta: 'Razón social', tipo: 'largo' },
  { clave: 'objeto_compra', etiqueta: 'Objeto de compra', tipo: 'largo' },
  {
    clave: 'cpc',
    etiqueta: 'CPC',
    tipo: 'largo',
  },
  { clave: 'funcionario', etiqueta: 'Responsable', tipo: 'largo' },
  { clave: 'provincia', etiqueta: 'Provincia · cantón', tipo: 'ubicacion' },
  { clave: 'estado', etiqueta: 'Estado', tipo: 'estado' },
  { clave: 'fecha_publicacion', etiqueta: 'Publicación', tipo: 'fecha' },
  { clave: 'fecha_limite_proformas', etiqueta: 'Límite de proformas', tipo: 'fecha' },
  { clave: 'dias_proforma', etiqueta: 'Días para proforma', tipo: 'plazo' },
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

/** Numeración corrida entre páginas: la página 2 empieza donde acabó la 1, no en 1 otra vez. */
function numeroDeFila(indice) {
  return (filtros.estado.pagina - 1) * filtros.estado.tamano + indice + 1
}

/**
 * Días que quedan para la proforma de una fila.
 *
 * El cálculo y el semáforo viven en `@/utils/plazo` porque los comparte con el listado que aparece
 * bajo el mapa: el mismo registro no puede salir verde en una pantalla y amarillo en la otra.
 */
function plazo(fila) {
  return diasParaProforma(valor(fila, 'fecha_limite_proformas'))
}

function alternar(fila) {
  const clave = valor(fila, 'codigo') || valor(fila, 'id')
  desplegado.value = desplegado.value === clave ? null : clave
}

/** Todas las claves del registro, para el detalle: la API no garantiza un conjunto fijo. */
function detalles(fila) {
  return Object.entries(fila)
    .filter(([, v]) => v !== null && v !== undefined && String(v).trim() !== '')
    // `enlace` es la dirección relativa que publica la fuente y `enlace_publico` es esa misma ya
    // resuelta. Las dos se quitan: la primera no lleva a ninguna parte fuera del portal y la segunda
    // ya está en el botón de arriba, así que como par de texto solo añadirían ruido.
    // `items` y `cpc_codigos` son las piezas con las que se arma el resumen del CPC: volcadas como
    // texto darían `[object Object]` y una lista de códigos sueltos. El resumen ya está en su
    // columna y el desglose, en la tabla de ítems de arriba.
    .filter(
      ([k]) => !['id', 'datos', 'enlace', 'enlace_publico', 'items', 'cpc_codigos'].includes(k),
    )
    .map(([clave, v]) => ({ clave, valor: sinEtiquetas(v) }))
}

function etiquetaEstado(estado) {
  const limpio = sinEtiquetas(estado).toLowerCase()
  if (limpio.includes('curso') || limpio.includes('activo') || limpio.includes('abiert')) return 'etiqueta--ok'
  if (limpio.includes('finaliz') || limpio.includes('cerrad') || limpio.includes('complete')) return 'etiqueta--info'
  if (limpio.includes('anulad') || limpio.includes('cancelad')) return 'etiqueta--error'
  return ''
}

function filtrarPorProvincia(valorCrudo) {
  const { provincia } = separarProvincia(valorCrudo)
  const codigo = codigoDeProvincia(provincia)
  // Desde la tabla el gesto es «ver esta provincia»: reemplaza la selección en lugar de sumarse a
  // ella. Pulsar la celda de una fila esperando ver *esa* provincia y encontrarse cuatro más sería
  // desconcertante; para comparar ya está el doble clic sobre el mapa.
  if (codigo) filtros.elegirProvincia(codigo)
}</script>

<template>
  <section class="tarjeta aparece retardo-5">
    <header class="tarjeta__cabecera">
      <div>
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
           dice para que nadie tenga que adivinarlo después de abrir el archivo. -->
      <div class="tabla__acciones-cabecera">
        <button
          type="button"
          class="boton boton--secundario boton--pequeno"
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

        <!-- El envoltorio `<template>` no crea ningún elemento: los tres botones quedan como hijos
             directos de la barra de acciones, que es la que reparte el espacio. Con `v-for` y `v-if`
             en el mismo botón, Vue evalúa antes el `v-if` y avisa de que la variable del recorrido
             todavía no existe. -->
        <template v-if="puedeExportar && descargaFueraDeVentana">
          <button
            type="button"
            class="boton boton--principal boton--pequeno"
            :disabled="Boolean(exportando) || !hayResultados"
            :title="`Pone el periodo del ${limiteDeLaVentana} a hoy y descarga lo que cumpla los demás filtros`"
            @click="descargarElPeriodoExportable"
          >
            <span v-if="exportando" class="girador" aria-hidden="true" />
            {{ exportando ? 'Generando…' : `Descargar los últimos ${MESES_EXPORTABLES} meses` }}
          </button>
        </template>

        <template v-else-if="puedeExportar">
          <button
            v-for="opcion in OPCIONES_EXPORTACION"
            :key="opcion.clave"
            type="button"
            class="boton boton--pequeno"
            :class="opcion.principal ? 'boton--principal' : 'boton--secundario'"
            :disabled="Boolean(exportando) || !hayResultados"
            :title="
              hayResultados ? opcion.pista : 'Sin resultados que exportar con los filtros actuales'
            "
            @click="exportar(opcion)"
          >
            <span v-if="exportando === opcion.clave" class="girador" aria-hidden="true" />
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
    <p v-if="puedeExportar && descargaFueraDeVentana && hayResultados" class="tabla__pista-descarga">
      La descarga a Excel cubre como mucho los últimos {{ MESES_EXPORTABLES }} meses, para no cargar
      el servidor con el histórico entero. El botón pone ese periodo en los filtros y lo descarga;
      para el histórico anterior, acota por palabra clave, CPC o provincia, o consúltalo aquí, que
      la tabla sí llega a todo.
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
        Prueba a quitar algún filtro o a probar con «Cualquiera» en vez de «Todas»: con «Todas» se
        exige que la contratación mencione **todas** las palabras a la vez, y es la causa habitual de
        que una búsqueda con varias palabras no devuelva nada.
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
              <th scope="col" class="tabla__th--nro">#<span class="solo-lectores"> Número de orden</span></th>
              <th v-for="columna in COLUMNAS" :key="columna.clave" scope="col" :class="`tabla__th--${columna.tipo}`">
                {{ columna.etiqueta }}
              </th>
              <th scope="col" class="tabla__th--acciones"><span class="solo-lectores">Detalle</span></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="(fila, indice) in registros" :key="valor(fila, 'codigo') || fila.id">
              <tr class="tabla__fila" @click="alternar(fila)">
                <td class="tabla__nro" data-etiqueta="Nro.">
                  <span class="numeros">{{ numeroDeFila(indice) }}</span>
                </td>
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

                  <span v-else-if="columna.tipo === 'estado'" class="etiqueta" :class="etiquetaEstado(valor(fila, columna.clave))">
                    {{ sinEtiquetas(valor(fila, columna.clave)) || 'Sin estado' }}
                  </span>

                  <span v-else-if="columna.tipo === 'fecha'" class="numeros">
                    {{ fechaCorta(valor(fila, columna.clave)) }}
                  </span>

                  <button
                    v-else-if="columna.tipo === 'ubicacion'"
                    type="button"
                    class="tabla__ubicacion"
                    :title="valor(fila, columna.clave)"
                    @click.stop="filtrarPorProvincia(valor(fila, columna.clave))"
                  >
                    {{ recortar(sinEtiquetas(valor(fila, columna.clave)), 30) || '—' }}
                  </button>

                  <span
                    v-else-if="columna.tipo === 'plazo'"
                    class="plazo"
                    :class="nivelDePlazo(plazo(fila))"
                  >
                    {{ textoDePlazo(plazo(fila)) }}
                  </span>

                  <span v-else class="tabla__largo" :title="sinEtiquetas(valor(fila, columna.clave))">
                    {{ recortar(sinEtiquetas(valor(fila, columna.clave)), 90) || '—' }}
                  </span>
                </td>
                <td class="tabla__acciones">
                  <button
                    type="button"
                    class="boton boton--fantasma boton--icono"
                    :aria-expanded="estaDesplegada(fila)"
                    :aria-label="`Ver el detalle de ${valor(fila, 'codigo') || 'esta contratación'}`"
                    @click.stop="alternar(fila)"
                  >
                    <span aria-hidden="true" class="tabla__chevron">▾</span>
                  </button>
                </td>
              </tr>

              <tr v-if="estaDesplegada(fila)" class="tabla__detalle-fila">
                <td :colspan="COLUMNAS.length + 2">
                  <!-- El enlace al portal va aquí arriba y destacado porque es la acción: quien abre
                       el detalle de una ínfima cuantía quiere ver el proceso completo, y el resto de
                       los campos son el contexto para decidir si vale la pena abrirlo. -->
                  <a
                    v-if="fila.enlace_publico"
                    class="boton boton--secundario boton--pequeno detalle__enlace"
                    :href="fila.enlace_publico"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <span aria-hidden="true">↗</span>
                    Abrir el proceso en el portal de la fuente
                  </a>

                  <dl class="detalle">
                    <div v-for="dato in detalles(fila)" :key="dato.clave" class="detalle__par">
                      <dt>{{ dato.clave.replaceAll('_', ' ') }}</dt>
                      <dd>{{ dato.valor }}</dd>
                    </div>
                  </dl>

                  <!--
                    El desglose del objeto de compra tal y como lo publica la ficha: un renglón por
                    ítem, con su clasificación CPC. El resumen de la columna dice **de qué** está
                    clasificada la contratación; esto dice **qué** se compra en cada línea, que es lo
                    que hace falta para decidir si vale la pena abrir el proceso en el portal.

                    Si no hay ítems puede ser que la ficha aún no se haya leído, y entonces no se
                    pinta nada: una tabla vacía parecería un error.
                  -->
                  <div v-if="itemsDe(fila).length" class="detalle__items">
                    <p class="detalle__items-titulo">
                      Detalle del objeto de compra ({{ itemsDe(fila).length }}
                      {{ itemsDe(fila).length === 1 ? 'ítem' : 'ítems' }})
                    </p>
                    <div class="items__marco">
                      <table class="items">
                        <thead>
                          <tr>
                            <th scope="col">#</th>
                            <th scope="col">CPC</th>
                            <th scope="col">Descripción del producto</th>
                            <th scope="col">Unidad</th>
                            <th scope="col">Cantidad</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="(item, indice) in itemsDe(fila)" :key="`${indice}-${item.codigo}`">
                            <td class="numeros">{{ item.numero ?? indice + 1 }}</td>
                            <td class="items__cpc">
                              <span class="codigo numeros">{{ item.codigo }}</span>
                              <span class="items__nombre">{{ item.descripcion_cpc }}</span>
                            </td>
                            <td>{{ item.descripcion }}</td>
                            <td>{{ item.unidad }}</td>
                            <td class="numeros">{{ item.cantidad }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Fichas para pantallas estrechas -->
      <ul class="fichas">
        <li v-for="fila in registros" :key="`f-${valor(fila, 'codigo') || fila.id}`" class="ficha-registro">
          <div class="ficha-registro__cabecera">
            <a
              v-if="fila.enlace_publico"
              class="codigo numeros codigo--enlace"
              :href="fila.enlace_publico"
              target="_blank"
              rel="noopener noreferrer"
              :title="`Abrir ${valor(fila, 'codigo')} en el portal de la fuente`"
            >
              {{ valor(fila, 'codigo') || '—' }}
              <span class="codigo__fuera" aria-hidden="true">↗</span>
            </a>
            <span v-else class="codigo numeros">{{ valor(fila, 'codigo') || '—' }}</span>
            <span class="etiqueta" :class="etiquetaEstado(valor(fila, 'estado'))">
              {{ sinEtiquetas(valor(fila, 'estado')) || 'Sin estado' }}
            </span>
            <span class="plazo" :class="nivelDePlazo(plazo(fila))">
              {{ textoDePlazo(plazo(fila)) }}
            </span>
          </div>
          <p class="ficha-registro__objeto">{{ sinEtiquetas(valor(fila, 'objeto_compra')) || '—' }}</p>
          <p class="ficha-registro__objeto">{{ sinEtiquetas(valor(fila, 'entidad')) || 'Sin razón social' }}</p>
          <div class="ficha-registro__pie">
            <button type="button" class="tabla__ubicacion" @click="filtrarPorProvincia(valor(fila, 'provincia'))">
              {{ recortar(sinEtiquetas(valor(fila, 'provincia')), 28) || 'Sin provincia' }}
            </button>
            <span class="numeros">{{ fechaCorta(valor(fila, 'fecha_publicacion')) }}</span>
          </div>
        </li>
      </ul>

      <slot name="paginacion" />
    </template>
  </section>
</template>

<style scoped>
.tabla__contenedor {
  overflow-x: auto;
}

.tabla__acciones-cabecera {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  align-items: center;
}

.tabla__exportacion {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  background: var(--ok-suave);
  color: var(--ok);
  font-size: var(--t-xs);
}

/*
 * La pista de la ventana de descarga: informa de un límite, no de un error, así que va en tono
 * neutro y no en el color de aviso. Con el color del error parecería que algo ha fallado.
 */
.tabla__pista-descarga {
  padding: var(--e-2) var(--e-3);
  border-radius: var(--r-1);
  background: var(--superficie-2);
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

.codigo--enlace:focus-visible {
  outline: 2px solid var(--acento);
  outline-offset: 2px;
  border-radius: var(--r-1);
}

.codigo__fuera {
  margin-left: 0.25em;
  font-size: 0.85em;
  opacity: 0.75;
}

.detalle__enlace {
  margin-bottom: var(--e-3);
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
  padding: var(--e-3) var(--e-4);
  text-align: left;
  font-size: var(--t-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--texto-tenue);
  background: var(--superficie);
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

.tabla td {
  padding: var(--e-3) var(--e-4);
  border-bottom: 1px solid var(--borde);
  vertical-align: top;
}

.tabla__largo {
  display: block;
  max-width: 42ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tabla__th--nro,
.tabla__nro {
  width: 1%;
  text-align: right;
  color: var(--texto-tenue);
}

.tabla__th--plazo,
.tabla__td--plazo {
  text-align: right;
  white-space: nowrap;
}

.codigo {
  font-family: var(--fuente-numeros);
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-suave);
  white-space: nowrap;
}

.tabla__ubicacion {
  border: 0;
  padding: 0;
  background: none;
  color: var(--acento);
  text-align: left;
  font-size: inherit;
  cursor: pointer;
  text-decoration: underline;
  text-decoration-color: transparent;
  transition: text-decoration-color var(--rapido) var(--curva);
}

.tabla__ubicacion:hover {
  text-decoration-color: currentColor;
}

.tabla__acciones {
  width: 44px;
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

.detalle {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--e-3) var(--e-5);
  padding: var(--e-4) var(--e-5);
  margin: 0;
  animation: aparecer var(--normal) var(--curva-entrada) both;
}

.detalle__par dt {
  font-size: var(--t-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-tenue);
  margin-bottom: 2px;
}

.detalle__par dd {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--texto-suave);
  overflow-wrap: anywhere;
}

/* El desglose de ítems: lo que la ficha publica línea a línea. */
.detalle__items {
  padding: 0 var(--e-5) var(--e-4);
  animation: aparecer var(--normal) var(--curva-entrada) both;
}

.detalle__items-titulo {
  font-size: var(--t-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-tenue);
  margin-bottom: var(--e-2);
}

/*
 * El marco lleva el desplazamiento y no la página: un desglose de treinta y seis ítems —los hay—
 * desplazaría la tabla entera de lado en pantallas medianas.
 */
.items__marco {
  overflow-x: auto;
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
}

.items {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--t-sm);
}

.items th,
.items td {
  text-align: left;
  padding: var(--e-2) var(--e-3);
  border-bottom: 1px solid var(--borde);
  vertical-align: top;
}

.items th {
  font-size: var(--t-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--texto-tenue);
  white-space: nowrap;
}

.items tbody tr:last-child td {
  border-bottom: none;
}

.items__cpc {
  white-space: nowrap;
}

.items__nombre {
  color: var(--texto-suave);
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
  margin: var(--e-4);
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
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

.ficha-registro__pie {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

@media (max-width: 1023px) {
  .tabla__contenedor {
    display: none;
  }

  .fichas {
    display: block;
  }
}
</style>
