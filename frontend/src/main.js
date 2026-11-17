import { createApp } from 'vue'

import App from './App.vue'
import './assets/main.css'

// Un campo numérico con el foco cambia su valor con la rueda del mouse: quien escribe un precio y
// luego baja la página para seguir leyendo termina con otro número sin darse cuenta. Al girar la
// rueda sobre el campo se le quita el foco, así el valor queda igual y la página sigue bajando.
document.addEventListener(
  'wheel',
  (evento) => {
    const campo = document.activeElement
    if (campo instanceof HTMLInputElement && campo.type === 'number' && campo === evento.target) {
      campo.blur()
    }
  },
  { passive: true },
)

createApp(App).mount('#app')
