<script setup>
/**
 * El panel: barra superior, filtros a un lado y el contenido al otro.
 *
 * Aquí vive la única pieza de lógica que no es de presentación: **una sola recarga por cambio de
 * filtro**, retrasada unos milisegundos.
 *
 * Por qué retrasada
 * -----------------
 * Cambiar de fecha con el selector dispara un cambio por cada tecla y por cada flecha del calendario.
 * Sin el retraso, mover la fecha dos días lanzaría cuatro peticiones y las respuestas podrían llegar
 * desordenadas: la tabla mostraría el resultado de una fecha intermedia y parecería que el filtro no
 * responde. Con el retraso se envía una sola petición, la del estado final.
 *
 * Y una sola, no dos
 * ------------------
 * Cada recarga pide los registros **y** las gráficas juntas, en vez de dejar que cada tarjeta pida lo
 * suyo al detectar el cambio. Si cada una lo hiciera por su cuenta, el mismo cambio de filtro
 * provocaría cuatro peticiones casi simultáneas, que además competirían por el mismo servidor y
 * podrían pintar estados intermedios distintos en la tabla y en el gráfico.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import BarraSuperior from '@/components/BarraSuperior.vue'
import CambiarContrasena from '@/components/CambiarContrasena.vue'
import GestionUsuarios from '@/components/GestionUsuarios.vue'
import GraficaFuentes from '@/components/GraficaFuentes.vue'
import GraficaProvincias from '@/components/GraficaProvincias.vue'
import GraficaSerie from '@/components/GraficaSerie.vue'
import ListaProvincia from '@/components/ListaProvincia.vue'
import MapaEcuador from '@/components/MapaEcuador.vue'
import OfertasTab from '@/components/OfertasTab.vue'
import PanelEmpresas from '@/components/PanelEmpresas.vue'
import Paginacion from '@/components/Paginacion.vue'
import PanelFiltros from '@/components/PanelFiltros.vue'
import TablaRegistros from '@/components/TablaRegistros.vue'
import { usePresencia } from '@/composables/usePresencia'
import { filtros } from '@/stores/filtros'
import { datos } from '@/stores/datos'
import { sesion } from '@/stores/sesion'
import { haceCuanto } from '@/utils/formato'

const props = defineProps({
  tema: { type: String, default: 'claro' },
})

const emit = defineEmits(['alternar-tema', 'cerrar-sesion'])

const presencia = usePresencia()

const panelCuentaAbierto = ref(false)
const filtrosAbiertos = ref(false)
const pestana = ref('resumen')
const cambiandoContrasena = ref(false)
const exito = ref('')

/** Pestañas del contenido. En móvil evitan apilar mapa, cuatro gráficas y una tabla. */
const PESTANAS_BASE = [
  { id: 'resumen', etiqueta: 'Resumen', icono: '◎' },
  { id: 'mapa', etiqueta: 'Mapa', icono: '▣' },
  { id: 'registros', etiqueta: 'Registros', icono: '≡' },
  // El listado del portal de procesos. Va aquí, junto a «Registros», porque es la otra forma de
  // mirar lo mismo: uno acota por palabras clave y el otro por entidad, tipo y código.
  { id: 'ofertas', etiqueta: 'Ofertas', icono: '▤' },
]

/**
 * La pestaña de usuarios solo existe para quien puede administrar cuentas.
 *
 * Se oculta en lugar de mostrarla y que falle: un consultor que pulse «Usuarios» y reciba un error de
 * permisos entendería que el sistema está roto, no que él no tiene esa capacidad. El servidor lo
 * rechazaría igualmente —ahí está la barrera de verdad—, pero no hay motivo para ofrecer a nadie un
 * botón que solo puede llevarle a un rechazo.
 */
const PESTANAS = computed(() => {
  const base = sesion.esAdministrativo.value
    ? [...PESTANAS_BASE, { id: 'usuarios', etiqueta: 'Usuarios', icono: '⬢' }]
    : PESTANAS_BASE
  // La pestaña de empresas es la única pantalla que mira a todas las empresas a la vez, así que solo
  // la tiene el dueño del sistema. Un administrador de negocio no la ve porque no hay nada suyo ahí.
  if (sesion.estado.rol !== 'super_admin') return base
  return [...base, { id: 'empresas', etiqueta: 'Empresas', icono: '⌂' }]
})

function alCambiarContrasena(resultado) {
  cambiandoContrasena.value = false
  exito.value = (resultado?.avisos || []).join(' ') || 'Tu contraseña ha cambiado.'
}

let temporizador = null

/**
 * Recarga con retraso. Se cancela el anterior en lugar de encolarlos: solo interesa el estado final
 * de los filtros, y ejecutar los intermedios gastaría peticiones en resultados que nadie verá.
 */
function recargar({ inmediato = false } = {}) {
  clearTimeout(temporizador)
  if (inmediato) {
    datos.cargar()
    return
  }
  temporizador = setTimeout(() => datos.cargar(), 280)
}

// `deep` porque los filtros son un objeto con una lista dentro: cambiar una palabra clave muta el
// arreglo y sin `deep` el vigilante no lo vería.
watch(
  () => filtros.parametros.value,
  () => recargar(),
  { deep: true },
)

onMounted(async () => {
  // Las tres primeras peticiones van a la vez: son independientes y encadenarlas daría tres esperas
  // seguidas antes de que aparezca nada.
  await Promise.all([filtros.cargarPalabras(), datos.cargarCatalogos()])
  await datos.cargar()
})

onBeforeUnmount(() => {
  clearTimeout(temporizador)
  // Aquí se avisaba al servidor del cierre de la ventana, y ese aviso revocaba la sesión. Se quitó
  // por dos motivos: al recargar la página no salta, pero **cualquier desmontaje del panel sí** —y
  // en desarrollo eso pasa en cada recarga en caliente—, así que la sesión se caía sola. Cerrar el
  // panel ya no cierra la sesión: la cierran el botón de salir, la expulsión por superar el tope y
  // la caducidad.
  datos.limpiar()
})

const aviso = computed(() => sesion.estado.error)

/** Permite ocultar el cartel de ejemplo sin recargar, aunque vuelve a aparecer al recargar. */
const ejemploOculto = ref(false)
const mostrarAvisoEjemplo = computed(() => datos.estado.usandoEjemplo && !ejemploOculto.value)

const ultimaActualizacion = computed(() =>
  datos.estado.generacion
    ? `Datos de la generación ${datos.estado.generacion}`
    : 'Sin ingesta registrada todavía',
)
</script>

<template>
  <div class="panel">
    <BarraSuperior
      :tema="props.tema"
      :nombre="sesion.estado.nombre"
      :email="sesion.estado.email"
      :admin="sesion.esAdministrativo.value"
      :conectados="presencia.conectados.value"
      :total="presencia.total.value"
      :personas="presencia.personas.value"
      :alcance="presencia.alcance.value"
      :en-vivo="presencia.enVivo.value"
      :panel-abierto="panelCuentaAbierto"
      @alternar-tema="emit('alternar-tema')"
      @cerrar-sesion="emit('cerrar-sesion')"
      @alternar-panel="panelCuentaAbierto = !panelCuentaAbierto"
      @cambiar-contrasena="cambiandoContrasena = true"
      @alternar-filtros="filtrosAbiertos = !filtrosAbiertos"
    />

    <p v-if="exito" class="panel__exito aparece" role="status">
      {{ exito }}
      <button type="button" class="boton boton--fantasma boton--pequeno" aria-label="Ocultar" @click="exito = ''">
        ✕
      </button>
    </p>

    <!-- Aviso de datos de ejemplo. No se puede cerrar de forma permanente a propósito: si se
         recordara la elección, alguien podría volver al panel semanas después, con datos reales ya
         cargados, y seguir con el cartel oculto sin darse cuenta de que ahora sí son reales. -->
    <Transition name="deslizar">
      <div v-if="mostrarAvisoEjemplo" class="aviso-ejemplo" role="status">
        <span class="aviso-ejemplo__icono" aria-hidden="true">⚗</span>
        <p>
          <strong>Estás viendo datos de ejemplo.</strong>
          No hay contrataciones ingestadas para estos filtros todavía, así que las cifras son
          inventadas para poder revisar el diseño. Aparecerán datos reales cuando el proceso de
          ingesta complete un ciclo.
        </p>
        <button
          type="button"
          class="boton boton--fantasma boton--pequeno"
          aria-label="Ocultar el aviso de datos de ejemplo"
          @click="ejemploOculto = true"
        >
          ✕
        </button>
      </div>
    </Transition>

    <p v-if="aviso" class="panel__aviso" role="alert">{{ aviso }}</p>

    <div class="panel__cuerpo">
      <!-- Filtros: columna fija en escritorio, cajón deslizante en móvil. -->
      <aside class="panel__lateral superficie" :class="{ 'panel__lateral--abierto': filtrosAbiertos }">
        <div class="panel__lateral-cabecera">
          <p class="panel__lateral-titulo">Filtros</p>
          <button
            type="button"
            class="boton boton--fantasma boton--icono panel__lateral-cerrar"
            aria-label="Cerrar los filtros"
            @click="filtrosAbiertos = false"
          >
            ✕
          </button>
        </div>
        <PanelFiltros />
      </aside>

      <!-- Velo que cierra el cajón al tocarlo. Solo se pinta cuando el cajón está abierto. -->
      <div
        v-if="filtrosAbiertos"
        class="panel__velo"
        aria-hidden="true"
        @click="filtrosAbiertos = false"
      />

      <main class="panel__principal">
        <nav class="pestanas" aria-label="Secciones del panel">
          <button
            v-for="opcion in PESTANAS"
            :key="opcion.id"
            type="button"
            class="pestanas__boton"
            :class="{ 'pestanas__boton--activa': pestana === opcion.id }"
            :aria-selected="pestana === opcion.id"
            role="tab"
            @click="pestana = opcion.id"
          >
            <span aria-hidden="true">{{ opcion.icono }}</span>
            {{ opcion.etiqueta }}
            <span v-if="opcion.id === 'registros' && datos.estado.total" class="pestanas__cuenta">
              {{ datos.estado.total }}
            </span>
          </button>
        </nav>

        <section v-show="pestana === 'resumen'" class="rejilla">
          <GraficaProvincias />
          <GraficaSerie />
          <GraficaFuentes />
        </section>

        <section v-show="pestana === 'mapa'" class="panel__pila">
          <div class="rejilla rejilla--mapa">
            <div class="tarjeta aparece">
              <header class="tarjeta__cabecera">
                <div>
                  <p class="tarjeta__titulo">Mapa de provincias</p>
                  <p class="tarjeta__pista">
                    Pulsa una provincia para ver solo sus contrataciones y aplica los filtros
                  </p>
                </div>
              </header>
              <div class="tarjeta__cuerpo">
                <MapaEcuador />
              </div>
            </div>
            <GraficaProvincias />
          </div>

          <ListaProvincia @ver-todos="pestana = 'registros'" />

          <!-- La misma tabla que la pestaña Registros, con su detalle desplegable y su paginación.
               Es lo que responde a «ver todas las contrataciones de la región con los filtros
               aplicados» sin cambiar de pestaña: el listado propio que había aquí recortaba el objeto
               y la entidad, no dejaba abrir el detalle de una ínfima cuantía y no paginaba. -->
          <TablaRegistros>
            <template #paginacion>
              <Paginacion
                :pagina="filtros.estado.pagina"
                :paginas="datos.estado.paginas"
                :total="datos.estado.total"
                :tamano="filtros.estado.tamano"
                @cambiar="filtros.cambiarPagina"
              />
            </template>
          </TablaRegistros>
        </section>

        <section v-show="pestana === 'empresas'">
          <PanelEmpresas />
        </section>

        <section v-show="pestana === 'registros'">
          <TablaRegistros>
            <template #paginacion>
              <Paginacion
                :pagina="filtros.estado.pagina"
                :paginas="datos.estado.paginas"
                :total="datos.estado.total"
                :tamano="filtros.estado.tamano"
                @cambiar="filtros.cambiarPagina"
              />
            </template>
          </TablaRegistros>
        </section>

        <section v-show="pestana === 'ofertas'">
          <OfertasTab />
        </section>

        <section v-show="pestana === 'usuarios'" class="tarjeta aparece">
          <div class="tarjeta__cuerpo">
            <GestionUsuarios />
          </div>
        </section>

        <footer class="panel__pie">
          <span>{{ ultimaActualizacion }}</span>
          <span v-if="datos.estado.desdeCache">· respuesta servida desde la memoria intermedia</span>
          <span v-if="presencia.enVivo.value">· presencia en vivo</span>
          <span v-else-if="presencia.error.value" :title="presencia.error.value">
            · presencia sin conexión
          </span>
        </footer>
      </main>
    </div>

    <CambiarContrasena
      v-if="cambiandoContrasena"
      @cerrar="cambiandoContrasena = false"
      @cambiada="alCambiarContrasena"
    />

    <!-- Botón flotante para abrir los filtros en móvil: la barra superior ya tiene el suyo, pero
         queda lejos del pulgar cuando la lista es larga. -->
    <button
      type="button"
      class="panel__flotante"
      :aria-label="filtros.hayFiltros.value ? 'Abrir los filtros (hay filtros activos)' : 'Abrir los filtros'"
      @click="filtrosAbiertos = true"
    >
      <span aria-hidden="true">⚙</span>
      <span v-if="filtros.hayFiltros.value" class="panel__flotante-marca" aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.panel {
  min-height: 100vh;
  padding-bottom: var(--e-6);
}

.panel__cuerpo {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: var(--e-5);
  align-items: start;
  padding: var(--e-5);
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
}

.panel__lateral {
  position: sticky;
  top: calc(var(--altura-cabecera) + var(--e-4));
  padding: var(--e-5);
  max-height: calc(100vh - var(--altura-cabecera) - var(--e-6));
  overflow-y: auto;
}

.panel__lateral-cabecera {
  display: none;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--e-3);
}

.panel__lateral-titulo {
  font-weight: 700;
  font-size: var(--t-md);
}

.panel__principal {
  display: flex;
  flex-direction: column;
  gap: var(--e-5);
  min-width: 0;
}

.rejilla {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: var(--e-5);
  align-items: start;
  animation: aparecer var(--normal) var(--curva-entrada) both;
}

.rejilla--mapa {
  grid-template-columns: minmax(0, 1.5fr) minmax(300px, 1fr);
}

/* El mapa arriba y, debajo, las contrataciones de la provincia elegida. Van en la misma pestaña
   porque mirar el mapa y tener que cambiar de pestaña para ver qué hay es un ida y vuelta. */
.panel__pila {
  display: flex;
  flex-direction: column;
  gap: var(--e-4);
}

.pestanas {
  display: flex;
  gap: var(--e-1);
  padding: var(--e-1);
  border-radius: var(--r-2);
  background: var(--superficie-2);
  border: 1px solid var(--borde);
  align-self: flex-start;
  max-width: 100%;
  overflow-x: auto;
}

.pestanas__boton {
  display: inline-flex;
  align-items: center;
  gap: var(--e-2);
  padding: 0.4rem 0.9rem;
  border: 0;
  border-radius: var(--r-1);
  background: transparent;
  font-size: var(--t-sm);
  font-weight: 600;
  color: var(--texto-tenue);
  cursor: pointer;
  white-space: nowrap;
  transition: background-color var(--rapido) var(--curva), color var(--rapido) var(--curva);
}

.pestanas__boton:hover {
  color: var(--texto);
}

.pestanas__boton--activa {
  background: var(--superficie);
  color: var(--texto);
  box-shadow: var(--sombra-1);
}

.pestanas__cuenta {
  padding: 0 0.35rem;
  border-radius: var(--r-redondo);
  background: var(--acento-tenue);
  color: var(--acento-fuerte);
  font-size: 0.7rem;
  font-weight: 700;
}

.panel__aviso {
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--error);
  background: var(--error-suave);
  color: var(--error);
  font-size: var(--t-sm);
}

/* Confirmación de una acción que salió bien. Se puede cerrar, pero no desaparece sola: los avisos que
   se van solos son los que nadie lee cuando llega justo en el momento en que uno mira a otro sitio. */
.panel__exito {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--e-3);
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border-left: 3px solid var(--ok);
  background: var(--ok-suave);
  color: var(--ok);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.aviso-ejemplo {
  display: flex;
  align-items: flex-start;
  gap: var(--e-3);
  margin: var(--e-4) var(--e-5) 0;
  padding: var(--e-3) var(--e-4);
  border-radius: var(--r-2);
  border: 1px dashed var(--aviso);
  background: var(--aviso-suave);
  color: var(--aviso);
  font-size: var(--t-sm);
  line-height: 1.5;
}

.aviso-ejemplo__icono {
  font-size: var(--t-md);
  line-height: 1.2;
}

.aviso-ejemplo p {
  flex: 1;
}

.panel__pie {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2);
  font-size: var(--t-xs);
  color: var(--texto-tenue);
}

.panel__velo {
  display: none;
}

.panel__flotante {
  display: none;
  position: fixed;
  right: var(--e-4);
  bottom: var(--e-4);
  z-index: 40;
  width: 52px;
  height: 52px;
  border: 0;
  border-radius: 50%;
  background: var(--acento);
  color: #fff;
  font-size: 1.3rem;
  box-shadow: var(--sombra-2);
  cursor: pointer;
}

.panel__flotante-marca {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--ok);
  border: 2px solid var(--acento);
}

/* Transición del cartel de datos de ejemplo. Se declara aquí porque las clases de `<Transition>`
   tienen que existir en algún sitio y este es el único componente que usa ese nombre. */
.deslizar-enter-active,
.deslizar-leave-active {
  transition: opacity var(--normal) var(--curva), transform var(--normal) var(--curva);
}

.deslizar-enter-from,
.deslizar-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (max-width: 1023px) {
  .panel__cuerpo {
    grid-template-columns: minmax(0, 1fr);
    padding: var(--e-4);
    gap: 0;
  }

  /* El panel de filtros pasa a ser un cajón. Se saca del flujo con `position: fixed` en lugar de
     apilarlo encima del contenido: apilado, cambiar un filtro obligaría a desplazarse hasta arriba
     para ver el efecto, y el efecto es justo lo que se quiere comprobar. */
  .panel__lateral {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 50;
    width: min(340px, 88vw);
    max-height: none;
    border-radius: 0;
    border: 0;
    border-right: 1px solid var(--borde);
    transform: translateX(-102%);
    transition: transform var(--normal) var(--curva);
    overflow-y: auto;
  }

  .panel__lateral--abierto {
    transform: translateX(0);
    box-shadow: var(--sombra-3);
  }

  .panel__lateral-cabecera {
    display: flex;
  }

  .panel__velo {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 45;
    background: rgb(0 0 0 / 35%);
    animation: aparecer var(--rapido) var(--curva) both;
  }

  .panel__flotante {
    display: grid;
    place-items: center;
  }

  .rejilla,
  .rejilla--mapa {
    grid-template-columns: minmax(0, 1fr);
  }

  .aviso-ejemplo,
  .panel__aviso {
    margin-left: var(--e-4);
    margin-right: var(--e-4);
  }
}

@media (min-width: 1024px) {
  .panel__flotante {
    display: none;
  }
}
</style>
