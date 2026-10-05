/**
 * Envoltorio de Chart.js para Vue.
 *
 * Hace tres cosas que, si se dejan a cada componente, se hacen mal o se olvidan:
 *
 * 1. **Destruye la gráfica al desmontar.** Chart.js guarda un lienzo y escuchas de eventos internos.
 *    Sin destruirla, cambiar de pestaña veinte veces deja veinte gráficas vivas pintando sobre un
 *    lienzo que ya no está en la página: consumo de memoria que crece y animaciones fantasma.
 *
 * 2. **Vuelve a pintar cuando cambia el tema.** Los colores se leen de las variables CSS, y Chart.js
 *    los copia en el momento de construirse. Al pasar a tema oscuro, las gráficas seguirían con los
 *    colores del claro sobre un fondo oscuro: líneas grises casi invisibles y leyendas ilegibles. Se
 *    observa el atributo del tema y se reconstruye.
 *
 * 3. **Filtra las animaciones si el sistema pide menos movimiento.** Chart.js anima por su cuenta y
 *    no mira `prefers-reduced-motion`.
 *
 * 4. **Dibuja la gráfica cuando su sección se ve.** El panel tiene todas las pestañas en el documento
 *    a la vez —se ocultan con `v-show`, no se desmontan—, así que una gráfica puede nacer con su
 *    sección en `display: none`. En ese caso Chart.js **no se entera** de que el contenedor aparece:
 *    su observador de tamaño vigila el lienzo, y el lienzo del taller mide 300×150 antes y después
 *    de mostrarse, así que el tamaño no cambia y no hay nada que redimensionar. La gráfica se queda
 *    en blanco hasta que algo la refresca —un filtro, el tema o una recarga de datos—, y desde
 *    fuera parece aleatorio: la misma pestaña se ve a veces y a veces no.
 */
import { onBeforeUnmount, onMounted, shallowRef, watch } from 'vue'

import {
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  Chart,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from 'chart.js'

// Registro explícito: solo entra en el paquete lo que se usa. Importar `chart.js/auto` traería
// todos los controladores, incluidos los que este panel nunca dibuja.
Chart.register(
  ArcElement,
  BarController,
  BarElement,
  CategoryScale,
  DoughnutController,
  Filler,
  Legend,
  LineController,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
)

/** Lee una variable CSS del documento. Es lo que ata las gráficas al tema del panel. */
export function colorDeToken(nombre, respaldo = '#888') {
  if (typeof window === 'undefined') return respaldo
  const valor = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim()
  return valor || respaldo
}

export function paletaSeries() {
  return [
    colorDeToken('--serie-1'),
    colorDeToken('--serie-2'),
    colorDeToken('--serie-3'),
    colorDeToken('--serie-4'),
    colorDeToken('--serie-5'),
    colorDeToken('--serie-6'),
  ]
}

function prefiereMenosMovimiento() {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  )
}

/**
 * @param {() => object} construir  Devuelve la configuración de Chart.js.
 * @param {() => boolean} [depende] Señal que, al cambiar, obliga a reconstruir.
 */
export function useGrafica(construir, depende) {
  const lienzo = shallowRef(null)
  let grafica = null
  let observador = null
  let visible = null

  function dibujar() {
    if (!lienzo.value) return
    grafica?.destroy()

    // Se construye **una sola vez**. Llamar dos veces devolvería dos objetos distintos, y el `onClick`
    // que quedara registrado podría no ser el del dibujo que se ve.
    const configuracion = construir()
    const sinMovimiento = prefiereMenosMovimiento()

    grafica = new Chart(lienzo.value, {
      ...configuracion,
      options: {
        ...configuracion.options,
        ...(sinMovimiento ? { animation: false, transitions: {} } : {}),
      },
    })

    vigilarVisibilidad(lienzo.value)
  }

  /**
   * Redibuja la gráfica cuando su lienzo entra en pantalla **si nunca llegó a dibujarse de verdad**.
   *
   * Es lo que saca del blanco a una gráfica que nació escondida. Las pestañas del panel conviven en
   * el documento con `v-show`, así que una gráfica puede montarse con su sección en `display: none`;
   * entonces Chart.js no se entera de que el contenedor aparece, porque su observador de tamaño
   * vigila el lienzo y el lienzo mide 300×150 antes y después de mostrarse: el tamaño no cambia y no
   * hay nada que redimensionar. Medido: `width: 300, height: 150` y **cero píxeles pintados** después
   * de mostrar la pestaña, hasta que algo la refrescaba (un filtro, el tema, una recarga) — y por eso
   * parecía aleatorio.
   *
   * `width` y `height` en cero son la firma de «nací escondida y nadie me ha medido». En los cambios
   * de visibilidad normales, con la gráfica ya medida, no se toca nada: rehacerla en cada ida y
   * vuelta perdería la animación y el estado del cursor.
   *
   * Se ata al lienzo que se acaba de dibujar y no al que hubiera al montar, y ahí estuvo un fallo que
   * tumbó el panel entero: una tarjeta con el lienzo detrás de un `v-if` monta **sin** canvas, así que
   * `observe(null)` lanzaba `parameter 1 is not of type 'Element'` dentro del `onMounted` y la
   * excepción se llevaba por delante el resto del montaje —el panel se quedaba pintado y sin datos,
   * sin una sola petición en la red—.
   */
  function vigilarVisibilidad(elemento) {
    visible?.disconnect()
    visible = new IntersectionObserver((entradas) => {
      for (const entrada of entradas) {
        if (entrada.isIntersecting && grafica && (!grafica.width || !grafica.height)) {
          dibujar()
        }
      }
    })
    visible.observe(elemento)
  }

  /**
   * Refresca los datos **sin destruir la gráfica**.
   *
   * Aquí estaba el parpadeo. Cada cambio de filtro llamaba a `dibujar`, que destruye el objeto y crea
   * otro: el lienzo se vacía, la gráfica arranca su animación desde cero y, si los cambios llegan
   * seguidos, nunca llega a asentarse. Se veía como barras que saltan y se reordenan solas.
   *
   * Reemplazar `data` y llamar a `update()` conserva el objeto: Chart.js interpola de la forma anterior
   * a la nueva, así que las barras **crecen o se acortan** en lugar de recomponerse. Es más rápido
   * —no se vuelven a calcular escalas ni se re-registran los escuchas— y es lo que hace que se sienta
   * fluido.
   *
   * Se rehace desde cero en dos casos, y los dos importan: si aún no existe, y si el lienzo **es otro**
   * porque el componente se ocultó y volvió (un `v-if` sobre el contenedor sustituye el canvas y la
   * gráfica anterior quedaría pintando en un nodo que ya no está en la página).
   */
  function actualizar() {
    if (!lienzo.value) return

    if (!grafica || grafica.canvas !== lienzo.value) {
      dibujar()
      return
    }

    const configuracion = construir()
    grafica.data = configuracion.data
    // Las opciones también se refrescan: ahí viven los colores del tema y el `onClick`, que dependen
    // del estado y cambiarían sin que la gráfica se enterara.
    if (configuracion.options) {
      grafica.options = { ...grafica.options, ...configuracion.options }
    }
    grafica.update()
  }

  onMounted(() => {
    dibujar()

    // El tema se cambia poniendo un atributo en `<html>`, así que se observa ese atributo concreto y
    // no todo el documento: observar el árbol entero dispararía el observador en cada cambio de la
    // interfaz y reconstruiría las gráficas sin motivo.
    observador = new MutationObserver(dibujar)
    observador.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-tema'],
    })
  })

  onBeforeUnmount(() => {
    observador?.disconnect()
    visible?.disconnect()
    grafica?.destroy()
    grafica = null
  })

  if (depende) {
    // `post` para dibujar **después** de que el navegador haya aplicado el cambio: si el aviso llega
    // junto con el de un `v-if` que acaba de crear el lienzo, en `pre` el canvas todavía no existe y
    // la gráfica nueva se quedaría sin dibujar hasta el siguiente cambio de datos.
    watch(depende, () => actualizar(), { deep: true, flush: 'post' })
  }

  return { lienzo, redibujar: dibujar }
}

/** Opciones comunes: rejilla discreta, sin leyenda cuando no aporta y con los colores del tema. */
export function opcionesBase({ conLeyenda = false } = {}) {
  const texto = colorDeToken('--texto-suave')
  const tenue = colorDeToken('--texto-tenue')
  const borde = colorDeToken('--borde')

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 700, easing: 'easeOutQuart' },
    plugins: {
      legend: {
        display: conLeyenda,
        position: 'bottom',
        labels: {
          color: texto,
          boxWidth: 10,
          boxHeight: 10,
          usePointStyle: true,
          pointStyle: 'circle',
          padding: 14,
          font: { size: 11 },
        },
      },
      tooltip: {
        backgroundColor: colorDeToken('--superficie'),
        titleColor: colorDeToken('--texto'),
        bodyColor: texto,
        borderColor: borde,
        borderWidth: 1,
        padding: 10,
        cornerRadius: 8,
        displayColors: false,
        titleFont: { size: 12, weight: '600' },
        bodyFont: { size: 12 },
      },
    },
    scales: {
      x: {
        grid: { display: false },
        border: { color: borde },
        ticks: { color: tenue, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 12 },
      },
      y: {
        beginAtZero: true,
        grid: { color: borde, drawTicks: false },
        border: { display: false },
        ticks: { color: tenue, font: { size: 11 }, padding: 6 },
      },
    },
  }
}
