<script setup>
/**
 * La portada.
 *
 * Es lo primero que ve quien llega desde un buscador o desde un enlace compartido, y su trabajo es
 * uno solo: contar qué es esto en diez segundos y ofrecer las dos salidas que existen —entrar o
 * crear una cuenta—. Nada más.
 *
 * Todo lo que se afirma aquí se puede comprobar en el repositorio o en la fuente oficial: lo que
 * hace el panel, de dónde salen los datos y qué no es. **No hay ninguna cifra de usuarios, ningún
 * cliente, ningún testimonio y ninguna promesa de resultado**, porque no hay ningún dato que los
 * respalde. Un dato inventado en la portada es lo primero que se cae cuando alguien pregunta.
 *
 * Las preguntas frecuentes están escritas con `<details>`, que es lo que el navegador ya sabe
 * desplegar: funciona sin JavaScript y un buscador lee su contenido aunque esté cerrado.
 */
import CabeceraPublica from '@/components/CabeceraPublica.vue'
import PiePublico from '@/components/PiePublico.vue'

defineProps({
  tema: { type: String, default: 'claro' },
})
const emit = defineEmits(['alternar-tema'])
</script>

<template>
  <div class="inicio">
    <CabeceraPublica :tema="tema" con-acciones @alternar-tema="emit('alternar-tema')" />

    <main>
      <section class="portada">
        <div class="envoltura portada__rejilla">
          <div class="aparece">
            <p class="portada__etiqueta">Contratación pública de Ecuador</p>
            <h1 class="portada__titulo">
              Encuentra oportunidades de contratación pública en Ecuador
            </h1>
            <p class="portada__entrada">
              CercoApp reúne lo que el SERCOP publica en abierto —las
              <strong>necesidades de contratación</strong> y los
              <strong>procesos publicados</strong>— y lo pone en una tabla filtrable, con gráficas
              interactivas y un mapa de las 24 provincias. Escribe una palabra clave y mira qué se
              está contratando, dónde y quién lo publica.
            </p>

            <div class="portada__acciones">
              <a class="boton boton--principal" href="/login">Ingresar</a>
              <a class="boton boton--secundario" href="/registro">Crear cuenta</a>
            </div>

            <p class="portada__nota">
              Para entrar hace falta una cuenta de empresa. Se crea desde el registro y al crearla se
              aceptan las condiciones de uso.
            </p>
          </div>

          <ul class="portada__lista aparece retardo-1">
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Búsqueda por varias palabras clave a la vez</strong>
                <span>Los registros que las contienen, sin ir una por una.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Mapa del Ecuador con las 24 provincias</strong>
                <span>Dónde se concentra lo que buscas.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Gráficas que filtran al pulsarlas</strong>
                <span>Pulsar una barra ajusta el resto del panel a lo que has pulsado.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>El resultado se exporta a Excel</strong>
                <span>Para seguir trabajándolo fuera del panel.</span>
              </span>
            </li>
          </ul>
        </div>
      </section>

      <section id="como-funciona" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Cómo funciona</h2>
          <p class="seccion__entrada">
            CercoApp no inventa datos ni los completa a mano: lee los que la fuente oficial publica y
            los deja consultables.
          </p>

          <ol class="pasos">
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">1</span>
              <h3 class="pasos__titulo">Se leen las fuentes oficiales</h3>
              <p>
                CercoApp consulta de forma automática los datos abiertos del SERCOP: el catálogo de
                procesos publicados en formato OCDS y el listado de necesidades de contratación.
              </p>
            </li>
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">2</span>
              <h3 class="pasos__titulo">Se guardan y se ordenan</h3>
              <p>
                Cada registro se archiva con su entidad, su provincia, su código CPC y sus fechas,
                para poder buscar por cualquiera de esos campos y no solo por el texto.
              </p>
            </li>
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">3</span>
              <h3 class="pasos__titulo">Se consultan desde el panel</h3>
              <p>
                Buscas, filtras, miras las gráficas y el mapa, y lo que te interesa lo descargas en
                Excel. Todo desde el navegador, sin instalar nada.
              </p>
            </li>
          </ol>
        </div>
      </section>

      <section id="funcionalidades" class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Qué encontrarás dentro</h2>
          <p class="seccion__entrada">
            Estas son las piezas del panel, sin más lista de la que hay.
          </p>

          <div class="rejilla">
            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Búsqueda por varias palabras clave</h3>
              <p class="pieza__texto">
                Escribe varias palabras a la vez y CercoApp encuentra los registros que las contienen,
                en lugar de obligarte a buscarlas de una en una.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Filtros que se combinan</h3>
              <p class="pieza__texto">
                Acota por provincia, por entidad contratante, por fechas y por el resto de campos de
                cada registro. Los filtros se suman entre sí.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Gráficas que filtran al pulsarlas</h3>
              <p class="pieza__texto">
                La evolución en el tiempo, el reparto por provincia, el origen de los datos y su
                distribución. Pulsar una barra o un sector ajusta el resto del panel.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Mapa de las 24 provincias</h3>
              <p class="pieza__texto">
                El Ecuador entero de un vistazo, con cada provincia pulsable para ver solo lo suyo.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Búsqueda por código CPC</h3>
              <p class="pieza__texto">
                El código CPC clasifica lo que se contrata. Puedes buscar por él cuando ya sabes
                exactamente qué familia de bienes o servicios te interesa.
              </p>
            </article>

            <article class="tarjeta pieza">
              <h3 class="pieza__titulo">Exportación a Excel</h3>
              <p class="pieza__texto">
                Lo que tengas filtrado en pantalla se descarga en una hoja de cálculo, con las
                columnas del panel, para seguir trabajándolo fuera.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="para-quien" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">A quién le sirve</h2>
          <p class="seccion__entrada">
            Sirve para mirar el mercado público desde fuera, antes de decidir nada.
          </p>

          <div class="rejilla rejilla--tres">
            <article class="perfil">
              <h3 class="perfil__titulo">Empresas proveedoras</h3>
              <p class="perfil__texto">
                Para ver qué se está necesitando, qué entidad lo publica y en qué provincia, y
                decidir si merece la pena prepararse para participar.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Analistas de mercado</h3>
              <p class="perfil__texto">
                Para seguir la evolución por provincia, entidad y periodo, y llevarse los datos a
                Excel cuando haga falta un análisis más largo.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Equipos comerciales y consultoría</h3>
              <p class="perfil__texto">
                Para tener localizadas las líneas de trabajo de un sector y repartirlas entre varias
                personas de la misma cuenta.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="fuentes" class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">De dónde salen los datos</h2>
          <p class="seccion__entrada">
            De dos fuentes públicas del Servicio Nacional de Contratación Pública. CercoApp no corrige
            ni completa lo que ellas publican.
          </p>

          <ul class="fuentes">
            <li class="fuentes__fila">
              <h3 class="fuentes__titulo">Datos abiertos en formato OCDS</h3>
              <p class="fuentes__texto">
                El catálogo de procesos de contratación que el SERCOP publica en el estándar Open
                Contracting Data Standard, pensado para que se pueda leer y comparar por máquinas.
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

            <li class="fuentes__fila">
              <h3 class="fuentes__titulo">Necesidades de contratación (NCO)</h3>
              <p class="fuentes__texto">
                El listado de necesidades que las entidades registran antes de convocar un
                procedimiento. Es la señal más temprana de que algo se va a contratar.
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
          </ul>

          <p class="aviso-fuente">
            CercoApp es una herramienta de consulta y no una página oficial. Para consultar el detalle
            de un procedimiento, presentar una oferta o hacer cualquier trámite, el sitio que vale es
            el del SERCOP.
          </p>

          <p class="seccion__enlace">
            <a href="/contratacion-publica-ecuador">
              Ver qué publica el SERCOP y cómo se busca una oportunidad
            </a>
          </p>
        </div>
      </section>

      <section id="preguntas" class="seccion">
        <div class="envoltura envoltura--estrecha">
          <h2 class="seccion__titulo">Preguntas frecuentes</h2>

          <details class="pregunta">
            <summary>¿CercoApp es una página oficial del SERCOP?</summary>
            <p>
              No. CercoApp es una herramienta independiente de consulta. Lee los datos que el SERCOP
              publica en abierto y los muestra ordenados, pero no es un sitio del Estado ni lo
              representa.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿De dónde salen exactamente los datos?</summary>
            <p>
              De dos sitios públicos del SERCOP: su catálogo de datos abiertos en formato OCDS y su
              listado de necesidades de contratación. CercoApp no añade datos propios ni modifica los
              que la fuente publica.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Cada cuánto se actualiza?</summary>
            <p>
              La consulta a las fuentes se hace de forma automática y continuada. Un registro aparece
              en el panel cuando la fuente lo publica; si la fuente todavía no lo ha publicado, no
              está, y eso es lo correcto.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Puedo descargarme los resultados?</summary>
            <p>
              Sí. Lo que tengas filtrado en pantalla se exporta a una hoja de cálculo con las columnas
              del panel.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Qué hace falta para entrar?</summary>
            <p>
              Una cuenta de empresa, que se crea desde el registro. Al crearla se aceptan las
              condiciones de uso del servicio, y al entrar por primera vez hay que confirmarlas.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Sirve para presentar una oferta o para hacer un trámite?</summary>
            <p>
              No. CercoApp sirve para consultar y seguir. Cualquier trámite se hace en el portal del
              SERCOP, que es la fuente oficial.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Hay que instalar algo?</summary>
            <p>
              No. Funciona en el navegador. Solo hace falta conexión a internet.
            </p>
          </details>
        </div>
      </section>

      <section class="cierre">
        <div class="envoltura cierre__caja">
          <h2 class="cierre__titulo">Empieza por mirar qué se está contratando</h2>
          <p class="cierre__texto">
            Crea la cuenta de tu empresa o entra si ya la tienes.
          </p>
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
.inicio {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* Todas las secciones comparten el mismo ancho y los mismos márgenes laterales. Está una sola vez
   aquí para que no haya dos secciones con medidas ligeramente distintas, que es como se ve que una
   página está hecha a trozos. */
.envoltura {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 var(--e-6);
}

.envoltura--estrecha {
  max-width: 800px;
}

/* --- Portada ------------------------------------------------------------- */

.portada {
  padding: var(--e-7) 0 var(--e-6);
}

.portada__rejilla {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: var(--e-7);
  align-items: center;
}

.portada__etiqueta {
  margin: 0;
  font-size: var(--t-xs);
  font-weight: 650;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--acento);
}

.portada__titulo {
  margin: var(--e-3) 0 0;
  font-size: var(--t-3xl);
  line-height: 1.15;
  letter-spacing: -0.02em;
}

.portada__entrada {
  margin: var(--e-4) 0 0;
  font-size: var(--t-lg);
  line-height: 1.65;
  color: var(--texto-suave);
  max-width: 60ch;
}

.portada__acciones {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
  margin-top: var(--e-5);
}

/* Los dos botones de la portada son la acción principal de la página, así que van algo más grandes
   que un botón corriente. El tamaño se pone aquí y no con una clase general porque en el resto del
   panel no hay ningún botón de este tamaño. */
.portada__acciones .boton,
.cierre__acciones .boton {
  padding: 0.7rem 1.4rem;
  font-size: var(--t-md);
  text-decoration: none;
}

.portada__nota {
  margin: var(--e-4) 0 0;
  font-size: var(--t-sm);
  color: var(--texto-tenue);
  max-width: 52ch;
  line-height: 1.6;
}

.portada__lista {
  list-style: none;
  margin: 0;
  padding: var(--e-5);
  display: grid;
  gap: var(--e-4);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-4);
  box-shadow: var(--sombra-2);
}

.portada__lista li {
  display: flex;
  gap: var(--e-3);
  align-items: flex-start;
}

.portada__lista strong {
  display: block;
  font-weight: 600;
  font-size: var(--t-md);
}

.portada__lista li span span {
  display: block;
  margin-top: 2px;
  font-size: var(--t-sm);
  color: var(--texto-suave);
  line-height: 1.55;
}

.portada__marca {
  color: var(--acento);
  font-size: var(--t-xs);
  line-height: 1.6;
}

/* --- Secciones ----------------------------------------------------------- */

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
  font-size: var(--t-md);
}

/* --- Pasos --------------------------------------------------------------- */

.pasos {
  list-style: none;
  counter-reset: paso;
  margin: var(--e-6) 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--e-5);
}

.pasos__paso {
  position: relative;
}

.pasos__numero {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--r-redondo);
  background: var(--acento-suave);
  color: var(--acento);
  font-weight: 700;
  font-size: var(--t-base);
}

.pasos__titulo {
  margin: var(--e-3) 0 var(--e-2);
  font-size: var(--t-lg);
}

.pasos__paso p {
  margin: 0;
  color: var(--texto-suave);
  line-height: 1.65;
  font-size: var(--t-base);
}

/* --- Rejillas ------------------------------------------------------------ */

.rejilla {
  margin-top: var(--e-6);
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--e-4);
}

.rejilla--tres {
  grid-template-columns: repeat(3, 1fr);
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

.perfil {
  padding: var(--e-5);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-left: 3px solid var(--acento);
  border-radius: var(--r-3);
}

.perfil__titulo {
  margin: 0;
  font-size: var(--t-md);
  font-weight: 650;
}

.perfil__texto {
  margin: var(--e-3) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-base);
  line-height: 1.65;
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
  color: var(--texto);
  font-size: var(--t-base);
  line-height: 1.6;
  max-width: 78ch;
}

/* --- Preguntas ----------------------------------------------------------- */

.pregunta {
  margin-top: var(--e-3);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-3);
  overflow: hidden;
}

.pregunta summary {
  padding: var(--e-4) var(--e-5);
  cursor: pointer;
  font-weight: 600;
  font-size: var(--t-md);
  list-style: none;
}

.pregunta summary::-webkit-details-marker {
  display: none;
}

/* El signo se dibuja con el propio marcador de `details`, que ya sabe girar: dos barras y una
   rotación, sin una imagen que cargar. */
.pregunta summary::after {
  content: '+';
  float: right;
  margin-left: var(--e-3);
  color: var(--acento);
  font-weight: 700;
}

.pregunta[open] summary::after {
  content: '−';
}

.pregunta summary:hover {
  background: var(--superficie-2);
}

.pregunta p {
  margin: 0;
  padding: 0 var(--e-5) var(--e-5);
  color: var(--texto-suave);
  line-height: 1.7;
  font-size: var(--t-base);
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

/* --- Adaptación a pantallas estrechas ------------------------------------ */

@media (max-width: 960px) {
  .portada__rejilla {
    grid-template-columns: 1fr;
    gap: var(--e-6);
  }

  .pasos {
    grid-template-columns: 1fr;
  }

  .rejilla,
  .rejilla--tres,
  .fuentes {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .envoltura {
    padding: 0 var(--e-4);
  }

  .portada,
  .seccion,
  .cierre {
    padding: var(--e-6) 0;
  }

  .portada__titulo {
    font-size: var(--t-2xl);
  }

  .portada__entrada {
    font-size: var(--t-md);
  }

  .seccion__titulo,
  .cierre__titulo {
    font-size: var(--t-xl);
  }

  .portada__acciones .boton,
  .cierre__acciones .boton {
    flex: 1;
  }
}
</style>
