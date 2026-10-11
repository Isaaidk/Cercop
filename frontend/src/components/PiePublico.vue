<script setup>
/**
 * El pie de las páginas públicas.
 *
 * Los enlaces que hay aquí son **los cuatro que existen de verdad**. No hay enlaces a una página de
 * privacidad ni a unas condiciones de uso porque esas páginas no están escritas: un enlace a una
 * dirección que no lleva a ninguna parte es peor que su ausencia, y engaña a quien lo pulsa y a quien
 * lo rastrea. Las condiciones se aceptan al crear la cuenta, y eso es lo que se dice, sin enlazar a
 * ningún sitio.
 */
</script>

<template>
  <footer class="pie">
    <div class="pie__envoltura">
      <div class="pie__identidad">
        <p class="pie__nombre">
          <span class="pie__icono" aria-hidden="true">CP</span>
          Cercop
        </p>
        <p class="pie__descripcion">
          Panel de seguimiento de la contratación pública del Ecuador.
        </p>
      </div>

      <nav class="pie__enlaces" aria-label="Enlaces del pie">
        <a href="/">Portada</a>
        <a href="/contratacion-publica-ecuador">Contratación pública en Ecuador</a>
        <a href="/login">Ingresar</a>
        <a href="/registro">Crear cuenta</a>
      </nav>
    </div>

    <div class="pie__envoltura">
      <p class="pie__aviso">
        Cercop no es una página oficial del SERCOP. Es una herramienta de consulta que lee los datos
        que el Servicio Nacional de Contratación Pública publica en abierto. Para cualquier trámite,
        la fuente que vale es siempre la oficial. Al crear una cuenta se aceptan las condiciones de
        uso del servicio.
      </p>
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
  width: 24px;
  height: 24px;
  border-radius: var(--r-1);
  background: var(--acento);
  color: #fff;
  font-size: 0.625rem;
  font-weight: 700;
}

.pie__descripcion {
  margin: var(--e-2) 0 0;
  color: var(--texto-suave);
  font-size: var(--t-base);
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

.pie__enlaces a:hover {
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
</style>
