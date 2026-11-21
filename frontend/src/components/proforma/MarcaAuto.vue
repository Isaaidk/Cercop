<script setup>
/**
 * El indicador discreto de «este dato se llenó solo: revísalo». Un punto junto a la etiqueta; el
 * texto completo lo leen los lectores de pantalla y aparece al pasar el ratón.
 */
</script>

<template>
  <span class="marca-auto" title="Autollenado: revísalo">
    <span aria-hidden="true" class="marca-auto__punto" />
    <span class="solo-lectores">(autollenado, revísalo)</span>
  </span>
</template>

<style scoped>
.marca-auto { display: inline-flex; align-items: center; margin-left: var(--e-1); vertical-align: middle; }
.marca-auto__punto { width: 7px; height: 7px; border-radius: 50%; background: var(--acento); opacity: 0.75; }
</style>
