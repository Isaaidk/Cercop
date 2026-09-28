import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

/**
 * Configuración del panel.
 *
 * El proxy de desarrollo existe para que el navegador no tenga que hablar con un origen distinto del
 * suyo. Sin él, cada petición sería «de otro sitio» y el navegador exigiría CORS, con su petición
 * previa de permiso, sus orígenes permitidos y sus credenciales: tres cosas que pueden fallar y que
 * en desarrollo no aportan nada. Con el proxy, el panel llama a `/v1/...` en su propio origen y es
 * Vite quien reenvía a la API.
 *
 * En producción no hay proxy: `VITE_API_BASE` apunta a la API real y la API declara los orígenes
 * permitidos. Son dos caminos distintos a propósito, porque en producción el proxy no existe.
 */
export default defineConfig(({ mode }) => {
  const entorno = loadEnv(mode, process.cwd(), '')
  const destino = entorno.VITE_API_PROXY || 'http://127.0.0.1:8001'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5174,
      proxy: {
        '/v1': { target: destino, changeOrigin: true },
        '/salud': { target: destino, changeOrigin: true },
        '/listo': { target: destino, changeOrigin: true },
      },
    },
    build: {
      // Un mapa de código fuente facilita muchísimo depurar un error que solo ocurre en producción,
      // y el archivo no se sirve a los usuarios salvo que alguien abra las herramientas del
      // navegador. El coste es un archivo más en el despliegue.
      sourcemap: true,
      chunkSizeWarningLimit: 900,
    },
  }
})
