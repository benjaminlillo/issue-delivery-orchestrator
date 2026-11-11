# Modo t3-runner

Aplica cuando el run se ejecuta en un runner remoto de T3 Code: un contenedor Linux sin escritorio
que T3 Code usa como entorno a través de T3 Connect. La imagen del runner exporta `T3_RUNNER=1` a
todos los agentes; esa es la única señal de detección.

## Workspace

- T3 Code crea el worktree del thread (`~/.t3/worktrees/<repo>/t3-<id>`, rama `t3/<id>`) y ejecuta
  el setup del proyecto antes de que empiece la sesión. El loop adopta ese worktree, cambia a la
  rama de Linear desde `origin/<base>` y nunca crea otro.
- Como la detección es automática, el motor exige un checkout sin cambios antes de limpiar. Si
  bloquea por cambios locales, anunciar la decisión, pedir que se preserven o limpien, o que el
  usuario elija explícitamente `modo t3-runner` para autorizar la limpieza normal.
- `modo vanilla` explícito sigue disponible en el runner, pero su reviewer Cua Driver necesita un
  escritorio que el runner no tiene; no sugerirlo para revisión visual.

## Reviewer

`issue-delivery-playwright-review` con Playwright headless del repositorio objetivo y el Chrome del
sistema (`google-chrome`). Es el reviewer principal y no genera `headlessAssistance`. No exportar
`DISPLAY`, no lanzar Xvfb ni navegadores con interfaz, y no usar `launch-browser`,
`desktop-prepare` ni `desktop-open`: el runner no tiene escritorio. Las apps se prueban por sus
URLs `http://127.0.0.1:<puerto>` del manifiesto del Local Runtime.

## Acceso del usuario al runtime

El usuario no puede abrir `127.0.0.1` del runner. El runner expone un único dominio público que
pasa por un gate autenticado y redirige al runtime y app que el usuario elija:

1. Al terminar un handoff (`manual-runtime` o `full`), ejecutar `preview-link`. Imprime un link
   de login de un solo uso que vence en 10 minutos.
2. Entregar el link junto con el runtime ID y las apps levantadas, e indicar: abrir el link (sirve
   también desde el celular), elegir el runtime y la app en `/__gate` y entrar con el usuario de
   pruebas del runtime. La sesión del gate dura 7 días; para cambiar de runtime o app, volver a
   `/__gate`.
3. Si el link venció, generar otro con `preview-link` cuando el usuario lo pida; no reutilizarlo.

El login de las apps Next funciona por el dominio público porque el runner fija
`LOCAL_RUNTIME_AUTH_TRUST_HOST=1` y la app deduce su auth URL del request. Si el worktree no
contiene ese soporte, el login falla con `Untrusted auth host`: informarlo como limitación de la
base, no como fallo del cambio.

Mencionar en el handoff que el link no reemplaza la revisión del reviewer: es la superficie para la
revisión humana.

## Prototipos

`prototype-open` es exclusivo de Conductor Cloud. En `t3-runner`, renderizar el prototipo con
Playwright headless, guardar las capturas bajo el directorio del prototipo del run y mostrarlas en
el chat con su ruta absoluta (T3 Code muestra imágenes del entorno). La aprobación sigue el flujo
normal de [prototype.md](prototype.md).
