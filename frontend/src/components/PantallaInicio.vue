<script setup>
/**
 * La portada.
 *
 * Es lo primero que ve quien llega desde un buscador o desde un enlace compartido, y su trabajo es
 * uno solo: contar qué es esto en diez segundos y ofrecer las dos salidas que existen —entrar o
 * crear una cuenta—. Debajo, para quien quiera leer más, va todo lo que el panel hace hoy, en el
 * mismo orden en que se usa: registrarse, encontrar, preparar la oferta y seguirla.
 *
 * Todo lo que se afirma aquí se puede comprobar en el repositorio (`docs/30-*` a `docs/39-*`) o en la
 * fuente oficial. **No hay ninguna cifra de usuarios, ningún cliente, ningún testimonio y ninguna
 * promesa de resultado**, porque no hay ningún dato que los respalde. Un dato inventado en la portada
 * es lo primero que se cae cuando alguien pregunta.
 *
 * El texto está pensado para dueños de negocio que no son técnicos: frases cortas, sin siglas sin
 * explicar y diciendo siempre qué gana la persona, no cómo está hecho por dentro.
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
            <p class="portada__etiqueta">Para proveedores del Estado ecuatoriano</p>
            <h1 class="portada__titulo">
              Encuentra ínfimas cuantías y prepara tu oferta en un solo lugar
            </h1>
            <p class="portada__entrada">
              CercoApp revisa por ti lo que el SERCOP publica —las
              <strong>necesidades de contratación</strong> y las
              <strong>ínfimas cuantías</strong>—, te muestra lo que calza con tu empresa, te avisa
              cuando sale algo nuevo y te ayuda a armar la proforma, lista en PDF o Word.
            </p>

            <div class="portada__acciones">
              <a class="boton boton--principal" href="/registro">Crear la cuenta de mi empresa</a>
              <a class="boton boton--secundario" href="/login">Ingresar</a>
            </div>

            <p class="portada__nota">
              Solo necesitas el <strong>RUC</strong> de tu empresa: los datos los traemos del SRI.
              Empiezas con 7 días de acceso a todo el panel y
              <strong>100 créditos de IA de bienvenida</strong>.
            </p>
          </div>

          <ul class="portada__lista aparece retardo-1">
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Propuestas para ti</strong>
                <span>Las ínfimas abiertas que tu empresa puede ofertar, y por qué te las sugerimos.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Alertas que te avisan</strong>
                <span>Por tus códigos CPC o tus palabras clave, en la provincia que elijas.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Asistente con IA</strong>
                <span>Pregunta con tus palabras: «recomiéndame ínfimas de limpieza en Guayas».</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Tu proforma en 4 pasos</strong>
                <span>Leemos todos los anexos del proceso y llenamos lo que ya sabemos.</span>
              </span>
            </li>
            <li>
              <span class="portada__marca" aria-hidden="true">◆</span>
              <span>
                <strong>Mis ofertas</strong>
                <span>En qué etapa va cada oferta y un aviso antes de que cierre el plazo.</span>
              </span>
            </li>
          </ul>
        </div>
      </section>

      <section id="como-funciona" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Cómo funciona</h2>
          <p class="seccion__entrada">
            Cuatro pasos, en el orden en que los vas a usar. Todo desde el navegador, sin instalar
            nada.
          </p>

          <ol class="pasos">
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">1</span>
              <h3 class="pasos__titulo">Registras tu empresa con el RUC</h3>
              <p>
                Escribes el RUC y traemos del SRI la razón social, la dirección y el representante
                legal. Si subes tu RUP en PDF, leemos tus códigos CPC y quedan en tu perfil.
              </p>
            </li>
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">2</span>
              <h3 class="pasos__titulo">Te mostramos lo que te calza</h3>
              <p>
                Con tu perfil armamos «Propuestas para ti» y puedes crear alertas. Lo nuevo del
                SERCOP llega solo, sin que tengas que entrar al portal a revisar.
              </p>
            </li>
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">3</span>
              <h3 class="pasos__titulo">Preparas la oferta</h3>
              <p>
                Eliges el proceso, revisas los requisitos y escribes tus precios. La proforma sale
                en PDF o Word, con tus datos y los de la entidad ya puestos.
              </p>
            </li>
            <li class="pasos__paso">
              <span class="pasos__numero" aria-hidden="true">4</span>
              <h3 class="pasos__titulo">Sigues cada oferta</h3>
              <p>
                En «Mis ofertas» ves en qué etapa va cada una y te avisamos cuando un proceso con
                tu proforma está por cerrar.
              </p>
            </li>
          </ol>
        </div>
      </section>

      <section id="funcionalidades" class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Qué encontrarás dentro</h2>
          <p class="seccion__entrada">
            Estas son las partes del panel, agrupadas como aparecen en el menú.
          </p>

          <div class="rejilla">
            <article class="tarjeta pieza">
              <p class="pieza__area">Buscar oportunidades</p>
              <h3 class="pieza__titulo">Necesidades e ínfimas, siempre al día</h3>
              <p class="pieza__texto">
                Las necesidades de contratación y las ínfimas cuantías del SERCOP se actualizan
                solas a lo largo del día, cada una con su código CPC, su entidad y su plazo.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Buscar oportunidades</p>
              <h3 class="pieza__titulo">Filtros, gráficas y mapa</h3>
              <p class="pieza__texto">
                Filtra por código CPC, provincia y varias palabras clave a la vez. Mira las gráficas
                y el mapa de las 24 provincias, y descarga lo filtrado a Excel.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Oportunidades para ti</p>
              <h3 class="pieza__titulo">Propuestas para ti</h3>
              <p class="pieza__texto">
                Las ínfimas abiertas que encajan con tus CPC, con lo que ofreces, con las provincias
                donde trabajas y con tu rango de presupuesto. Cada una dice por qué te la sugerimos.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Oportunidades para ti</p>
              <h3 class="pieza__titulo">Alertas con aviso</h3>
              <p class="pieza__texto">
                Elige códigos CPC o palabras clave, la provincia y cada cuánto quieres revisar. Antes
                de guardar ves cuántos resultados traería, y cuando sale algo nuevo te avisamos.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Asistente</p>
              <h3 class="pieza__titulo">Asistente con IA</h3>
              <p class="pieza__texto">
                Un chat para pedir las cosas con tus palabras: buscar ínfimas, ver cómo va un
                proceso, consultar los procesos que ha ganado un RUC, crear una alerta o empezar una
                proforma. Tus conversaciones quedan guardadas.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Ofertar</p>
              <h3 class="pieza__titulo">Preparar oferta en 4 pasos</h3>
              <p class="pieza__texto">
                Leemos todos los anexos del proceso, marcas los requisitos que cumples, escribes tus
                precios y descargas la proforma en PDF o Word.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Ofertar</p>
              <h3 class="pieza__titulo">Mis ofertas</h3>
              <p class="pieza__texto">
                Todas tus proformas en un tablero por etapa, con un calendario de cierres y un aviso
                cuando un proceso está por cerrar.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Mi empresa</p>
              <h3 class="pieza__titulo">Perfil desde el RUC y el RUP</h3>
              <p class="pieza__texto">
                Los datos del SRI se llenan solos. Sube tu RUP o tu RUC en PDF —incluso escaneado—
                y leemos tus CPC y tus actividades para completar el perfil.
              </p>
            </article>

            <article class="tarjeta pieza">
              <p class="pieza__area">Mi empresa</p>
              <h3 class="pieza__titulo">Tu equipo en la misma cuenta</h3>
              <p class="pieza__texto">
                Quien registra la empresa queda como administrador y puede crear las cuentas de su
                equipo. Todos trabajan con el mismo perfil y los mismos CPC de la empresa.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="preparar-oferta" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Tu oferta, lista en 4 pasos</h2>
          <p class="seccion__entrada">
            Lo que ya sabemos —tus datos, los de la entidad y lo que pide el proceso— llega escrito y
            marcado para que lo revises. Tú pones tus precios: esos nunca los inventamos.
          </p>

          <div class="oferta">
            <ol class="oferta__pasos">
              <li>
                <strong>Lee el proceso.</strong>
                Escribe el código y leemos todos sus anexos: TDR, pliegos, documentos Word, hojas de
                Excel y archivos ZIP. Si un anexo está escaneado, lo subes y lo leemos igual.
              </li>
              <li>
                <strong>Marca los requisitos.</strong>
                Te mostramos lo que pide la entidad en una lista para marcar lo que cumples y lo que
                no aplica.
              </li>
              <li>
                <strong>Arma tu proforma.</strong>
                Revisa lo marcado como «autollenado» y escribe tus precios. Mientras escribes ves
                cuánto del presupuesto usas, y te avisamos si te pasas.
              </li>
              <li>
                <strong>Descárgala.</strong>
                Mira la vista previa y bájala en PDF o Word. Queda guardada en «Mis ofertas».
              </li>
            </ol>

            <div class="tarjeta oferta__incluye">
              <h3 class="oferta__titulo">Qué lleva la proforma</h3>
              <ul class="oferta__lista">
                <li>Los datos de tu empresa, sacados de tu perfil.</li>
                <li>
                  Los datos de la entidad contratante —RUC, dirección, teléfono y correo—, sacados
                  de la ficha del proceso y de sus anexos.
                </li>
                <li>Un título propio para cada proforma, sin repetidos, para encontrarla después.</li>
                <li>El control del presupuesto, para no pasarte del monto del proceso.</li>
                <li>
                  Tu firma electrónica (archivo .p12 o .pfx) con un sello al estilo FirmaEC y código
                  QR. Tu certificado y tu clave no se guardan.
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      <section id="asistente" class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">Pregúntale al asistente</h2>
          <p class="seccion__entrada">
            Si no quieres aprender cada pantalla, escribe lo que necesitas como se lo dirías a una
            persona. El asistente responde en español sencillo y te muestra los datos con un botón
            para ir directo a la pantalla que corresponde.
          </p>

          <ul class="ejemplos" aria-label="Ejemplos de preguntas">
            <li class="ejemplos__frase">«Recomiéndame ínfimas para mi empresa»</li>
            <li class="ejemplos__frase">«¿Cómo va el proceso NIC-…?»</li>
            <li class="ejemplos__frase">«¿Qué procesos ha ganado el RUC 17…001?»</li>
            <li class="ejemplos__frase">«Crea una alerta de impresoras en Pichincha»</li>
            <li class="ejemplos__frase">«Prepara la proforma para este proceso»</li>
          </ul>

          <p class="nota">
            Cada empresa empieza con <strong>100 créditos de IA de bienvenida</strong>. Las preguntas
            sencillas —tus alertas, tus ofertas, el estado de un proceso— no gastan créditos; las
            que necesitan la IA usan uno por respuesta.
          </p>
        </div>
      </section>

      <section id="seguridad" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">Tus datos, seguros</h2>
          <p class="seccion__entrada">
            Tus precios y tus ofertas son tuyos. Así los cuidamos.
          </p>

          <div class="rejilla rejilla--tres">
            <article class="perfil">
              <h3 class="perfil__titulo">Cada empresa ve solo lo suyo</h3>
              <p class="perfil__texto">
                La separación entre empresas la impone la propia base de datos: aunque hubiera un
                error en una pantalla, una empresa no puede ver los datos de otra.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Conexión cifrada</h3>
              <p class="perfil__texto">
                Todo viaja por HTTPS, el candado del navegador: lo que escribes no se puede leer por
                el camino.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Sesiones que caducan</h3>
              <p class="perfil__texto">
                Si dejas el panel sin usar, la sesión se cierra sola. Si olvidas cerrar en otra
                computadora, nadie podrá seguir usándola indefinidamente.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="para-quien" class="seccion seccion--alterna">
        <div class="envoltura">
          <h2 class="seccion__titulo">A quién le sirve</h2>
          <p class="seccion__entrada">
            A cualquier negocio que quiera venderle al Estado sin pasar el día revisando el portal.
          </p>

          <div class="rejilla rejilla--tres">
            <article class="perfil">
              <h3 class="perfil__titulo">Pequeñas y medianas empresas</h3>
              <p class="perfil__texto">
                Para enterarse a tiempo de las ínfimas que les calzan y armar la proforma sin
                empezar cada vez desde una hoja en blanco.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Equipos comerciales</h3>
              <p class="perfil__texto">
                Para repartir el trabajo entre varias personas de la misma empresa y ver en qué
                etapa va cada oferta.
              </p>
            </article>

            <article class="perfil">
              <h3 class="perfil__titulo">Quien estudia el mercado</h3>
              <p class="perfil__texto">
                Para ver qué se compra, dónde y quién lo compra, con gráficas, mapa y descarga a
                Excel.
              </p>
            </article>
          </div>
        </div>
      </section>

      <section id="fuentes" class="seccion">
        <div class="envoltura">
          <h2 class="seccion__titulo">De dónde salen los datos</h2>
          <p class="seccion__entrada">
            De fuentes públicas del Servicio Nacional de Contratación Pública. CercoApp no corrige ni
            completa lo que ellas publican. Los datos de tu empresa en el registro salen del SRI.
          </p>

          <ul class="fuentes">
            <li class="fuentes__fila">
              <h3 class="fuentes__titulo">Necesidades de contratación e ínfimas cuantías</h3>
              <p class="fuentes__texto">
                Lo que las entidades publican que van a necesitar y las compras de ínfima cuantía,
                con sus anexos. Es la señal más temprana de que algo se va a contratar.
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
              <h3 class="fuentes__titulo">Datos abiertos en formato OCDS</h3>
              <p class="fuentes__texto">
                El catálogo de procesos de contratación del SERCOP. De aquí sale, por ejemplo, el
                historial de procesos que ha ganado un RUC.
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
            CercoApp es una herramienta independiente y no una página oficial. Te ayuda a encontrar y
            preparar, pero la oferta se presenta y cualquier trámite se hace en el portal del SERCOP.
          </p>

          <p class="seccion__enlace">
            <a href="/contratacion-publica-ecuador">
              Ver qué publica el SERCOP y cómo se busca una oportunidad
            </a>
          </p>
        </div>
      </section>

      <section id="preguntas" class="seccion seccion--alterna">
        <div class="envoltura envoltura--estrecha">
          <h2 class="seccion__titulo">Preguntas frecuentes</h2>

          <details class="pregunta">
            <summary>¿CercoApp es una página oficial del SERCOP?</summary>
            <p>
              No. CercoApp es una herramienta independiente. Lee los datos que el SERCOP publica en
              abierto y los muestra ordenados, pero no es un sitio del Estado ni lo representa.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Qué necesito para crear la cuenta?</summary>
            <p>
              El RUC de tu empresa, un correo y una contraseña. Con el RUC traemos tus datos del SRI;
              tú solo los revisas. Al crear la cuenta se aceptan los términos y condiciones del
              servicio.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Cada cuánto se actualizan las ínfimas?</summary>
            <p>
              Se revisan de forma automática varias veces por hora. Una ínfima aparece en el panel en
              cuanto el SERCOP la publica; si todavía no la ha publicado, no está.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿CercoApp presenta la oferta por mí?</summary>
            <p>
              No. CercoApp te ayuda a encontrar el proceso y a preparar la proforma en PDF o Word.
              La oferta la presentas tú en el portal del SERCOP, que es el sitio oficial.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Qué son los créditos de IA?</summary>
            <p>
              Son el saldo para las funciones que usan inteligencia artificial, como el asistente.
              Cada empresa empieza con 100 créditos de bienvenida. Las preguntas sencillas del
              asistente no gastan créditos.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Otras empresas pueden ver mis precios u ofertas?</summary>
            <p>
              No. Cada empresa ve solo sus propios datos, y esa separación la impone la base de datos.
              Tus precios y tus ofertas no se comparten con nadie de fuera de tu empresa.
            </p>
          </details>

          <details class="pregunta">
            <summary>¿Hay que instalar algo?</summary>
            <p>
              No. Funciona en el navegador de la computadora o del celular. Solo hace falta conexión
              a internet.
            </p>
          </details>
        </div>
      </section>

      <section class="cierre">
        <div class="envoltura cierre__caja">
          <h2 class="cierre__titulo">Empieza hoy con el RUC de tu empresa</h2>
          <p class="cierre__texto">
            7 días de acceso a todo el panel y 100 créditos de IA para probarlo.
          </p>
          <div class="cierre__acciones">
            <a class="boton boton--principal" href="/registro">Crear la cuenta de mi empresa</a>
            <a class="boton boton--secundario" href="/login">Ya tengo cuenta</a>
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
  max-width: 56ch;
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
  margin: var(--e-6) 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

/* El área del menú en la que vive cada pieza: así quien entra por primera vez ya sabe dónde
   buscarla. */
.pieza__area {
  margin: 0 0 var(--e-2);
  font-size: var(--t-xs);
  font-weight: 650;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--acento);
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

/* --- Preparar oferta ----------------------------------------------------- */

.oferta {
  margin-top: var(--e-6);
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: var(--e-6);
  align-items: start;
}

.oferta__pasos {
  margin: 0;
  padding: 0 0 0 var(--e-5);
  display: grid;
  gap: var(--e-4);
  color: var(--texto-suave);
  font-size: var(--t-base);
  line-height: 1.7;
}

.oferta__pasos li::marker {
  color: var(--acento);
  font-weight: 700;
}

.oferta__pasos strong {
  color: var(--texto);
  font-weight: 650;
}

.oferta__incluye {
  padding: var(--e-5);
}

.oferta__titulo {
  margin: 0;
  font-size: var(--t-md);
  font-weight: 650;
}

.oferta__lista {
  list-style: none;
  margin: var(--e-3) 0 0;
  padding: 0;
  display: grid;
  gap: var(--e-3);
  color: var(--texto-suave);
  font-size: var(--t-base);
  line-height: 1.6;
}

.oferta__lista li {
  position: relative;
  padding-left: var(--e-5);
}

.oferta__lista li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: var(--acento);
  font-weight: 700;
}

/* --- Asistente ----------------------------------------------------------- */

.ejemplos {
  list-style: none;
  margin: var(--e-5) 0 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-3);
}

.ejemplos__frase {
  padding: var(--e-2) var(--e-4);
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: var(--r-redondo);
  font-size: var(--t-base);
  color: var(--texto);
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
  .portada__rejilla,
  .oferta {
    grid-template-columns: 1fr;
    gap: var(--e-6);
  }

  .pasos {
    grid-template-columns: repeat(2, 1fr);
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

  .pasos {
    grid-template-columns: 1fr;
  }

  .portada__acciones .boton,
  .cierre__acciones .boton {
    flex: 1 1 100%;
  }
}
</style>
