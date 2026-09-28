# Pruebas de extremo a extremo

Recorren el sistema completo desde el punto de vista del usuario, con navegador automatizado.

Se implementan en las fases 4, 5 y 6:

- **CU-01 + CU-02:** primer login → gate de consentimiento → entrada al aplicativo.
- **CU-03 + CU-04:** consulta multi-palabra → agregar término nuevo → estado de ingesta → resultados completos.
- **CU-07:** exportar por criterios y por selección → descargar el archivo.
- **CU-08:** tres usuarios entran; el tercero expulsa a uno y el semáforo cambia a rojo **sin recargar**.

**Regla:** ninguna prueba de este directorio debe alcanzar la fuente oficial. La ingesta se simula con
una fuente falsa.
