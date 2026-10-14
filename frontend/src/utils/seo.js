/**
 * Título, descripción y dirección canónica de cada página.
 *
 * Por qué hace falta esto
 * -----------------------
 * El panel se sirve como una sola página: el servidor entrega siempre el mismo documento y es el
 * navegador quien decide qué se ve. Sin este archivo, las cuatro direcciones públicas compartirían
 * el título y la descripción que están escritos en `index.html`, y para un buscador serían la misma
 * página repetida cuatro veces con cuatro direcciones distintas. Aquí se corrigen en cuanto la
 * aplicación arranca.
 *
 * Que una página se pueda indexar o no **se decide en el servidor**, no aquí: las direcciones de
 * entrada y de registro no aparecen en `sitemap.xml`. Lo de este archivo es la segunda mitad de esa
 * decisión —decirle al buscador que no las guarde si llega a ellas por un enlace—, y las dos juntas
 * son las que valen. Solo con `noindex` seguirían siendo rastreables; solo con el sitemap, nada
 * impide que un enlace externo las meta en el índice.
 *
 * Lo que esto resuelve y lo que no
 * --------------------------------
 * Un buscador que ejecute el JavaScript —el de Google lo hace— ve el título y la descripción que
 * corresponden a cada dirección. Uno que no lo ejecute verá en todas el título de la portada. Esa
 * diferencia se deja dicha en el resumen de la entrega en vez de taparla, porque cerrarla del todo
 * obligaría a generar cuatro documentos al compilar y eso es una pieza más en el despliegue.
 */

/** El dominio público. Uno solo: dos dominios sirviendo lo mismo reparten la autoridad y no suman. */
const SITIO = 'https://cercoapp.com'

/**
 * La ficha de cada página.
 *
 * `indexar` no se pone a `true` por omisión en ninguna: se escribe en cada una. El panel y la
 * aceptación de términos son las únicas que no llevan el `true`, y no es un olvido —detrás hay datos
 * de una empresa y una sesión abierta, y eso no se indexa nunca—. Escribirlo explícito hace que la
 * excepción se lea como lo que es.
 *
 * `ruta` ausente o `null` significa que no hay una dirección única que declarar como canónica, y
 * entonces la etiqueta se retira. Es el caso de «no encontrada»: declarar canónica una dirección
 * que no existe es peor que no declarar ninguna.
 */
const FICHAS = {
  inicio: {
    titulo: 'CercoApp · Contratación pública del Ecuador en un solo panel',
    descripcion:
      'Busca por palabra clave y sigue las necesidades de contratación y los procesos que publica el SERCOP en Ecuador: tabla filtrable, gráficas interactivas, mapa de las 24 provincias y exportación a Excel.',
    ruta: '/',
    indexar: true,
  },
  contratacion: {
    titulo: 'Contratación pública en Ecuador: cómo encontrar y seguir las oportunidades',
    descripcion:
      'Qué publica el SERCOP, qué es el CPC y el código OCDS, y cómo localizar las necesidades de contratación y los procesos que le interesan a una empresa en Ecuador.',
    ruta: '/contratacion-publica-ecuador',
    indexar: true,
  },
  login: {
    titulo: 'Entrar · CercoApp',
    descripcion:
      'Accede con tu cuenta de CercoApp para consultar las necesidades de contratación y los procesos publicados por el SERCOP.',
    ruta: '/login',
    // No se indexa: es una pantalla de paso, y en un resultado de búsqueda no aporta nada a nadie.
    indexar: false,
  },
  registro: {
    titulo: 'Crear la cuenta de tu empresa · CercoApp',
    descripcion:
      'Crea la cuenta de tu empresa en CercoApp y empieza a seguir la contratación pública del Ecuador.',
    ruta: '/registro',
    // No se indexa: una página de alta en un buscador solo trae registros que nadie ha pedido.
    indexar: false,
  },
  'no-encontrada': {
    titulo: 'Esta dirección no existe · CercoApp',
    descripcion: 'La dirección que has escrito no corresponde a ninguna página de CercoApp.',
    indexar: false,
  },

  // Las que no son direcciones. Nunca se indexan y no declaran canónica.
  panel: {
    titulo: 'CercoApp',
    descripcion: 'Panel de contratación pública del Ecuador.',
    indexar: false,
  },
  terminos: {
    titulo: 'Términos y condiciones · CercoApp',
    descripcion: 'Aceptación de los términos y condiciones de uso de CercoApp.',
    indexar: false,
  },
  suspendido: {
    titulo: 'Acceso suspendido · CercoApp',
    descripcion: 'El acceso de esta empresa a CercoApp está suspendido.',
    indexar: false,
  },
}

/**
 * Crea o actualiza una etiqueta `meta`.
 *
 * Se busca por su atributo identificador y no por su posición en el documento: el orden de estas
 * etiquetas no importa para nada y sí cambia cada vez que alguien toca `index.html`.
 */
function fijarMeta(atributo, nombre, contenido) {
  const selector = `meta[${atributo}="${nombre}"]`
  let etiqueta = document.head.querySelector(selector)
  if (!etiqueta) {
    etiqueta = document.createElement('meta')
    etiqueta.setAttribute(atributo, nombre)
    document.head.appendChild(etiqueta)
  }
  etiqueta.setAttribute('content', contenido)
}

/** Igual que `fijarMeta`, para el enlace canónico. `url` nulo lo retira. */
function fijarCanonica(url) {
  let enlace = document.head.querySelector('link[rel="canonical"]')

  if (!url) {
    if (enlace) enlace.remove()
    return
  }

  if (!enlace) {
    enlace = document.createElement('link')
    enlace.setAttribute('rel', 'canonical')
    document.head.appendChild(enlace)
  }
  enlace.setAttribute('href', url)
}

/**
 * Aplica a la pestaña y a las etiquetas lo que corresponde a una página.
 *
 * Un nombre que no esté en las fichas no hace nada. Es deliberado: durante el arranque la aplicación
 * pasa por un estado que no es ninguna página —mientras pregunta al servidor si hay sesión—, y ahí lo
 * correcto es no tocar nada y dejar el título que ya venía escrito en el documento.
 */
export function aplicarSeo(nombrePagina) {
  const ficha = FICHAS[nombrePagina]
  if (!ficha) return

  document.title = ficha.titulo
  fijarMeta('name', 'description', ficha.descripcion)

  // La canónica se declara solo si la página tiene una dirección propia. Cuando la hay, se construye
  // sobre el dominio público y no sobre la dirección que se está viendo: así `https://www.…` y
  // `http://…` apuntan las dos al mismo sitio y no compiten entre ellas.
  fijarCanonica(ficha.ruta ? `${SITIO}${ficha.ruta}` : null)

  // El panel y las pantallas de sesión no se indexan nunca. `follow` se mantiene porque los enlaces
  // que llevan de vuelta a la portada sí interesa que se sigan.
  fijarMeta('name', 'robots', ficha.indexar ? 'index, follow, max-image-preview:large' : 'noindex, follow')

  // Lo que se ve al compartir el enlace tiene que decir lo mismo que la página, o el enlace promete
  // una cosa y entrega otra.
  fijarMeta('property', 'og:title', ficha.titulo)
  fijarMeta('property', 'og:description', ficha.descripcion)
  fijarMeta('property', 'og:url', ficha.ruta ? `${SITIO}${ficha.ruta}` : SITIO)
  fijarMeta('name', 'twitter:title', ficha.titulo)
  fijarMeta('name', 'twitter:description', ficha.descripcion)
}
