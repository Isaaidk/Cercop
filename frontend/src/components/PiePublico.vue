<script setup>
/**
 * El pie de las páginas públicas.
 *
 * Lleva los enlaces de navegación pública, los dos textos legales (términos y privacidad) y el aviso
 * de derechos. Los enlaces son `<a href>` normales, igual que en la cabecera: funcionan sin
 * JavaScript y un buscador los sigue.
 *
 * El año del aviso de derechos se calcula al montar el componente: escrito a mano, se queda viejo el
 * 1 de enero y nadie se acuerda de cambiarlo.
 */
const anio = new Date().getFullYear()
</script>

<template>
  <footer class="pie">
    <div class="pie__envoltura">
      <div class="pie__identidad">
        <p class="pie__nombre">
          <span class="pie__icono">
            <img src="/logo-cercoapp.png" alt="" width="28" height="28" />
          </span>
          CercoApp
        </p>
        <p class="pie__descripcion">
          Encuentra ínfimas cuantías y necesidades de contratación del Ecuador, y prepara tu oferta
          en el mismo sitio.
        </p>
      </div>

      <nav class="pie__enlaces" aria-label="Enlaces del pie">
        <a href="/">Portada</a>
        <a href="/contratacion-publica-ecuador">Contratación pública en Ecuador</a>
        <a href="/login">Ingresar</a>
        <a href="/registro">Crear cuenta</a>
        <a href="/terminos">Términos y condiciones</a>
        <a href="/privacidad">Política de privacidad</a>
      </nav>
    </div>

    <div class="pie__envoltura">
      <p class="pie__aviso">
        CercoApp no es una página oficial del SERCOP. Es una herramienta independiente que lee los
        datos que el Servicio Nacional de Contratación Pública publica en abierto. Para presentar una
        oferta o hacer cualquier trámite, la fuente que vale es siempre el portal oficial.
      </p>

      <div class="pie__legal">
        <p>© {{ anio }} CercoApp. Todos los derechos reservados.</p>
        <p>
          Prohibida la reproducción, copia o distribución total o parcial de este sitio, su
          contenido, diseño y marca sin autorización escrita.
        </p>
      </div>
    </div>
  </footer>
</template>

<style scoped>
.pie {
  margin-top: var(--e-7);
  border-top: 1px solid var(--borde);
  background: var(--superficie-2);
  padding: var(--e-6) 0 var(--e-5);
}

.pie__envoltura {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 var(--e-6);
}

.pie__envoltura + .pie__envoltura {
  margin-top: var(--e-4);
}

.pie__identidad {
  margin-bottom: var(--e-4);
}

.pie__nombre {
  display: flex;
  align-items: center;
  gap: var(--e-2);
  margin: 0;
  font-weight: 650;
  font-size: var(--t-md);
}

.pie__icono {
  display: grid;
  place-items: center;
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  overflow: hidden;
}

.pie__icono img {
  display: block;
  width: 100%;
  height: 100%;
}

html[data-tema='oscuro'] .pie__icono {
  box-shadow: 0 0 0 1px rgb(255 255 255 / 16%);
}

.pie__descripcion {
  margin: var(--e-2) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-base);
  max-width: 70ch;
}

.pie__enlaces {
  display: flex;
  flex-wrap: wrap;
  gap: var(--e-2) var(--e-5);
  font-size: var(--t-base);
}

.pie__enlaces a {
  color: var(--texto-suave);
  text-decoration: none;
}

.pie__enlaces a:hover,
.pie__enlaces a:focus-visible {
  color: var(--acento);
  text-decoration: underline;
}

.pie__aviso {
  margin: 0;
  padding-top: var(--e-4);
  border-top: 1px solid var(--borde);
  color: var(--texto-tenue);
  font-size: var(--t-sm);
  line-height: 1.6;
  max-width: 78ch;
}

.pie__legal {
  margin-top: var(--e-4);
  color: var(--texto-tenue);
  font-size: var(--t-sm);
  line-height: 1.6;
}

.pie__legal p {
  margin: 0;
}

.pie__legal p + p {
  margin-top: var(--e-1);
  max-width: 78ch;
}

@media (max-width: 640px) {
  .pie__envoltura {
    padding: 0 var(--e-4);
  }
}
</style>
