<script setup>
/**
 * Detalle de un proceso publicado, en un cajón lateral.
 *
 * Por qué no sigue dentro de la tabla
 * -----------------------------------
 * Antes el detalle se abría **dentro** de la tabla, como una fila más con una celda que ocupaba las
 * siete columnas. Funcionaba con una fila abierta y rompía la pantalla: la rejilla de campos mide
 * como la tabla, y la tabla mide como su fila más ancha, así que al abrir un proceso el ancho total
 * se disparaba por encima de la pantalla y **todo el panel se iba de lado** —las columnas se
 * estrechaban, aparecía el desplazamiento horizontal y había que volver a buscar dónde estaba lo que
 * se estaba leyendo—. Sacarlo de la tabla es lo que arregla eso: el ancho de las columnas ya no
 * depende de lo que haya abierto.
 *
 * Por qué con secciones y no una lista de campos
 * ----------------------------------------------
 * Un proceso de OCDS trae catorce datos y leerlos seguidos no dice nada: el identificador interno, el
 * importe y la provincia pesan distinto y se miran por motivos distintos. Agrupados —qué proceso es,
 * quién y dónde, cuánto, quién se lo llevó, cuándo— la pregunta de quien abre el cajón se responde
 * bajando la vista, y los bloques que no tienen datos no se pintan en lugar de dejar huecos.
 *
 * El bloque del producto
 * ---------------------
 * Es el que responde a «¿qué se está comprando?». El objeto de compra —arriba, en la cabecera— es el
 * párrafo que escribió la entidad; el desglose son **sus ítems**, con el código del CPC, el nombre
 * estándar de lo que se compra, la unidad y la cantidad. Lo publica el fichero mensual del portal y
 * hasta hace poco se estaba tirando.
 *
 * No todos los procesos lo traen —es una parte de las publicaciones, no todas—, y por eso el bloque
 * distingue las dos ausencias en lugar de callarse: «esta fuente no publica el desglose de este
 * proceso» no es lo mismo que un hueco, y sin decirlo lo que se lee es que al panel le falta algo.
 *
 * El enlace al portal va arriba y es lo más visible, porque es la única acción del cajón.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { itemsDe } from '@/utils/cpc'
import { decimal, fechaCorta, sinEtiquetas } from '@/utils/formato'

const props = defineProps({
  /** La fila tal y como la devuelve la API: el cajón la interpreta, no la completa. */
  fila: { type: Object, required: true },
})

const emit = defineEmits(['cerrar'])

const botonCerrar = ref(null)

/** A dónde volver cuando el cajón se cierre: quien lo abrió, para no dejarlo perdido en la tabla. */
let dondeEstaba = null

const codigo = computed(() => sinEtiquetas(String(props.fila.codigo || '')) || 'Proceso sin código')
const objeto = computed(() => sinEtiquetas(String(props.fila.objeto_compra || '')))
const enlace = computed(() => props.fila.enlace_publico || null)

/**
 * Los ítems del producto, tal y como los devuelve la API.
 *
 * Se leen con `itemsDe`, la misma función que usa la tabla para la columna del CPC: si el cajón
 * tuviera su propia lectura de la misma lista, el día que una cambiara la tabla y el detalle
 * dirían cosas distintas del mismo proceso.
 */
const items = computed(() => itemsDe(props.fila))

/** La cantidad va con su unidad: «3» a secas no dice de qué. */
function cantidadDe(item) {
  const cantidad = String(item.cantidad || '').trim()
  const unidad = String(item.unidad || '').trim()
  if (!cantidad) return unidad
  return unidad ? `${cantidad} ${unidad}` : cantidad
}

/**
 * Los bloques del detalle, ya sin los campos vacíos y sin los bloques que se quedan sin ninguno.
 *
 * Se construye aquí y no con una lista de etiquetas porque el orden **es** el del contenido: primero
 * qué es el proceso, después quién lo compra y dónde, después el dinero. Un campo que la fuente no
 * publica no se enseña: una raya en un cajón que se abre a propósito parece un dato que falta.
 */
const bloques = computed(() => {
  const fila = props.fila
  const bloques = [
    {
      titulo: 'El proceso',
      campos: [
        campo('codigo', 'Código', fila.codigo),
        campo('ocid', 'Identificador OCDS', fila.ocid),
        campo('id_proceso', 'Identificador en la fuente', fila.id_proceso),
        campo('fuente', 'Fuente', fila.fuente),
        campo('tipo_proceso', 'Tipo de contratación', fila.tipo_proceso),
        campo('tipo_necesidad', 'Tipo de compra', fila.tipo_necesidad),
        campo('metodo', 'Método', nombreDeMetodo(fila.metodo)),
        campo('estado', 'Estado', fila.estado),
      ],
    },
    {
      titulo: 'La entidad y el lugar',
      campos: [
        campo('entidad', 'Entidad contratante', fila.entidad),
        campo('provincia', 'Provincia', fila.provincia),
        campo('canton', 'Cantón', fila.canton),
      ],
    },
    {
      titulo: 'El dinero',
      campos: [
        campo('presupuesto', 'Presupuesto referencial', dinero(fila.presupuesto)),
        campo('monto', 'Monto adjudicado', dinero(fila.monto)),
      ],
    },
    {
      titulo: 'El proveedor',
      campos: [campo('proveedor', 'Proveedor adjudicado', fila.proveedor)],
    },
    {
      titulo: 'Las fechas',
      campos: [
        campo('fecha_publicacion', 'Fecha de publicación', fechaCorta(fila.fecha_publicacion)),
        campo('fecha_limite_proformas', 'Límite para proformas', fechaCorta(fila.fecha_limite_proformas)),
      ],
    },
    {
      // El seguimiento es del **dato**, no del proceso: cuándo lo vimos por primera vez, cuándo por
      // última y si la fuente sigue publicándolo. Es lo que permite distinguir «se publicó ayer» de
      // «lleva dos meses en la base y ya no aparece en la fuente», que es la pregunta que se hace
      // cuando alguien busca un proceso que ya no encuentra en el portal.
      titulo: 'El dato',
      campos: [
        campo('primera_vez_visto', 'Primera vez visto', fechaCorta(fila.primera_vez_visto)),
        campo('ultima_vez_visto', 'Visto por última vez', fechaCorta(fila.ultima_vez_visto)),
        campo('clave_natural', 'Clave en la fuente', fila.clave_natural),
      ],
    },
  ]

  return bloques
    .map((bloque) => ({ ...bloque, campos: bloque.campos.filter(Boolean) }))
    .filter((bloque) => bloque.campos.length > 0)
})

function campo(clave, etiqueta, valor) {
  if (valor === null || valor === undefined || valor === '') return null
  return { clave, etiqueta, valor: String(valor) }
}

/**
 * El método de contratación llega en el vocabulario del estándar —`open`, `selective`— y en pantalla
 * no significa nada para quien lee. Se traduce lo que se conoce y se deja el original en lo demás:
 * inventar una traducción para un valor que no se ha visto sería peor que enseñarlo tal cual.
 */
function nombreDeMetodo(valor) {
  const texto = String(valor || '').trim()
  if (!texto) return ''
  const conocidos = {
    open: 'Abierto',
    selective: 'Selectivo',
    limited: 'Limitado',
    direct: 'Directo',
  }
  return conocidos[texto.toLowerCase()] || texto
}

/** Los importes van con la moneda y con dos decimales, como en la tabla de donde se abre el cajón. */
function dinero(valor) {
  if (valor === null || valor === undefined || valor === '') return ''
  return `$ ${decimal(valor)}`
}

function cerrar() {
  emit('cerrar')
}

function alTeclear(evento) {
  if (evento.key === 'Escape') cerrar()
}

onMounted(() => {
  dondeEstaba = document.activeElement
  botonCerrar.value?.focus()
  document.addEventListener('keydown', alTeclear)
  // Con el cajón abierto, la rueda del ratón detrás del velo movería la tabla que hay debajo y el
  // usuario volvería al cajón con la lista en otro sitio.
  //
  // Y se compensa el ancho de la barra con un relleno: al bloquear el desplazamiento la barra del
  // navegador desaparece y **todo el ancho disponible crece** unos píxeles, así que la tabla se
  // reacomoda justo cuando la persona acaba de pulsar. Medido sin la compensación: el área visible
  // de la tabla pasaba de 925 a 948 píxeles, que es exactamente el movimiento que este cajón viene a
  // evitar.
  const anchoBarra = window.innerWidth - document.documentElement.clientWidth
  if (anchoBarra > 0) document.body.style.paddingRight = `${anchoBarra}px`
  document.body.style.overflow = 'hidden'
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', alTeclear)
  document.body.style.overflow = ''
  document.body.style.paddingRight = ''
  if (dondeEstaba instanceof HTMLElement) dondeEstaba.focus()
})
</script>

<template>
  <div class="velo" @click.self="cerrar()">
    <aside class="cajon" role="dialog" aria-modal="true" aria-labelledby="titulo-del-proceso">
      <header class="cajon__cabecera">
        <div class="cajon__encabezado">
          <p class="cajon__etiqueta">Proceso publicado</p>
          <h2 id="titulo-del-proceso" class="cajon__titulo">{{ codigo }}</h2>
          <p v-if="objeto" class="cajon__objeto">{{ objeto }}</p>
        </div>
        <button
          ref="botonCerrar"
          type="button"
          class="boton boton--fantasma boton--icono"
          aria-label="Cerrar el detalle"
          @click="cerrar()"
        >
          ✕
        </button>
      </header>

      <div class="cajon__cuerpo">
        <!--
          La única acción del cajón, y por eso lo primero: quien abre un proceso en los datos
          abiertos quiere ver el proceso **de verdad**, con sus documentos y sus etapas. La dirección
          se compone en el servidor a partir del identificador del portal, así que aquí solo se
          pinta; cuando no hay, se dice en lugar de dejar un botón que no lleva a ninguna parte.
        -->
        <a
          v-if="enlace"
          class="boton boton--principal cajon__enlace"
          :href="enlace"
          target="_blank"
          rel="noopener noreferrer"
        >
          <span aria-hidden="true">↗</span>
          Abrir el proceso en el portal
        </a>
        <p v-else class="cajon__sin-enlace">
          Este proceso no trae dirección en los datos abiertos, así que no hay nada que abrir.
        </p>

        <section v-for="bloque in bloques" :key="bloque.titulo" class="bloque">
          <h3 class="bloque__titulo">{{ bloque.titulo }}</h3>
          <dl class="bloque__campos">
            <div v-for="dato in bloque.campos" :key="dato.clave" class="campo">
              <dt class="campo__etiqueta">{{ dato.etiqueta }}</dt>
              <dd class="campo__valor" :class="{ numeros: dato.clave === 'ocid' }">
                {{ dato.valor }}
              </dd>
            </div>
          </dl>
        </section>

        <!--
          El desglose del producto. Cada ítem va con lo que la entidad compra, la clasificación
          estándar de ese gasto y cuánto: es lo que responde a «¿qué se está comprando?» cuando el
          objeto de compra es un párrafo largo.

          Cuando no lo hay se dice, y se dice distinto según por qué: un proceso de una fuente que no
          publica desglose no es un proceso al que le falte el detalle. Callarse deja al usuario
          creyendo que el panel no cargó.
        -->
        <section v-if="items.length" class="bloque">
          <h3 class="bloque__titulo">
            El producto
            <span class="bloque__cuenta numeros">
              {{ items.length }} {{ items.length === 1 ? 'ítem' : 'ítems' }}
            </span>
          </h3>
          <ul class="producto">
            <li v-for="(item, indice) in items" :key="`${item.codigo}-${indice}`" class="producto__item">
              <p class="producto__cpc numeros">
                {{ item.codigo }}
                <span v-if="item.descripcion_cpc" class="producto__nombre">
                  {{ item.descripcion_cpc }}
                </span>
              </p>
              <p v-if="item.descripcion" class="producto__descripcion">{{ item.descripcion }}</p>
              <p v-if="cantidadDe(item)" class="producto__cantidad">
                Cantidad: <span class="numeros">{{ cantidadDe(item) }}</span>
              </p>
            </li>
          </ul>
        </section>

        <section v-else class="bloque">
          <h3 class="bloque__titulo">El producto</h3>
          <p class="producto__sin-desglose">
            Los datos abiertos no publican el desglose del producto de este proceso. Lo que la
            entidad describe que va a comprar está arriba, en el objeto de compra.
          </p>
        </section>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.velo {
  position: fixed;
  inset: 0;
  /* Por encima del cajón de filtros del móvil (50) y de los diálogos (60): el detalle se abre desde
     dentro de la tabla, así que nunca debe quedar detrás de nada. */
  z-index: 70;
  display: flex;
  justify-content: flex-end;
  background: rgb(0 0 0 / 40%);
  animation: aparecer var(--rapido) var(--curva) both;
}

.cajon {
  display: flex;
  flex-direction: column;
  width: min(34rem, 100%);
  height: 100%;
  background: var(--superficie);
  border-left: 1px solid var(--borde);
  box-shadow: var(--sombra-3);
  animation: cajon-entrada var(--normal) var(--curva-entrada) both;
}

@keyframes cajon-entrada {
  from {
    transform: translateX(12px);
    opacity: 0;
  }
  to {
    transform: translateX(0);
    opacity: 1;
  }
}

.cajon__cabecera {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--e-3);
  padding: var(--e-4) var(--e-5);
  border-bottom: 1px solid var(--borde);
}

.cajon__encabezado {
  min-width: 0;
}

.cajon__etiqueta {
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--texto-tenue);
}

.cajon__titulo {
  font-size: var(--t-lg);
  font-weight: 700;
  overflow-wrap: anywhere;
}

.cajon__objeto {
  margin-top: var(--e-1);
  font-size: var(--t-sm);
  color: var(--texto-suave);
}

.cajon__cuerpo {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
  padding: var(--e-5);
  overflow-y: auto;
}

.cajon__enlace {
  align-self: flex-start;
}

.cajon__sin-enlace {
  font-size: var(--t-sm);
  color: var(--texto-tenue);
}

.bloque {
  display: flex;
  flex-direction: column;
  gap: var(--e-2);
}

.bloque__titulo {
  font-size: var(--t-sm);
  font-weight: 700;
  color: var(--texto-suave);
}

.bloque__campos {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr));
  gap: var(--e-3);
  margin: 0;
  padding: var(--e-3) var(--e-4);
  border: 1px solid var(--borde);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

.campo {
  min-width: 0;
}

.campo__etiqueta {
  font-size: var(--t-xs);
  font-weight: 600;
  color: var(--texto-tenue);
}

.campo__valor {
  margin: 0.1rem 0 0;
  font-size: var(--t-sm);
  overflow-wrap: anywhere;
}

/*
 * El desglose del producto, ítem a ítem.
 *
 * Cada ítem es un bloque y no una fila de la rejilla de campos: el código, el nombre estándar, la
 * descripción de la entidad y la cantidad son una unidad, y repartidos por columnas se leerían como
 * cuatro datos sueltos que hay que volver a juntar con la vista.
 */
.bloque__cuenta {
  margin-left: var(--e-2);
  font-weight: 600;
  color: var(--texto-tenue);
}

.producto {
  display: flex;
  flex-direction: column;
  gap: var(--e-3);
  margin: 0;
  padding: 0;
  list-style: none;
}

.producto__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--e-3) var(--e-4);
  border: 1px solid var(--borde);
  border-left: 3px solid var(--acento);
  border-radius: var(--r-2);
  background: var(--superficie-2);
}

/* El código primero y en su tipografía, como en la tabla: es lo que se copia para buscar. */
.producto__cpc {
  font-size: var(--t-sm);
  font-weight: 700;
  overflow-wrap: anywhere;
}

.producto__nombre {
  font-weight: 400;
  color: var(--texto-suave);
}

.producto__descripcion {
  font-size: var(--t-sm);
  color: var(--texto-suave);
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.producto__cantidad,
.producto__sin-desglose {
  font-size: var(--t-xs);
  color: var(--texto-tenue);
  line-height: 1.5;
}

@media (width <= 720px) {
  .cajon {
    width: 100%;
  }

  .cajon__cabecera,
  .cajon__cuerpo {
    padding: var(--e-4);
  }
}
</style>
