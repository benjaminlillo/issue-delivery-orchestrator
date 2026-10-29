# Prototipo de UI durante el grill

Las decisiones de UI y UX acordadas sólo con palabras suelen cambiar cuando el usuario prueba el
resultado al final del run. El prototipo las vuelve concretas antes del spec: un mock barato que el
usuario mira y comenta, y que se aprueba junto con los criterios `UX-NNN` y `UXD-NNN`.

## Cuándo

- Siempre que el cambio tenga historias de UI, después de conversar la experiencia de usuario y
  antes de presentar el spec.
- Se omite si el usuario dice "sin prototipo", si no hay cambios de UI, o en un run autónomo.
  Registrar la omisión con
  `python3 <plugin-root>/scripts/issue-delivery <issue> prototype-approve --skip-reason "<motivo>"`.

## Construirlo barato

Todo vive en `.local-runtime/issue-delivery-orchestrator/<run-id>/prototype/`, fuera del código
del producto. No levantar el Local Runtime, la app ni el backend.

- Elegir la forma más barata que muestre la decisión: HTML estático con JavaScript mínimo para
  las interacciones acordadas. Usar una app propia sólo si el flujo lo exige.
- Replicar la UI real. Copiar la estructura y las clases de los componentes y páginas hermanas
  nombrados en el grill, y duplicar en el mock los componentes que haga falta. No importar código
  del producto ni editarlo.
- Generar los estilos reales de la app con el Tailwind del repositorio. En TurboShop, crear
  `prototype/tailwind.config.js` que extienda la config de la app y apunte `content` al mock, y
  compilar el CSS global de la app:

  ```js
  const app = require('<worktree>/apps/<app>/tailwind.config.js');
  module.exports = { ...app, content: ['<prototype-dir>/**/*.html'] };
  ```

  ```bash
  node_modules/.bin/tailwindcss -c <prototype-dir>/tailwind.config.js \
    -i apps/<app>/src/app/global.css -o <prototype-dir>/styles.css
  ```

- Usar datos falsos realistas y mostrar los estados acordados (vacío, carga, error, éxito,
  permisos), por ejemplo con un selector de estado visible sólo en el prototipo.

## Mostrarlo e iterar

- En `conductor-cloud`, ejecutar
  `python3 <plugin-root>/scripts/issue-delivery <issue> prototype-open --path <prototipo>/index.html`.
  El motor sirve la carpeta del prototipo y la comparte en el preview URL del workspace con
  `conductor preview set`. Entregar al usuario la `url` que devuelve: la abre en su navegador con
  su sesión de Conductor. El workspace tiene un solo preview URL; el prototipo lo ocupa mientras se
  itera.
- Si Conductor no comparte el preview, reintentar una vez y luego usar `--desktop`, que abre el
  prototipo en Chrome en el escritorio de Conductor. Ese modo exige el escritorio abierto: si el
  motor responde que no lo está, pedir al usuario que lo abra desde la app y esperar su aviso.
- En los otros modos, entregar la ruta del archivo para que el usuario lo abra en su navegador.
- No tomar capturas ni videos mientras se itera. Tras cada comentario, ajustar el mock y
  recompilar el CSS si cambiaron clases. El servidor entrega siempre la versión actual: basta con
  pedir al usuario que recargue. Ejecutar otra vez `prototype-open` sólo para mostrar otra página.

## Aprobarlo

Cuando el usuario apruebe:

1. Tomar capturas PNG de cada estado acordado con Chrome headless del workspace, a 1440x900,
   en `prototype/approved/`.
2. Escribir `prototype/approved/manifest.json` con `{"screenshots": [{"title", "path"}]}` y
   ejecutar `prototype-approve --manifest <ruta>`. El motor sube las capturas a la issue de Linear,
   en la sección "Prototipo aprobado", y registra el prototipo en el estado del run.
3. En `User Experience Acceptance`, usar `Prototype: <título de la captura>` como fuente de cada
   fila `UXD` que el prototipo define.

## Después del grill

- Implement recibe en su paquete la carpeta del prototipo y las capturas aprobadas como
  referencia visual. Implementa según el spec, con los componentes reales del producto; no copia
  el HTML ni el CSS del mock.
- La revisión UI final compara el resultado con las capturas aprobadas en cada fila `UXD` con
  fuente `Prototype` y reporta las diferencias visibles como fallos.
