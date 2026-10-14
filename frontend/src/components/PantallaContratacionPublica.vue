<script setup>
/**
 * Contratación pública en Ecuador: qué publica el SERCOP y cómo se busca una oportunidad.
 *
 * Esta página existe por dos razones que van juntas. La primera es que quien busca cómo encontrar
 * procedimientos en Ecuador merece una explicación en condiciones y no un puñado de frases con la
 * palabra clave repetida. La segunda es que una cuenta nueva casi nunca sabe por dónde empezar: sabe
 * que «quiere trabajar con el Estado» y no sabe que hay dos momentos distintos —la necesidad y el
 * proceso— ni que el código CPC es la pieza que hace que una búsqueda sirva de algo.
 *
 * Todo lo que se dice aquí o está en el repositorio o se puede comprobar en la fuente oficial que se
 * enlaza. **No se cita ningún artículo, ningún umbral ni ningún plazo**: esos números cambian con la
 * norma y quien los necesita tiene que leerlos donde se publican, no en la web de una herramienta.
 */
import CabeceraPublica from '@/components/CabeceraPublica.vue'
import PiePublico from '@/components/PiePublico.vue'

defineProps({
  tema: { type: String, default: 'claro' },
})
const emit = defineEmits(['alternar-tema'])
</script>

<template>
  <div class="guia">
    <CabeceraPublica :tema="tema" con-acciones @alternar-tema="emit('alternar-tema')" />

    <main>
      <section class="encabezado">
        <div class="envoltura envoltura--estrecha aparece">
          <p class="guia__etiqueta">Guía</p>
          <h1 class="guia__titulo">
            Contratación pública en Ecuador: cómo encontrar y seguir las oportunidades
          </h1>
          <p class="guia__entrada">
            El Estado ecuatoriano compra bienes, obras y servicios a través de procedimientos que se
            publican en el portal del SERCOP. Encontrar los que le interesan a una empresa no es
            cuestión de suerte: es cuestión de saber qué se publica, dónde se publica y con qué
            nombre.
          </p>
        </div>
      </section>

      <section class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Lo que se publica, y en qué momento</h2>
          <p class="seccion__entrada">
            Hay dos momentos distintos y conviene no confundirlos, porque el segundo es el que todo el
            mundo mira y el primero es el que da ventaja.
          </p>

          <div class="momentos">
            <article class="momento">
              <p class="momento__cuando">Antes</p>
              <h3 class="momento__titulo">La necesidad de contratación</h3>
              <p class="momento__texto">
                Una entidad sabe que va a necesitar algo y lo registra. Es el anuncio más temprano que
                existe: todavía no hay procedimiento, pero ya se sabe qué se va a necesitar, quién lo
                necesita y para cuándo. En el portal aparecen agrupadas en el listado de necesidades
                de contratación, conocido por sus siglas, NCO.
              </p>
            </article>

            <article class="momento">
              <p class="momento__cuando">Después</p>
              <h3 class="momento__titulo">El procedimiento publicado</h3>
              <p class="momento__texto">
                Cuando la entidad convoca, el procedimiento aparece con su código, su presupuesto
                referencial, sus fechas, sus requisitos y el detalle de lo que se contrata. Es el
                momento en el que ya se puede participar, y también el momento en el que hay más
                gente mirando.
              </p>
            </article>
          </div>

          <p class="nota">
            Seguir las necesidades además de los procedimientos es lo que permite prepararse con
            tiempo. Quien solo mira los procedimientos ya convocados llega cuando la mayoría de las
            decisiones —qué se pide, cómo se puntúa, qué experiencia se exige— ya están escritas.
          </p>
        </div>
      </section>

      <section class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Las palabras que hay que conocer</h2>
          <p class="seccion__entrada">
            Estas cuatro siglas aparecen en cualquier búsqueda. Sin entenderlas, buscar es adivinar.
          </p>

          <dl class="glosario">
            <div class="glosario__fila">
              <dt>Entidad contratante</dt>
              <dd>
                La institución pública que compra: un ministerio, un municipio, una universidad, un
                hospital, una empresa pública. Es uno de los filtros más útiles, porque cada entidad
                compra siempre cosas parecidas.
              </dd>
            </div>

            <div class="glosario__fila">
              <dt>CPC</dt>
              <dd>
                El Clasificador Central de Productos. Es la forma de decir «qué es exactamente lo que
                se contrata» con un código, en lugar de con una descripción que cada entidad escribe a
                su manera. Buscar por CPC encuentra cosas que buscar por palabra clave deja fuera,
                porque en el texto libre cada uno usa sus propias palabras para lo mismo.
              </dd>
            </div>

            <div class="glosario__fila">
              <dt>OCDS</dt>
              <dd>
                El estándar de datos abiertos de contratación, pensado para que los procesos se
                puedan leer y comparar de forma automática, entre entidades y entre países. Es el
                formato en el que el SERCOP publica su catálogo de datos abiertos.
              </dd>
            </div>

            <div class="glosario__fila">
              <dt>NCO</dt>
              <dd>
                El listado de necesidades de contratación del portal: lo que las entidades han
                registrado que van a necesitar, antes de convocar nada.
              </dd>
            </div>

            <div class="glosario__fila">
              <dt>Procedimiento</dt>
              <dd>
                El trámite concreto por el que una entidad compra algo. Tiene un código propio y un
                ciclo con fechas: publicación, preguntas, ofertas, calificación, adjudicación.
              </dd>
            </div>
          </dl>
        </div>
      </section>

      <section class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Cómo se busca una oportunidad</h2>
          <p class="seccion__entrada">
            El orden importa. Empezar por el texto libre es lo más cómodo y lo que peor funciona.
          </p>

          <ol class="pasos">
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">1</span>
              <div>
                <h3 class="pasos__titulo">Decide qué vendes, en términos de código</h3>
                <p class="pasos__texto">
                  Antes de buscar, traduce tu actividad a los códigos CPC que la cubren. Es el paso
                  que más tiempo ahorra después: una vez los tienes, la búsqueda deja de depender de
                  cómo se le haya ocurrido escribir a cada entidad.
                </p>
              </div>
            </li>

            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">2</span>
              <div>
                <h3 class="pasos__titulo">Busca por esos códigos, no solo por palabras</h3>
                <p class="pasos__texto">
                  El código encuentra registros que el texto libre deja fuera. Después, las palabras
                  clave sirven para afinar dentro de lo que ha salido.
                </p>
              </div>
            </li>

            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">3</span>
              <div>
                <h3 class="pasos__titulo">Acota por entidad y por provincia</h3>
                <p class="pasos__texto">
                  Un mismo producto se contrata de forma muy distinta según quién lo compre y dónde.
                  Filtrar por entidad te dice quién compra lo tuyo de forma recurrente; filtrar por
                  provincia te dice si puedes atenderlo.
                </p>
              </div>
            </li>

            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">4</span>
              <div>
                <h3 class="pasos__titulo">Mira hacia atrás, no solo lo de hoy</h3>
                <p class="pasos__texto">
                  La serie histórica enseña la estacionalidad: hay compras que se repiten cada año en
                  las mismas fechas. Saberlo es lo que permite preparar la documentación antes de que
                  se publique la convocatoria, en lugar de correr después.
                </p>
              </div>
            </li>

            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">5</span>
              <div>
                <h3 class="pasos__titulo">Verifica siempre en la fuente oficial</h3>
                <p class="pasos__texto">
                  Cualquier herramienta de consulta —esta incluida— sirve para orientarse, no para
                  decidir. Las fechas, los requisitos y las condiciones que obligan son los que
                  publique el SERCOP.
                </p>
              </div>
            </li>
          </ol>
        </div>
      </section>

      <section class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Qué se puede mirar una vez tienes los datos ordenados</h2>

          <div class="rejilla">
            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">La evolución en el tiempo</h3>
              <p class="pieza__texto">
                Cuánto se publica cada mes y en qué meses se concentra. Sirve para saber cuándo hay
                que estar preparado en lugar de enterarse sobre la marcha.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Dónde se concentra</h3>
              <p class="pieza__texto">
                El reparto por provincia. Hay compras que solo existen en determinadas zonas, y eso
                decide si una empresa puede atenderlas.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Quién compra</h3>
              <p class="pieza__texto">
                Qué entidades publican lo que te interesa. Es la lista de la que sale el trabajo
                repetido: un cliente público que ya te compró suele volver a comprarte.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Las líneas de un sector</h3>
              <p class="pieza__texto">
                Los códigos CPC que más se repiten en un área. Dibujan qué se está comprando de
                verdad, que no siempre coincide con lo que uno supondría.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Cómo lo resuelve CercoApp</h2>
          <p class="seccion__entrada">
            CercoApp hace el trabajo de ordenar todo eso y lo deja en una pantalla.
          </p>

          <ul class="lista-ventajas">
            <li>
              Reúne las necesidades y los procesos del SERCOP en un mismo sitio, para no tener que
              ir a mirarlos a dos listados distintos.
            </li>
            <li>
              Guarda cada registro con su entidad, su provincia, su código CPC y sus fechas, para
              poder buscar por cualquiera de esos campos.
            </li>
            <li>
              Deja filtrar por varias palabras clave a la vez y por código CPC, y combinar los
              filtros.
            </li>
            <li>
              Muestra la evolución, el reparto por provincia y el mapa de las 24 provincias, con
              gráficas que filtran al pulsarlas.
            </li>
            <li>
              Exporta a Excel lo que tengas en pantalla, con las columnas del panel.
            </li>
          </ul>

          <p class="seccion__enlace">
            <a href="/contratacion-publica-ecuador">↑ Volver al principio de esta página</a> ·
            <a href="/">Ir a la portada</a> ·
            <a href="/registro">Crear la cuenta de tu empresa</a>
          </p>
        </div>
      </section>

      <section class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Fuentes oficiales</h2>
          <p class="seccion__entrada">
            Para consultar el detalle de un procedimiento o hacer cualquier trámite, estas son las
            que valen.
          </p>

          <ul class="fuentes">
            <li class="fuentes__fila">
              <h3 class="fuentes__titulo">Portal del SERCOP</h3>
              <p class="fuentes__texto">
                El sitio del Servicio Nacional de Contratación Pública: normativa, procedimientos y
                el sistema de contratación pública.
              </p>
              <a
                class="fuentes__enlace"
                href="https://www.compraspublicas.gob.ec/"
                target="_blank"
                rel="noopener"
              >
                compraspublicas.gob.ec
              </a>
            </li>

            <li class="fuentes__fila">
              <h3 class="fuentes__titulo">Datos abiertos de contratación</h3>
              <p class="fuentes__texto">
                El catálogo público de procesos de contratación en formato OCDS, para consultarlos y
                descargarlos.
              </p>
              <a
                class="fuentes__enlace"
                href="https://datosabiertos.compraspublicas.gob.ec/"
                target="_blank"
                rel="noopener"
              >
                datosabiertos.compraspublicas.gob.ec
              </a>
            </li>
          </ul>

          <p class="aviso-fuente">
            CercoApp no es una página oficial ni sustituye a ninguna de las dos. Es una herramienta de
            consulta que lee esos datos públicos y los muestra ordenados.
          </p>
        </div>
      </section>

      <section class="cierre">
        <div class="envoltura cierre__caja">
          <h2 class="cierre__titulo">Mira qué se está contratando en tu sector</h2>
          <p class="cierre__texto">Crea la cuenta de tu empresa o entra si ya la tienes.</p>
          <div class="cierre__acciones">
            <a class="boton boton--principal" href="/login">Ingresar</a>
            <a class="boton boton--secundario" href="/registro">Crear cuenta</a>
          </div>
        </div>
      </section>
    </main>

    <PiePublico />
  </div>
</template>

<style scoped>
.guia {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.envoltura {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 var(--e-6);
}

.envoltura--estrecha {
  max-width: 820px;
}

.encabezado {
  padding: var(--e-7) 0 var(--e-5);
}

.guia__etiqueta {
  margin: 0;
  font-size: var(--t-xs);
  font-weight: 650;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--acento);
}

.guia__titulo {
  margin: var(--e-3) 0 0;
  font-size: var(--t-2xl);
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.guia__entrada {
  margin: var(--e-4) 0 0;
  font-size: var(--t-lg);
  line-height: 1.65;
  color: var(--texto-suave);
}

.seccion {
  padding: var(--e-7) 0;
}

.seccion--alterna {
  background: var(--superficie-2);
  border-top: 1px solid var(--borde);
  border-bottom: 1px solid var(--borde);
}

.seccion__titulo {
  margin: 0;
  font-size: var(--t-2xl);
  letter-spacing: -0.01em;
}

.seccion__entrada {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-md);
  line-height: 1.65;
  max-width: 70ch;
}

.seccion__enlace {
  margin: var(--e-5) 0 0;
  font-size: var(--t-base);
  color: var(--texto-tenue);
}

/* --- Los dos momentos ---------------------------------------------------- */

.momentos {
  margin-top: var(--e-6);
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--e-4);
}

.momento {
  padding: var(--e-5);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
}

.momento__cuando {
  margin: 0;
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--texto-tenue);
}

.momento__titulo {
  margin: var(--e-2) 0 0;
  font-size: var(--t-lg);
}

.momento__texto {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
  line-height: 1.7;
  font-size: var(--t-base);
}

.nota {
  margin: var(--e-5) 0 0;
  padding: var(--e-4) var(--e-5);
  border-left: 3px solid var(--acento);
  background: var(--acento-tenue);
  border-radius: var(--r-2);
  line-height: 1.7;
  font-size: var(--t-base);
  max-width: 78ch;
}

/* --- Glosario ------------------------------------------------------------ */

.glosario {
  margin: var(--e-6) 0 0;
  display: grid;
  gap: var(--e-3);
}

.glosario__fila {
  padding: var(--e-4) var(--e-5);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
}

.glosario dt {
  font-weight: 650;
  font-size: var(--t-md);
}

.glosario dd {
  margin: var(--e-2) 0 0;
  color: var(--texto-suave);
  line-height: 1.7;
  font-size: var(--t-base);
}

/* --- Pasos --------------------------------------------------------------- */

.pasos {
  list-style: none;
  margin: var(--e-6) 0 0;
  padding: 0;
  display: grid;
  gap: var(--e-4);
}

.pasos__paso {
  display: flex;
  gap: var(--e-4);
  align-items: flex-start;
}

.pasos__numero {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--r-redondo);
  background: var(--acento-suave);
  color: var(--acento);
  font-weight: 700;
  font-size: var(--t-base);
}

.pasos__titulo {
  margin: 0;
  font-size: var(--t-md);
  font-weight: 650;
}

.pasos__texto {
  margin: var(--e-2) 0 0;
  color: var(--texto-suave);
  line-height: 1.7;
  font-size: var(--t-base);
  max-width: 74ch;
}

/* --- Tarjetas y listas --------------------------------------------------- */

.rejilla {
  margin-top: var(--e-6);
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--e-4);
}

.pieza {
  padding: var(--e-5);
}

.pieza__titulo {
  margin: 0;
  font-size: var(--t-md);
  font-weight: 650;
}

.pieza__texto {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-base);
  line-height: 1.65;
}

.lista-ventajas {
  margin: var(--e-5) 0 0;
  padding: 0 0 0 var(--e-5);
  display: grid;
  gap: var(--e-3);
  color: var(--texto-suave);
  line-height: 1.7;
  font-size: var(--t-base);
  max-width: 82ch;
}

/* --- Fuentes ------------------------------------------------------------- */

.fuentes {
  list-style: none;
  margin: var(--e-6) 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--e-4);
}

.fuentes__fila {
  padding: var(--e-5);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
}

.fuentes__titulo {
  margin: 0;
  font-size: var(--t-md);
  font-weight: 650;
}

.fuentes__texto {
  margin: var(--e-3) 0 var(--e-4);
  color: var(--texto-suave);
  font-size: var(--t-base);
  line-height: 1.65;
}

.fuentes__enlace {
  font-size: var(--t-sm);
  font-weight: 550;
  word-break: break-all;
}

.aviso-fuente {
  margin: var(--e-5) 0 0;
  padding: var(--e-4) var(--e-5);
  border-left: 3px solid var(--aviso);
  background: var(--aviso-suave);
  border-radius: var(--r-2);
  font-size: var(--t-base);
  line-height: 1.6;
  max-width: 78ch;
}

/* --- Cierre -------------------------------------------------------------- */

.cierre {
  padding: var(--e-7) 0 var(--e-6);
}

.cierre__caja {
  text-align: center;
}

.cierre__titulo {
  margin: 0;
  font-size: var(--t-2xl);
  letter-spacing: -0.01em;
}

.cierre__texto {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-lg);
}

.cierre__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  justify-content: center;
  margin-top: var(--e-5);
}

.cierre__acciones .boton {
  padding: 0.7rem 1.4rem;
  font-size: var(--t-md);
  text-decoration: none;
}

@media (max-width: 960px) {
  .momentos,
  .rejilla,
  .fuentes {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .envoltura {
    padding: 0 var(--e-4);
  }

  .encabezado,
  .seccion,
  .cierre {
    padding: var(--e-6) 0;
  }

  .guia__titulo,
  .seccion__titulo,
  .cierre__titulo {
    font-size: var(--t-xl);
  }

  .guia__entrada {
    font-size: var(--t-md);
  }

  .cierre__acciones .boton {
    flex: 1;
  }
}
</style>
